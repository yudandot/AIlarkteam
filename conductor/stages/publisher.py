# -*- coding: utf-8 -*-
"""
Stage 4: 发布 — 将内容发布到社交媒体平台。

发布策略（三级）：
  Level 1 — 仅存储：生成内容包存入仓库（默认）
  Level 2 — 人工确认后自动发布：在飞书审批通过后，通过 Playwright 发布
  Level 3 — 全自动：定时自动扫描+生成+发布（需 CONDUCTOR_AUTO_PUBLISH=true）

自动发布支持的平台：
  - 小红书（图文笔记）— 通过 Playwright 浏览器自动化
  - 微博（图文微博）  — 通过 Playwright 浏览器自动化
"""
from __future__ import annotations

import os
import time

from conductor.config import Platform, log
from conductor.models import ContentDraft, PublishResult
from conductor.store import ContentItem, ContentStatus, store


def publish_draft(
    draft: ContentDraft,
    platform: Platform,
    run_id: str = "",
    brainstorm_session: str = "",
) -> PublishResult:
    """
    处理内容发布。

    默认只存储到仓库。如果配置了 CONDUCTOR_AUTO_PUBLISH=true 且
    安装了 playwright，则尝试自动发布。
    """
    result = PublishResult(platform=platform, published_at=time.time())

    item = ContentItem(
        title=draft.idea.title,
        topic=draft.idea.title,
        content_type=draft.idea.content_type,
        platform_copy=draft.platform_copy,
        hashtags=draft.hashtags,
        visual_prompt=draft.visual_prompt,
        visual_prompt_en=draft.visual_prompt_en,
        generated_assets=getattr(draft, "generated_assets", []),
        idea_title=draft.idea.title,
        idea_angle=draft.idea.angle,
        idea_hook=draft.idea.hook,
        quality_score=draft.quality_score,
        quality_feedback=draft.quality_feedback,
        target_platforms=[platform.value],
        status=ContentStatus.READY,
        run_id=run_id,
        idea_id=getattr(draft.idea, "idea_id", ""),
        brainstorm_session=brainstorm_session,
    )
    content_id = store.save(item)
    result.post_id = content_id
    result.success = True

    # 默认直接发布；设 CONDUCTOR_AUTO_PUBLISH=false 则只存仓库
    auto = os.getenv("CONDUCTOR_AUTO_PUBLISH", "true").lower() in ("1", "true", "yes")
    if auto:
        try:
            pub_result = publish_content(content_id, platform.value)
            if pub_result.success:
                result.post_url = pub_result.post_url
                log.info("自动发布成功: %s → %s", platform.value, result.post_url)
        except Exception as e:
            log.warning("自动发布失败（内容已存入仓库）: %s", e)

    return result


def publish_content(content_id: str, platform: str) -> PublishResult:
    """
    发布指定内容到指定平台。

    通过 Playwright 浏览器自动化完成实际的社交媒体发布。
    """
    result = PublishResult(
        platform=Platform.from_str(platform) or Platform.XIAOHONGSHU,
        published_at=time.time(),
    )

    item = store.get(content_id)
    if not item:
        result.error = f"内容 {content_id} 不存在"
        return result

    # 获取对应平台的文案，并解析为标题 / 正文 / 话题（发布时只用标题+正文+一次话题，不把整段 prompt 塞进正文）
    copy_raw = _get_platform_copy(item, platform)
    title, body, parsed_tags = _parse_platform_copy_for_publish(copy_raw)
    if not title:
        title = item.title[:80]
    hashtags = parsed_tags if parsed_tags else (item.hashtags or [])
    content = body  # 正文仅用 body，话题由 autopublish 在末尾统一追加一次

    # 获取本地图片路径
    image_paths = _get_local_images(item)

    try:
        if platform in ("xiaohongshu", "小红书", "xhs"):
            from conductor.autopublish import publish_xiaohongshu
            url = publish_xiaohongshu(
                title=title,
                content=content,
                image_paths=image_paths,
                hashtags=hashtags,
            )
        elif platform in ("weibo", "微博", "wb"):
            from conductor.autopublish import publish_weibo
            url = publish_weibo(content=content, image_paths=image_paths)
        else:
            result.error = f"平台 {platform} 暂不支持自动发布，内容已存入仓库，请手动复制发布"
            return result

        result.success = True
        result.post_url = url
        result.post_id = content_id
        store.mark_published(content_id, platform, url)

        platform_post_id = _extract_post_id(url, platform)
        if platform_post_id:
            store.set_post_id(content_id, platform, platform_post_id)

    except ImportError:
        result.error = "自动发布需要安装 playwright: pip install playwright && playwright install chromium"
        log.warning(result.error)
    except Exception as e:
        result.error = str(e)
        store.mark_failed(content_id, platform, str(e))
        log.error("发布失败: %s → %s: %s", content_id, platform, e)

    return result


