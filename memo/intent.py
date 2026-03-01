# -*- coding: utf-8 -*-
"""
意图解析：备忘 / 任务 / 日程 / 脑暴 / 规划 / 聊天。

关键词快速识别（不走 LLM） + LLM 语义理解兜底。
"""
import json
import re
from typing import Any, Dict, Optional

from core.llm import chat


def _quick_intent(text: str) -> Optional[tuple[str, dict]]:
    t = (text or "").strip()
    if not t:
        return None

    # 备忘列表（模糊匹配：含"备忘"+"列表/看/有哪些/都有"等）
    if re.search(r"备忘.*(列表|有哪些|都有|看看|列出)", t) or re.search(r"(看看|列出|查看).*备忘", t):
        if "所有" in t or "全部" in t or "所有" in t:
            return ("list_all_memos", {})
        if "日常" in t:
            return ("list_memos_by_category", {"category": "日常"})
        if "灵感" in t:
            return ("list_memos_by_category", {"category": "灵感"})
        if "要事" in t:
            return ("list_memos_by_category", {"category": "要事"})
        return ("list_memos", {})

    if re.match(r"^(备忘列表|看看备忘|列出备忘|备忘有哪些|查看备忘)$", t):
        return ("list_memos", {})
    if re.match(r"^(任务列表|待办列表|看看任务|未完成任务|有哪些任务|查看任务|查看待办)$", t):
        return ("list_tasks", {})
    if re.match(r"^(所有备忘|显示所有备忘|全部备忘|列出所有备忘)$", t):
        return ("list_all_memos", {})
    if re.match(r"^(日常备忘|日常类备忘|列出日常)$", t):
        return ("list_memos_by_category", {"category": "日常"})
    if re.match(r"^(灵感备忘|灵感类备忘|列出灵感)$", t):
        return ("list_memos_by_category", {"category": "灵感"})
    if re.match(r"^(要事备忘|要事类备忘|列出要事)$", t):
        return ("list_memos_by_category", {"category": "要事"})

    # 线程相关
    if re.match(r"^(线程|threads?|我在做什么|工作线程|项目列表)$", t, re.IGNORECASE):
        return ("list_threads", {})
    if re.match(r"^(这周|本周|周报).*", t) and ("做了" in t or "总结" in t or "汇总" in t or "周报" in t):
        return ("weekly_report", {})
    m_thread = re.match(r"^#?([\w\u4e00-\u9fff]+)\s*(进展|进度|状态|怎么样了|做到哪了).*$", t)
    if m_thread:
        return ("thread_progress", {"thread": m_thread.group(1)})
    if re.match(r"^(哪条线|什么线|哪个项目).*(没动|沉寂|最久|冷了).*$", t):
        return ("stale_threads", {})

    # 删除备忘
    m = re.match(r"^(清除备忘|删除备忘)\s*[：:]\s*(\d+)$", t) or re.match(r"^(清除备忘|删除备忘)\s+(\d+)$", t)
    if m:
        return ("delete_memo", {"index": int(m.group(2))})

    # 完成任务
    if re.match(r"^完成\s*[：:]\s*.+", t) or re.match(r"^完成\s+.+", t):
        task_title = re.sub(r"^完成\s*[：:]\s*", "", t).strip()
        task_title = re.sub(r"^完成\s+", "", task_title).strip()
        return ("complete_task", {"task_title": task_title})

    # 查日程（更宽泛）
    if re.match(r"^(今天|今日|今天有什么|今日日程|今天有什么安排|今日安排|今天的?(日程|安排|计划))$", t):
        return ("get_schedule", {"date": "today"})
    if re.match(r"^(明天|明日|明天有什么|明日日程|明天有什么安排|明日安排|明天的?(日程|安排|计划))$", t):
        return ("get_schedule", {"date": "tomorrow"})
    if "今天" in t and ("日程" in t or "安排" in t or "有什么" in t):
        return ("get_schedule", {"date": "today"})
    if "明天" in t and ("日程" in t or "安排" in t or "有什么" in t):
        return ("get_schedule", {"date": "tomorrow"})
    if "今日" in t and ("日程" in t or "安排" in t or "备忘" in t):
        return ("get_schedule", {"date": "today"})

    return None


