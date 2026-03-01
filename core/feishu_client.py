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


# ── 电子表格 ─────────────────────────────────────────────────

def _parse_markdown_table(content: str) -> tuple[list[str], list[list[str]], str]:
    """从 Markdown 内容中提取表格数据。

    Returns: (headers, rows, extra_text)
      - headers: 表头列名
      - rows: 数据行
      - extra_text: 表格外的文本（如时间线的"瓶颈"注释）
    """
    lines = content.split("\n")
    table_lines: list[str] = []
    extra_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.count("|") >= 3:
            table_lines.append(stripped)
        elif stripped and stripped not in ("---", "***", "___"):
            extra_lines.append(stripped)

    if not table_lines:
        return [], [], content.strip()

    def _split_row(line: str) -> list[str]:
        cells = line.strip().strip("|").split("|")
        return [c.strip() for c in cells]

    def _is_separator(line: str) -> bool:
        cells = line.strip().strip("|").split("|")
        return all(re.fullmatch(r"[\s\-:]+", c) for c in cells if c.strip())

    headers = _split_row(table_lines[0])
    rows: list[list[str]] = []
    for line in table_lines[1:]:
        if _is_separator(line):
            continue
        row = _split_row(line)
        if any(c for c in row):
            rows.append(row)

    extra_text = "\n".join(extra_lines).strip()
    return headers, rows, extra_text


_THEME_PRESETS = {
    "blue": {
        "header_bg": "#3370FF",
        "header_fg": "#FFFFFF",
        "stripe_bg": "#F0F4FF",
        "border_color": "#D0D5DD",
    },
    "indigo": {
        "header_bg": "#4F46E5",
        "header_fg": "#FFFFFF",
        "stripe_bg": "#EEF2FF",
        "border_color": "#C7D2FE",
    },
    "green": {
        "header_bg": "#16A34A",
        "header_fg": "#FFFFFF",
        "stripe_bg": "#F0FDF4",
        "border_color": "#BBF7D0",
    },
    "gray": {
        "header_bg": "#374151",
        "header_fg": "#FFFFFF",
        "stripe_bg": "#F9FAFB",
        "border_color": "#E5E7EB",
    },
}


def _style_spreadsheet(
    ss_token: str, sheet_id: str,
    headers: list[str], rows: list[list[str]],
    end_col: str, token: str,
    theme: str = "blue",
) -> None:
    """美化飞书电子表格。

    样式包括：主题配色表头、交替行色、全边框、列宽自适应、
    统一行高、冻结首行、垂直居中。所有操作 best-effort。
    """
    hdrs = _headers(token)
    palette = _THEME_PRESETS.get(theme, _THEME_PRESETS["blue"])
    num_rows = len(rows)
    total_rows = 1 + num_rows

    style_url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{ss_token}/styles_batch_update"

    batch_styles = []

    # 1) 表头样式
    batch_styles.append({
        "ranges": f"{sheet_id}!A1:{end_col}1",
        "style": {
            "bold": True,
            "fontSize": 11,
            "foreColor": palette["header_fg"],
            "backColor": palette["header_bg"],
            "hAlign": 1,
            "vAlign": 1,
            "borderType": "FULL_BORDER",
            "borderColor": palette["border_color"],
        },
    })

    # 2) 数据区域：交替行色 + 边框 + 垂直居中
    if num_rows > 0:
        batch_styles.append({
            "ranges": f"{sheet_id}!A2:{end_col}{total_rows}",
            "style": {
                "fontSize": 10,
                "vAlign": 1,
                "borderType": "FULL_BORDER",
                "borderColor": palette["border_color"],
            },
        })

        # 偶数行（第 2, 4, 6… 数据行 → 表格行 3, 5, 7…）加条纹背景
        stripe_ranges = []
        for i in range(1, num_rows, 2):
            row_num = i + 2
            stripe_ranges.append(f"{sheet_id}!A{row_num}:{end_col}{row_num}")
        if stripe_ranges:
            for sr in stripe_ranges[:50]:
                batch_styles.append({
                    "ranges": sr,
                    "style": {"backColor": palette["stripe_bg"]},
                })

    # 发送批量样式请求（单次最多 50 条范围，分批）
    for start in range(0, len(batch_styles), 50):
        chunk = batch_styles[start:start + 50]
        try:
            requests.post(
                style_url,
                json={"data": chunk},
                headers=hdrs, timeout=15,
            )
        except Exception:
            pass

    # 3) 列宽自适应
    dim_url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{ss_token}/dimension_range"
    for col_idx in range(len(headers)):
        max_len = len(headers[col_idx]) if col_idx < len(headers) else 0
        for row in rows:
            if col_idx < len(row):
                cell_val = str(row[col_idx]) if row[col_idx] else ""
                max_len = max(max_len, len(cell_val))
        width = min(max(max_len * 14 + 32, 80), 420)
        try:
            requests.put(dim_url, json={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": "COLUMNS",
                    "startIndex": col_idx,
                    "endIndex": col_idx + 1,
                },
                "dimensionProperties": {"fixedSize": width},
            }, headers=hdrs, timeout=10)
        except Exception:
            pass

    # 4) 统一行高：表头 36px，数据行 30px
    try:
        requests.put(dim_url, json={
            "dimension": {
                "sheetId": sheet_id,
                "majorDimension": "ROWS",
                "startIndex": 0,
                "endIndex": 1,
            },
            "dimensionProperties": {"fixedSize": 36},
        }, headers=hdrs, timeout=10)
    except Exception:
        pass
    if num_rows > 0:
        try:
            requests.put(dim_url, json={
                "dimension": {
                    "sheetId": sheet_id,
                    "majorDimension": "ROWS",
                    "startIndex": 1,
                    "endIndex": total_rows,
                },
                "dimensionProperties": {"fixedSize": 30},
            }, headers=hdrs, timeout=10)
        except Exception:
            pass

    # 5) 冻结首行
    try:
        requests.post(
            f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{ss_token}/sheets_batch_update",
            json={"requests": [{"updateSheet": {"properties": {
                "sheetId": sheet_id,
                "frozenRowCount": 1,
            }}}]},
            headers=hdrs, timeout=10,
        )
    except Exception:
        pass


