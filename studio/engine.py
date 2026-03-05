# -*- coding: utf-8 -*-
"""
studio/engine.py — 引擎封装层
==============================
把项目现有的 brainstorm / planner / creative / agent 引擎
包装为 Streamlit 友好的接口：
  - 自动配置 sys.path
  - 进度捕获（stdout → Streamlit 容器）
  - API key 校验与持久化
  - 禁用飞书推送、跳过 sleep
"""
from __future__ import annotations

import builtins
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

# ── 模型插槽 & 预设 ─────────────────────────────────────────

MODEL_SLOTS = [
    {
        "name": "primary",
        "label": "主力模型",
        "desc": "规划、分析、逻辑推理",
        "env_key": "DEEPSEEK_API_KEY",
        "env_url": "DEEPSEEK_BASE_URL",
        "env_model": "DEEPSEEK_MODEL",
    },
    {
        "name": "creative",
        "label": "创意模型",
        "desc": "脑暴中的创意发散角色",
        "env_key": "DOUBAO_API_KEY",
        "env_url": "DOUBAO_BASE_URL",
        "env_model": "DOUBAO_MODEL",
    },
    {
        "name": "longctx",
        "label": "长文本模型",
        "desc": "素材交付、长文本处理",
        "env_key": "KIMI_API_KEY",
        "env_url": "KIMI_BASE_URL",
        "env_model": "KIMI_MODEL",
    },
]

PRESETS: dict[str, dict[str, str]] = {
    "DeepSeek": {
        "url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
    "Gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": "gemini-2.5-flash",
    },
    "GPT-4o": {
        "url": "https://api.openai.com",
        "model": "gpt-4o",
    },
    "Kimi (Moonshot)": {
        "url": "https://api.moonshot.cn/v1",
        "model": "moonshot-v1-128k",
    },
    "豆包 (Doubao)": {
        "url": "https://ark.cn-beijing.volces.com/api/v3",
        "model": "doubao-1.5-pro-32k",
    },
    "通义千问": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
    },
}

ENV_PATH = _PROJECT_ROOT / ".env"


def load_env() -> dict[str, str]:
    """从 .env 读取所有已配置的 key。"""
    env: dict[str, str] = {}
    if not ENV_PATH.exists():
        return env
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    except Exception:
        pass
    return env


def save_env(updates: dict[str, str]) -> None:
    """把 key-value 追加/覆盖到 .env，保留已有内容和注释。"""
    existing: dict[str, int] = {}
    lines: list[str] = []
    if ENV_PATH.exists():
        try:
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    k = stripped.split("=", 1)[0].strip()
                    existing[k] = len(lines)
                lines.append(line)
        except Exception:
            lines = []
            existing = {}

    for k, v in updates.items():
        if not v:
            continue
        new_line = f"{k}={v}"
        if k in existing:
            lines[existing[k]] = new_line
        else:
            lines.append(new_line)

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for k, v in updates.items():
        if v:
            os.environ[k] = v


def check_keys() -> dict[str, bool]:
    """检查三个模型插槽的 API Key 是否已配置。"""
    return {
        slot["label"]: bool(os.environ.get(slot["env_key"], "").strip())
        for slot in MODEL_SLOTS
    }


def all_keys_ready() -> bool:
    return all(check_keys().values())


def detect_preset(base_url: str) -> str:
    """根据 Base URL 推断当前使用的服务商。"""
    if not base_url:
        return ""
    for name, cfg in PRESETS.items():
        if cfg["url"] and base_url.rstrip("/").startswith(cfg["url"].rstrip("/")[:25]):
            return name
    return "自定义"


# ── CN MKT Skills ────────────────────────────────────────────

_MODULES_DIR = _PROJECT_ROOT / "CN-MKT-Skills" / "modules"


_MODULE_TITLES_ZH: dict[str, str] = {
    "01": "游戏与品牌",
    "02": "目标受众与生命周期",
    "03": "竞品分析",
    "04": "社交媒体平台运营",
    "05": "用户获取与分发",
    "06": "数据分析",
    "07": "内容与本地化",
    "08": "素材制作",
    "09": "社区建设",
    "10": "活动策划与项目管理",
    "11": "营销 SOP",
    "12": "预算管理",
    "13": "游戏发行",
    "14": "运营与商业化",
    "15": "测试与上线",
    "16": "跨平台",
    "17": "代理商与合作伙伴",
    "18": "线下活动与周边 IP",
    "19": "跨境协作",
    "20": "提案与汇报",
    "21": "AI 营销应用",
    "22": "合规与监管",
}


def list_skills() -> list[dict[str, str]]:
    """列出所有可用的 CN MKT 知识模块，返回 [{file, title}]。"""
    if not _MODULES_DIR.exists():
        return []
    modules = []
    for f in sorted(_MODULES_DIR.glob("*.md")):
        num = f.stem.split("-", 1)[0] if "-" in f.stem else ""
        title = _MODULE_TITLES_ZH.get(num, f.stem.replace("-", " "))
        modules.append({"file": f.name, "title": title})
    return modules


