# -*- coding: utf-8 -*-
"""
规划机器人（长连接模式）：给机器人发消息即可启动理性规划。

运行：python3 -m planner
环境变量：PLANNER_FEISHU_APP_ID / PLANNER_FEISHU_APP_SECRET（或复用 FEISHU_APP_ID）

消息格式：
  直接发消息即为规划主题，例如：
    设计一个 AI agent 系统来自动化日常工作
  或带前缀 / 模式：
    规划：Q3 用户增长策略
    快速模式：下周产品发布计划
  多行消息第一行为主题，其余为背景材料。
  发送「帮助」查看使用说明。
"""
import json
import os
import random
import sys
import threading
import time
import traceback
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import lark_oapi as lark
from lark_oapi import EventDispatcherHandler, LogLevel

from core.feishu_client import reply_message, reply_card, send_message_to_user, send_card_to_user, create_document_with_content
from core.cards import welcome_card, progress_card, result_card, error_card, help_card, make_card
from core.llm import chat_completion
from core.utils import truncate_for_display
from planner.run import run_planning, generate_doc, detect_mode
from planner.prompts import PLANNER_SYSTEM, DOC_TYPES, DOC_MENU, DOC_CATEGORY_TYPES, detect_doc_category, build_doc_menu

# ── 日志 ─────────────────────────────────────────────────────

_log_lock = threading.Lock()
_bot_log_path: Optional[str] = None


def _log(msg: str) -> None:
    line = f"[PlannerBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    global _bot_log_path
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_planner.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 消息解析 ─────────────────────────────────────────────────

_TOPIC_PREFIXES = (
    "规划 ", "规划：", "规划:", "plan ", "plan:", "plan：",
    "计划 ", "计划：", "计划:",
)
_MODE_PREFIXES = (
    "快速模式 ", "快速模式：", "快速模式:",
    "分析模式 ", "分析模式：", "分析模式:",
    "方案模式 ", "方案模式：", "方案模式:",
    "执行模式 ", "执行模式：", "执行模式:",
)

def _welcome() -> dict:
    return welcome_card(
        "规划机器人",
        "可以聊任何话题，也可以做深度规划。\n\n"
        "**直接聊** → 我像朋友一样跟你讨论\n"
        "**发「规划：话题」** → 启动理性六步法深度拆解",
        examples=[
            "最近想转行，不知道该不该",
            "周末想做个 side project，帮我想想方向",
            "规划：Q3 用户增长策略",
            "快速模式：下周产品发布计划",
        ],
        hints=["日常问题直接发，复杂决策加「规划：」前缀", "发送「帮助」查看所有模式"],
    )


def _help() -> dict:
    return help_card("规划机器人", [
        ("日常对话", "直接发消息，我像朋友一样聊。生活、职业、兴趣、想法都行。"),
        ("深度规划", "消息前加「规划：」触发理性六步法：\n> 规划：要不要读个 MBA\n> 规划：Q3 用户增长策略"),
        ("五种模式",
         "**完整规划**（默认）六步全走\n"
         "**快速模式** 跳过现状分析和反馈，更快\n"
         "**分析模式** 仅问题定义 + 现状分析\n"
         "**方案模式** 仅生成 3 个方案\n"
         "**执行模式** 仅生成执行计划"),
        ("切换模式", "在消息前加模式名：\n> 快速模式：下周产品发布计划"),
        ("多行消息", "第一行 = 主题，其余行 = 背景材料"),
    ], footer="对话秒回 | 规划约 2-4 分钟")


def _extract_text(content: str) -> str:
    if not content or not content.strip():
        return ""
    try:
        data = json.loads(content)
        if isinstance(data, dict) and "text" in data:
            return (data["text"] or "").strip()
        return content.strip()
    except (json.JSONDecodeError, TypeError):
        return content.strip()


def _parse_planning_input(text: str) -> tuple[str, str, str]:
    t = (text or "").strip()
    mode = "完整规划"
    for prefix in _MODE_PREFIXES:
        if t.lower().startswith(prefix) or t.startswith(prefix):
            mode = prefix.rstrip(" ：:").strip()
            t = t[len(prefix):].strip()
            break
    for prefix in _TOPIC_PREFIXES:
        if t.lower().startswith(prefix):
            t = t[len(prefix):].strip()
            break
    if mode == "完整规划":
        mode = detect_mode(t)
    lines = t.split("\n", 1)
    topic = lines[0].strip()
    context = lines[1].strip() if len(lines) > 1 else ""
    if context.startswith("---"):
        context = context[3:].strip()
    return topic, context, mode