def create_spreadsheet_with_data(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    extra_text: str = "",
    owner_open_id: Optional[str] = None,
    theme: str = "blue",
) -> Tuple[bool, str]:
    """创建飞书电子表格并写入结构化数据。

    需要飞书应用开通 sheets:spreadsheet 权限。
    theme: 主题色 blue/indigo/green/gray
    """
    token = get_user_access_token("doc_create") or get_tenant_access_token()

    url = f"{FEISHU_API_BASE}/sheets/v3/spreadsheets"
    resp = requests.post(url, json={"title": title}, headers=_headers(token), timeout=15)
    data = resp.json()
    if data.get("code") != 0:
        return False, data.get("msg", "创建表格失败") or str(data)

    ss = (data.get("data") or {}).get("spreadsheet") or {}
    ss_token = ss.get("spreadsheet_token")
    ss_url = ss.get("url") or ""
    if not ss_token:
        return False, "创建表格失败：未返回 token"

    # 获取默认工作表 ID
    meta_url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{ss_token}/metainfo"
    resp2 = requests.get(meta_url, headers=_headers(token), timeout=10)
    d2 = resp2.json()
    sheets_meta = (d2.get("data") or {}).get("sheets") or []
    sheet_id = sheets_meta[0].get("sheetId") if sheets_meta else None
    if not sheet_id:
        query_url = f"{FEISHU_API_BASE}/sheets/v3/spreadsheets/{ss_token}/sheets/query"
        resp2b = requests.get(query_url, headers=_headers(token), timeout=10)
        d2b = resp2b.json()
        sheets_v3 = (d2b.get("data") or {}).get("sheets") or []
        sheet_id = sheets_v3[0].get("sheet_id") if sheets_v3 else None
    if not sheet_id:
        return False, "无法获取工作表 ID"

    all_data = [headers] + rows
    if extra_text:
        all_data.append([""] * len(headers))
        all_data.append([extra_text] + [""] * (len(headers) - 1))

    num_cols = max(len(r) for r in all_data) if all_data else 1
    padded = [r + [""] * (num_cols - len(r)) for r in all_data]

    def _col_letter(n: int) -> str:
        result = ""
        while n > 0:
            n, remainder = divmod(n - 1, 26)
            result = chr(65 + remainder) + result
        return result

    end_col = _col_letter(num_cols)
    num_rows = len(padded)
    range_str = f"{sheet_id}!A1:{end_col}{num_rows}"

    write_url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{ss_token}/values"
    resp3 = requests.put(
        write_url,
        json={"valueRange": {"range": range_str, "values": padded}},
        headers=_headers(token),
        timeout=30,
    )
    d3 = resp3.json()
    if d3.get("code") != 0:
        _warn(f"写入表格数据失败: code={d3.get('code')} msg={d3.get('msg')}")

    _style_spreadsheet(ss_token, sheet_id, headers, rows, end_col, token, theme=theme)

    if owner_open_id:
        perm_url = f"{FEISHU_API_BASE}/drive/v1/permissions/{ss_token}/members"
        try:
            requests.post(
                perm_url, params={"type": "sheet"},
                json={"member_type": "openid", "member_id": owner_open_id, "perm": "full_access"},
                headers=_headers(token), timeout=10,
            )
        except Exception:
            pass

    if not ss_url:
        base = (os.environ.get("FEISHU_DOC_BASE_URL") or "").strip().rstrip("/")
        if not base:
            base = "feishu.cn"
        ss_url = f"https://{base}/sheets/{ss_token}" if not base.startswith("http") else f"{base}/sheets/{ss_token}"

    return True, ss_url


