# -*- coding: utf-8 -*-
"""
每日简报、周报与提醒：线程化日程+备忘+跨 bot 感知，由 LLM 生成简报并推送到飞书。

推送时间由 assistant/__main__.py 的 scheduler 控制：
  - 08:00 晨报（日程+备忘+线程概览+跨bot动态+到期提醒）
  - 18:00 收尾（今日回顾+明日准备）
  - 周一 09:00 周报（线程活跃度+沉寂线程+跨bot汇总）
"""
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from core.llm import chat


def _format_events(events: List[dict]) -> str:
    if not events:
        return "（无）"
    lines = []
    for e in events:
        s = (e.get("summary") or "(无标题)").strip()
        start = e.get("start") or ""
        end = e.get("end") or ""
        if isinstance(start, dict):
            start = str(start.get("timestamp", ""))
        if isinstance(end, dict):
            end = str(end.get("timestamp", ""))
        lines.append(f"  - {s}  {start}～{end}")
    return "\n".join(lines)


def _format_memos(memos: List[dict]) -> str:
    if not memos:
        return "（无）"
    lines = []
    for m in memos:
        thread = m.get("thread") or ""
        tag = f"[#{thread}] " if thread else ""
        lines.append(f"  - {tag}{m.get('content', '')}")
    return "\n".join(lines)


def _scan_bot_activity(hours: int = 24) -> str:
    """扫描其他 bot 最近的产出。"""
    cutoff = time.time() - hours * 3600
    activity = []

    project_root = Path(__file__).resolve().parent.parent
    runs_dir = project_root / "runs"
    if runs_dir.exists():
        recent_sessions = []
        for f in runs_dir.glob("*.md"):
            try:
                if f.stat().st_mtime >= cutoff:
                    recent_sessions.append(f.name)
            except OSError:
                pass
        if recent_sessions:
            activity.append(f"  - brainstorm: {len(recent_sessions)} 场新脑暴 ({', '.join(recent_sessions[:3])})")

    content_dir = project_root / "data" / "conductor" / "content"
    if content_dir.exists():
        recent_content = []
        for f in content_dir.glob("*.json"):
            try:
                if f.stat().st_mtime >= cutoff:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    status = data.get("status", "")
                    title = (data.get("title") or "")[:30]
                    recent_content.append(f"{title} [{status}]")
            except (OSError, json.JSONDecodeError):
                pass
        if recent_content:
            activity.append(f"  - conductor: {len(recent_content)} 条内容 ({', '.join(recent_content[:3])})")

    planner_runs = project_root / "runs"
    if planner_runs.exists():
        planner_sessions = []
        for f in planner_runs.glob("plan_*.md"):
            try:
                if f.stat().st_mtime >= cutoff:
                    planner_sessions.append(f.name)
            except OSError:
                pass
        if planner_sessions:
            activity.append(f"  - planner: {len(planner_sessions)} 次规划")

    return "\n".join(activity) if activity else "（无）"


def _format_thread_summary(days: int = 1) -> str:
    """线程活跃度摘要。"""
    try:
        from memo.store import thread_summary
        summary = thread_summary(days=days)
        active = summary.get("active", {})
        stale = summary.get("stale", [])

        lines = []
        if active:
            for t, info in sorted(active.items(), key=lambda x: x[1]["count"], reverse=True):
                if t == "(未分类)":
                    continue
                lines.append(f"  #{t}: {info['count']}条 — {', '.join(info['items'][:2])}")
        if stale and days >= 7:
            stale_names = [f"#{s['thread']}({s['days_silent']}天)" for s in stale[:5]]
            lines.append(f"  💤 沉寂: {', '.join(stale_names)}")
        return "\n".join(lines) if lines else "（无线程备忘）"
    except Exception:
        return "（无法加载）"


def _format_reminders() -> str:
    """获取今日到期的提醒。"""
    try:
        from memo.store import get_due_reminders
        reminders = get_due_reminders()
        if not reminders:
            return ""
        lines = ["⏰ 今日提醒："]
        for r in reminders:
            thread = r.get("thread") or ""
            tag = f"[#{thread}] " if thread else ""
            lines.append(f"  - {tag}{r.get('content', '')}")
        return "\n".join(lines)
    except Exception:
        return ""


