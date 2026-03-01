# -*- coding: utf-8 -*-
"""
飞书开放平台 API 客户端 —— 所有和飞书交互的操作都在这里。
==========================================================

本模块封装了飞书 API 的常用操作，机器人通过它：
  - 给用户回复/主动发送消息（文本 + 消息卡片）
  - 操作日历（创建日程、查看日程）
  - 创建飞书文档并写入内容
  - OAuth 授权流程（获取用户级别的 token）

认证机制说明（小白必读）：
  飞书 API 有两种身份：
  1. tenant_access_token（应用身份）：用 App ID + App Secret 获取，
     可以发消息、读公开数据，大部分操作都用这个。
  2. user_access_token（用户身份）：需要用户授权后获取，
     用于操作用户个人日历等隐私数据。

  本模块会自动缓存 token，过期前 60 秒刷新，不需要手动管理。
"""
import json
import os
import re
import sys
import threading
import time
from typing import List, Optional, Tuple

import requests

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"

# ── Token 缓存 ──────────────────────────────────────────────
# 缓存已获取的 token 和过期时间，避免每次 API 调用都重新申请。
# token 有效期约 2 小时，提前 60 秒刷新以防止过期请求失败。

_token_cache: Optional[str] = None
_token_expire_at: float = 0.0
_app_token_cache: Optional[str] = None
_app_token_expire_at: float = 0.0
_token_lock = threading.Lock()


def _warn(msg: str) -> None:
    print(f"[Feishu API] {msg}", file=sys.stderr, flush=True)