def create_spreadsheet_detail(
    title: str,
    headers: list[str],
    rows: list[list[str]],
    owner_open_id: Optional[str] = None,
    theme: str = "indigo",
) -> Tuple[bool, dict]:
    """创建电子表格并返回详细信息（供项目注册用）。

    Returns: (ok, {"url", "spreadsheet_token", "sheet_id"} | error_str)
    """
    ok, url_or_err = create_spreadsheet_with_data(
        title=title, headers=headers, rows=rows,
        owner_open_id=owner_open_id, theme=theme,
    )
    if not ok:
        return False, {"error": url_or_err}

    ss_url = url_or_err
    ss_token = ""
    if "/sheets/" in ss_url:
        ss_token = ss_url.split("/sheets/")[-1].split("?")[0].split("/")[0]

    sheet_id = ""
    if ss_token:
        try:
            meta_url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{ss_token}/metainfo"
            t = get_user_access_token("doc_create") or get_tenant_access_token()
            resp = requests.get(meta_url, headers=_headers(t), timeout=10)
            sheets_meta = (resp.json().get("data") or {}).get("sheets") or []
            sheet_id = sheets_meta[0].get("sheetId", "") if sheets_meta else ""
        except Exception:
            pass

    return True, {
        "url": ss_url,
        "spreadsheet_token": ss_token,
        "sheet_id": sheet_id,
    }


# ── 飞书妙记（Minutes）──────────────────────────────────────
# 只能通过 minute_token 获取单条元数据（标题/时长/创建者），无列出/搜索 API。