def load_skill(filename: str, max_chars: int = 8000) -> str:
    """加载指定 skill 模块的内容。"""
    path = _MODULES_DIR / filename
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    return text[:max_chars] if len(text) > max_chars else text


_TOTAL_SKILL_BUDGET = 25000


def build_skill_context(selected_files: list[str]) -> str:
    """将用户选择的 skill 模块拼接为背景知识文本。动态分配每个模块的字符预算。"""
    if not selected_files:
        return ""
    files = selected_files[:3]
    per_file = _TOTAL_SKILL_BUDGET // len(files)
    chunks = []
    for f in files:
        text = load_skill(f, max_chars=per_file)
        if text:
            chunks.append(text)
    if not chunks:
        return ""
    return "\n\n━━ 以下为参考的营销知识 ━━\n\n" + "\n\n---\n\n".join(chunks)


# ── 禁用飞书推送 & 减少 sleep ────────────────────────────────

def _disable_feishu():
    """设置空 webhook，引擎会静默跳过推送。同时缩短 sleep 间隔。"""
    for k in ("FEISHU_WEBHOOK", "PLANNER_FEISHU_WEBHOOK",
              "CONDUCTOR_BRAINSTORM_WEBHOOK", "BRAINSTORM_FEISHU_WEBHOOK"):
        os.environ.pop(k, None)
    try:
        import brainstorm.run as _bm
        _bm.FEISHU_INTERVAL = 0
    except Exception:
        pass
    try:
        import planner.run as _pm
        _pm.FEISHU_INTERVAL = 0
    except Exception:
        pass


# ── 进度捕获 ─────────────────────────────────────────────────

def run_with_progress(
    fn: Callable,
    progress_container,
    *args,
    **kwargs,
) -> Any:
    """
    在后台线程运行 fn，将 print 输出实时显示到 Streamlit 容器中。
    返回 fn 的返回值；fn 抛出异常则原样 raise。
    """
    _disable_feishu()
    pq: queue.Queue[Optional[str]] = queue.Queue()
    result_holder: list[Any] = [None]
    error_holder: list[Optional[Exception]] = [None]
    _orig = builtins.print

    def _patched(*pargs, flush=False, **pkwargs):
        msg = " ".join(str(a) for a in pargs)
        if msg.strip():
            pq.put(msg.rstrip())
        _orig(*pargs, flush=flush, **pkwargs)

    def _worker():
        builtins.print = _patched
        try:
            result_holder[0] = fn(*args, **kwargs)
        except Exception as e:
            error_holder[0] = e
        finally:
            builtins.print = _orig
            pq.put(None)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    lines: list[str] = []
    while True:
        try:
            msg = pq.get(timeout=0.4)
            if msg is None:
                break
            lines.append(msg)
            progress_container.code("\n".join(lines[-30:]), language=None)
        except queue.Empty:
            if lines:
                progress_container.code("\n".join(lines[-30:]), language=None)

    t.join(timeout=10)
    if error_holder[0]:
        raise error_holder[0]
    return result_holder[0]


# ── 引擎调用 ─────────────────────────────────────────────────

def run_brainstorm_engine(
    topic: str,
    context: str = "",
    topic_type: str = "",
    skill_context: str = "",
    progress_container=None,
) -> dict:
    """运行脑暴引擎，返回结构化结果。"""
    from brainstorm.run import run_brainstorm

    if progress_container is None:
        import streamlit as st
        progress_container = st.empty()

    full_context = context
    if skill_context:
        full_context = (context + "\n\n" + skill_context) if context else skill_context

    result = run_with_progress(
        run_brainstorm,
        progress_container,
        topic=topic,
        context=full_context,
        topic_type=topic_type if topic_type != "auto" else "",
    )
    session_path = str(result)
    session_content = ""
    if Path(session_path).exists():
        session_content = Path(session_path).read_text(encoding="utf-8")

    return {
        "session_path": session_path,
        "session_content": session_content,
        "round_summaries": getattr(result, "round_summaries", []),
        "final_output": getattr(result, "final_output", ""),
        "topic_refined": getattr(result, "topic_refined", ""),
    }


def run_research_engine(
    question: str,
    context: str = "",
    skill_context: str = "",
    progress_container=None,
) -> str:
    """运行调研引擎（Researcher — fact-checked 深度研究），返回调研报告。"""
    from research.researcher import Researcher

    _disable_feishu()

    if progress_container is None:
        import streamlit as st
        progress_container = st.empty()

    def _run():
        query = question
        if context:
            query += f"\n\n补充背景：{context}"
        if skill_context:
            query += f"\n\n{skill_context}"
        r = Researcher()
        return r.research(query, verbose=True)

    return run_with_progress(_run, progress_container)


