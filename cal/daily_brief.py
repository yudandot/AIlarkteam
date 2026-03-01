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

【其他 bot 动态（过去24h）】
{bot_activity}

{reminders_text}

{f'【近期节点】{chr(10)}{calendar_context}' if calendar_context else ''}

请输出：
1. 今日日程（列出所有日历事件，标注时间）
2. 今日重点（从备忘+日程+线程中提炼，最多3条）
3. 线程概览（哪些线程最近活跃，用一句话说）
4. 需要注意（冲突、到期提醒、近期节点、沉寂的线程等）
5. 一句话建议（今天的工作节奏建议）

语言：中文，不要使用 Markdown 加粗，纯文本。"""
    else:
        prompt = f"""你是我的工作助手，请根据以下信息生成今日收尾 checklist。风格：简洁。

【今日日历事件】
{events_text}

【今日备忘】
{memos_text}

【今日线程动态】
{thread_text}

【其他 bot 动态（过去24h）】
{bot_activity}

请输出：
1. 今日回顾（哪些线程有进展，哪些没动）
2. 明日可提前准备的事项（最多3条）
3. 一句话收尾建议

语言：中文，简洁，不要 Markdown 加粗。"""

    return chat(prompt, system_prompt="你是日程与任务助手，输出简洁、可执行的文本。对线程概览要具体到线程名。")


def generate_weekly_report(user_open_id: Optional[str] = None) -> str:
    """生成周报。"""
    thread_text = _format_thread_summary(days=7)
    bot_activity = _scan_bot_activity(hours=168)

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

【本周 bot 动态】
{bot_activity}

{f'【未来2周节点】{chr(10)}{calendar_context}' if calendar_context else ''}

请输出：
1. 本周进展概览（按活跃线程分组，每个线程1-2句话说做了什么）
2. 沉寂提醒（哪些线程超过一周没动，是需要跟进还是可以暂时搁置？）
3. 下周建议（结合即将到来的节点，建议优先推进什么）

风格：简洁、有判断力、像一个了解你所有工作线的助手在帮你复盘。
语言：中文。"""

    return chat(prompt, system_prompt="你是工作助手，了解用户同时在做多条工作线。输出有重点、有判断、有行动建议的周报。")


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