def _format_project_overview() -> str:
    """项目管理概览：预算执行 + 目标进度 + 近期到期目标。"""
    lines = []
    try:
        from memo.projects import list_projects
        from memo.finance import (
            list_budgets, budget_vs_actual, list_goals,
            month_summary,
        )

        projects = list_projects()
        budgets = list_budgets()
        goals = list_goals()

        if not projects and not budgets and not goals:
            return ""

        # 预算执行摘要
        for b in budgets:
            proj = b["project"]
            _, _, summary = budget_vs_actual(proj)
            if "error" in summary:
                continue
            total_b = summary.get("total_budget", 0)
            total_a = summary.get("total_actual", 0)
            pct = summary.get("usage_pct", "-")
            status = "⚠️ 超支" if total_a > total_b else ("🟡 >80%" if total_b > 0 and total_a / total_b > 0.8 else "✅")
            lines.append(f"  💰 {proj}: ¥{total_a:,.0f}/¥{total_b:,.0f} ({pct}) {status}")

        # 目标进度
        for g in goals:
            try:
                t_val = float(g["target"])
                c_val = float(g["current"])
                pct = f"{c_val / t_val * 100:.0f}%"
            except (ValueError, ZeroDivisionError):
                pct = "-"
            deadline_warn = ""
            if g.get("deadline"):
                try:
                    dl = datetime.strptime(g["deadline"], "%Y-%m-%d")
                    days_left = (dl - datetime.utcnow()).days
                    if days_left <= 7:
                        deadline_warn = f" ⏰ {days_left}天后到期"
                    elif days_left <= 0:
                        deadline_warn = " 🔴 已过期"
                except ValueError:
                    pass
            lines.append(f"  🎯 {g['project']}/{g['name']}: {g['current']}/{g['target']}{g.get('unit','')} ({pct}){deadline_warn}")

        # 本月花费快照
        ms = month_summary()
        if ms["count"] > 0:
            lines.append(f"  📊 本月累计: ¥{ms['total_expense']:,.0f}（{ms['count']}笔）")

    except Exception:
        pass
    return "\n".join(lines) if lines else ""


def generate_daily_brief(
    events_feishu: List[dict],
    events_google: List[dict],
    memos: List[dict],
    date_str: str,
    is_morning: bool = True,
) -> str:
    events_all = []
    for e in events_feishu + events_google:
        events_all.append({"summary": e.get("summary"), "start": e.get("start"), "end": e.get("end")})

    events_text = _format_events(events_all)
    memos_text = _format_memos(memos)
    thread_text = _format_thread_summary(days=1)
    bot_activity = _scan_bot_activity(hours=24)
    reminders_text = _format_reminders()
    project_text = _format_project_overview()

    calendar_context = ""
    try:
        from skills import get_skill
        cal_skill = get_skill("calendar")
        if cal_skill:
            calendar_context = cal_skill.get_context(lookahead_days=7)
    except Exception:
        pass

    if is_morning:
        prompt = f"""你是我的工作助手，请根据以下信息生成今日工作简报。风格：简洁、有重点、像一个靠谱的助手在帮我整理思路。

【今日日历事件】
{events_text}

【最近备忘（按线程分组）】
{memos_text}

【今日线程动态】
{thread_text}

【项目管理概览】
{project_text or '（无项目数据）'}

【其他 bot 动态（过去24h）】
{bot_activity}

{reminders_text}

{f'【近期节点】{chr(10)}{calendar_context}' if calendar_context else ''}

请输出：
1. 今日日程（列出所有日历事件，标注时间）
2. 今日重点（从备忘+日程+线程+项目中提炼，最多3条）
3. 线程概览（哪些线程最近活跃，用一句话说）
4. 项目状态（预算执行、目标进度，有异常的优先提醒：超支、目标即将到期等）
5. 需要注意（冲突、到期提醒、近期节点、沉寂的线程、预算告警等）
6. 一句话建议（今天的工作节奏建议）

语言：中文，不要使用 Markdown 加粗，纯文本。"""
    else:
        prompt = f"""你是我的工作助手，请根据以下信息生成今日收尾 checklist。风格：简洁。

【今日日历事件】
{events_text}

【今日备忘】
{memos_text}

【今日线程动态】
{thread_text}

【项目管理概览】
{project_text or '（无项目数据）'}

【其他 bot 动态（过去24h）】
{bot_activity}

请输出：
1. 今日回顾（线程进展 + 今日花费/项目动态）
2. 项目提醒（预算使用率 >80% 告警、目标即将到期等）
3. 明日可提前准备的事项（最多3条）
4. 一句话收尾建议

语言：中文，简洁，不要 Markdown 加粗。"""

    return chat(prompt, system_prompt="你是日程与任务助手，输出简洁、可执行的文本。对线程概览要具体到线程名。")