def run_planning_engine(
    topic: str,
    context: str = "",
    mode: str = "完整规划",
    skill_context: str = "",
    progress_container=None,
) -> dict:
    """运行规划引擎，返回结构化结果。"""
    from planner.run import run_planning

    if progress_container is None:
        import streamlit as st
        progress_container = st.empty()

    full_context = context
    if skill_context:
        full_context = (context + "\n\n" + skill_context) if context else skill_context

    result = run_with_progress(
        run_planning,
        progress_container,
        topic=topic,
        context=full_context,
        mode=mode,
    )

    session_path, step_outputs = result
    session_content = ""
    if Path(session_path).exists():
        session_content = Path(session_path).read_text(encoding="utf-8")

    return {
        "session_path": session_path,
        "session_content": session_content,
        "step_outputs": step_outputs,
    }


def run_creative_engine(
    topic: str,
    brand: str = "",
    platform: str = "抖音",
    duration: str = "30秒",
    skill_context: str = "",
    progress_container=None,
) -> dict:
    """运行创作引擎：选题 → 素材 prompt(含分镜) → brief。"""
    from core.llm import chat_completion
    from creative.knowledge import (
        CORE_SYSTEM_PROMPT, build_system_prompt, build_user_prompt,
        build_exec_brief_prompt, load_brand_by_name, detect_brand_from_text,
    )

    _disable_feishu()

    if progress_container is None:
        import streamlit as st
        progress_container = st.empty()

    def _run():
        # --- Stage 1: 选题思考 ---
        print("[选题] 正在分析主题，生成选题方向...", flush=True)
        topic_system = (
            "你是资深内容策划。根据用户的创作需求，输出 3 个差异化的选题方向。\n\n"
            "每个方向包含：\n"
            "1. **选题标题**（一句话抓眼球）\n"
            "2. **核心创意**（用什么角度/手法来表达）\n"
            "3. **目标受众的 hook**（为什么会停下来看）\n"
            "4. **平台适配建议**（适合哪个平台/格式）\n\n"
            "用中文输出，简洁有力。"
        )
        topic_input = f"创作需求：{topic}"
        if brand:
            topic_input += f"\n品牌：{brand}"
        topic_input += f"\n目标平台：{platform}\n时长：{duration}"
        if skill_context:
            topic_input += f"\n\n{skill_context}"
        ideas_text = chat_completion(
            provider="deepseek", system=topic_system,
            user=topic_input, temperature=0.8,
        ).strip()
        print("[选题] 完成", flush=True)

        # --- Stage 2: 素材 Prompt（含分镜） ---
        print("[素材Prompt] 正在生成视频/图片 prompt...", flush=True)
        brand_profile = None
        if brand:
            brand_profile = load_brand_by_name(brand)
        if not brand_profile and (brand or topic):
            brand_profile = detect_brand_from_text(f"{brand} {topic}")

        creative_system = build_system_prompt(
            brand=brand_profile, user_text=topic,
        )
        creative_user = build_user_prompt(
            f"{topic}，{duration}，发布到{platform}。"
            f"参考选题方向：\n{ideas_text[:1500]}"
        )
        creative_prompt = chat_completion(
            provider="kimi", system=creative_system,
            user=creative_user, temperature=0.7,
        ).strip()
        print("[素材Prompt] 完成", flush=True)

        # --- Stage 3: 执行 Brief ---
        print("[Brief] 正在生成执行 Brief...", flush=True)
        brief_user = build_exec_brief_prompt(
            discussion_summary=ideas_text[:800],
            ai_prompt=creative_prompt[:1000],
        )
        brief_system = (
            "你是专业的创意执行策划师。根据提供的创意概念和讨论内容，"
            "生成一份简洁完整的执行 Brief。使用中文。"
        )
        brief_text = chat_completion(
            provider="deepseek", system=brief_system,
            user=brief_user, temperature=0.5,
        ).strip()
        print("[Brief] 完成", flush=True)

        # --- AI 深化 Prompt ---
        print("[AI Prompt] 正在生成 AI 深化 prompt...", flush=True)
        handoff_system = (
            "根据以下创作产出，写一段完整的 prompt 让用户复制给 Claude / GPT 继续深化。\n"
            "prompt 要包含：选题方向、素材描述、执行要求，让 AI 能独立产出更多变体或优化方案。\n"
            "prompt 必须自洽完整、使用中文。"
        )
        handoff_input = (
            f"选题方向：\n{ideas_text[:1000]}\n\n"
            f"素材 Prompt：\n{creative_prompt[:1500]}\n\n"
            f"执行 Brief：\n{brief_text[:1000]}"
        )
        handoff_text = chat_completion(
            provider="deepseek", system=handoff_system,
            user=handoff_input, temperature=0.5,
        ).strip()
        print("[AI Prompt] 完成", flush=True)

        return {
            "ideas": ideas_text,
            "creative_prompt": creative_prompt,
            "brief": brief_text,
            "handoff": handoff_text,
        }

    return run_with_progress(_run, progress_container)
