# -*- coding: utf-8 -*-
"""
助手机器人 —— 你的飞书日常工作伴侣。
=====================================

这是什么？
  在飞书上和这个机器人对话，它能帮你管理备忘、操作日历、
  每天自动推送简报，还能做 AI 对话。

四大功能：
  1. 备忘管理：发「备忘 买牛奶」就记下来，发「备忘列表」就查看
  2. 日程管理：发「明天下午3点开会」自动加入飞书日历
  3. 每日简报：08:00 自动推送今日安排，18:00 推送收尾 checklist
  4. AI 对话 ：其他消息走 DeepSeek 自由对话

消息处理逻辑（按优先级）：
  用户消息 → 帮助？ → 关键词匹配（备忘/待办/清除）
           → AI 意图解析 → 分发到对应处理函数
           → 都不匹配？走自由对话

运行：python3 -m assistant
环境变量：ASSISTANT_FEISHU_APP_ID / ASSISTANT_FEISHU_APP_SECRET（或复用 FEISHU_APP_ID）
"""
import json
import os
import re
import random
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import lark_oapi as lark
from lark_oapi import EventDispatcherHandler, LogLevel

from core.feishu_client import (
    reply_message, reply_card,
    send_message_to_user, send_card_to_user,
    get_primary_calendar_id,
    create_calendar_event,
    get_user_access_token,
)
from core.cards import welcome_card, action_card, help_card, error_card
from core.llm import chat
from memo.intent import parse_intent
from memo.store import (
    add_memo as store_add_memo,
    list_memos as store_list_memos,
    delete_memo_by_index as store_delete_memo_by_index,
    set_memo_category_by_index as store_set_memo_category_by_index,
    list_threads as store_list_threads,
    thread_summary as store_thread_summary,
    get_due_reminders,
    mark_reminder_sent,
    MEMO_CATEGORY_DISPLAY,
    MEMO_CATEGORIES,
)
from memo.threads import extract_thread_tag, detect_thread
from cal.aggregator import aggregate_for_date
from cal.push_target import save_push_target_open_id

# ── 日志 ─────────────────────────────────────────────────────

_bot_log_path: Optional[str] = None
_log_lock = threading.Lock()


def _log(msg: str) -> None:
    global _bot_log_path
    line = f"[AssistantBot] {msg}"
    print(line, file=sys.stderr, flush=True)
    with _log_lock:
        if _bot_log_path is None:
            _bot_log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bot_assistant.log")
        try:
            with open(_bot_log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}\n")
        except Exception:
            pass


# ── 工具函数 ─────────────────────────────────────────────────

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


def _parse_memo_content_and_category(text: str) -> tuple[str, Optional[str]]:
    """旧版分类解析，保留兼容。"""
    t = (text or "").strip()
    for name, key in MEMO_CATEGORIES.items():
        tag = f"#{name}"
        if tag in t:
            parts = t.split(tag, 1)
            content = (parts[0] + (parts[1] or "")).strip().replace("  ", " ").strip()
            return content or t.replace(tag, "").strip(), key
    return t, None


def _parse_memo_with_thread(text: str) -> tuple[str, Optional[str], str]:
    """
    从备忘文本中提取内容、旧分类和 #线程 标签。

    「Starboard 策展流程 #creator」→ ("Starboard 策展流程", None, "creator")
    「写周报 #要事」→ ("写周报", "project", "")  (旧分类兼容)
    「对话系统用三层架构」→ ("对话系统用三层架构", None, "催婚")  (自动识别)
    """
    t = (text or "").strip()
    content, old_cat = _parse_memo_content_and_category(t)
    if old_cat:
        return content, old_cat, ""

    content, thread_tag = extract_thread_tag(t)
    if thread_tag:
        return content, None, thread_tag

    existing = [info["thread"] for info in store_list_threads() if info["thread"] != "(未分类)"]
    auto_thread = detect_thread(content, existing_threads=existing)
    return content, None, auto_thread


def _memo_category_tag(memo: dict) -> str:
    key = memo.get("category") or ""
    if not key:
        return ""
    name = MEMO_CATEGORY_DISPLAY.get(key, "")
    return f"[{name}] " if name else ""


# ── 消息处理 ─────────────────────────────────────────────────

