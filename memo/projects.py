# -*- coding: utf-8 -*-
"""
团队项目注册表 — 记录每个项目对应的飞书电子表格信息，支持持续维护。

存储路径：data/projects.json
每个项目：{id, name, spreadsheet_token, sheet_id, url, created_at, created_by}
"""
import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent / "data" / "projects.json")
_lock = threading.Lock()

PROJECT_HEADERS = ["任务/议题", "来源", "负责人", "状态", "优先级", "截止日期", "备注"]


def _path() -> str:
    return (os.environ.get("PROJECT_STORE_PATH") or "").strip() or _DEFAULT_PATH


def _load() -> List[Dict[str, Any]]:
    p = _path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def _save(items: List[Dict[str, Any]]) -> None:
    p = _path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def register_project(
    name: str,
    spreadsheet_token: str,
    sheet_id: str,
    url: str,
    created_by: str = "",
) -> str:
    """注册新项目，返回 project_id。"""
    project = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "spreadsheet_token": spreadsheet_token,
        "sheet_id": sheet_id,
        "url": url,
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by": created_by,
    }
    with _lock:
        items = _load()
        items.append(project)
        _save(items)
    return project["id"]


def list_projects() -> List[Dict[str, Any]]:
    """列出所有项目。"""
    return _load()


def find_project(name: str) -> Optional[Dict[str, Any]]:
    """按名称模糊查找项目（大小写不敏感）。"""
    name_lower = name.strip().lower()
    items = _load()
    for p in items:
        if p["name"].lower() == name_lower:
            return p
    for p in items:
        if name_lower in p["name"].lower():
            return p
    return None


def delete_project(name: str) -> Tuple[bool, str]:
    """按名称删除项目注册（不删飞书表格）。"""
    name_lower = name.strip().lower()
    with _lock:
        items = _load()
        before = len(items)
        items = [p for p in items if p["name"].lower() != name_lower]
        if len(items) == before:
            return False, f"未找到项目「{name}」"
        _save(items)
    return True, f"已移除项目「{name}」的注册"