# ── 对话模式（非规划） ───────────────────────────────────────

_PLANNING_SIGNALS = (
    "规划", "计划", "策略", "方案", "怎么做", "怎么搞", "如何",
    "plan", "strategy", "how to", "how do",
    "帮我想想", "帮我分析", "帮我拆解",
)

_PLANNING_PREFIXES = _TOPIC_PREFIXES + _MODE_PREFIXES


def _needs_planning(text: str) -> bool:
    """判断消息是否需要走完整规划流水线。"""
    t = text.strip()
    for prefix in _PLANNING_PREFIXES:
        if t.lower().startswith(prefix) or t.startswith(prefix):
            return True
    lower = t.lower()
    if any(sig in lower for sig in _PLANNING_SIGNALS):
        return True
    if len(t) > 100:
        return True
    return False


_CHAT_SYSTEM = PLANNER_SYSTEM + """

当前是对话模式——不走六步流水线，但你仍然是一个有方案的人。

你要做的：
1. 先听清楚用户在说什么、真正纠结的是什么
2. 给出你的判断（不是"各有利弊"这种废话）
3. 如果值得，给 1-2 个具体方案或建议，附理由
4. 如果有思维盲区，直接指出

不要做的：
- 不要变成情感陪聊（"我理解你的感受"然后没了）
- 不要变成信息搬运工（百度能查到的不用你说）
- 不要没有立场

话题可以是任何事：生活、职业、关系、兴趣、side project、纠结的选择。
保持简洁。一个好回复 = 一个判断 + 一个方案 + 一个用户没想到的角度。

如果问题复杂到值得深度拆解，建议用户："这个值得认真规划一下，发「规划：你的问题」我帮你系统拆。"
"""


def _generate_short_title(topic: str) -> str:
    """用 LLM 将冗长话题凝练为文档标题（≤15字）。"""
    try:
        result = chat_completion(
            provider="deepseek",
            system="将用户输入凝练为一个文档标题。要求：≤15个中文字，不加标点，保留核心主题和关键限定词。只输出标题，不要解释。",
            user=topic,
        ).strip().strip("\"'「」《》【】")
        if result and len(result) <= 30:
            return result
    except Exception:
        pass
    return topic[:20]


def _chat_reply(text: str) -> str:
    """轻量对话：单轮 LLM 回复。"""
    try:
        from core.skill_router import enrich_prompt
        system = enrich_prompt(_CHAT_SYSTEM, user_text=text, bot_type="planner")
    except Exception:
        system = _CHAT_SYSTEM
    return chat_completion(provider="deepseek", system=system, user=text).strip()


# ── 文档交付 ─────────────────────────────────────────────────

_pending_docs: dict[str, dict] = {}
_pending_docs_lock = threading.Lock()
_DOC_SESSION_TTL = 1800  # 30 min

_DOC_DESCRIPTIONS = {
    "brief": "执行 Brief — 可直接发给团队的方案摘要",
    "calendar": "内容日历 — 按周排列的内容排期表",
    "timeline": "里程碑时间线 — 关键节点 + 依赖 + 风险",
    "decision": "决策备忘 — 一页纸决策记录",
    "itinerary": "行程表 — 按天排列的完整行程",
    "budget": "预算清单 — 分项预算 + 省钱建议",
    "packing": "打包清单 — 根据目的地定制的行李清单",
    "action": "行动清单 — 按步骤排列的执行 TODO",
    "spec": "项目 Spec — 范围定义 + MVP + 技术选型",
    "features": "功能优先级 — P0/P1/P2 功能拆分表",
}


def _doc_menu_card(category: str = "general") -> dict:
    """根据话题类别生成文档选择菜单卡片。"""
    types = DOC_CATEGORY_TYPES.get(category, DOC_CATEGORY_TYPES["general"])
    lines = ["规划完成！可以帮你生成以下文档：\n"]
    for i, dt in enumerate(types, 1):
        desc = _DOC_DESCRIPTIONS.get(dt, DOC_TYPES[dt]["name"])
        lines.append(f"**{i}. {desc}**")
    lines.append("")
    lines.append("回复数字（如 `1`）或名称即可生成。")
    lines.append("回复 `全部` 生成所有文档。")
    return make_card("需要生成文档吗？", [
        {"text": "\n".join(lines)},
        {"divider": True},
        {"note": "30 分钟内有效  ·  也可以继续聊别的"},
    ], color="purple")