def _handle_message(data: lark.im.v1.P2ImMessageReceiveV1) -> None:
    _log("收到消息事件")
    message_id = None
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
        if open_id:
            save_push_target_open_id(open_id)
        _log(f"message_id={message_id!r} open_id={open_id!r} 文本长度={len(user_text)}")
        if not user_text:
            threading.Thread(
                target=lambda: reply_card(message_id, _welcome()),
                daemon=True,
            ).start()
            return
    except Exception as e:
        _log(f"解析消息异常: {e}\n{traceback.format_exc()}")
        return

    def _process(mid: str, text: str, user_open_id: Optional[str]):
        try:
            t = (text or "").strip()

            # 帮助
            if t.lower() in ("帮助", "help", "?", "？"):
                reply_card(mid, _help())
                return

            # ── 关键词快速匹配：备忘 ──
            prefixes = (
                "备忘 ", "备忘：", "备忘:", "记一下 ", "记一下：", "记一下:",
                "别忘了 ", "别忘了：", "别忘了:", "任务 ", "任务：", "任务:",
                "待办 ", "待办：", "待办:",
            )
            for prefix in prefixes:
                if t.startswith(prefix):
                    raw_content = t[len(prefix):].strip()
                    if not raw_content:
                        reply_message(mid, "请说一下要记的内容，例如：任务 写周报")
                        return
                    content, category, thread = _parse_memo_with_thread(raw_content)
                    if not content:
                        reply_message(mid, "请说一下要记的内容，例如：任务 写周报")
                        return
                    store_add_memo(content, user_open_id=user_open_id, category=category, thread=thread)
                    tag_hint = ""
                    if thread:
                        tag_hint = f" #{thread}"
                    elif category:
                        tag_hint = f"（{MEMO_CATEGORY_DISPLAY.get(category, category)}）"
                    reply_card(mid, action_card(
                        f"📝 已记下备忘{tag_hint}",
                        f"**{content[:100]}**",
                        hints=["发「线程」查看工作线程", "发「备忘列表」查看全部"],
                        color="green",
                    ))
                    _log(f"备忘(关键词): 已写入 thread={thread}")
                    return

            if t.lower().startswith("todo ") or t.lower().startswith("todo:"):
                raw_content = t[5:].lstrip(" :").strip()
                if raw_content:
                    content, category, thread = _parse_memo_with_thread(raw_content)
                    store_add_memo(content, user_open_id=user_open_id, category=category, thread=thread)
                    tag_hint = f" #{thread}" if thread else ""
                    reply_card(mid, action_card(
                        f"📝 已记下备忘{tag_hint}",
                        f"**{content[:100]}**",
                        hints=["发「线程」查看工作线程", "发「备忘列表」查看全部"],
                        color="green",
                    ))
                    _log(f"todo(关键词): 已写入 thread={thread}")
                    return

            if t in ("备忘", "记一下", "别忘了", "任务", "待办"):
                reply_message(mid, "请说「备忘 具体内容」或「任务 具体内容」～")
                return

            # ── 清除备忘 ──
            m_clear = re.match(r"^(清除备忘|删除备忘)\s*[：:]\s*(\d+)$", t)
            if not m_clear:
                m_clear = re.match(r"^(清除备忘|删除备忘)\s+(\d+)$", t)
            if m_clear:
                try:
                    idx = int(m_clear.group(2))
                    ok, msg_text = store_delete_memo_by_index(idx, user_open_id=user_open_id)
                    reply_message(mid, msg_text)
                    return
                except ValueError:
                    pass

            # ── 设置分类 ──
            m_set_cat = (
                re.match(r"^(?:把)?第\s*(\d+)\s*条\s*(?:标成|设为|标为)\s*(日常|灵感|要事)\s*$", t)
                or re.match(r"^(日常|灵感|要事)\s*[：:]\s*第\s*(\d+)\s*条\s*$", t)
            )
            if m_set_cat:
                if m_set_cat.lastindex == 2 and m_set_cat.group(1).isdigit():
                    idx, cat = int(m_set_cat.group(1)), m_set_cat.group(2)
                else:
                    cat, idx = m_set_cat.group(1), int(m_set_cat.group(2))
                ok, msg_text = store_set_memo_category_by_index(idx, cat, user_open_id=user_open_id)
                reply_message(mid, msg_text)
                return

            # ── 意图解析 ──
            _log("解析意图...")
            intent = parse_intent(text)
            action = intent.get("action", "chat")
            params = intent.get("params") or {}
            reply = intent.get("reply") or ""
            _log(f"意图: action={action}")

            # ── 加日历 ──
            if action == "add_calendar" and user_open_id:
                title = params.get("title") or "日程"
                start_time = params.get("start_time") or ""
                end_time = params.get("end_time") or ""
                if not start_time or not end_time:
                    reply_message(mid, "加日历需要明确开始和结束时间，请再说清楚一点～")
                    return
                cal_token_create = get_user_access_token("calendar_create")
                cal_id = (os.environ.get("FEISHU_CALENDAR_ID") or "").strip()
                if not cal_id:
                    cal_token_get = get_user_access_token("calendar_get")
                    cal_id = get_primary_calendar_id(user_open_id, user_access_token=cal_token_get)
                if not cal_id:
                    reply_message(mid, "无法获取你的日历，请配置 FEISHU_TOKEN_CALENDAR_GET 后重试。")
                    return
                ok, msg_text = create_calendar_event(
                    cal_id, title, start_time, end_time,
                    params.get("description") or "",
                    user_access_token=cal_token_create,
                )
                if not ok and ("access_role" in msg_text.lower() or "no calendar" in msg_text.lower()) and not cal_token_create:
                    msg_text = "往你的个人日历里加日程需要「用户身份」授权。请在 .env 中配置 FEISHU_TOKEN_CALENDAR_CREATE 后再试。"
                reply_message(mid, msg_text)
                return

            # ── 备忘相关 ──
            if action in ("add_todo", "add_task"):
                content = (params.get("title") or params.get("summary") or params.get("content") or text).strip()
                for prefix in ("待办 ", "待办：", "待办:", "任务 ", "任务：", "任务:", "todo "):
                    if content.lower().startswith(prefix) or content.startswith(prefix):
                        content = content[len(prefix):].strip()
                        break
                store_add_memo(content or "未命名", user_open_id=user_open_id)
                reply_message(mid, "已记下备忘～")
                return

            if action == "add_memo":
                raw = params.get("content") or text.strip()
                content, category, thread = _parse_memo_with_thread(raw)
                if not content:
                    reply_message(mid, "请说一下要记的备忘内容～")
                    return
                if not thread:
                    thread = (params.get("thread") or "").strip()
                reminder = (params.get("reminder_date") or "").strip() or None
                store_add_memo(content, user_open_id=user_open_id, reminder_date=reminder, category=category, thread=thread)
                tag_hint = f" #{thread}" if thread else ""
                date_hint = f"（提醒：{reminder}）" if reminder else ""
                reply_message(mid, f"已记下备忘～{tag_hint}{date_hint}")
                return

            if action == "list_memos":
                memos = store_list_memos(limit=10, user_open_id=user_open_id)
                if not memos:
                    reply_card(mid, action_card("📋 暂无备忘", hints=["发「备忘 内容」开始记"], color="blue"))
                    return
                lines = []
                for i, m in enumerate(memos, 1):
                    lines.append(f"{i}. {_memo_category_tag(m)}{m.get('content', '')}")
                reply_card(mid, action_card(
                    f"📋 备忘列表（{len(memos)} 条）",
                    "\n".join(lines)[:2000],
                    hints=["「清除备忘 3」删除", "「第2条标成灵感」改分类"],
                    color="blue",
                ))
                return

            if action == "list_tasks":
                memos = store_list_memos(limit=10, user_open_id=user_open_id)
                if not memos:
                    reply_message(mid, "暂无备忘。")
                    return
                lines = ["最近备忘（可用「清除备忘 序号」删除）："]
                for i, m in enumerate(memos, 1):
                    lines.append(f"{i}. {_memo_category_tag(m)}{m.get('content', '')}")
                reply_message(mid, "\n".join(lines)[:2000])
                return

            if action == "list_all_memos":
                memos = store_list_memos(limit=200, user_open_id=user_open_id)
                if not memos:
                    reply_message(mid, "暂无备忘。")
                    return
                lines = [f"所有备忘（共 {len(memos)} 条，可用「清除备忘 序号」删除）："]
                for i, m in enumerate(memos, 1):
                    lines.append(f"{i}. {_memo_category_tag(m)}{m.get('content', '')}")
                reply_message(mid, "\n".join(lines)[:4000])
                return

            if action == "list_memos_by_category":
                cat = (params.get("category") or "").strip()
                memos = store_list_memos(limit=200, user_open_id=user_open_id, category=cat)
                if not memos:
                    reply_message(mid, f"暂无「{cat}」类备忘。")
                    return
                lines = [f"「{cat}」类备忘（共 {len(memos)} 条）："]
                for i, m in enumerate(memos, 1):
                    lines.append(f"{i}. {m.get('content', '')}")
                reply_message(mid, "\n".join(lines)[:4000])
                return

            if action == "set_memo_category":
                idx = params.get("index") or params.get("序号")
                cat = (params.get("category") or params.get("分类") or "").strip()
                if not idx or not cat:
                    reply_message(mid, "请说「第3条标成灵感」或「把第2条设为要事」。")
                    return
                try:
                    num = int(idx)
                except (TypeError, ValueError):
                    reply_message(mid, "序号需为数字。")
                    return
                ok, msg_text = store_set_memo_category_by_index(num, cat, user_open_id=user_open_id)
                reply_message(mid, msg_text)
                return

            if action == "delete_memo":
                idx = params.get("index") or params.get("序号")
                if idx is None:
                    reply_message(mid, "请说「清除备忘 序号」或「删除备忘 3」。")
                    return
                try:
                    num = int(idx)
                except (TypeError, ValueError):
                    reply_message(mid, "序号需为数字，例如：清除备忘 3")
                    return
                ok, msg_text = store_delete_memo_by_index(num, user_open_id=user_open_id)
                reply_message(mid, msg_text)
                return

            if action == "complete_task":
                reply_message(mid, "已统一为备忘啦，没有单独勾选完成。可以说「备忘列表」查看～")
                return

            # ── 线程相关 ──
            if action == "list_threads":
                threads = store_list_threads(user_open_id=user_open_id)
                if not threads:
                    reply_card(mid, action_card("📂 暂无工作线程", "发备忘时加 #标签 即可创建线程\n例如：备忘 完成 deck #creator", color="blue"))
                    return
                lines = []
                for info in threads:
                    t = info["thread"]
                    latest = info.get("latest_content", "")[:30]
                    count = info["count"]
                    lines.append(f"**#{t}** ({count}条) — {latest}{'…' if len(info.get('latest_content', '')) > 30 else ''}")
                reply_card(mid, action_card(
                    f"📂 工作线程（{len(threads)} 个）",
                    "\n".join(lines)[:2000],
                    hints=["「#creator进展」查某条线", "「哪条线最久没动」查沉寂"],
                    color="blue",
                ))
                return

            if action == "thread_progress":
                thread_name = (params.get("thread") or "").strip()
                if not thread_name:
                    reply_message(mid, "请说线程名，例如「#creator进展」。")
                    return
                memos = store_list_memos(thread=thread_name, user_open_id=user_open_id, limit=10)
                if not memos:
                    reply_message(mid, f"#{thread_name} 暂无备忘。")
                    return
                lines = [f"**#{thread_name}** 最近动态（{len(memos)} 条）：\n"]
                for i, m in enumerate(memos, 1):
                    date = (m.get("created_at") or "")[:10]
                    lines.append(f"{i}. [{date}] {m.get('content', '')}")
                reply_card(mid, action_card(
                    f"📌 #{thread_name} 进展",
                    "\n".join(lines)[:2000],
                    hints=["「线程」看所有线程", f"「备忘 xxx #{thread_name}」继续记"],
                    color="indigo",
                ))
                return

            if action == "stale_threads":
                summary = store_thread_summary(user_open_id=user_open_id, days=7)
                stale = summary.get("stale", [])
                if not stale:
                    reply_message(mid, "所有线程本周都有动态，没有沉寂的 👍")
                    return
                lines = ["本周没有新备忘的线程：\n"]
                for s in stale[:8]:
                    lines.append(f"💤 **#{s['thread']}** — {s['days_silent']}天没动了（共{s['total']}条备忘）")
                reply_card(mid, action_card(
                    "💤 沉寂线程",
                    "\n".join(lines)[:2000],
                    hints=["发「#xxx进展」查某条线详情"],
                    color="yellow",
                ))
                return

            if action == "weekly_report":
                summary = store_thread_summary(user_open_id=user_open_id, days=7)
                active = summary.get("active", {})
                stale = summary.get("stale", [])
                lines = ["📊 **本周工作线程概览**\n"]
                if active:
                    lines.append("🔥 **活跃**")
                    for t, info in sorted(active.items(), key=lambda x: x[1]["count"], reverse=True):
                        if t == "(未分类)":
                            continue
                        preview = "、".join(info["items"][:2])
                        lines.append(f"  **#{t}** ({info['count']}条) — {preview}")
                    uncat = active.get("(未分类)")
                    if uncat:
                        lines.append(f"  _(未分类 {uncat['count']}条)_")
                if stale:
                    lines.append("\n💤 **沉寂**")
                    for s in stale[:5]:
                        lines.append(f"  **#{s['thread']}** — {s['days_silent']}天没动")
                if not active and not stale:
                    lines.append("本周暂无备忘记录。")
                reply_card(mid, action_card(
                    "📊 周报",
                    "\n".join(lines)[:2000],
                    hints=["「#xxx进展」查某条线", "「线程」查所有"],
                    color="indigo",
                ))
                return

            # ── 查日程 ──
            if action == "get_schedule":
                date_param = (params.get("date") or "today").strip()
                agg = aggregate_for_date(date_param, user_open_id=user_open_id)
                feishu = agg.get("feishu_events") or []
                google_ev = agg.get("google_events") or []
                memos = agg.get("memos") or []
                lines = [f"【{agg['date']}】"]
                if feishu:
                    lines.append("飞书日程：")
                    for e in feishu:
                        s = e.get("summary") or "(无标题)"
                        st = e.get("start") or {}
                        ts = st.get("timestamp") if isinstance(st, dict) else ""
                        lines.append(f"  - {s}" + (f" 时间戳:{ts}" if ts else ""))
                if google_ev:
                    lines.append("Google 日程：")
                    for e in google_ev:
                        lines.append(f"  - {e.get('summary', '')} {e.get('start', '')}～{e.get('end', '')}")
                if memos:
                    lines.append("备忘：")
                    for m in memos:
                        lines.append(f"  - {m.get('content', '')}")
                if not feishu and not google_ev and not memos:
                    reply_card(mid, action_card(
                        f"📅 {agg['date']} 暂无安排",
                        "今天是空白的一天，可以安心安排～",
                        hints=["发「明天下午3点开会」加日程", "发「备忘 xxx」记事情"],
                        color="blue",
                    ))
                    return
                raw_text = "\n".join(lines)
                from core.skill_router import enrich_prompt
                system_prompt = enrich_prompt(
                    "你是日程助手。根据下面汇总的日程与备忘，给用户一段简洁友好的总结与建议，控制在 200 字内。",
                    user_text=raw_text, bot_type="assistant",
                )
                reply_text = chat(raw_text, system_prompt=system_prompt) or raw_text
                reply_card(mid, action_card(
                    f"📅 {agg['date']} 日程概览",
                    reply_text[:2000],
                    hints=["发「明天」看明日安排", "发时间+事项可加日历"],
                    color="blue",
                ))
                return

            # ── 普通聊天 ──
            if action == "chat" and reply:
                reply_text = reply
            else:
                from core.skill_router import enrich_prompt
                system_prompt = enrich_prompt(
                    "你是飞书里的备忘与日程助手。可以帮用户记备忘、加日历、查日程。请用简洁友好的中文回复。",
                    user_text=text, bot_type="assistant",
                )
                reply_text = chat(text, system_prompt=system_prompt) or "（暂无回复）"
            reply_message(mid, reply_text[:2000])

        except Exception as e:
            _log(f"处理异常: {e}\n{traceback.format_exc()}")
            try:
                reply_card(mid, error_card("处理出错", "内部错误，请稍后重试", suggestions=["重新发送试试", "发「帮助」看指令"]))
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
            save_push_target_open_id(open_id)
            send_card_to_user(open_id, _welcome())
    except Exception as e:
        _log(f"发送欢迎卡片异常: {e}")


