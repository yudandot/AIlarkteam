# -*- coding: utf-8 -*-
"""
意图解析：备忘 / 任务 / 日程 / 脑暴 / 规划 / 聊天。

关键词快速识别（不走 LLM） + LLM 语义理解兜底。
"""
import json
import re
from datetime import datetime
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
    # 月报: "月报" / "本月总结" / "3月月报"
    if re.match(r"^(月报|月度总结|月度报告|本月总结)$", t):
        return ("monthly_report", {})
    m_mr = re.match(r"^(\d{1,2})月\s*(月报|总结|报告)$", t)
    if m_mr:
        month = f"{datetime.now().year}-{int(m_mr.group(1)):02d}"
        return ("monthly_report", {"month": month})
    m_thread = re.match(r"^#?([\w\u4e00-\u9fff]+)\s*(进展|进度|状态|怎么样了|做到哪了).*$", t)
    if m_thread:
        return ("thread_progress", {"thread": m_thread.group(1)})
    if re.match(r"^(哪条线|什么线|哪个项目).*(没动|沉寂|最久|冷了).*$", t):
        return ("stale_threads", {})

    # 删除备忘
    m = re.match(r"^(清除备忘|删除备忘)\s*[：:]\s*(\d+)$", t) or re.match(r"^(清除备忘|删除备忘)\s+(\d+)$", t)
    if m:
        return ("delete_memo", {"index": int(m.group(2))})

    # 完成备忘（按序号或关键词）
    m_done = re.match(r"^(完成|done|搞定|✅)\s*[：:]?\s*(\d+)$", t, re.IGNORECASE)
    if m_done:
        return ("complete_memo", {"index": int(m_done.group(2))})
    m_done_kw = re.match(r"^(完成|done|搞定|✅)\s*[：:]?\s*(.+)$", t, re.IGNORECASE)
    if m_done_kw:
        return ("complete_memo", {"keyword": m_done_kw.group(2).strip()})

    # ── 看板（线程导出）──
    m_export = re.match(
        r"^(看板|项目看板|生成看板|导出看板)\s*[：:]?\s*(?:#?([\w\u4e00-\u9fff]+))?\s*$", t,
    )
    if m_export:
        thread = (m_export.group(2) or "").strip()
        return ("export_board", {"thread": thread} if thread else {})

    # ── 项目管理 ──
    # 创建项目
    m_new_proj = re.match(
        r"^(创建项目|新建项目|创建看板|新建看板|做个表)\s*[：:]?\s*(.+)$", t,
    )
    if m_new_proj:
        return ("create_project", {"name": m_new_proj.group(2).strip()})

    # 项目列表
    if re.match(r"^(项目列表|所有项目|列出项目|查看项目|我的项目)$", t):
        return ("list_projects", {})

    # 加任务到项目: "Q2营销 加任务 写方案" / "加任务 写方案 到 Q2营销"
    m_add = re.match(
        r"^(.+?)\s*(加任务|添加任务|新增任务)\s*[：:]?\s*(.+)$", t,
    )
    if m_add:
        return ("add_project_task", {
            "project": m_add.group(1).strip(),
            "task": m_add.group(3).strip(),
        })
    m_add2 = re.match(
        r"^(加任务|添加任务|新增任务)\s*[：:]?\s*(.+?)\s+(到|给)\s+(.+)$", t,
    )
    if m_add2:
        return ("add_project_task", {
            "task": m_add2.group(2).strip(),
            "project": m_add2.group(4).strip(),
        })

    # 妙记链接（自动检测 feishu.cn/minutes/xxx）
    if "feishu.cn/minutes/" in t or "larkoffice.com/minutes/" in t:
        m_to = re.search(r"(?:到|归档到?|导入到?|写入)\s*(.+?)$", t)
        project = m_to.group(1).strip() if m_to else ""
        return ("import_minutes", {"text": t, "project": project})

    # 导入内容到项目: "导入到 Q2营销" / "写入项目 Q2营销"
    m_import = re.match(
        r"^(导入到?|写入项目?|录入到?|添加到)\s*(.+)$", t,
    )
    if m_import:
        return ("import_content", {"project": m_import.group(2).strip()})

    # ── 财务管理 ──
    # 记账: "记账 午餐 35" / "支出 办公用品 200 #Q2营销"
    m_exp = re.match(
        r"^(记账|支出|花费|报销|收入)\s*[：:]?\s*(.+?)\s+(\d+(?:\.\d+)?)\s*元?\s*(?:#([\w\u4e00-\u9fff]+))?\s*$", t,
    )
    if m_exp:
        exp_type = "收入" if m_exp.group(1) == "收入" else "支出"
        return ("add_expense", {
            "description": m_exp.group(2).strip(),
            "amount": m_exp.group(3),
            "type": exp_type,
            "project": (m_exp.group(4) or "").strip(),
        })

    # 批量记账: "记这些账" / "导入费用" / 带关键词 + 多行内容
    m_batch = re.match(
        r"^(记这些账?|导入费用|批量记账|录入费用|这些费用?)\s*(?:到|给)?\s*#?([\w\u4e00-\u9fff]*)\s*$", t,
    )
    if m_batch:
        return ("import_expenses", {"project": (m_batch.group(2) or "").strip()})

    # 自动检测：多行且含多个金额数字 → 可能是费用表
    lines = t.strip().split("\n")
    if len(lines) >= 3:
        amount_count = sum(1 for line in lines if re.search(r'\d{2,}(?:\.\d+)?', line))
        if amount_count >= 2:
            m_proj = re.search(r'(?:到|给|归入|项目)\s*#?([\w\u4e00-\u9fff]+)\s*$', lines[0])
            if m_proj or any(kw in lines[0] for kw in ("费用", "账", "花费", "报销", "支出", "开销")):
                proj = m_proj.group(1) if m_proj else ""
                return ("import_expenses", {"project": proj, "content": t})

    # 创建预算: "创建预算 Q2营销"
    m_budget = re.match(
        r"^(创建预算|新建预算|预算)\s*[：:]?\s*(.+)$", t,
    )
    if m_budget:
        return ("create_budget", {"project": m_budget.group(2).strip()})

    # 预算概览: "预算概览 Q2营销" / "Q2营销 预算"
    m_bv = re.match(r"^(预算概览|预算报表)\s*[：:]?\s*(.+)$", t)
    if m_bv:
        return ("budget_overview", {"project": m_bv.group(2).strip()})
    m_bv2 = re.match(r"^(.+?)\s*预算$", t)
    if m_bv2:
        return ("budget_overview", {"project": m_bv2.group(1).strip()})

    # 月度花费: "本月花费" / "月度报表" / "3月花费"
    if re.match(r"^(本月花费|本月支出|月度报表|月度花费|这个月花了多少)$", t):
        return ("month_expenses", {})
    m_month = re.match(r"^(\d{1,2})月(花费|支出|报表|花了多少)$", t)
    if m_month:
        year = datetime.now().year
        month_str = f"{year}-{int(m_month.group(1)):02d}"
        return ("month_expenses", {"month": month_str})

    # 设目标: "Q2营销 设目标 新增用户 10000人"
    m_goal = re.match(
        r"^(.+?)\s*(设目标|加目标|添加目标|新增目标)\s*[：:]?\s*(.+?)\s+(\d+(?:\.\d+)?)\s*(.*)$", t,
    )
    if m_goal:
        return ("add_goal", {
            "project": m_goal.group(1).strip(),
            "name": m_goal.group(3).strip(),
            "target": m_goal.group(4),
            "unit": m_goal.group(5).strip(),
        })

    # 更新目标: "更新目标 新增用户 7500"
    m_ug = re.match(
        r"^(更新目标|目标进度)\s*[：:]?\s*(.+?)\s+(\d+(?:\.\d+)?)\s*$", t,
    )
    if m_ug:
        return ("update_goal", {"keyword": m_ug.group(2).strip(), "current": m_ug.group(3)})

    # 项目总览: "Q2营销 总览" / "项目总览 Q2营销"
    m_dash = re.match(r"^(项目总览|项目看板|项目概览)\s*[：:]?\s*(.+)$", t)
    if m_dash:
        return ("project_dashboard", {"project": m_dash.group(2).strip()})
    m_dash2 = re.match(r"^(.+?)\s*(总览|概览|仪表盘|dashboard)$", t, re.IGNORECASE)
    if m_dash2:
        return ("project_dashboard", {"project": m_dash2.group(1).strip()})

    # 研究/调研
    m_research = re.match(
        r"^(研究|调研|research|调查|fact[- ]?check|深度分析)\s*[：:]?\s*(.+)$", t, re.IGNORECASE,
    )
    if m_research:
        return ("research", {"topic": m_research.group(2).strip()})

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
5. 备忘列表 - 用户要看最近备忘。action: list_memos，params: {}。可选 thread 参数筛选。可选 include_done: true 看已完成的。
6. 完成备忘 - 用户说「完成 xxx」「搞定 xxx」「done 3」。action: complete_memo，params: index（序号）或 keyword（关键词）。
7. 发起脑暴 - 用户说「脑暴 xxx」「brainstorm xxx」。action: brainstorm，params: topic（主题）。
8. 发起规划 - 用户说「规划 xxx」「计划 xxx」「plan xxx」或「快速模式/分析模式/方案模式/执行模式：xxx」。action: planner，params: topic（主题）, mode（可选）。
9. 查线程 - 用户说「线程」「我在做什么」「工作线程」。action: list_threads，params: {}。
10. 线程进展 - 用户说「xxx进展」「xxx做到哪了」。action: thread_progress，params: thread（线程名）。
11. 沉寂线程 - 用户说「哪条线最久没动」。action: stale_threads，params: {}。
12. 周报 - 用户说「周报」「这周做了什么」。action: weekly_report，params: {}。
13. 联网研究 - 用户说「研究 xxx」「调研 xxx」「research xxx」「深度分析 xxx」「fact check xxx」。action: research，params: topic（研究主题）。
14. 导出线程看板 - 用户说「看板」「导出看板」「看板 #线程名」。action: export_board，params: 可选 thread。
15. 创建项目 - 用户说「创建项目 xxx」「新建项目 xxx」「做个表 xxx」。action: create_project，params: name。
16. 项目列表 - 用户说「项目列表」「我的项目」。action: list_projects，params: {}。
17. 加任务到项目 - 用户说「xxx 加任务 yyy」或「加任务 yyy 到 xxx」。action: add_project_task，params: project, task。
18. 导入妙记 - 消息包含飞书妙记链接。action: import_minutes，params: text（原文）, project（目标项目名，可为空）。
19. 导入内容到项目 - 用户粘贴大段会议纪要/笔记，要求归入某项目。action: import_content，params: content（粘贴内容）, project（项目名）。
20. 记账 - 用户说「记账 午餐 35」「支出 打车 50 #Q2营销」「收入 退款 200」。action: add_expense，params: description, amount, type（支出/收入）, project（可选）。
21. 批量记账 - 用户发送表格/列表/多行费用数据，或说「记这些账」「导入费用」。action: import_expenses，params: content（原始文本）, project（可选）。
22. 创建预算。action: create_budget，params: project。
23. 预算概览。action: budget_overview，params: project。
24. 月度花费。action: month_expenses，params: 可选 month（YYYY-MM）。
25. 设目标。action: add_goal，params: project, name, target, unit。
26. 更新目标。action: update_goal，params: keyword, current。
27. 项目总览。action: project_dashboard，params: project。
28. 月报 - 用户说「月报」「月度总结」「3月月报」。action: monthly_report，params: 可选 month（YYYY-MM）。
29. 普通聊天 - 以上都不是。action: chat，reply: 你的简短回复。

输出格式示例：
- 记备忘：{"action":"add_memo","params":{"content":"对话系统用三层架构","thread":"催婚"},"reply":""}
- 联网研究：{"action":"research","params":{"topic":"Character.ai 为什么增长这么快"},"reply":""}
- 创建项目：{"action":"create_project","params":{"name":"Q2营销计划"},"reply":""}
- 记账：{"action":"add_expense","params":{"description":"团队午餐","amount":"350","type":"支出","project":"Q2营销"},"reply":""}
- 月度花费：{"action":"month_expenses","params":{},"reply":""}
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
                "complete_memo", "complete_task", "brainstorm", "planner",
                "list_threads", "thread_progress", "stale_threads", "weekly_report",
                "research", "export_board",
                "create_project", "list_projects", "add_project_task",
                "import_minutes", "import_content",
                "add_expense", "import_expenses",
                "create_budget", "budget_overview", "month_expenses",
                "add_goal", "update_goal", "project_dashboard",
                "monthly_report",
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