SYSTEM_PROMPT = """你是意图解析助手。根据用户消息判断意图，只输出一个合法 JSON，不要其他文字。

意图与格式：
1. 记备忘 - 「备忘 xxx」「记一下 xxx」「别忘了 xxx」。action: add_memo，params: content（备忘内容）, 可选 reminder_date（YYYY-MM-DD）, 可选 thread（工作线程标签）。
2. 创建任务 - 「任务 xxx」「待办 xxx」「todo xxx」。action: add_task，params: title（任务标题）。
3. 加日历 - 用户要安排某时间做某事。action: add_calendar，params: title, start_time, end_time（ISO8601）。
4. 查今日/明日日程 - 「今天有什么」「明日日程」等。action: get_schedule，params: date 为 "today"/"tomorrow" 或 YYYY-MM-DD。
5. 备忘列表 - 用户要看最近备忘。action: list_memos，params: {}。可选 thread 参数筛选。
6. 任务列表 - 用户要看未完成任务。action: list_tasks，params: {}。
7. 发起脑暴 - 用户说「脑暴 xxx」「brainstorm xxx」。action: brainstorm，params: topic（主题）。
8. 发起规划 - 用户说「规划 xxx」「计划 xxx」「plan xxx」或「快速模式/分析模式/方案模式/执行模式：xxx」。action: planner，params: topic（主题）, mode（可选）。
9. 查线程 - 用户说「线程」「我在做什么」「工作线程」。action: list_threads，params: {}。
10. 线程进展 - 用户说「xxx进展」「xxx做到哪了」。action: thread_progress，params: thread（线程名）。
11. 沉寂线程 - 用户说「哪条线最久没动」。action: stale_threads，params: {}。
12. 周报 - 用户说「周报」「这周做了什么」。action: weekly_report，params: {}。
13. 普通聊天 - 以上都不是。action: chat，reply: 你的简短回复。

输出格式示例：
- 记备忘：{"action":"add_memo","params":{"content":"对话系统用三层架构","thread":"催婚"},"reply":""}
- 线程进展：{"action":"thread_progress","params":{"thread":"creator"},"reply":""}
- 聊天：{"action":"chat","params":{},"reply":"好的"}
"""


def parse_intent(user_message: str) -> Dict[str, Any]:
    """解析用户意图，返回 {"action": str, "params": dict, "reply": str}。"""
    text = (user_message or "").strip()
    quick = _quick_intent(text)
    if quick is not None:
        action, params = quick
        return {"action": action, "params": params, "reply": ""}

    prompt = f"用户说：{text}\n\n请输出上述格式的 JSON："
    raw = chat(prompt, system_prompt=SYSTEM_PROMPT)
    if not raw:
        return {"action": "chat", "params": {}, "reply": ""}

    raw = raw.strip()
    json_match = re.search(r"\{[\s\S]*\}", raw)
    if json_match:
        try:
            obj = json.loads(json_match.group())
            action = obj.get("action", "chat")
            allowed = (
                "chat", "add_calendar", "add_todo", "add_memo", "add_task",
                "get_schedule", "list_memos", "list_tasks", "list_all_memos",
                "list_memos_by_category", "delete_memo", "set_memo_category",
                "complete_task", "brainstorm", "planner",
                "list_threads", "thread_progress", "stale_threads", "weekly_report",
            )
            if action not in allowed:
                action = "chat"
            params = obj.get("params") or {}
            return {
                "action": action,
                "params": params,
                "reply": obj.get("reply") or (raw if action == "chat" else ""),
            }
        except json.JSONDecodeError:
            pass
    return {"action": "chat", "params": {}, "reply": raw}