def _handle_message_read(_data) -> None:
    pass


# ── 帮助文本 ─────────────────────────────────────────────────

def _welcome() -> dict:
    return welcome_card(
        "小助手",
        "我能帮你 **记备忘、管日历、追踪工作线程、推简报**，也可以随便聊聊。",
        examples=[
            "备忘 完成 deck #creator",
            "线程",
            "今天有什么安排？",
            "周报",
        ],
        hints=["发送「帮助」查看所有指令", "备忘加 #标签 自动归入工作线程"],
    )


def _help() -> dict:
    return help_card("小助手", [
        ("记备忘（加 #线程 标签）",
         "> 备忘 完成 deck #creator\n"
         "> 备忘 对话系统三层架构 #催婚\n"
         "> 任务 写周报\n\n"
         "加 `#标签` 归入工作线程，不加会自动识别"),
        ("工作线程",
         "> **线程** — 查看所有工作线程\n"
         "> **#creator进展** — 查某条线的备忘\n"
         "> **哪条线最久没动** — 查沉寂线程\n"
         "> **周报** — 本周线程概览"),
        ("查看 / 管理备忘",
         "> 备忘列表 · 所有备忘\n"
         "> 清除备忘 3（删除第3条）"),
        ("日程管理",
         "> 明天下午3点开会 → 自动加入飞书日历\n"
         "> 今天 / 明天 → 查看日程安排"),
        ("每日简报",
         "08:00 晨报（日程+线程概览+bot动态+提醒）\n"
         "18:00 收尾（回顾+明日准备）\n"
         "周一 09:00 周报"),
    ], footer="其他消息我会当做聊天，AI 回复你")


