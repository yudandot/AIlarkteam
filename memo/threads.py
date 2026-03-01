# -*- coding: utf-8 -*-
"""
线程自动识别 — 根据备忘内容推断所属工作线程。

信号词来源（优先级递减）：
  1. 用户 personal skill profile 中的 focus_areas 和 role signals
  2. 已有线程名的模糊匹配
"""

from __future__ import annotations

import re
from typing import Optional

_PERSONAL_SIGNALS: Optional[dict[str, list[str]]] = None


def _load_personal_signals() -> dict[str, list[str]]:
    """从 personal skill 的 SKILL.md 中提取信号词。"""
    global _PERSONAL_SIGNALS
    if _PERSONAL_SIGNALS is not None:
        return _PERSONAL_SIGNALS

    _PERSONAL_SIGNALS = {}
    try:
        from skills import get_skill
        ps = get_skill("personal")
        if not ps:
            return _PERSONAL_SIGNALS
        path = ps._find_profile_path()
        if not path or not path.exists():
            return _PERSONAL_SIGNALS

        text = path.read_text(encoding="utf-8")

        signal_match = re.search(
            r'\|\s*Signal\s*\|\s*Role\s*\|.*?\n\|[-\s|]+\n(.*?)(?:\n\n|\n---)',
            text, re.DOTALL
        )
        if signal_match:
            for line in signal_match.group(1).strip().split("\n"):
                parts = [p.strip() for p in line.strip().strip("|").split("|")]
                if len(parts) >= 2:
                    signals = [s.strip().strip('"') for s in parts[0].split(",") if s.strip()]
                    role = parts[1].strip()
                    if "上班" in role:
                        thread_name = "工作"
                    elif "捣鼓" in role:
                        thread_name = "个人项目"
                    else:
                        continue
                    for sig in signals:
                        if sig and len(sig) >= 2:
                            _PERSONAL_SIGNALS.setdefault(thread_name, []).append(sig)

        focus_pattern = re.compile(
            r'^\*\*(.+?)\*\*\s*[—–-]\s*(.+?)$',
            re.MULTILINE
        )
        for m in focus_pattern.finditer(text):
            title = m.group(1).strip()
            if len(title) < 2 or len(title) > 30:
                continue
            if any(skip in title.lower() for skip in ["上班", "可以依赖", "需要补偿", "自己捣鼓"]):
                continue
            short = re.split(r'[（()）/\s]+', title)
            keywords = [k for k in short if len(k) >= 2]
            sub_keywords = []
            for kw in keywords:
                sub_keywords.append(kw)
                parts = re.findall(r'[\u4e00-\u9fff]{2,}', kw)
                for p in parts:
                    if p != kw and len(p) >= 2:
                        sub_keywords.append(p)
            if sub_keywords:
                _PERSONAL_SIGNALS[title] = list(dict.fromkeys(sub_keywords))

    except Exception:
        pass

    return _PERSONAL_SIGNALS


def detect_thread(content: str, existing_threads: Optional[list[str]] = None) -> str:
    """
    从备忘内容推断线程名。
    优先匹配已有线程 > focus area 线程 > 宽泛角色线程。
    返回空字符串表示无法识别。
    """
    if not content or not content.strip():
        return ""

    lower = content.lower()

    if existing_threads:
        for t in existing_threads:
            if t.lower() in lower:
                return t

    signals = _load_personal_signals()
    generic = {"工作", "个人项目", "通用"}

    best_thread = ""
    best_score = 0
    best_is_generic = True

    for thread_name, keywords in signals.items():
        score = 0
        for kw in keywords:
            kw_l = kw.lower()
            if kw_l in lower:
                score += 1
            elif len(kw_l) >= 5 and kw_l[:4] in lower:
                score += 0.5
        is_generic = thread_name in generic
        if score > 0:
            if (not best_is_generic and is_generic):
                continue
            if (best_is_generic and not is_generic and score >= 1) or (score > best_score):
                best_score = score
                best_thread = thread_name
                best_is_generic = is_generic

    if best_score > 0:
        return best_thread

    return ""


def extract_thread_tag(text: str) -> tuple[str, str]:
    """
    从文本中提取 #标签，返回 (clean_text, thread_name)。

    >>> extract_thread_tag("Starboard 策展流程 #creator")
    ('Starboard 策展流程', 'creator')
    """
    m = re.search(r'#([\w\u4e00-\u9fff]+)', text)
    if m:
        tag = m.group(1)
        clean = text[:m.start()].rstrip() + text[m.end():].lstrip()
        return clean.strip(), tag
    return text.strip(), ""