def generate_weekly_report(user_open_id: Optional[str] = None) -> str:
    """生成周报。"""
    thread_text = _format_thread_summary(days=7)
    bot_activity = _scan_bot_activity(hours=168)
    project_text = _format_project_overview()

    calendar_context = ""
    try:
        from skills import get_skill
        cal_skill = get_skill("calendar")
        if cal_skill:
            calendar_context = cal_skill.get_context(lookahead_days=14)
    except Exception:
        pass

    prompt = f"""你是我的工作助手，请根据以下信息生成本周工作总结。

【本周线程活跃度】
{thread_text}

【项目管理概览】
{project_text or '（无项目数据）'}

【本周 bot 动态】
{bot_activity}

{f'【未来2周节点】{chr(10)}{calendar_context}' if calendar_context else ''}

请输出：
1. 本周进展概览（按活跃线程分组，每个线程1-2句话说做了什么）
2. 项目与财务状态（各项目预算执行率、目标完成度、本周花费汇总，异常优先提醒）
3. 沉寂提醒（哪些线程超过一周没动，是需要跟进还是可以暂时搁置？）
4. 下周建议（结合即将到来的节点+预算+目标进度，建议优先推进什么）

风格：简洁、有判断力、像一个了解你所有工作线的助手在帮你复盘。
语言：中文。"""

    return chat(prompt, system_prompt="你是工作助手，了解用户同时在做多条工作线和项目预算。输出有重点、有判断、有行动建议的周报。")


def generate_monthly_report(month: str = "", user_open_id: Optional[str] = None) -> str:
    """生成月报：线程 + 项目 + 财务 + 目标全维度复盘。"""
    if not month:
        now = datetime.utcnow()
        first = now.replace(day=1)
        last_month = first - timedelta(days=1)
        month = last_month.strftime("%Y-%m")

    thread_text = _format_thread_summary(days=30)
    project_text = _format_project_overview()

    finance_text = ""
    try:
        from memo.finance import month_summary, list_budgets, budget_vs_actual, list_goals
        ms = month_summary(month)
        if ms["count"] > 0:
            lines = [f"  总支出: ¥{ms['total_expense']:,.0f}（{ms['count']}笔）"]
            if ms["total_income"] > 0:
                lines.append(f"  总收入: ¥{ms['total_income']:,.0f}")
            if ms["by_category"]:
                cat_parts = [f"{k} ¥{v:,.0f}" for k, v in list(ms["by_category"].items())[:6]]
                lines.append(f"  按类别: {' / '.join(cat_parts)}")
            if ms["by_project"]:
                proj_parts = [f"{k} ¥{v:,.0f}" for k, v in list(ms["by_project"].items())[:6]]
                lines.append(f"  按项目: {' / '.join(proj_parts)}")
            finance_text = "\n".join(lines)

            budget_lines = []
            for b in list_budgets():
                _, _, summary = budget_vs_actual(b["project"])
                if "error" in summary:
                    continue
                budget_lines.append(
                    f"  {b['project']}: 预算 ¥{summary['total_budget']:,.0f} / "
                    f"实际 ¥{summary['total_actual']:,.0f} / "
                    f"使用率 {summary['usage_pct']}"
                )
            if budget_lines:
                finance_text += "\n\n  [预算执行]\n" + "\n".join(budget_lines)

            goal_lines = []
            for g in list_goals():
                try:
                    pct = f"{float(g['current']) / float(g['target']) * 100:.0f}%"
                except (ValueError, ZeroDivisionError):
                    pct = "-"
                goal_lines.append(f"  {g['project']}/{g['name']}: {g['current']}/{g['target']}{g.get('unit','')} ({pct})")
            if goal_lines:
                finance_text += "\n\n  [目标达成]\n" + "\n".join(goal_lines)
    except Exception:
        pass

    bot_activity = _scan_bot_activity(hours=720)

    prompt = f"""你是我的工作助手，请根据以下信息生成 {month} 月度工作与财务总结。

【本月线程活跃度】
{thread_text}

【项目管理概览】
{project_text or '（无）'}

【月度财务数据】
{finance_text or '（无花费记录）'}

【本月 bot 动态】
{bot_activity}

请输出：
1. 月度概览（一段话总结这个月的工作重心和成果）
2. 线程进展（按线程分组，每个1-2句话说本月做了什么，标注哪些推进顺利/哪些滞后）
3. 财务总结（总花费、按项目拆分、预算执行率、有无超支风险）
4. 目标达成（各项目目标进度，哪些达标/哪些落后，原因推测）
5. 下月建议（结合线程+预算+目标进度，建议下月优先什么、缩减什么）

风格：有数据支撑、有判断力、像 CFO + COO 联合给你的月度 briefing。
语言：中文。"""

    return chat(prompt, system_prompt="你是工作助手兼财务顾问，输出有数据、有判断、有行动建议的月度报告。")