# ── 长连接 & 定时推送 ────────────────────────────────────────

RECONNECT_INITIAL_DELAY = 5
RECONNECT_MAX_DELAY = 300
RECONNECT_MULTIPLIER = 2


def _run_health_server(port: int) -> None:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        def log_message(self, *args):
            pass
    server = HTTPServer(("0.0.0.0", port), _Handler)
    _log(f"健康检查 HTTP 已监听 0.0.0.0:{port}")
    server.serve_forever()


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
    app_id = (os.environ.get("ASSISTANT_FEISHU_APP_ID") or os.environ.get("FEISHU_APP_ID") or "").strip()
    app_secret = (os.environ.get("ASSISTANT_FEISHU_APP_SECRET") or os.environ.get("FEISHU_APP_SECRET") or "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "请设置环境变量 ASSISTANT_FEISHU_APP_ID / ASSISTANT_FEISHU_APP_SECRET\n"
            "（或复用 FEISHU_APP_ID / FEISHU_APP_SECRET）"
        )

    # TODO: 传递凭证应通过配置对象而非修改全局环境变量，同进程多机器人时会冲突
    os.environ["FEISHU_APP_ID"] = app_id
    os.environ["FEISHU_APP_SECRET"] = app_secret

    _log("备忘与日程助手启动")
    print("=" * 60)
    print("备忘与日程助手（长连接模式）")
    print()
    print("功能：记备忘、查日程、每日简报、AI 对话")
    print()
    print("断线后将自动重连，无需人工干预。")
    print("=" * 60)

    # 健康检查（PaaS 保活）
    port_str = (os.environ.get("PORT") or "").strip()
    if port_str:
        try:
            threading.Thread(target=_run_health_server, args=(int(port_str),), daemon=True).start()
        except ValueError:
            pass

    def _run_scheduler():
        try:
            from cal.daily_brief import run_daily_brief, run_weekly_report
        except Exception as e:
            _log(f"定时推送：导入失败: {e}")
            return
        try:
            import schedule as sched_lib
            sched_lib.every().day.at("08:00").do(lambda: run_daily_brief(is_morning=True))
            sched_lib.every().day.at("18:00").do(lambda: run_daily_brief(is_morning=False))
            sched_lib.every().monday.at("09:00").do(run_weekly_report)
            sched_lib.every().day.at("09:00").do(_run_reminder_check)
            while True:
                sched_lib.run_pending()
                time.sleep(60)
        except ImportError:
            _log("定时推送已禁用：未安装 schedule。pip install schedule")
        except Exception as e:
            _log(f"定时任务异常: {e}\n{traceback.format_exc()}")

    def _run_reminder_check():
        """检查到期提醒并推送。"""
        try:
            from cal.push_target import get_push_target_open_id
            open_id = get_push_target_open_id()
            if not open_id:
                return
            reminders = get_due_reminders(user_open_id=open_id)
            if not reminders:
                return
            lines = ["⏰ 到期提醒：\n"]
            for r in reminders:
                thread = r.get("thread") or ""
                tag = f"[#{thread}] " if thread else ""
                lines.append(f"- {tag}{r.get('content', '')}")
                mark_reminder_sent(r.get("id", ""))
            send_message_to_user(open_id, "\n".join(lines))
            _log(f"已推送 {len(reminders)} 条到期提醒")
        except Exception as e:
            _log(f"提醒检查失败: {e}")

    try:
        import schedule as _s  # noqa: F401
        threading.Thread(target=_run_scheduler, daemon=True).start()
        _log("定时推送已启用：08:00 晨报 / 18:00 收尾 / 周一 09:00 周报 / 每日 09:00 提醒检查")
    except ImportError:
        _log("定时推送已跳过：未安装 schedule")

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