def _try_create_feishu_doc(title: str, content: str, open_id: Optional[str] = None) -> Optional[str]:
    """尝试创建飞书云文档，返回文档 URL 或 None。"""
    owner = open_id or (os.environ.get("FEISHU_DOC_OWNER_OPEN_ID") or "").strip() or None
    try:
        ok, result = create_document_with_content(title, content, owner_open_id=owner)
        if ok:
            return result
        _log(f"创建飞书文档失败: {result}")
    except Exception as e:
        _log(f"创建飞书文档异常: {e}")
    return None


# ── 运行中追踪 ───────────────────────────────────────────────

_running_sessions: dict[str, str] = {}
_running_lock = threading.Lock()


# ── 文档选择解析与生成 ─────────────────────────────────────

def _resolve_doc_choice(text: str, user_key: str) -> Optional[list[str]]:
    """检查用户消息是否是文档选择，返回 doc_type 列表或 None。

    支持多种输入格式：
      "1"       → 单选
      "123"     → 多选（连续数字）
      "1,3"     → 多选（逗号分隔）
      "1 3"     → 多选（空格分隔）
      "1、3"    → 多选（顿号分隔）
      "全部"    → 全选
      "brief"   → 单选（关键词）
    """
    with _pending_docs_lock:
        session = _pending_docs.get(user_key)
    if not session:
        return None
    if time.time() - session["ts"] > _DOC_SESSION_TTL:
        with _pending_docs_lock:
            _pending_docs.pop(user_key, None)
        return None

    menu = session.get("doc_menu") or DOC_MENU
    t = text.strip().lower()

    # 先尝试精确匹配
    matched = menu.get(t)
    if matched is not None:
        return [matched] if isinstance(matched, str) else list(matched)

    # 尝试解析多数字选择：「123」「1,3」「1 3」「1、3」
    import re
    digits = re.findall(r"[1-9]", t)
    if digits and re.fullmatch(r"[\d,、\s]+", t):
        seen = set()
        result = []
        for d in digits:
            dt = menu.get(d)
            if dt and isinstance(dt, str) and dt not in seen:
                seen.add(dt)
                result.append(dt)
        if result:
            return result

    # 关键词模糊匹配
    for key, val in menu.items():
        if key in t:
            return [val] if isinstance(val, str) else list(val)

    return None


def _handle_doc_choice(mid: str, uid: Optional[str], user_key: str, doc_types: list[str]) -> None:
    """生成用户选择的文档并发送。1 个→独立文档，2+→合并成一个文档。"""
    with _pending_docs_lock:
        session = _pending_docs.get(user_key)
    if not session:
        reply_message(mid, "文档会话已过期，请重新发起规划。")
        return

    topic = session["topic"]
    short_title = session.get("short_title") or topic[:20]
    outputs = session["outputs"]
    open_id = session.get("open_id")
    names = [DOC_TYPES[dt]["name"] for dt in doc_types if dt in DOC_TYPES]
    reply_card(mid, progress_card("正在生成文档", f"**类型：**{' + '.join(names)}\n\n稍等片刻…"))

    is_single = len(doc_types) == 1
    generated: list[tuple[str, str]] = []  # (doc_name, content)

    for doc_type in doc_types:
        cfg = DOC_TYPES.get(doc_type)
        if not cfg:
            continue
        doc_name = cfg["name"]
        _log(f"生成文档: type={doc_type} topic={topic[:40]}")
        try:
            content = generate_doc(doc_type, topic, outputs)
            generated.append((doc_name, content))
        except Exception as e:
            _log(f"文档生成异常: {e}\n{traceback.format_exc()}")
            err_text = f"生成{doc_name}时出错了，请重试。"
            if uid:
                send_message_to_user(uid, err_text)
            else:
                reply_message(mid, err_text)

    if not generated:
        return

    if is_single:
        doc_name, content = generated[0]
        display = truncate_for_display(content)
        doc_card = result_card(f"{doc_name}", body=display, color="purple")
        if uid:
            send_card_to_user(uid, doc_card)
        else:
            reply_card(mid, doc_card)
        feishu_url = _try_create_feishu_doc(
            f"{short_title} — {doc_name}", content, open_id=open_id,
        )
        if feishu_url:
            link_msg = f"飞书文档已创建：{feishu_url}"
            if uid:
                send_message_to_user(uid, link_msg)
            else:
                reply_message(mid, link_msg)
            _log(f"飞书文档: {feishu_url}")
    else:
        # 合并成一个文档（带目录）
        toc_items = [f"{i}. {name}" for i, (name, _) in enumerate(generated, 1)]
        toc = "**目录：**" + " ｜ ".join(toc_items)
        merged_parts = [f"# {short_title}\n\n{toc}\n"]
        for doc_name, content in generated:
            merged_parts.append(f"\n---\n\n## {doc_name}\n\n{content}\n")
        merged_content = "\n".join(merged_parts)

        display = truncate_for_display(merged_content)
        names_str = " + ".join(n for n, _ in generated)
        doc_card = result_card(
            f"文档包（{names_str}）",
            body=display,
            color="purple",
        )
        if uid:
            send_card_to_user(uid, doc_card)
        else:
            reply_card(mid, doc_card)

        feishu_url = _try_create_feishu_doc(
            f"{short_title} — 规划文档包", merged_content, open_id=open_id,
        )
        if feishu_url:
            link_msg = f"飞书文档已创建（含 {len(generated)} 份文档）：{feishu_url}"
            if uid:
                send_message_to_user(uid, link_msg)
            else:
                reply_message(mid, link_msg)
            _log(f"飞书合并文档: {feishu_url}")

    category = session.get("category", "general")
    category_types = DOC_CATEGORY_TYPES.get(category, DOC_CATEGORY_TYPES["general"])
    remaining = [DOC_TYPES[k]["name"] for k in category_types if k not in doc_types and k in DOC_TYPES]
    if remaining:
        hint = f"还可以生成：{'、'.join(remaining)}（回复对应数字或名称）"
        if uid:
            send_message_to_user(uid, hint)
        else:
            reply_message(mid, hint)