def get_tenant_access_token() -> str:
    global _token_cache, _token_expire_at
    now = time.time()
    if _token_cache and _token_expire_at > now + 60:
        return _token_cache
    with _token_lock:
        now = time.time()
        if _token_cache and _token_expire_at > now + 60:
            return _token_cache
        app_id = (os.environ.get("FEISHU_APP_ID") or "").strip()
        app_secret = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
        if not app_id or not app_secret:
            raise ValueError("请设置环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
        _token_cache = data["tenant_access_token"]
        _token_expire_at = now + data.get("expire", 7200)
        return _token_cache


def get_app_access_token() -> str:
    global _app_token_cache, _app_token_expire_at
    now = time.time()
    if _app_token_cache and _app_token_expire_at > now + 60:
        return _app_token_cache
    with _token_lock:
        now = time.time()
        if _app_token_cache and _app_token_expire_at > now + 60:
            return _app_token_cache
        app_id = (os.environ.get("FEISHU_APP_ID") or "").strip()
        app_secret = (os.environ.get("FEISHU_APP_SECRET") or "").strip()
        if not app_id or not app_secret:
            raise ValueError("请设置环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET")
        url = f"{FEISHU_API_BASE}/auth/v3/app_access_token/internal"
        resp = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 app_access_token 失败: {data}")
        _app_token_cache = data["app_access_token"]
        _app_token_expire_at = now + data.get("expire", 7200)
        return _app_token_cache


def _headers(access_token: Optional[str] = None) -> dict:
    token = access_token or get_tenant_access_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ── 按 scope 读取 user token ────────────────────────────────
# 某些操作（如写入用户个人日历）需要用户级 token。
# 这些 token 按「权限范围(scope)」分别存储在不同的环境变量中，
# 需要用户先通过 OAuth 授权获取，然后手动填入 .env 文件。

_TOKEN_SCOPE_ENV = {
    "calendar_get": "FEISHU_TOKEN_CALENDAR_GET",
    "calendar_create": "FEISHU_TOKEN_CALENDAR_CREATE",
    "calendar_update": "FEISHU_TOKEN_CALENDAR_UPDATE",
    "calendar_delete": "FEISHU_TOKEN_CALENDAR_DELETE",
    "doc_create": "FEISHU_TOKEN_DOC_CREATE",
}


def get_user_access_token(scope: Optional[str] = None) -> Optional[str]:
    if not scope:
        return None
    env_key = _TOKEN_SCOPE_ENV.get(scope)
    if not env_key:
        return None
    t = (os.environ.get(env_key) or "").strip()
    return t or None


# ── OAuth ────────────────────────────────────────────────────

def get_oauth_authorize_url(redirect_uri: str, state: str = "feishu_oauth") -> str:
    app_id = (os.environ.get("FEISHU_APP_ID") or "").strip()
    if not app_id:
        raise ValueError("请设置环境变量 FEISHU_APP_ID")
    from urllib.parse import quote
    scope = "contact:user.base:readonly calendar:calendar:read_as_user calendar:calendar_event:write_as_user"
    base = "https://open.feishu.cn/open-apis/authen/v1/authorize"
    return f"{base}?app_id={quote(app_id)}&redirect_uri={quote(redirect_uri)}&scope={quote(scope)}&state={quote(state)}"


def exchange_code_for_user_token(code: str) -> Tuple[bool, str, Optional[str]]:
    app_token = get_app_access_token()
    url = f"{FEISHU_API_BASE}/authen/v1/access_token"
    headers = {"Authorization": f"Bearer {app_token}", "Content-Type": "application/json"}
    resp = requests.post(url, json={"grant_type": "authorization_code", "code": code}, headers=headers, timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        return False, data.get("msg", str(data)) or "兑换 token 失败", None
    d = data.get("data") or {}
    access_token = d.get("access_token")
    if not access_token:
        return False, "响应中无 access_token", None
    return True, access_token, d.get("refresh_token")


# ── 消息 ─────────────────────────────────────────────────────

def reply_message(message_id: str, text: str) -> dict:
    url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
    payload = {"msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)}
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"回复消息失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"回复消息异常: {e}")
        return {"code": -1, "msg": str(e)}


def send_message_to_user(open_id: str, text: str) -> dict:
    url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
    payload = {
        "receive_id": open_id,
        "msg_type": "text",
        "content": json.dumps({"text": text}, ensure_ascii=False),
    }
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"主动发消息失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"主动发消息异常: {e}")
        return {"code": -1, "msg": str(e)}


def reply_card(message_id: str, card: dict) -> dict:
    """用消息卡片回复。card 是完整的 interactive card JSON。"""
    url = f"{FEISHU_API_BASE}/im/v1/messages/{message_id}/reply"
    payload = {
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"回复卡片失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"回复卡片异常: {e}")
        return {"code": -1, "msg": str(e)}


def send_card_to_user(open_id: str, card: dict) -> dict:
    """主动给用户发送消息卡片。"""
    url = f"{FEISHU_API_BASE}/im/v1/messages?receive_id_type=open_id"
    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
    }
    try:
        resp = requests.post(url, json=payload, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            _warn(f"主动发卡片失败 code={data.get('code')} msg={data.get('msg')}")
        return data
    except Exception as e:
        _warn(f"主动发卡片异常: {e}")
        return {"code": -1, "msg": str(e)}


# ── 日历 ─────────────────────────────────────────────────────

def get_primary_calendar_id(open_id: str, user_access_token: Optional[str] = None) -> Optional[str]:
    try:
        token = user_access_token or get_user_access_token("calendar_get")
        if token:
            url = f"{FEISHU_API_BASE}/calendar/v4/calendars/primary"
            resp = requests.post(url, json={}, headers=_headers(token), timeout=10)
        else:
            url = f"{FEISHU_API_BASE}/calendar/v4/calendars/primarys?user_id_type=open_id"
            resp = requests.post(url, json={"user_ids": [open_id]}, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            return None
        calendars = (data.get("data") or {}).get("calendars") or []
        if not calendars:
            return None
        first = calendars[0]
        cal = first.get("calendar") if isinstance(first, dict) else None
        return cal.get("calendar_id") if cal else None
    except Exception:
        return None


def create_calendar_event(
    calendar_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    description: str = "",
    user_access_token: Optional[str] = None,
) -> Tuple[bool, str]:
    try:
        token = user_access_token or get_user_access_token("calendar_create")
        from datetime import datetime

        def to_ts(s: str) -> str:
            s = s.strip()
            if s.isdigit():
                return s
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                return str(int(dt.timestamp()))
            except Exception:
                return s

        start_ts, end_ts = to_ts(start_time), to_ts(end_time)
        url = f"{FEISHU_API_BASE}/calendar/v4/calendars/{calendar_id}/events"
        payload = {
            "summary": summary,
            "description": description or "",
            "start_time": {"timestamp": start_ts},
            "end_time": {"timestamp": end_ts},
        }
        resp = requests.post(url, json=payload, headers=_headers(token), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            return False, data.get("msg", "创建日程失败") or str(data)
        event = (data.get("data") or {}).get("event") or {}
        if isinstance(event, dict) and event.get("event_id"):
            return True, "已帮你加入日历。请打开飞书「日历」查看。"
        return True, "已帮你加入日历"
    except Exception as e:
        return False, f"创建日程异常: {e}"


def list_calendar_events(
    calendar_id: str,
    start_ts: int,
    end_ts: int,
    user_access_token: Optional[str] = None,
) -> List[dict]:
    try:
        token = user_access_token or get_user_access_token("calendar_get")
        url = f"{FEISHU_API_BASE}/calendar/v4/calendars/{calendar_id}/events"
        params = {"start_time": str(start_ts), "end_time": str(end_ts), "page_size": 100}
        resp = requests.get(url, params=params, headers=_headers(token), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            return []
        items = (data.get("data") or {}).get("items") or []
        return items if isinstance(items, list) else []
    except Exception:
        return []


# ── 文档 ─────────────────────────────────────────────────────

_BLOCK_BATCH_SIZE = 50


def _parse_inline(text: str) -> list:
    """解析行内 Markdown（**加粗**）为飞书 text_run 元素。"""
    elements = []
    parts = re.split(r"(\*\*.*?\*\*)", text)
    for part in parts:
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            elements.append({
                "text_run": {
                    "content": part[2:-2],
                    "text_element_style": {"bold": True},
                }
            })
        else:
            elements.append({"text_run": {"content": part}})
    return elements or [{"text_run": {"content": text or ""}}]


def _markdown_to_blocks(content: str) -> list:
    """将 Markdown 文本转换为飞书 DocX block 数组。

    支持：# 标题 / **加粗** / - 列表 / 1. 有序列表 / > 引用 / - [ ] 待办
    连续表格行合并为代码块保持等宽对齐，分割线(---)跳过。
    """
    blocks: list[dict] = []
    lines = content.split("\n")
    i = 0

    def _flush_table(table_lines: list[str]) -> None:
        if not table_lines:
            return
        code_text = "\n".join(table_lines)
        blocks.append({
            "block_type": 14,
            "code": {
                "elements": [{"text_run": {"content": code_text}}],
                "style": {"language": 1},
            },
        })

    table_buf: list[str] = []

    while i < len(lines):
        stripped = lines[i].strip()
        i += 1

        if not stripped:
            _flush_table(table_buf)
            table_buf = []
            continue

        if stripped in ("---", "***", "___"):
            _flush_table(table_buf)
            table_buf = []
            continue

        # 表格行（含分隔行）收集到 buffer
        if stripped.startswith("|"):
            table_buf.append(stripped)
            continue

        # 非表格行：先 flush 已有的表格
        _flush_table(table_buf)
        table_buf = []

        if stripped.startswith("### "):
            blocks.append({"block_type": 5, "heading3": {"elements": _parse_inline(stripped[4:])}})
        elif stripped.startswith("## "):
            blocks.append({"block_type": 4, "heading2": {"elements": _parse_inline(stripped[3:])}})
        elif stripped.startswith("# "):
            blocks.append({"block_type": 3, "heading1": {"elements": _parse_inline(stripped[2:])}})
        elif stripped.startswith("- [ ] "):
            blocks.append({"block_type": 2, "text": {"elements": _parse_inline("☐ " + stripped[6:])}})
        elif stripped.startswith(("- [x] ", "- [X] ")):
            blocks.append({"block_type": 2, "text": {"elements": _parse_inline("☑ " + stripped[6:])}})
        elif stripped.startswith("- ") or stripped.startswith("* "):
            blocks.append({"block_type": 12, "bullet": {"elements": _parse_inline(stripped[2:])}})
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            blocks.append({"block_type": 13, "ordered": {"elements": _parse_inline(text)}})
        elif stripped.startswith("> "):
            blocks.append({"block_type": 2, "text": {"elements": _parse_inline("「" + stripped[2:] + "」")}})
        else:
            blocks.append({"block_type": 2, "text": {"elements": _parse_inline(stripped)}})

    _flush_table(table_buf)
    return blocks or [{"block_type": 2, "text": {"elements": [{"text_run": {"content": ""}}]}}]


def _plain_text_blocks(content: str) -> list:
    """降级方案：全部转为纯文本段落。"""
    lines = [l.strip() for l in content.split("\n") if l.strip()] or [""]
    return [{"block_type": 2, "text": {"elements": [{"text_run": {"content": l}}]}} for l in lines]


def create_document_with_content(
    title: str,
    content: str,
    owner_open_id: Optional[str] = None,
    doc_create_token: Optional[str] = None,
) -> Tuple[bool, str]:
    token = doc_create_token or get_user_access_token("doc_create")
    url = f"{FEISHU_API_BASE}/docx/v1/documents"
    resp = requests.post(url, json={"title": title}, headers=_headers(token), timeout=10)
    data = resp.json()
    if data.get("code") != 0:
        return False, data.get("msg", "创建文档失败") or str(data)
    doc = (data.get("data") or {}).get("document") or {}
    doc_id, revision_id = doc.get("document_id"), doc.get("revision_id")
    if not doc_id or revision_id is None:
        return False, "创建文档失败"

    blocks_url = f"{FEISHU_API_BASE}/docx/v1/documents/{doc_id}/blocks"
    resp2 = requests.get(blocks_url, params={"document_revision_id": -1, "page_size": 20}, headers=_headers(token), timeout=10)
    d2 = resp2.json()
    items = (d2.get("data") or {}).get("items") or []
    root_block = items[0].get("block_id") if items and isinstance(items[0], dict) else None
    if not root_block:
        return False, "无法获取文档结构"

    try:
        children = _markdown_to_blocks(content)
    except Exception:
        children = _plain_text_blocks(content)

    write_url = f"{FEISHU_API_BASE}/docx/v1/documents/{doc_id}/blocks/{root_block}/children"
    write_ok = False
    for start in range(0, len(children), _BLOCK_BATCH_SIZE):
        batch = children[start:start + _BLOCK_BATCH_SIZE]
        resp3 = requests.post(
            write_url,
            params={"document_revision_id": -1},
            json={"children": batch, "index": start},
            headers=_headers(token),
            timeout=30,
        )
        d3 = resp3.json()
        if d3.get("code") != 0:
            if start == 0:
                # 首批失败：降级为纯文本重试
                _warn(f"格式化写入失败 code={d3.get('code')}，降级纯文本重试")
                children = _plain_text_blocks(content)
                for fallback_start in range(0, len(children), _BLOCK_BATCH_SIZE):
                    fb = children[fallback_start:fallback_start + _BLOCK_BATCH_SIZE]
                    requests.post(
                        write_url,
                        params={"document_revision_id": -1},
                        json={"children": fb, "index": fallback_start},
                        headers=_headers(token),
                        timeout=30,
                    )
                write_ok = True
                break
            _warn(f"第 {start} 批写入失败: {d3.get('msg')}")
            break
        write_ok = True

    if not write_ok:
        return False, "写入内容失败"

    if owner_open_id:
        perm_url = f"{FEISHU_API_BASE}/drive/v1/permissions/{doc_id}/members"
        requests.post(
            perm_url, params={"type": "docx"},
            json={"member_type": "openid", "member_id": owner_open_id, "perm": "full_access"},
            headers=_headers(token), timeout=10,
        )

    base = (os.environ.get("FEISHU_DOC_BASE_URL") or "").strip().rstrip("/")
    if not base:
        base = "feishu.cn"
    doc_url = f"https://{base}/docx/{doc_id}" if not base.startswith("http") else f"{base}/docx/{doc_id}"
    return True, doc_url