def get_minutes_info(minute_token: str) -> Tuple[bool, dict]:
    """获取妙记基本信息。

    Args:
        minute_token: 24 位妙记标识，可从链接末尾提取。

    Returns: (ok, {title, owner_id, create_time, duration, url} | {error})
    """
    try:
        url = f"{FEISHU_API_BASE}/minutes/v1/minutes/{minute_token}"
        resp = requests.get(url, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            return False, {"error": data.get("msg", "获取妙记失败") or str(data)}
        minute = (data.get("data") or {}).get("minute") or {}
        dur_ms = int(minute.get("duration", 0) or 0)
        dur_min = dur_ms // 60000
        return True, {
            "title": minute.get("title", ""),
            "owner_id": minute.get("owner_id", ""),
            "create_time": minute.get("create_time", ""),
            "duration": f"{dur_min}分钟",
            "url": minute.get("url", ""),
            "token": minute.get("token", minute_token),
        }
    except Exception as e:
        return False, {"error": f"获取妙记异常: {e}"}


def extract_minute_token(text: str) -> Optional[str]:
    """从文本中提取飞书妙记链接的 minute_token。"""
    import re
    m = re.search(r'feishu\.cn/minutes/([a-zA-Z0-9]{20,})', text)
    if m:
        return m.group(1)
    m2 = re.search(r'larkoffice\.com/minutes/([a-zA-Z0-9]{20,})', text)
    if m2:
        return m2.group(1)
    return None


def create_spreadsheet_from_markdown(
    title: str,
    content: str,
    owner_open_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """从 Markdown 表格内容创建飞书电子表格。

    解析内容中的 Markdown 表格，写入飞书 Sheet。
    如无有效表格数据，返回 (False, reason)。
    """
    headers, rows, extra = _parse_markdown_table(content)
    if not headers or not rows:
        return False, "未找到有效的表格数据"
    return create_spreadsheet_with_data(title, headers, rows, extra, owner_open_id, theme="gray")


# ── 项目看板（基于电子表格）──────────────────────────────────
# 用已有的 create_spreadsheet_with_data 创建项目管理表格。

PROJECT_BOARD_HEADERS = ["任务名称", "负责人", "状态", "优先级", "截止日期", "备注"]


def create_project_board(
    name: str,
    tasks: Optional[list[dict]] = None,
    owner_open_id: Optional[str] = None,
) -> Tuple[bool, str]:
    """一步创建项目看板电子表格。

    Args:
        name: 项目名称
        tasks: 初始任务，如 [{"任务名称": "设计", "负责人": "张三", "状态": "待开始"}, ...]
        owner_open_id: 授予编辑权限的用户

    Returns: (ok, url_or_error)
    """
    headers = PROJECT_BOARD_HEADERS
    rows: list[list[str]] = []
    for t in (tasks or []):
        row = [str(t.get(h, "")) for h in headers]
        rows.append(row)
    if not rows:
        rows.append(["（示例）确定项目目标", "", "待开始", "P1-重要", "", ""])
    return create_spreadsheet_with_data(
        title=f"📋 {name}",
        headers=headers,
        rows=rows,
        owner_open_id=owner_open_id,
        theme="indigo",
    )


def append_spreadsheet_rows(
    spreadsheet_token: str,
    sheet_id: str,
    rows: list[list[str]],
) -> Tuple[bool, str]:
    """往已有电子表格追加行。"""
    try:
        url = f"{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}/values_append"
        num_cols = max(len(r) for r in rows) if rows else 1
        end_col = chr(64 + min(num_cols, 26))
        range_str = f"{sheet_id}!A1:{end_col}1"
        padded = [r + [""] * (num_cols - len(r)) for r in rows]
        resp = requests.post(
            url,
            json={"valueRange": {"range": range_str, "values": padded}},
            headers=_headers(),
            timeout=15,
        )
        data = resp.json()
        if data.get("code") != 0:
            return False, data.get("msg", "追加行失败") or str(data)
        return True, f"已追加 {len(rows)} 行"
    except Exception as e:
        return False, f"追加行异常: {e}"


# ── 飞书任务（Task）──────────────────────────────────────────
# 轻量级任务管理：创建的任务会出现在飞书「任务中心」。
# 用 tenant_access_token 创建的任务归应用所有，需要加执行者后对方才能看到。
# 权限要求：task:task:readwrite

def create_task(
    summary: str,
    description: str = "",
    due_timestamp: Optional[str] = None,
    collaborator_open_ids: Optional[list[str]] = None,
) -> Tuple[bool, str, str]:
    """创建飞书任务。

    Args:
        summary: 任务标题
        description: 任务描述
        due_timestamp: 截止时间戳（秒）
        collaborator_open_ids: 执行者 open_id 列表

    Returns: (ok, task_id_or_error, message)
    """
    try:
        url = f"{FEISHU_API_BASE}/task/v1/tasks"
        body: dict = {"summary": summary}
        if description:
            body["description"] = description
        if due_timestamp:
            body["due"] = {"timestamp": str(due_timestamp), "is_all_day": False}
        resp = requests.post(url, json=body, headers=_headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            return False, data.get("msg", "创建任务失败") or str(data), ""
        task = (data.get("data") or {}).get("task") or {}
        task_id = task.get("id", "")
        if not task_id:
            return False, "创建成功但未返回 task_id", ""

        added = []
        for oid in (collaborator_open_ids or []):
            if oid:
                _add_task_collaborator(task_id, oid)
                added.append(oid)

        msg = f"任务已创建"
        if added:
            msg += f"，已分配给 {len(added)} 人"
        return True, task_id, msg
    except Exception as e:
        return False, f"创建任务异常: {e}", ""


def _add_task_collaborator(task_id: str, open_id: str) -> bool:
    try:
        url = f"{FEISHU_API_BASE}/task/v1/tasks/{task_id}/collaborators"
        resp = requests.post(
            url, json={"id": open_id, "id_type": "open_id"},
            headers=_headers(), timeout=10,
        )
        return resp.json().get("code") == 0
    except Exception:
        return False


def complete_task(task_id: str) -> Tuple[bool, str]:
    """完成飞书任务。"""
    try:
        url = f"{FEISHU_API_BASE}/task/v1/tasks/{task_id}"
        resp = requests.patch(
            url, json={"task": {"status": "completed"}},
            headers=_headers(), timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            return False, data.get("msg", "完成任务失败") or str(data)
        return True, "任务已标记完成"
    except Exception as e:
        return False, f"完成任务异常: {e}"