# ── 消息处理 ─────────────────────────────────────────────────

def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _log("收到消息事件")
    try:
        if not data.event or not data.event.message:
            _log("事件或消息体为空，忽略")
            return
        msg = data.event.message
        message_id = msg.message_id
        user_text = _extract_text(msg.content or "{}")
        open_id = None
        if data.event.sender and data.event.sender.sender_id:
            open_id = getattr(data.event.sender.sender_id, "open_id", None)
        _log(f"message_id={message_id!r} open_id={open_id!r} 文本={user_text[:80]!r}")
        if not user_text:
            threading.Thread(
                target=lambda: reply_card(message_id, _welcome()),
                daemon=True,
            ).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _process(mid: str, text: str, uid: Optional[str]):
        try:
            lower = text.strip().lower()
            if lower in ("帮助", "help", "?", "？"):
                reply_card(mid, _help())
                return

            # ── 检查是否是文档选择 ──
            user_key = uid or mid
            doc_choice = _resolve_doc_choice(text, user_key)
            if doc_choice is not None:
                _handle_doc_choice(mid, uid, user_key, doc_choice)
                return

            if not _needs_planning(text):
                _log(f"对话模式: {text[:60]!r}")
                try:
                    answer = _chat_reply(text)
                    reply_message(mid, answer)
                except Exception as e:
                    _log(f"对话回复异常: {e}")
                    reply_message(mid, "抱歉，出了点问题，稍后再试。")
                return

            topic, context, mode = _parse_planning_input(text)
            if not topic:
                reply_card(mid, _welcome())
                return
            with _running_lock:
                if user_key in _running_sessions:
                    reply_card(mid, progress_card(
                        "规划进行中",
                        f"当前主题：**{_running_sessions[user_key][:40]}**\n\n请等当前规划结束后再发起新的。",
                        color="orange",
                    ))
                    return
                _running_sessions[user_key] = topic
            reply_card(mid, progress_card(
                "正在启动理性规划",
                f"**主题：**{topic[:200]}\n**模式：**{mode}\n\n规划过程将实时推送到飞书群，完成后我会通知你。",
            ))
            _log(f"启动规划: topic={topic[:80]!r} mode={mode}")
            try:
                path, planning_outputs = run_planning(topic=topic, context=context, mode=mode)
                done_card = result_card(
                    "规划完成",
                    fields=[("主题", topic[:100]), ("模式", mode), ("会话文件", f"`{path}`")],
                    next_actions=["回复数字生成文档", "发新主题继续规划"],
                )
                if uid:
                    send_card_to_user(uid, done_card)
                else:
                    reply_card(mid, done_card)

                # 生成凝练的文档标题
                short_title = _generate_short_title(topic)

                # 存储规划结果以便后续生成文档
                category = detect_doc_category(topic)
                with _pending_docs_lock:
                    _pending_docs[user_key] = {
                        "topic": topic,
                        "short_title": short_title,
                        "outputs": planning_outputs,
                        "path": path,
                        "open_id": uid,
                        "category": category,
                        "doc_menu": build_doc_menu(category),
                        "ts": time.time(),
                    }
                time.sleep(1)
                menu_card = _doc_menu_card(category)
                if uid:
                    send_card_to_user(uid, menu_card)
                else:
                    reply_card(mid, menu_card)

                _log(f"规划完成: {path}")
            except Exception as e:
                _log(f"规划异常: {e}\n{traceback.format_exc()}")
                err = error_card("规划执行出错", "内部错误，请稍后重试", suggestions=["重新发送主题再试一次"])
                if uid:
                    send_card_to_user(uid, err)
                else:
                    reply_card(mid, err)
            finally:
                with _running_lock:
                    _running_sessions.pop(user_key, None)
        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                reply_card(mid, error_card("处理出错", "内部错误，请稍后重试", suggestions=["重新发送试试"]))
            except Exception:
                pass

    threading.Thread(target=_process, args=(message_id, user_text, open_id), daemon=True).start()