def _extract_post_id(url: str, platform: str) -> str:
    """从发布 URL 中提取平台侧的帖子 ID。"""
    import re
    if not url:
        return ""
    if platform in ("xiaohongshu", "小红书", "xhs"):
        m = re.search(r'/explore/([a-f0-9]+)', url)
        return m.group(1) if m else ""
    if platform in ("weibo", "微博", "wb"):
        m = re.search(r'/(\d+)/([A-Za-z0-9]+)', url)
        return m.group(2) if m else ""
    return ""


def _get_platform_copy(item: ContentItem, platform: str) -> str:
    """获取对应平台的文案，找不到则用第一个。"""
    aliases = {
        "xiaohongshu": ["xiaohongshu", "小红书", "xhs"],
        "weibo": ["weibo", "微博", "wb"],
        "douyin": ["douyin", "抖音", "dy"],
        "bilibili": ["bilibili", "b站", "哔哩哔哩"],
    }
    for key, names in aliases.items():
        if platform.lower() in names:
            for name in names:
                if name in item.platform_copy:
                    return item.platform_copy[name]

    for plat_name, text in item.platform_copy.items():
        if platform.lower() in plat_name.lower():
            return text

    return list(item.platform_copy.values())[0] if item.platform_copy else item.title


def _parse_platform_copy_for_publish(full_text: str) -> tuple[str, str, list[str]]:
    """
    从存储的 platform_copy 全文解析出：标题、正文、话题标签。
    用于发布时：标题填标题框，正文填正文框（不含 prompt/格式说明），话题在正文末尾补一次。
    """
    import re
    if not (full_text or "").strip():
        return "", "", []

    parts = [p.strip() for p in full_text.strip().split("\n\n") if p.strip()]
    if not parts:
        return "", "", []

    title = parts[0][:80]  # 标题框通常有字数限制
    # 最后一段若全是 # 开头或短标签，视为 hashtags
    tags: list[str] = []
    if len(parts) >= 2:
        last = parts[-1]
        if re.match(r"^[\s#\w\u4e00-\u9fff]+$", last) and ("#" in last or len(last) < 120):
            tags = [t.strip() for t in re.split(r"[\s\n]+", last) if t.strip() and "#" in t]
            body_parts = parts[1:-1]
        else:
            body_parts = parts[1:]
    else:
        body_parts = []

    body_raw = "\n\n".join(body_parts) if body_parts else ""
    body = _sanitize_publish_body(body_raw)
    return title, body, tags


def _sanitize_publish_body(body: str) -> str:
    """去掉正文里不应出现在发布内容中的 prompt/格式/画面描述。"""
    import re
    if not body or not body.strip():
        return ""
    lines = []
    for line in body.split("\n"):
        s = line.strip()
        if not s:
            lines.append("")
            continue
        # 去掉：格式说明、分隔线、纯括号画面描述
        if re.match(r"^格式[一二三四五六七八九十\d]+[：:]\s*", s):
            continue
        if re.match(r"^[-─—]{2,}\s*$", s):
            continue
        if re.match(r"^[（(].*[）)]\s*$", s) and ("左" in s or "右" in s or "图" in s or "画面" in s):
            continue
        if s.startswith("（") and "：" in s and ("左" in s or "右" in s):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _get_local_images(item: ContentItem) -> list[str]:
    """
    获取本地图片路径（用于浏览器上传）。
    若 generated_assets 是远程 URL，会先下载到 data/conductor/assets/，
    再返回本地路径，供 Playwright 自动完成上传发布。
    小红书单张建议 <10MB，当前 Seedream 1920x1920 通常 1～3MB，可自动上传。
    """
    local_paths = []
    for asset in (item.generated_assets or []):
        from pathlib import Path
        p = Path(asset)
        if p.exists() and p.is_file():
            local_paths.append(str(p))

    if not local_paths and item.generated_assets:
        try:
            from conductor.visual import download_asset
            for url in item.generated_assets[:4]:  # 小红书单篇最多 9 张，取前 4 张
                if url.startswith("http"):
                    path = download_asset(url)
                    local_paths.append(str(path))
                    # 若单张超过 10MB，小红书可能上传失败；必要时可在此做压缩
                    size_mb = path.stat().st_size / (1024 * 1024)
                    if size_mb > 10:
                        log.warning("素材 %s 超过 10MB (%.1f MB)，小红书可能拒绝上传", path.name, size_mb)
        except Exception as e:
            log.warning("下载素材失败: %s", e)

    return local_paths
