# -*- coding: utf-8 -*-
"""
财务管理 — 记账、预算、月度汇总。

数据模型：
  expenses.json  — 所有花费的中央账本，每笔带 project 标签
  budgets.json   — 项目预算定义（预算项 + 额度）

项目预算的「实际花费」从 expenses 中按 project 聚合，不重复存储。
月度花费表 = 当月 expenses 的全量导出。
"""
import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DATA_DIR = str(Path(__file__).resolve().parent.parent / "data")
_lock = threading.Lock()

# ── 花费表模板列 ──────────────────────────────────────────────
EXPENSE_HEADERS = ["日期", "类别", "项目", "描述", "金额", "收/支", "付款方式", "备注"]

# ── 预算表模板列 ──────────────────────────────────────────────
BUDGET_HEADERS = ["预算项", "类别", "预算金额", "实际花费", "剩余", "使用率", "备注"]

DEFAULT_CATEGORIES = ["人力", "营销", "设计", "技术", "办公", "差旅", "餐饮", "其他"]


# ═══════════════════════════════════════════════════════════════
#  Expense（花费记录）
# ═══════════════════════════════════════════════════════════════

def _expense_path() -> str:
    return os.path.join(_DATA_DIR, "expenses.json")


def _load_expenses() -> List[Dict[str, Any]]:
    p = _expense_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_expenses(items: List[Dict[str, Any]]) -> None:
    p = _expense_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add_expense(
    amount: float,
    description: str,
    category: str = "其他",
    project: str = "",
    date: str = "",
    expense_type: str = "支出",
    payment: str = "",
    user_open_id: str = "",
) -> Dict[str, Any]:
    """记一笔花费，返回记录。"""
    record = {
        "id": str(uuid.uuid4()),
        "date": date or datetime.utcnow().strftime("%Y-%m-%d"),
        "category": category.strip() or "其他",
        "project": project.strip(),
        "description": description.strip(),
        "amount": round(float(amount), 2),
        "type": expense_type,
        "payment": payment.strip(),
        "user_open_id": user_open_id,
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with _lock:
        items = _load_expenses()
        items.append(record)
        _save_expenses(items)
    return record


def list_expenses(
    month: str = "",
    project: str = "",
    user_open_id: str = "",
) -> List[Dict[str, Any]]:
    """查询花费记录。month 格式 YYYY-MM，空则当月。"""
    if not month:
        month = datetime.utcnow().strftime("%Y-%m")
    items = _load_expenses()
    items = [e for e in items if e["date"].startswith(month)]
    if project:
        p = project.strip().lower()
        items = [e for e in items if e.get("project", "").lower() == p]
    if user_open_id:
        items = [e for e in items if e.get("user_open_id") == user_open_id]
    items.sort(key=lambda e: e["date"])
    return items


def month_summary(month: str = "") -> Dict[str, Any]:
    """月度汇总：总额、按类别、按项目。"""
    expenses = list_expenses(month=month)
    total = sum(e["amount"] for e in expenses if e["type"] == "支出")
    income = sum(e["amount"] for e in expenses if e["type"] == "收入")

    by_category: Dict[str, float] = {}
    by_project: Dict[str, float] = {}
    for e in expenses:
        if e["type"] != "支出":
            continue
        cat = e.get("category") or "其他"
        by_category[cat] = by_category.get(cat, 0) + e["amount"]
        proj = e.get("project") or "(无项目)"
        by_project[proj] = by_project.get(proj, 0) + e["amount"]

    return {
        "month": month or datetime.utcnow().strftime("%Y-%m"),
        "total_expense": round(total, 2),
        "total_income": round(income, 2),
        "count": len(expenses),
        "by_category": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        "by_project": {k: round(v, 2) for k, v in sorted(by_project.items(), key=lambda x: -x[1])},
    }


def export_month_rows(month: str = "") -> Tuple[List[str], List[List[str]]]:
    """导出月度花费为表格行，用于生成飞书表格。"""
    expenses = list_expenses(month=month)
    rows = []
    for e in expenses:
        rows.append([
            e["date"],
            e.get("category", ""),
            e.get("project", ""),
            e.get("description", ""),
            str(e["amount"]),
            e.get("type", "支出"),
            e.get("payment", ""),
            "",
        ])
    return EXPENSE_HEADERS, rows


# ═══════════════════════════════════════════════════════════════
#  Budget（项目预算）
# ═══════════════════════════════════════════════════════════════

def _budget_path() -> str:
    return os.path.join(_DATA_DIR, "budgets.json")


def _load_budgets() -> List[Dict[str, Any]]:
    p = _budget_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_budgets(items: List[Dict[str, Any]]) -> None:
    p = _budget_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def create_budget(
    project: str,
    items: List[Dict[str, Any]],
    spreadsheet_token: str = "",
    sheet_id: str = "",
    url: str = "",
) -> Dict[str, Any]:
    """创建项目预算。

    items: [{"name": "广告投放", "category": "营销", "budget": 50000}, ...]
    """
    total = sum(it.get("budget", 0) for it in items)
    budget = {
        "id": str(uuid.uuid4()),
        "project": project.strip(),
        "items": items,
        "total_budget": round(total, 2),
        "spreadsheet_token": spreadsheet_token,
        "sheet_id": sheet_id,
        "url": url,
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with _lock:
        budgets = _load_budgets()
        budgets = [b for b in budgets if b["project"].lower() != project.strip().lower()]
        budgets.append(budget)
        _save_budgets(budgets)
    return budget


def find_budget(project: str) -> Optional[Dict[str, Any]]:
    """按项目名查找预算。"""
    p = project.strip().lower()
    for b in _load_budgets():
        if b["project"].lower() == p:
            return b
    for b in _load_budgets():
        if p in b["project"].lower():
            return b
    return None


def list_budgets() -> List[Dict[str, Any]]:
    return _load_budgets()


def budget_vs_actual(project: str) -> Tuple[List[str], List[List[str]], Dict[str, Any]]:
    """生成预算 vs 实际花费对比表。

    从 expenses 中按项目+类别聚合实际花费，与预算项对比。
    Returns: (headers, rows, summary)
    """
    budget = find_budget(project)
    if not budget:
        return BUDGET_HEADERS, [], {"error": f"未找到项目「{project}」的预算"}

    all_expenses = _load_expenses()
    proj_lower = project.strip().lower()
    proj_expenses = [e for e in all_expenses if e.get("project", "").lower() == proj_lower and e["type"] == "支出"]

    actual_by_category: Dict[str, float] = {}
    for e in proj_expenses:
        cat = e.get("category", "其他")
        actual_by_category[cat] = actual_by_category.get(cat, 0) + e["amount"]

    total_budget = 0.0
    total_actual = 0.0
    rows = []
    for item in budget["items"]:
        name = item.get("name", "")
        cat = item.get("category", "")
        bgt = float(item.get("budget", 0))
        actual = actual_by_category.get(cat, 0)
        remaining = bgt - actual
        usage = f"{actual / bgt * 100:.0f}%" if bgt > 0 else "-"
        total_budget += bgt
        total_actual += actual
        rows.append([name, cat, f"{bgt:.0f}", f"{actual:.0f}", f"{remaining:.0f}", usage, ""])

    total_remaining = total_budget - total_actual
    total_usage = f"{total_actual / total_budget * 100:.0f}%" if total_budget > 0 else "-"
    rows.append(["合计", "", f"{total_budget:.0f}", f"{total_actual:.0f}",
                 f"{total_remaining:.0f}", total_usage, ""])

    summary = {
        "project": project,
        "total_budget": round(total_budget, 2),
        "total_actual": round(total_actual, 2),
        "total_remaining": round(total_remaining, 2),
        "usage_pct": total_usage,
        "expense_count": len(proj_expenses),
    }
    return BUDGET_HEADERS, rows, summary


# ═══════════════════════════════════════════════════════════════
#  Goals（目标追踪）
# ═══════════════════════════════════════════════════════════════

def _goals_path() -> str:
    return os.path.join(_DATA_DIR, "goals.json")


def _load_goals() -> List[Dict[str, Any]]:
    p = _goals_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save_goals(items: List[Dict[str, Any]]) -> None:
    p = _goals_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def add_goal(
    project: str,
    name: str,
    target: str,
    unit: str = "",
    deadline: str = "",
) -> Dict[str, Any]:
    """为项目添加目标/KPI。"""
    goal = {
        "id": str(uuid.uuid4()),
        "project": project.strip(),
        "name": name.strip(),
        "target": target.strip(),
        "current": "0",
        "unit": unit.strip(),
        "deadline": deadline.strip(),
        "status": "进行中",
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    with _lock:
        goals = _load_goals()
        goals.append(goal)
        _save_goals(goals)
    return goal


def update_goal(goal_id: str, current: Optional[str] = None, status: Optional[str] = None) -> Tuple[bool, str]:
    """更新目标进度。"""
    with _lock:
        goals = _load_goals()
        for g in goals:
            if g["id"] == goal_id:
                if current is not None:
                    g["current"] = current.strip()
                if status is not None:
                    g["status"] = status.strip()
                _save_goals(goals)
                return True, f"已更新：{g['name']} → {g.get('current','')}/{g['target']}"
        return False, "未找到该目标"


def list_goals(project: str = "") -> List[Dict[str, Any]]:
    """列出目标，可按项目筛选。"""
    goals = _load_goals()
    if project:
        p = project.strip().lower()
        goals = [g for g in goals if g.get("project", "").lower() == p]
    return goals


def find_goal_by_keyword(keyword: str, project: str = "") -> Optional[Dict[str, Any]]:
    """按关键词模糊查找目标。"""
    goals = list_goals(project)
    kw = keyword.strip().lower()
    for g in goals:
        if kw in g["name"].lower():
            return g
    return None


# ═══════════════════════════════════════════════════════════════
#  Project Dashboard（项目总览聚合）
# ═══════════════════════════════════════════════════════════════

DASHBOARD_HEADERS = ["维度", "指标", "目标", "当前", "进度", "状态"]


def project_dashboard(project: str) -> Tuple[List[str], List[List[str]]]:
    """聚合项目的任务、预算、目标，生成总览表。

    从三个数据源拉取：
      - memo/projects → 项目元信息
      - finance/expenses → 实际花费
      - finance/budgets → 预算定义
      - finance/goals → 目标 KPIs
    """
    proj_lower = project.strip().lower()
    rows: List[List[str]] = []

    # 预算维度
    budget = find_budget(project)
    if budget:
        all_expenses = _load_expenses()
        proj_expenses = [e for e in all_expenses if e.get("project", "").lower() == proj_lower and e["type"] == "支出"]
        total_budget = budget.get("total_budget", 0)
        total_actual = sum(e["amount"] for e in proj_expenses)
        usage = f"{total_actual / total_budget * 100:.0f}%" if total_budget > 0 else "-"
        remaining = total_budget - total_actual
        status = "正常" if remaining >= 0 else "超支"
        rows.append([
            "💰 预算", "花费",
            f"¥{total_budget:,.0f}", f"¥{total_actual:,.0f}",
            usage, status,
        ])

    # 目标维度
    goals = list_goals(project)
    for g in goals:
        try:
            t_val = float(g["target"])
            c_val = float(g["current"])
            pct = f"{c_val / t_val * 100:.0f}%" if t_val > 0 else "-"
        except (ValueError, ZeroDivisionError):
            pct = "-"
        unit = g.get("unit", "")
        rows.append([
            "🎯 目标", g["name"],
            f"{g['target']}{unit}", f"{g['current']}{unit}",
            pct, g.get("status", "进行中"),
        ])

    if not rows:
        rows.append(["—", "暂无数据", "—", "—", "—", "尚未设置预算或目标"])

    return DASHBOARD_HEADERS, rows


def available_project_tags() -> List[str]:
    """返回所有可用的项目标签（用于记账时提示用户选择）。"""
    from memo.projects import list_projects
    tags = [p["name"] for p in list_projects()]
    for b in _load_budgets():
        if b["project"] not in tags:
            tags.append(b["project"])
    return tags