def _handle_bot_p2p_chat_entered(data) -> None:
    _log("用户打开了与机器人的单聊")
    try:
        open_id = None
        if hasattr(data, "event") and data.event:
            user_id = getattr(data.event, "user_id", None) or getattr(data.event, "operator", None)
            if user_id:
                open_id = getattr(user_id, "open_id", None)
        if open_id:
            send_card_to_user(open_id, _welcome())
    except Exception as e:
        _log(f"发送欢迎卡片异常: {e}")


def _handle_message_read(_data) -> None:
    pass


# ── 长连接 ───────────────────────────────────────────────────

RECONNECT_INITIAL_DELAY = 5
RECONNECT_MAX_DELAY = 300
RECONNECT_MULTIPLIER = 2


def _run_client(app_id: str, app_secret: str) -> None:
    # SECURITY TODO: 配置飞书事件订阅的 Verification Token 和 Encrypt Key 以启用签名校验
    # 当前为空字符串，不校验事件来源，生产环境建议配置
    event_handler = (
        EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_handle_message)
        .register_p2_im_chat_access_event_bot_p2p_chat_entered_v1(_handle_bot_p2p_chat_entered)
        .register_p2_im_message_message_read_v1(_handle_message_read)
        .build()
    )
    cli = lark.ws.Client(app_id, app_secret, event_handler=event_handler, log_level=LogLevel.DEBUG, domain="https://open.feishu.cn")
    cli.start()


def main():
    app_id = (os.environ.get("PLANNER_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("PLANNER_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 PLANNER_FEISHU_APP_ID / PLANNER_FEISHU_APP_SECRET\n"
            "（或复用 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )

    # TODO: 传递凭证应通过配置对象而非修改全局环境变量，同进程多机器人时会冲突
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    _log("规划机器人启动")
    print("=" * 60)
    print("理性规划 AI 助手（长连接模式）")
    print()
    print("使用方式：在飞书上给机器人发消息，内容即为规划主题。")
    print()
    print("支持模式：完整规划 | 快速模式 | 分析模式 | 方案模式 | 执行模式")
    print()
    print("断线后将自动重连，无需人工干预。")
    print("=" * 60)

    delay = RECONNECT_INITIAL_DELAY
    attempt = 0
    while True:
        attempt += 1
        _log(f"正在连接飞书… (第 {attempt} 次)")
        try:
            _run_client(app_id, app_secret)
            _log("飞书长连接已断开，将自动重连")
        except Exception as e:
            _log(f"连接失败: {e}\n{traceback.format_exc()}")
            if attempt == 1:
                print("\n若持续失败，请检查应用凭证和网络。", file=sys.stderr)
        wait = min(delay, RECONNECT_MAX_DELAY)
        jitter = random.uniform(0, min(5, wait * 0.2))
        wait += jitter
        _log(f"{wait:.1f} 秒后重连…")
        time.sleep(wait)
        delay = min(delay * RECONNECT_MULTIPLIER, RECONNECT_MAX_DELAY)


if __name__ == "__main__":
    main()