def run_monthly_report() -> bool:
    """执行一次月报推送。"""
    from cal.push_target import get_push_target_open_id
    from core.feishu_client import send_message_to_user

    open_id = get_push_target_open_id()
    if not open_id:
        return False

    try:
        report = generate_monthly_report(user_open_id=open_id)
        if not report:
            report = "本月暂无工作与财务汇总。"
        if len(report) > 4000:
            report = report[:3997] + "..."
        send_message_to_user(open_id, f"📊 月度工作与财务总结\n\n{report}")
        return True
    except Exception as e:
        print(f"[MonthlyReport] 生成或推送失败: {e}", file=sys.stderr, flush=True)
        return False


def run_daily_brief(is_morning: bool = True) -> bool:
    """执行一次每日简报推送。"""
    from cal.push_target import get_push_target_open_id
    open_id = get_push_target_open_id()
    if not open_id:
        return False

    from cal.aggregator import aggregate_for_date
    from memo.store import list_memos, get_due_reminders, mark_reminder_sent
    from core.feishu_client import send_message_to_user

    agg = aggregate_for_date("today", user_open_id=open_id)
    events_feishu = agg.get("feishu_events") or []
    events_google = agg.get("google_events") or []
    memos = list_memos(limit=20, user_open_id=open_id)
    date_str = agg.get("date", "")

    try:
        brief = generate_daily_brief(events_feishu, events_google, memos, date_str, is_morning=is_morning)
        if not brief:
            brief = "今日暂无日程与备忘汇总。"

        if is_morning:
            reminders = get_due_reminders(user_open_id=open_id)
            if reminders:
                reminder_lines = ["\n⏰ 到期提醒："]
                for r in reminders:
                    thread = r.get("thread") or ""
                    tag = f"[#{thread}] " if thread else ""
                    reminder_lines.append(f"  - {tag}{r.get('content', '')}")
                    mark_reminder_sent(r.get("id", ""))
                brief += "\n".join(reminder_lines)

        if len(brief) > 4000:
            brief = brief[:3997] + "..."
        send_message_to_user(open_id, brief)
        return True
    except Exception as e:
        print(f"[DailyBrief] 生成或推送失败: {e}", file=sys.stderr, flush=True)
        return False


def run_weekly_report() -> bool:
    """执行一次周报推送。"""
    from cal.push_target import get_push_target_open_id
    from core.feishu_client import send_message_to_user

    open_id = get_push_target_open_id()
    if not open_id:
        return False

    try:
        report = generate_weekly_report(user_open_id=open_id)
        if not report:
            report = "本周暂无工作汇总。"
        if len(report) > 4000:
            report = report[:3997] + "..."
        send_message_to_user(open_id, f"📊 本周工作总结\n\n{report}")
        return True
    except Exception as e:
        print(f"[WeeklyReport] 生成或推送失败: {e}", file=sys.stderr, flush=True)
        return False
