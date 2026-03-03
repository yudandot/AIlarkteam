# -*- coding: utf-8 -*-
"""
脑暴主流程 —— 坚果五仁 v3 四轮讨论协议。
==========================================

这是脑暴机器人的核心引擎，编排 5 个 AI 角色进行四轮结构化讨论：

  第 1 轮 Idea Expansion（发散）  → 产出约 10 个体验方向
  第 2 轮 Experience Embodiment   → 压缩为 6 个可执行候选
  第 3 轮 Brutal Selection（淘汰）→ 三道筛子，只留 3 个方向
  第 4 轮 Execution Conversion    → 交付物（总结 + Claude Code prompt + 视觉 prompt）

5 个角色（坚果五仁）：
  芝麻仁 — 现实架构师（DeepSeek）：负责可行性、成本、约束
  核桃仁 — 玩家化身（豆包）    ：第一人称验证体验真实性
  杏仁   — 体验导演（Kimi）    ：设计具体瞬间、情绪峰值
  瓜子仁 — 传播架构师（Kimi）  ：设计可分享单元、传播路径
  松子仁 — 体验总成（DeepSeek）：收敛、裁决、产出最终交付物

每轮结束后自动生成摘要，作为下一轮的上下文记忆。
全程结果保存到 runs/ 目录，并实时推送到飞书群。

使用方式：
  CLI  : python3 -m brainstorm --topic "主题" --context "背景"
  代码 : from brainstorm.run import run_brainstorm
"""
import argparse
import json
import time
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import re as _re
from core.feishu_webhook import send_text, _send_card
import os as _os
from core.llm import chat_completion, get_model_for_role
from core.utils import load_context, run_timestamp, save_session, truncate_for_display
from skills import load_context as load_skill_context


def _format_discussion_for_readability(text: str) -> str:
    """提升讨论内容可读性：在逻辑分段前插入空行，便于扫读。"""
    if not text or not text.strip():
        return text
    lines = text.rstrip().split("\n")
    out = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 新逻辑块开头：前一行非空则先加空行
        is_section_start = (
            stripped.startswith("对于")
            or stripped.startswith("还有")
            or stripped.startswith("另外")
            or stripped.startswith("→")
            or _re.match(r"^(保留|淘汰)[：:]", stripped)
            or stripped.startswith("同意")
            or stripped.startswith("我同意")
            or _re.match(r"^方向[一二三四五六七八九十\d]+", stripped)
            or (_re.match(r"^\*\*", stripped) and i > 0)
        )
        if is_section_start and out and out[-1].strip():
            out.append("")
        out.append(line)
    return "\n".join(out)


def _send_brainstorm_card(title: str, content: str, color: str = "blue", webhook_override: Optional[str] = None) -> bool:
    # 优先使用调用方传入的 webhook（脑暴机器人 vs 自媒体助手 分群推送）
    if webhook_override:
        webhook = webhook_override.strip()
    else:
        webhook = (_os.environ.get("CONDUCTOR_BRAINSTORM_WEBHOOK") or _os.environ.get("FEISHU_WEBHOOK") or "").strip()
    if not webhook:
        return False
    secret = (_os.environ.get("FEISHU_SECRET") or "").strip()
    return _send_card(title, content, webhook, secret=secret, color=color)


REFINE_SYSTEM_CAMPAIGN = """You are a Creative Strategy Architect.

Your task is to clarify and structure the user's raw topic into a Brainstorm Seed. Stay close to the user's original topic: do not over-interpret, over-expand, or replace it with a different brief. Preserve the core intent and wording; only add structure and clarity. Do not add assumptions or objectives the user did not imply.

Extract USER INSIGHTS and PROJECT INSIGHTS only from what the topic and materials actually imply. Keep insights concise.

You must output in the following structure:

---

INSIGHT LAYER

User Insight:
(concise; only what the topic/materials support)

Project Insight:
(nature of project, constraints, behavioral success; concise)

Campaign Context Insight:
(how participants encounter it, defining moment, after; concise)

---

Then generate the Brainstorm Seed:

---

#brainstorm

原始主题：
(Copy the user's raw topic verbatim, character for character. Do not paraphrase or rewrite.)

Theme:
(reframe only slightly; stay aligned with original topic)

Background:
(brief, from materials)

Core Challenge:
(the real difficulty implied by the topic)

Constraints:
(realistic; from topic/materials)

Core Goal:
(one clear experiential goal; do not broaden scope)

Campaign Role:
offline experiential core / online propagation trigger / hybrid campaign anchor

Campaign Phase:
Seed / Ignite / Spread / Peak / Echo

Core Task:

Design a Core Experience Atom:

When【trigger】
Participant【experiences】
Participant【emotion】
Participant【behavior】

---

Requirements:

Total length: under 500 words. Insights and theme must not expand beyond what the raw topic implies.

All output must be in Chinese (中文).

Do not use asterisks (* or **). Plain text only.

Do not over-interpret: if the topic is narrow, keep the seed narrow. If the topic does not specify something, do not invent it.

Only output the structured content; do not explain your reasoning."""


REFINE_SYSTEM_PROJECT = """You are a Creative Strategy Architect for product and project brainstorming.

Your task is to clarify and structure the user's raw topic into a Brainstorm Seed. Stay close to the user's original topic: do not over-interpret, over-expand, or replace it with a different brief.

You must output in the following structure:

---

INSIGHT LAYER

User Insight:
(what the creator wants to achieve or explore; concise)

Project Insight:
(nature of project, current stage, technical/resource constraints; concise)

---

#brainstorm

原始主题：
(Copy the user's raw topic verbatim, character for character.)

Theme:
(reframe only slightly; stay aligned with original topic)

Background:
(brief, from materials)

Core Challenge:
(the real difficulty implied by the topic)

Constraints:
(realistic; from topic/materials)

Core Goal:
(one clear goal for this project; do not broaden scope)

Target User:
(who benefits from this; what they currently lack)

Key Design Tension:
(the core tradeoff or dilemma the project must resolve)

Core Task:

Design the Core Experience:

User【does what action】
User【feels what】
User【then does what as a result】

---

Requirements:

Total length: under 500 words. All output in Chinese (中文). Plain text only, no asterisks.
Do not over-interpret. Only output the structured content; do not explain your reasoning."""


REFINE_SYSTEM_EXPLORE = """You are a Creative Strategy Architect for life and personal brainstorming.

Your task is to clarify and structure the user's raw topic into a Brainstorm Seed. Stay close to the user's original topic: do not over-interpret, over-expand, or replace it with a different brief.

You must output in the following structure:

---

INSIGHT LAYER

User Insight:
(what the person actually wants — not just what they said; concise)

Situation Insight:
(current state, real constraints, what has been tried or assumed; concise)

---

#brainstorm

原始主题：
(Copy the user's raw topic verbatim, character for character.)

Theme:
(reframe only slightly; stay aligned with original topic)

Background:
(brief, from materials or implied context)

Core Challenge:
(the real difficulty — often not what the person thinks it is)

Constraints:
(time, resources, personality, situation; realistic)

Goal:
(one clear outcome to brainstorm toward; do not broaden scope)

Hidden Assumption:
(what the person might be taking for granted that could be wrong)

Core Task:

Design the Core Action:

When【trigger or opportunity arises】
Person【does what specific action】
Person【gets what result or feeling】

---

Requirements:

Total length: under 500 words. All output in Chinese (中文). Plain text only, no asterisks.
Do not over-interpret. Only output the structured content; do not explain your reasoning."""


REFINE_SYSTEM_STRATEGY = """You are a Strategic Thinking Facilitator.

Your task is to structure the user's open-ended strategic question into a Brainstorm Seed that PRESERVES the breadth and depth of the original question. Do NOT narrow it down to a single action or solution. The goal is to map the debate landscape, not to converge prematurely.

You must output in the following structure:

---

INSIGHT LAYER

Strategic Insight:
(what is really being asked — the deeper strategic tension beneath the surface question; concise)

Assumption Audit:
(2-3 hidden assumptions embedded in the question that deserve scrutiny)

Landscape Insight:
(what the current state of thinking/practice is on this topic, based on your search; concise)

---

#brainstorm

原始主题：
(Copy the user's raw topic verbatim, character for character.)

Theme:
(reframe to highlight the core strategic tension; do not narrow)

Background:
(brief context from materials or implied knowledge)

The Debate:
(frame the question as 2-3 competing positions/hypotheses, each with its strongest argument)

Key Variables:
(what factors would make each position more or less true?)

What Would Change Our Mind:
(what evidence or insight would decisively tip the balance?)

Scope Boundaries:
(what this discussion is NOT about — prevent drift)

Core Task:

Explore the strategic question from multiple angles:
1. Stress-test each position with real examples and counterexamples
2. Find the hidden third option that transcends the either/or framing
3. Identify actionable implications regardless of which position wins

---

Requirements:

Total length: under 600 words. All output in Chinese (中文). Plain text only, no asterisks.
CRITICAL: Do NOT collapse the question into a single goal or action plan. Keep the exploration space OPEN.
Only output the structured content; do not explain your reasoning."""


# ── 话题类型检测 ──────────────────────────────────────────────

_CAMPAIGN_SIGNALS = (
    "营销", "推广", "活动", "传播", "品牌", "campaign", "launch",
    "内容策略", "社媒", "线下活动", "联动", "合作", "种草",
    "周年", "发布", "曝光", "宣传", "事件营销", "快闪",
    "小红书", "抖音", "B站", "微博", "快手",
)

_PROJECT_SIGNALS = (
    "设计", "开发", "产品", "功能", "系统", "工具", "app", "游戏",
    "模拟器", "bot", "机器人", "架构", "原型", "MVP",
    "project", "side project", "对话系统", "玩法", "机制",
)

_STRATEGY_SIGNALS = (
    "价值", "本质", "还是", "应该", "如何", "为什么", "是否",
    "策略", "战略", "定位", "方向", "选择", "取舍", "路线",
    "底层逻辑", "第一性", "假设", "前提", "悖论", "矛盾",
    "模式", "思考", "探讨", "辩论", "反思", "洞察",
    "advocacy", "advocator", "philosophy", "strategy",
)

_STRATEGY_STRONG_PATTERNS = (
    "还是", "是否应该", "本质是", "价值来自", "到底是",
    "如果是后者", "如果是前者", "应该如何",
)


def _detect_topic_type(topic: str, context: str = "") -> str:
    """从话题内容推断脑暴类型：campaign / project / strategy / explore"""
    combined = f"{topic} {context}".lower()

    strong_strategy = sum(1 for p in _STRATEGY_STRONG_PATTERNS if p in combined)
    if strong_strategy >= 2:
        return "strategy"

    campaign_score = sum(1 for s in _CAMPAIGN_SIGNALS if s.lower() in combined)
    project_score = sum(1 for s in _PROJECT_SIGNALS if s.lower() in combined)
    strategy_score = sum(1 for s in _STRATEGY_SIGNALS if s.lower() in combined)

    if strategy_score >= 3 and strategy_score > campaign_score and strategy_score > project_score:
        return "strategy"
    if campaign_score >= project_score and campaign_score > 0:
        return "campaign"
    if project_score > 0:
        return "project"
    if strategy_score >= 2:
        return "strategy"
    return "explore"


_REFINE_SYSTEMS = {
    "campaign": REFINE_SYSTEM_CAMPAIGN,
    "project": REFINE_SYSTEM_PROJECT,
    "strategy": REFINE_SYSTEM_STRATEGY,
    "explore": REFINE_SYSTEM_EXPLORE,
}

REFINE_SYSTEM = REFINE_SYSTEM_CAMPAIGN


def refine_brainstorm_topic_deepseek(topic: str, context: str, topic_type: str = "campaign") -> str:
    """用 AgentLoop 优化脑暴主题——LLM 可搜索行业信息、竞品案例来丰富 Insight。"""
    from core.agent import AgentLoop
    from core.tools import WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, TRENDING_TOOL, SEARCH_PLATFORM_TOOL

    user = f"""Input: Raw brainstorming topic and background materials below.

Output: First the INSIGHT LAYER (concise), then the Brainstorm Seed. In the #brainstorm section you must include "原始主题：" and copy the raw topic below verbatim (一字不改). Stay close to the user's topic; do not over-interpret or add objectives they did not imply. All content in Chinese (中文). No asterisks; plain text only.

---

Raw topic:
{topic}

Background materials:
{context[:8000] if len(context) > 8000 else context}"""

    refine_sys = _REFINE_SYSTEMS.get(topic_type, REFINE_SYSTEM_CAMPAIGN)
    refine_sys += (
        "\n\n你拥有搜索工具。在生成 Insight Layer 之前，建议先搜索：\n"
        "1. 相关行业/话题的最新动态（用 web_search 或 news_search）\n"
        "2. 如果涉及社交平台内容，搜一下平台上相关话题的热度和角度（用 search_platform）\n"
        "3. 如果需要了解当前热点，用 get_trending\n"
        "搜索结果可以帮你写出更有洞察力的 Insight Layer，但不要过度搜索——2-3次搜索足够。"
    )

    try:
        from core.skill_router import enrich_prompt
        refine_sys = enrich_prompt(refine_sys, user_text=user, bot_type="brainstorm")
    except Exception:
        pass

    try:
        agent = AgentLoop(
            provider="deepseek",
            system=refine_sys,
            max_rounds=5,
            temperature=0.7,
            on_tool_call=lambda name, args: print(f"  🔍 [主题调研] {name}: {str(args)[:80]}", flush=True),
        )
        agent.add_tools([WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, TRENDING_TOOL, SEARCH_PLATFORM_TOOL])
        result = agent.run(user)
        if result.tool_calls_made:
            print(f"  [主题优化] 搜索了 {len(result.tool_calls_made)} 次", flush=True)
        return result.content
    except Exception as e:
        print(f"  [主题优化] AgentLoop 失败({e}), 回退简单调用", flush=True)
        try:
            return chat_completion(provider="deepseek", system=refine_sys, user=user).strip()
        except Exception:
            return ""


# ── 角色 & 轮次配置 ─────────────────────────────────────────
# 下面保留了两套角色系统：
# 1. legacy 八仙 —— 旧版本（已弃用，保留兼容性）
# 2. 坚果五仁 v3 —— 当前版本（从 prompts.json 加载）
# 程序启动时自动检测 prompts.json，有则用坚果五仁，无则回退八仙。

ROLES_LEGACY = [
    "Strategy Lead", "Audience Insight", "Online Growth", "Offline Experience",
    "Brand Guardian", "Conversion & Funnel", "Risk & Compliance", "Synthesizer",
]
ROLE_CN_LEGACY = {
    "Strategy Lead": ("铁拐李", "策略负责人"),
    "Audience Insight": ("汉钟离", "用户洞察"),
    "Online Growth": ("张果老", "线上增长"),
    "Offline Experience": ("吕洞宾", "线下体验"),
    "Brand Guardian": ("何仙姑", "品牌守门人"),
    "Conversion & Funnel": ("蓝采和", "转化/漏斗"),
    "Risk & Compliance": ("韩湘子", "风险/合规"),
    "Synthesizer": ("曹国舅", "收敛/交付物编排"),
}
ROUND_NAMES_LEGACY = {1: "Diverge", 2: "Align", 3: "Converge"}
ROUND_GOALS_LEGACY = {
    1: "Round 1 (Diverge): Propose 2-3 executable directions. Be concrete, no vague ideas.",
    2: "Round 2 (Align): Identify disagreements, give 2-3 options with trade-offs, and recommend one path clearly.",
    3: "Round 3 (Converge): State clear decisions, MVP scope, and action list (Owner/Support/Deadline). Synthesizer must output the full Claude Code Handoff Pack.",
}

PASS_NAMES = {1: "Idea Expansion", 2: "Experience Embodiment", 3: "Brutal Selection", 4: "Execution Conversion"}
ROUND_COLORS = {1: "blue", 2: "purple", 3: "orange", 4: "green"}
AGENT_COLORS = {"芝麻仁": "blue", "核桃仁": "orange", "杏仁": "purple", "瓜子仁": "indigo", "松子仁": "green"}
PASS_GOALS = {
    1: "第一轮 Idea Expansion：扩展可能空间，产出约 10 个体验方向。禁止收敛、禁止执行计划。每个方向必须足够具体（谁、在哪、做什么、参与者有什么反应），不接受「沉浸式体验」「VR 互动」等空洞概念。",
    2: "第二轮 Experience Embodiment：将方向转化为可被相信的亲身经历，压缩成约 6 个强体验候选。每个方向必须能回答：参与者会因此发生什么具体行为改变？激活哪种传播动机（身份/惊喜/稀缺/发现/地位）？用户最终会发一条什么样的朋友圈/小红书？回答不了的方向直接砍掉。",
    3: "第三轮 Brutal Selection：每位 agent 必须对上轮留下的每个方向逐一投「保留」或「淘汰」票并说明理由。不允许全票通过——至少一半方向必须被淘汰。三道筛：新颖性（体验模式是否已被用烂？若是则淘汰）、行为改变（带来什么具体行为改变？说不清则淘汰）、传播动机（激活身份/惊喜/稀缺/发现/地位中的哪一种？无则淘汰）。松子仁最后发言做最终裁决，只保留 3 个方向，不妥协、不合并。",
    4: "第四轮 Execution Conversion：本轮仅围绕第三轮保留的 3 个方向展开。严禁复活已淘汰方向，严禁引入新方向——违反者由松子仁当场制止。产出两样：（1）讨论总结 + 供 Claude Code 完善成具体计划和工作流的 prompt；（2）供视觉大模型生成创意概念可视化的 prompt（3 个方向各一份）。松子仁须输出上述两样。",
}
CONTROLLER_ANNOUNCE = {1: "进入第一轮：Idea Expansion", 2: "进入第二轮：Experience Embodiment", 3: "进入第三轮：Brutal Selection", 4: "进入第四轮：Execution Conversion"}

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
PROMPTS_JSON = Path(__file__).resolve().parent.parent / "prompts.json"
FEISHU_INTERVAL = 1.0

_PROMPTS_JSON_CACHE = None


def _load_prompts_json():
    global _PROMPTS_JSON_CACHE
    if _PROMPTS_JSON_CACHE is not None:
        return _PROMPTS_JSON_CACHE
    out = {"by_cn": {}, "controller_prompt": None, "roles_order": None}
    if not PROMPTS_JSON.exists():
        _PROMPTS_JSON_CACHE = out
        return out
    try:
        data = json.loads(PROMPTS_JSON.read_text(encoding="utf-8"))
        agents = data.get("agents", [])
        out["by_cn"] = {
            ag["name"]: {"system_prompt": ag["system_prompt"], "role": ag.get("role", ag["name"])}
            for ag in agents
        }
        out["controller_prompt"] = data.get("controller_prompt")
        if agents and out["controller_prompt"] and len(agents) == 5:
            out["roles_order"] = [ag["name"] for ag in agents]
        _PROMPTS_JSON_CACHE = out
        return out
    except Exception:
        _PROMPTS_JSON_CACHE = out
        return out


def _prompt_path(role: str) -> Path:
    m = {
        "Strategy Lead": "strategy_lead", "Audience Insight": "audience_insight",
        "Online Growth": "online_growth", "Offline Experience": "offline_experience",
        "Brand Guardian": "brand_guardian", "Conversion & Funnel": "conversion_funnel",
        "Risk & Compliance": "risk_compliance", "Synthesizer": "synthesizer",
    }
    name = m.get(role, role.replace(" ", "_").replace("&", "").lower())
    return PROMPTS_DIR / f"{name}.txt"


def _get_roles_and_config():
    j = _load_prompts_json()
    by_cn = j["by_cn"]
    if j["roles_order"] and len(j["roles_order"]) == 5:
        def _display_v3(role):
            r = by_cn.get(role, {}).get("role", role)
            return (role, r)
        return j["roles_order"], _display_v3, PASS_NAMES, PASS_GOALS, True
    ROLES = ROLES_LEGACY
    def _display_legacy(role):
        cn_name, default_role = ROLE_CN_LEGACY.get(role, (role, role))
        if by_cn and cn_name in by_cn and by_cn[cn_name].get("role"):
            return cn_name, by_cn[cn_name]["role"]
        return cn_name, default_role
    return ROLES, _display_legacy, ROUND_NAMES_LEGACY, ROUND_GOALS_LEGACY, False


def load_system_prompt(role: str) -> str:
    j = _load_prompts_json()
    by_cn = j["by_cn"]
    cn_name = role if role in by_cn else ROLE_CN_LEGACY.get(role, (role, role))[0]
    if by_cn and cn_name in by_cn:
        return by_cn[cn_name]["system_prompt"].strip()
    p = _prompt_path(role)
    if not p.exists():
        return "You are " + role + ". Output: One-line stance / Reason (max 3 bullets) / Actions (max 3 bullets) / Open questions (max 2, optional)."
    return p.read_text(encoding="utf-8").strip()


def get_role_display(role: str) -> tuple:
    _, display_fn, _, _, _ = _get_roles_and_config()
    return display_fn(role)


# ── 质量关卡 ─────────────────────────────────────────────────
# 第 1、2 轮结束后，由独立 critic 评估本轮产出质量。
# 逐个方向打分，标记「水货」并说明原因，结果注入下一轮上下文。

_QUALITY_GATE_SYSTEM = """你是脑暴质量关卡评审员（Quality Gate Critic）。你刚看完一轮 AI 多角色脑暴讨论。

你的唯一任务：逐个审查本轮提出的每个创意方向，标记哪些是「水货」（表面好听但实际空洞）。

「水货」的典型特征（命中任何一条即判定）：
- 万金油概念：换个品牌/话题也成立，没有针对性（如「沉浸式体验」「打造社交货币」「限定快闪」）
- 模糊体验：说不清参与者在哪个具体瞬间做什么、感受到什么
- 已被用烂：这种玩法/形式在近两年已经被大量品牌做过（如盲盒、打卡墙、联名周边）
- 伪创新：只是把旧形式换了个名字或包装（如把快闪店叫「体验空间」）
- 无传播锚点：想不出参与者会发什么样的朋友圈/短视频
- 逻辑跳跃：从洞察到创意之间缺乏因果关系，硬凑的

输出格式（严格遵守）：
逐个方向评价，每个方向用一行：
⚠️ [方向名称]：水货 — [一句话原因]
✅ [方向名称]：过关 — [一句话亮点]

最后输出「下一轮行动指令」，根据过关比例分档（具体措辞见下方注入的轮次专用指令模板）。

要求：
- 宁可误杀不可放过——「还行」也算水货
- 必须使用中文
- 不要解释评审标准，直接给结论"""

_QUALITY_GATE_R1_EXTRA = """
注意：第一轮是发散轮，评审标准比第二轮宽松。
不要用第二轮的「体验完整性」「传播路径」等标准来评判第一轮——第一轮的想法允许粗糙、不完整。

第一轮的评审标准（只看两点）：
1. 具体性：能不能说清谁、在哪、做什么？（纯抽象概念 = 水货）
2. 有趣度：这个想法是否让人想了解更多？有没有意外感或新鲜感？（无聊的正确 = 水货）

标记格式调整：
⭐ [方向名称]：亮点方向 — [一句话说清为什么有趣]
🔸 [方向名称]：有潜力但需具体化 — [缺什么]
⚠️ [方向名称]：水货 — [一句话原因]

轮次专用行动指令模板（第一轮 → 第二轮可以发散新想法）：
- 亮点方向多（⭐ ≥ 4）：下一轮聚焦打磨这些亮点方向。
- 亮点方向少（⭐ 1-3）：下一轮打磨亮点 + 把🔸方向具体化 + 针对水货方向的失败原因想替代方向。
- 亮点方向 = 0：思路可能太窄了。下一轮从不同角度重新发散，不要在上一轮的框架里打转。"""

_QUALITY_GATE_R2_EXTRA = """
额外要求（第二轮专用）：
本轮的目标是把方向具体化为可执行体验。对每个方向还需检查：
- 体验旅程是否完整（有头有尾，不是只有一个模糊的高潮点）
- 成本/可行性是否被认真考虑过
- 传播路径是否具体到「用户会发一条什么」
任何一项说不清，判水货。

轮次专用行动指令模板（第二轮 → 第三轮是淘汰轮，只能从现有方向中选，不能发散新想法）：
- 过关数 ≥ 4：第三轮正常筛选，优先保留过关方向。
- 过关数 1-3：第三轮选择时优先保留这几个过关方向。对水货方向，如果有人能在第三轮中补充足够具体的体验设计使其脱水，可以考虑保留；否则淘汰。
- 过关数 = 0：情况严峻但第三轮仍必须从中选出相对最好的 3 个。第三轮投票时要明确标注「勉强保留」，并说清楚该方向最大的缺陷是什么，第四轮必须重点修补这些缺陷。"""


def _run_quality_gate(full_round_text: str, round_num: int, topic_type: str) -> str:
    """运行质量关卡评估，返回 critic 评审结果文本。"""
    system = _QUALITY_GATE_SYSTEM
    if round_num == 1:
        system += _QUALITY_GATE_R1_EXTRA
    elif round_num == 2:
        system += _QUALITY_GATE_R2_EXTRA

    user = (
        f"以下是第{round_num}轮讨论的全部发言，请逐个审查其中提出的每个创意方向：\n\n"
        f"{full_round_text}"
    )
    try:
        result = chat_completion(provider="deepseek", system=system, user=user, temperature=0.3)
        return f"━━ 第{round_num}轮质量关卡 ━━\n{result.strip()}"
    except Exception as e:
        print(f"  [质量关卡] 评估失败: {e}", flush=True)
        return ""


# ── 单轮执行 ────────────────────────────────────────────────
# 一轮讨论的流程：
# 1. 构建上下文（主题 + 背景 + 之前各轮摘要 + 当前轮次目标 + 风格约束）
# 2. 5 个角色按顺序发言，每人看到所有前面角色的发言并回应
# 3. 每人发言完毕后推送到飞书群
# 4. 全部发言完成后，用 AI 生成本轮摘要 + 质量关卡评估

def run_round(
    round_num: int,
    topic: str,
    context: str,
    deliverables: str,
    round_summaries: list[str],
    ts: str,
    brand_context: str = "",
    webhook_override: Optional[str] = None,
    topic_type: str = "campaign",
) -> tuple[list[str], str]:
    ROLES, display_fn, round_names, round_goals, is_v3 = _get_roles_and_config()
    goal = round_goals.get(round_num, "")
    round_name = round_names.get(round_num, f"Round {round_num}")

    parts = [f"Topic: {topic}"]
    if context:
        parts.append(f"Initial context: {context}")
    if brand_context:
        parts.append(f"品牌知识参考（创意方向需符合品牌调性）：\n{brand_context}")
    if deliverables:
        parts.append(f"Requested deliverables: {deliverables}")
    for i, s in enumerate(round_summaries, 1):
        parts.append(f"--- 第 {i} 轮 Summary ---\n{s}")
    parts.append(f"\n--- 当前轮次 ---\n{goal}")
    parts.append(
        "【风格】发言必须使用中文，尽量简约精炼。像飞书群里的真实内部讨论：纯自然发言，可接上面人的话、可简短回应。"
        "禁止使用星号（* 或 **），禁止 markdown、bullet、编号列表。一律纯文本。不要咨询报告腔、不要企业黑话。"
        "每条最多 3～4 段短段，像真人打字，能一句话说清的不写长段。"
    )

    # ── 按话题类型适配讨论纪律 ──
    if is_v3 and topic_type == "campaign":
        parts.append(
            "【节奏】讨论中大家要想清楚整个 campaign 的节奏：若是传播向，需明确预热、高潮、收尾；若是现场活动，需明确具体时长与体验节奏设置（例如几点到几点、每个环节多久、情绪曲线如何）。"
        )
    elif is_v3 and topic_type == "project":
        parts.append(
            "【节奏】这是产品/项目脑暴。聚焦用户体验和技术可行性。每个方向要说清楚：用户怎么用、核心体验是什么、技术上能不能做、和现有方案有什么不同。"
        )
    elif is_v3 and topic_type == "strategy":
        parts.append(
            "【节奏】这是一场策略探讨型脑暴。核心不是快速产出方案，而是把问题想透。"
            "每位发言者要：（1）先亮明自己的立场倾向，（2）给出支撑这个立场的真实案例或逻辑，（3）主动指出自己立场的最大漏洞。"
            "鼓励对立观点的碰撞。如果所有人都同意一个观点，松子仁必须扮演反方来压力测试。"
            "不要急着给行动建议——先把'为什么'搞清楚，'怎么做'自然会浮现。"
        )
    elif is_v3 and topic_type == "explore":
        parts.append(
            "【节奏】这是生活/个人话题脑暴。聚焦可执行性和个人契合度。每个方向要说清楚：具体怎么做、需要多少时间精力、适不适合这个人的性格和现状、最可能卡在哪。"
        )

    if is_v3 and round_num == 3 and topic_type == "campaign":
        parts.append(
            "【第三轮纪律——严格执行】\n"
            "1. 每位 agent 必须对上轮留下的每个方向逐一表态：「保留」或「淘汰」，附一句话理由。不允许含糊或跳过。\n"
            "2. 禁止全票通过——至少一半方向必须被淘汰。如果你觉得某方向「还行但不够强」，投淘汰票。\n"
            "3. 三道筛子：新颖性（体验模式是否已被品牌/活动用烂？若是→淘汰）、行为改变（带来什么具体行为改变？说不清→淘汰）、传播动机（激活身份/惊喜/稀缺/发现/地位？无→淘汰）。\n"
            "4. 松子仁最后发言，做出不可翻转的最终裁决。只留 3 个方向，不妥协、不合并。\n"
            "5. 评价维度：行为改变、新颖性、传播动机。不按情绪基调或「听起来不错」来评价。"
        )
    elif is_v3 and round_num == 3 and topic_type == "project":
        parts.append(
            "【第三轮纪律——严格执行】\n"
            "1. 每位 agent 必须对上轮留下的每个方向逐一表态：「保留」或「淘汰」，附一句话理由。\n"
            "2. 禁止全票通过——至少一半方向必须被淘汰。\n"
            "3. 三道筛子：体验完整性（用户的核心体验闭环能不能跑通？跑不通→淘汰）、技术可行性（以当前资源和能力能不能做出来？不能→淘汰）、差异化（和已有方案比有没有本质不同？没有→淘汰）。\n"
            "4. 松子仁最后发言，做出不可翻转的最终裁决。只留 3 个方向，不妥协、不合并。\n"
            "5. 评价维度：体验完整性、技术可行性、差异化。"
        )
    elif is_v3 and round_num == 3 and topic_type == "strategy":
        parts.append(
            "【第三轮纪律——严格执行】\n"
            "1. 经过前两轮发散，现在需要收敛。每位 agent 对前两轮出现的每个观点/立场/路径逐一表态：「保留」或「淘汰」，附一句话理由。\n"
            "2. 禁止全票通过——至少一半观点必须被淘汰或合并。\n"
            "3. 三道筛子：洞察深度（这个观点是否揭示了别人没看到的东西？只是正确的废话→淘汰）、可证伪性（能不能用真实案例或数据来验证/推翻？纯粹抽象→淘汰）、行动差异（持这个观点 vs 持相反观点，做出的决策会有本质不同吗？没区别→淘汰）。\n"
            "4. 松子仁最后发言，做出不可翻转的最终裁决。保留 3 个最有洞察力的观点/路径，不妥协、不合并。\n"
            "5. 评价维度：洞察深度、可证伪性、行动差异。"
        )
    elif is_v3 and round_num == 3 and topic_type == "explore":
        parts.append(
            "【第三轮纪律——严格执行】\n"
            "1. 每位 agent 必须对上轮留下的每个方向逐一表态：「保留」或「淘汰」，附一句话理由。\n"
            "2. 禁止全票通过——至少一半方向必须被淘汰。\n"
            "3. 三道筛子：可执行性（这个人真的能做到吗？考虑时间、性格、现状。做不到→淘汰）、个人契合度（做这件事会让ta更开心/更接近目标吗？不会→淘汰）、创新度（这个建议是不是ta早就想过的废话？是→淘汰）。\n"
            "4. 松子仁最后发言，做出不可翻转的最终裁决。只留 3 个方向，不妥协、不合并。\n"
            "5. 评价维度：可执行性、个人契合度、创新度。"
        )

    if is_v3 and round_num == 4 and topic_type == "campaign":
        parts.append(
            "【第四轮纪律——严格执行】\n"
            "本轮仅围绕第三轮松子仁裁决保留的 3 个方向展开。\n"
            "严禁复活已淘汰方向，严禁引入新方向。违反者由松子仁当场制止。\n"
            "所有讨论和产出必须聚焦于如何让这 3 个方向落地、传播、视觉化。"
        )
    elif is_v3 and round_num == 4 and topic_type == "project":
        parts.append(
            "【第四轮纪律——严格执行】\n"
            "本轮仅围绕第三轮松子仁裁决保留的 3 个方向展开。\n"
            "严禁复活已淘汰方向，严禁引入新方向。\n"
            "聚焦：每个方向的 MVP 怎么做、第一步是什么、需要什么资源、多久能验证。"
        )
    elif is_v3 and round_num == 4 and topic_type == "strategy":
        parts.append(
            "【第四轮纪律——严格执行】\n"
            "本轮仅围绕第三轮松子仁裁决保留的 3 个核心洞察/路径展开。\n"
            "严禁复活已淘汰观点，严禁引入全新议题。\n"
            "聚焦：将每个洞察转化为可操作的策略——如果我们相信这个观点，具体应该怎么做？"
            "需要什么样的验证实验来确认？最大的执行风险是什么？如何设计一个最小化风险的第一步？"
        )
    elif is_v3 and round_num == 4 and topic_type == "explore":
        parts.append(
            "【第四轮纪律——严格执行】\n"
            "本轮仅围绕第三轮松子仁裁决保留的 3 个方向展开。\n"
            "严禁复活已淘汰方向，严禁引入新方向。\n"
            "聚焦：每个方向的具体行动计划——第一步做什么、什么时候做、怎么知道有没有效、卡住了怎么办。"
        )

    if is_v3 and round_num == 1:
        parts.append(
            "【第一轮特别规则——先发散，不要自我审查】\n"
            "本轮目标是尽可能多样地探索创意空间。暂时不要用三道筛（新颖性/行为改变/传播动机）过滤自己的想法——那是第三轮的事。\n"
            "第一轮的唯一标准：这个想法是否具体（说得清谁、在哪、做什么）且有趣（让人想了解更多）。\n"
            "模糊的抽象概念仍然不行（如「沉浸式体验」「O2O闭环」），但具体的、意想不到的想法即使看起来不完美也要提出来。"
        )
        parts.append(
            "【创意灵感——试试从这些角度想，不要只从一个角度发散】\n"
            "→ 反差/意外组合：把不该出现在一起的东西放在一起（如漫展上出现机器人 cosplayer、菜市场里开音乐会）\n"
            "→ 身份反转：让参与者扮演一个他们平时不会扮演的角色\n"
            "→ 感官剥夺或放大：去掉一种感官（蒙眼晚餐）或极端放大一种（巨型装置/微缩世界）\n"
            "→ 时间操控：快进、慢放、穿越——让参与者体验不同的时间感\n"
            "→ 秘密/发现：只有少数人知道的隐藏体验，发现后会忍不住分享\n"
            "→ 共创/留痕：参与者亲手做出的东西会留下来，成为下一个人体验的一部分\n"
            "→ 日常入侵：在完全意想不到的日常场景中突然出现的体验（地铁里、外卖包装上、电梯里）\n"
            "→ 游戏化挑战：有明确规则、有胜负、有奖励的短时间挑战\n"
            "→ 情感链接：让陌生人之间产生真实的情感连接的机制\n"
            "不需要用到所有角度，但不要所有人都从同一个角度想。"
        )
    elif is_v3 and round_num == 2:
        parts.append(
            "【反面案例——以下是典型的水货思路，在具体化体验时必须避开】\n"
            "❌「打造沉浸式 XX 体验空间」— 万金油概念，换个品牌也能说，没有具体的峰值瞬间\n"
            "❌「推出限定联名周边/盲盒」— 近两年被做烂了，零新颖性\n"
            "❌「设置互动打卡墙/拍照装置」— 流量逻辑而非体验逻辑，参与者拍完就忘\n"
            "❌「线上线下联动/O2O 闭环」— 抽象框架不是创意，说不清用户到底做了什么\n"
            "❌ 把技术（AR/AI/互动屏等）或资源（KOL/KOC/明星等）当作创意本身 — 技术和资源是手段不是体验，必须说清楚「用这个手段之后，参与者具体会做什么、感受到什么」，否则就是偷懒\n"
            "如果你发现自己正在想上述类型的东西，立刻停下来，从「参与者在某个具体的 5 秒内会做什么、感受到什么」重新想。"
        )

    if not is_v3:
        parts.append("【约束】方案需符合游戏调性与 IP，但优先做游戏外、社媒上、线下、现实场景的体验；这类体验由市场团队更可控、更好落地。")
    base_context = "\n\n".join(parts)

    messages_this_round = []
    n_roles = len(ROLES)

    for idx, role in enumerate(ROLES, 1):
        cn_name, cn_role = display_fn(role)
        print(f"    [{idx}/{n_roles}] {cn_name}（{cn_role}）发言中...", flush=True)
        system = load_system_prompt(role)
        prior_msgs = messages_this_round if messages_this_round else []

        style_instruction = (
            "用自然群聊体回复，简约精炼，最多 3～4 段短段。"
            "可用 **加粗** 标记关键词，可用 → 或 - 引导要点，但不要写长列表。"
            "信息密度要高——每段必须包含具体判断或信息，不允许空话套话。"
        )

        if is_v3 and round_num == 1:
            # 第 1 轮：每个角色必须先从自己的专业视角提 2-3 个新方向，再回应别人
            if not prior_msgs:
                speak_instruction = (
                    "轮到你发言了。你是本轮第一个发言的人。"
                    "从你的专业视角出发，提出 2-3 个具体的体验方向。"
                    "每个方向必须包含：谁、在哪、做什么、参与者的具体感受。" + style_instruction
                )
            else:
                speak_instruction = (
                    "轮到你发言了。你必须做两件事：\n"
                    "1. 先从你自己的专业视角提出 2-3 个全新的体验方向（不是改良前面的人说的，是你独立想的新方向）。"
                    "每个方向必须包含：谁、在哪、做什么、参与者的具体感受。\n"
                    "2. 然后对前面的人提出的方向，挑 1-2 个回应（同意+补充 或 反对+理由）。\n"
                    "注意：先提新想法，再回应别人。不要只当点评员。" + style_instruction
                )
        else:
            # 第 2-4 轮：正常的回应+讨论模式
            speak_instruction = "轮到你发言了。" + style_instruction

        if prior_msgs:
            if is_v3 and round_num == 1:
                prior_header = "【本轮前面的人已经提出的方向——你要提和他们不同的新方向，同时可以回应他们】\n\n"
            else:
                prior_header = "【本轮所有人目前的发言——你必须回应其中至少一位的观点（同意+补充具体内容 或 反对+理由），禁止忽略前面的发言自说自话】\n\n"
            prior_block = prior_header
            for r, m in prior_msgs:
                pn, pr = display_fn(r)
                prior_block += f"{pn}（{pr}）：\n{m}\n\n"
            user = base_context + "\n\n" + prior_block + speak_instruction
        else:
            user = base_context + "\n\n" + speak_instruction
        if not is_v3 and round_num == 3 and role == "Synthesizer":
            user += " 最后必须附上完整的 Claude Code Handoff Pack（A 决策与理由、B 行动清单、C 可复制块）。"

        provider = get_model_for_role(role)
        is_songzi = cn_name == "松子仁" or role == "Synthesizer"
        use_agent = is_songzi and round_num >= 3

        if use_agent:
            try:
                from core.agent import AgentLoop
                from core.tools import WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, SEARCH_PLATFORM_TOOL
                tool_system = system + (
                    "\n\n你拥有搜索工具。作为总成角色做最终裁决时，如果需要数据支撑你的判断"
                    "（如验证某个方向的市场可行性、查竞品案例、确认技术可行性），可以主动搜索。"
                    "但不要过度搜索——你的主要职责是基于讨论做出判断，搜索只用于关键决策点。"
                )
                agent = AgentLoop(
                    provider=provider, system=tool_system, max_rounds=4, temperature=0.7,
                    on_tool_call=lambda name, args: print(f"      🔍 [{cn_name}] {name}: {str(args)[:60]}", flush=True),
                )
                agent.add_tools([WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, SEARCH_PLATFORM_TOOL])
                result = agent.run(user)
                raw = result.content
                if result.tool_calls_made:
                    print(f"      [{cn_name}] 搜索了 {len(result.tool_calls_made)} 次", flush=True)
            except Exception as e:
                print(f"    [{idx}/{n_roles}] {cn_name} AgentLoop 失败({e}), 回退简单调用", flush=True)
                try:
                    raw = chat_completion(provider=provider, system=system, user=user)
                except Exception as e2:
                    print(f"    [{idx}/{n_roles}] {cn_name} LLM 调用失败: {e2}", flush=True)
                    raw = "(该角色暂时无法发言)"
        else:
            try:
                raw = chat_completion(provider=provider, system=system, user=user)
            except Exception as e:
                print(f"    [{idx}/{n_roles}] {cn_name} LLM 调用失败: {e}", flush=True)
                raw = "(该角色暂时无法发言)"
        raw_display = truncate_for_display(raw)
        display = _format_discussion_for_readability(raw_display)
        messages_this_round.append((role, display))

        round_label = f"第{round_num}轮 {round_name}" if is_v3 else f"Round {round_num}"
        card_title = f"{cn_name}（{cn_role}）| {round_label}"
        card_color = AGENT_COLORS.get(cn_name, ROUND_COLORS.get(round_num, "blue"))
        _send_brainstorm_card(card_title, display, color=card_color, webhook_override=webhook_override)
        print(f"    [{idx}/{n_roles}] {cn_name}（{cn_role}）完成 ({len(display)} 字) 已推送到飞书", flush=True)
        time.sleep(FEISHU_INTERVAL)

    print(f"  [第{round_num}轮] 生成本轮摘要...", flush=True)
    summary_prompt = (
        "用中文把下面这场讨论总结成 8～12 行。必须包含：本轮讨论到的所有创意/方向（逐一列出），主要分歧（如有），已定的结论或下一步。"
        "语气像真人做的会议纪要，不要套话。可用 **加粗** 标记关键词，可用 - 列要点，段间留空行。只输出摘要，不要加标题。"
    )
    full_round_text = "\n\n".join(f"[{r}]\n{msg}" for r, msg in messages_this_round)
    provider_summary = get_model_for_role(ROLES[0])
    round_summary = chat_completion(
        provider=provider_summary,
        system="你是会议记录员，用中文写简洁、口语化的会议摘要。可用 **加粗** 和 - 列表增强可读性。",
        user=summary_prompt + "\n\n" + full_round_text,
    )
    round_summary = truncate_for_display(round_summary)
    print(f"  [第{round_num}轮] 摘要完成", flush=True)

    # ── 质量关卡：第 1、2 轮结束后由 critic 评估，标记弱方向 ──
    if is_v3 and round_num in (1, 2):
        print(f"  [第{round_num}轮] 质量关卡评估中...", flush=True)
        critic_verdict = _run_quality_gate(full_round_text, round_num, topic_type)
        if critic_verdict:
            round_summary += "\n\n" + critic_verdict
            _send_brainstorm_card(
                f"第{round_num}轮 质量关卡",
                truncate_for_display(critic_verdict),
                color="red",
                webhook_override=webhook_override,
            )
            time.sleep(FEISHU_INTERVAL)
            print(f"  [第{round_num}轮] 质量关卡完成", flush=True)

    return messages_this_round, round_summary


# ── 完整脑暴流程 ─────────────────────────────────────────────
# 完整流程：
# 1. DeepSeek 将原始主题优化为结构化的 Brainstorm Seed
# 2. 执行 4 轮讨论（每轮 5 个角色依次发言 → 生成摘要）
# 3. Kimi 根据 4 轮摘要生成最终交付物（讨论总结 + Claude Code prompt + 视觉 prompt）
# 4. 保存完整 session 到 runs/ 目录

class BrainstormResult(str):
    """脑暴结果：str(result) 返回 session 文件路径（兼容旧调用方），
    同时携带 round_summaries / final_output / topic_refined 等结构化数据。"""

    def __new__(cls, path: str, **kwargs):
        obj = super().__new__(cls, path)
        obj.round_summaries: list[str] = kwargs.get("round_summaries", [])
        obj.final_output: str = kwargs.get("final_output", "")
        obj.topic_refined: str = kwargs.get("topic_refined", "")
        return obj


def run_brainstorm(
    topic: str,
    context: str = "",
    deliverables: str = "",
    no_refine: bool = False,
    brand: str = "",
    webhook: Optional[str] = None,
    topic_type: str = "",
) -> BrainstormResult:
    """执行完整的脑暴流程，返回 BrainstormResult（str 兼容，可取 .round_summaries 等）。

    webhook: 本场脑暴推送的飞书 webhook URL。由调用方传入以区分：
      - 脑暴机器人发起：传 FEISHU_WEBHOOK（或 BRAINSTORM_FEISHU_WEBHOOK）
      - 自媒体助手(conductor)发起：传 CONDUCTOR_BRAINSTORM_WEBHOOK
    不传则回退到 FEISHU_WEBHOOK（CLI 等）。

    brand: 可选，指定品牌名。留空则自动从 topic/context 中检测。
    topic_type: 手动指定话题类型 (campaign/project/strategy/explore)，留空则自动检测。
    """
    resolved_webhook = (webhook or "").strip() or (_os.environ.get("FEISHU_WEBHOOK") or "").strip() or None

    if not topic_type or topic_type not in ("campaign", "project", "strategy", "explore"):
        topic_type = _detect_topic_type(topic, context)
    _type_labels = {"campaign": "营销活动", "project": "创意项目", "strategy": "策略探讨", "explore": "通用探索"}
    print(f"[话题类型] {_type_labels.get(topic_type, topic_type)}", flush=True)

    if not deliverables:
        if topic_type == "campaign":
            deliverables = "方案文档（md）、执行清单（md）、飞书群公告/brief（md）"
        elif topic_type == "project":
            deliverables = "方案文档（md）、MVP 定义、执行步骤"
        elif topic_type == "strategy":
            deliverables = "洞察框架、决策依据、验证路径、AI 深化 prompt"
        else:
            deliverables = "行动方案、具体步骤、检验标准"

    brand_context = ""
    if topic_type in ("campaign", "project", "strategy"):
        if brand:
            brand_context = load_skill_context("brand", brand_name=brand)
        else:
            brand_context = load_skill_context("brand", detect_from=f"{topic} {context}")
        if brand_context:
            print(f"[品牌知识] 已加载品牌知识，将注入到讨论上下文中。", flush=True)

    ts = run_timestamp()
    round_summaries: list[str] = []
    topic_refined = ""
    final_output = ""
    session_lines = [
        f"# Session {ts}",
        f"Topic (raw): {topic}",
        f"Context: {context}",
        f"Deliverables: {deliverables}",
        "",
    ]

    if not no_refine:
        print("[DeepSeek] 正在优化脑暴主题与讨论思路...", flush=True)
        refined = refine_brainstorm_topic_deepseek(topic, context, topic_type=topic_type)
        if refined:
            topic = refined
            topic_refined = refined
            session_lines.append("DeepSeek 优化后的主题与思路：")
            session_lines.append("")
            session_lines.append(refined)
            session_lines.append("")
            session_lines.append("---")
            session_lines.append("")
            print("[DeepSeek] 已确定主题与思路。", flush=True)
            _send_brainstorm_card("本场脑暴主题", truncate_for_display(refined), color="indigo", webhook_override=resolved_webhook)
            time.sleep(FEISHU_INTERVAL)
        else:
            print("[DeepSeek] 调用失败，使用原始主题。", flush=True)

    session_lines[1] = f"Topic: {topic}"

    ROLES, display_fn, round_names, round_goals, is_v3 = _get_roles_and_config()
    num_rounds = 4 if is_v3 else 3
    if is_v3:
        session_lines.append("Controller: 坚果五仁体验创新 v3.0，四轮协议")
        session_lines.append("")
    print(f"[脑暴开始] 主题: {topic[:120]}{'...' if len(topic) > 120 else ''}", flush=True)
    if context:
        print(f"  背景: {context[:80]}{'...' if len(context) > 80 else ''}", flush=True)
    print("", flush=True)

    for round_num in range(1, num_rounds + 1):
        round_name = round_names.get(round_num, f"Round {round_num}")
        goal = round_goals.get(round_num, "")

        print(f"========== 第 {round_num} 轮 / {round_name} ==========", flush=True)

        if is_v3:
            controller_msg = CONTROLLER_ANNOUNCE.get(round_num, f"进入第{round_num}轮")
            print(f"  [Controller] {controller_msg}", flush=True)
            round_color = ROUND_COLORS.get(round_num, "blue")
            _send_brainstorm_card(f"第 {round_num} 轮：{round_name}", controller_msg, color=round_color, webhook_override=resolved_webhook)
            session_lines.append("## " + controller_msg)
        else:
            header = f"Round {round_num} / {round_name} / 主题: {topic} / 目标与约束: {goal}"
            print(f"  [飞书] 发送本轮开场...", flush=True)
            _send_brainstorm_card(f"Round {round_num}: {round_name}", header, color=ROUND_COLORS.get(round_num, "blue"), webhook_override=resolved_webhook)
            session_lines.append("## " + header)
        session_lines.append("")
        time.sleep(FEISHU_INTERVAL)

        print(f"  [第{round_num}轮] {len(ROLES)} 个角色依次发言中...", flush=True)
        messages_this_round, round_summary = run_round(
            round_num=round_num, topic=topic, context=context,
            deliverables=deliverables, round_summaries=round_summaries, ts=ts,
            brand_context=brand_context,
            webhook_override=resolved_webhook,
            topic_type=topic_type,
        )
        round_summaries.append(round_summary)

        for role, msg in messages_this_round:
            cn_name, cn_role = display_fn(role)
            round_label = f"第{round_num}轮 {round_name}" if is_v3 else f"Round {round_num}"
            session_lines.append(f"### {cn_name}（{cn_role}）| {round_label}")
            session_lines.append("")
            session_lines.append(msg)
            session_lines.append("")
            session_lines.append("---")
            session_lines.append("")
        session_lines.append("### 第" + str(round_num) + "轮 Summary")
        session_lines.append("")
        session_lines.append(round_summary)
        session_lines.append("")
        session_lines.append("---")
        session_lines.append("")

    if is_v3 and round_summaries:
        summary_input = f"主题：{topic}\n\n各轮摘要：\n" + "\n\n".join(f"第{i}轮：{s}" for i, s in enumerate(round_summaries, 1))

        # ── 创意全清单：提取所有 idea，排序，AI 推荐 Top 3 ──
        print("[创意全清单] 提取所有创意方向并排序...", flush=True)
        _inventory_system = (
            "你是脑暴创意盘点员。从以下四轮讨论摘要中，提取所有出现过的创意方向/idea（包括被淘汰的），"
            "按综合潜力从高到低排序，输出一份完整清单。\n\n"
            "输出格式（严格遵守）：\n\n"
            "🏆 AI 推荐 Top 3\n\n"
            "1. [方向名称]\n"
            "   核心思路：一句话说清楚\n"
            "   胜出理由：为什么在讨论中胜出\n"
            "   风险提醒：最大的不确定性是什么\n\n"
            "2. ...\n3. ...\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 被淘汰但有亮点（可捞回）\n\n"
            "4. [方向名称]\n"
            "   核心思路：一句话\n"
            "   亮点：这个 idea 最值得保留的部分\n"
            "   被淘汰原因：为什么没入选\n"
            "   复活建议：如果要用，需要补什么\n\n"
            "5. ...\n（列出所有被淘汰的方向，不遗漏）\n\n"
            "要求：\n"
            "- 必须用中文\n"
            "- 编号连续（1, 2, 3, 4, 5, 6...），Top 3 和被淘汰的共用一个序号体系\n"
            "- 对被淘汰的方向要客观公正——说清楚亮点，不要因为被淘汰就贬低\n"
            "- 每个方向的描述要简洁，一个方向不超过 4 行"
        )
        try:
            _inventory = chat_completion(
                provider="deepseek", system=_inventory_system, user=summary_input, temperature=0.3,
            ).strip()
        except Exception as _inv_err:
            print(f"  [创意全清单] 生成失败: {_inv_err}", flush=True)
            _inventory = ""

        if _inventory:
            session_lines.append("## 创意全清单")
            session_lines.append("")
            session_lines.append(_inventory)
            session_lines.append("")
            session_lines.append("---")
            session_lines.append("")
            _send_brainstorm_card(
                "📋 创意全清单（所有 idea 排序）",
                truncate_for_display(_inventory),
                color="indigo",
                webhook_override=resolved_webhook,
            )
            time.sleep(FEISHU_INTERVAL)
            print("[创意全清单] 已生成并推送", flush=True)

        if topic_type == "campaign":
            print("[最终交付] 由 Kimi 生成：问对问题 + AI深化prompt + 视觉概念prompt...", flush=True)
            final_system = (
                "你是体验创新流程的交付整理员。根据以下四轮讨论摘要，输出三个板块，分开写、标题明确。全文必须使用中文。"
                "可用 **加粗** 标记关键词，可用 - 列要点，段间留空行，提高可读性。\n\n"
                "⚠️ 重要格式要求：每个板块的标题必须严格以【一】、【二】、【三】开头，不要使用「板块一」或「### 一、」等其他格式。\n\n"
                "【一】去问对的人对的问题\n"
                "从整个讨论中提炼 3-5 个必须由真人判断的关键问题，按紧急度排序（最先要确认的排最前）。\n"
                "每个问题必须包含四项：\n"
                "- **问谁**：具体角色（决策者/客户/目标用户/领域专家/执行团队），不要笼统\n"
                "- **拿这句话去问**：写成可以直接发给对方的一句话，对方看到就能回答，不需要额外解释\n"
                "- **背景**：一两句话给对方上下文，如果你搜索到了相关数据/案例，附上作为参考依据\n"
                "- **为什么不能跳过**：不确认这个会卡住什么后续动作\n"
                "这些必须是AI替代不了的判断——涉及价值观、品牌调性取舍、对目标人群的体感、资源/预算决策、政治考量等。\n\n"
                "【二】交给最强 AI 继续深化（可直接复制）\n"
                "写一段完整的 prompt，用户可以直接复制粘贴给 Claude / Opus 使用。这段 prompt 必须：\n"
                "- 开头用两三句话说清楚脑暴主题和背景\n"
                "- 列出最终保留的方向（通常 3 个），每个方向一句话说清核心思路和为什么胜出\n"
                "- 说明已经做过的取舍和约束（淘汰了什么、为什么）\n"
                "- 明确要求 AI 输出：**执行计划 + 工作流**——包含具体步骤、建议负责人角色、每步产出物、验收标准、时间节点\n"
                "- prompt 本身要自洽完整，不依赖外部文档就能让 AI 理解并执行\n\n"
                "【三】生成视觉概念增强既视感（可直接复制给图像/视频模型）\n"
                "为最终保留的每个方向各写一份 prompt，可直接交给图像或视频生成模型。每份须包含：\n"
                "（1）**视觉场景描述**——场景、光线、氛围、关键瞬间、人物动作、色彩、质感、情绪基调，"
                "融入品牌调性的视觉语言，语言简洁精准，适合直接作为生成模型输入\n"
                "（2）**用户视角创意脚本**——从用户/观众视角可被拍摄或讲述的脚本梗概，"
                "要有传播力（易转发、可引发共鸣或讨论、具备记忆点）"
            )
        elif topic_type == "project":
            print("[最终交付] 由 Kimi 生成：问对问题 + AI深化prompt + 产品视觉概念prompt...", flush=True)
            final_system = (
                "你是产品/项目脑暴的交付整理员。根据以下四轮讨论摘要，输出三个板块，分开写、标题明确。全文必须使用中文。"
                "可用 **加粗** 标记关键词，可用 - 列要点，段间留空行，提高可读性。\n\n"
                "⚠️ 重要格式要求：每个板块的标题必须严格以【一】、【二】、【三】开头，不要使用「板块一」或「### 一、」等其他格式。\n\n"
                "【一】去问对的人对的问题\n"
                "从讨论中提炼 3-5 个必须由真人判断的关键问题，按紧急度排序。\n"
                "每个问题必须包含四项：\n"
                "- **问谁**：具体角色（决策者/目标用户/技术专家/业务负责人），不要笼统\n"
                "- **拿这句话去问**：写成可以直接发给对方的一句话，对方看到就能回答\n"
                "- **背景**：一两句话给对方上下文，如果你搜索到了相关数据/案例/竞品信息，附上作为参考\n"
                "- **为什么不能跳过**：不确认这个会卡住什么后续动作\n"
                "这些必须是AI替代不了的判断——涉及优先级取舍、用户真实需求洞察、资源/人力投入决策、技术可行性确认等。\n\n"
                "【二】交给最强 AI 继续深化（可直接复制）\n"
                "写一段完整的 prompt，用户可以直接复制粘贴给 Claude / Opus 使用。这段 prompt 必须：\n"
                "- 开头说清楚项目背景和要解决的问题\n"
                "- 列出最终保留的方向（通常 3 个），每个方向包含：核心功能、第一个用户怎么用、MVP 最小验证范围\n"
                "- 说明已经做过的取舍（淘汰了什么方向、为什么）\n"
                "- 明确要求 AI 输出：**MVP 技术方案 + 实现路径**——包含架构设计、技术栈建议、实现步骤、第一步从哪开始、验收标准、预估时间\n"
                "- prompt 本身要自洽完整，不依赖外部文档就能让 AI 理解并执行\n\n"
                "【三】生成视觉概念增强既视感（可直接复制给图像/视频模型）\n"
                "为最终保留的每个方向各写一份 prompt，可直接交给图像生成模型。每份须包含：\n"
                "（1）**产品界面概念**——核心页面/交互场景的视觉描述：布局、配色、关键 UI 元素、用户正在进行的操作，"
                "风格清晰（如 minimal/material/glassmorphism），适合直接作为 UI 概念图生成的输入\n"
                "（2）**用户旅程关键帧**——从用户视角描述 2-3 个使用场景的关键时刻：用户在哪、在做什么、看到什么、感受是什么"
            )
        elif topic_type == "strategy":
            print("[最终交付] 由 Kimi 生成：关键判断 + AI深化prompt + 思维可视化prompt...", flush=True)
            final_system = (
                "你是策略探讨型脑暴的交付整理员。根据以下四轮讨论摘要，输出三个板块，分开写、标题明确。全文必须使用中文。"
                "可用 **加粗** 标记关键词，可用 - 列要点，段间留空行，提高可读性。\n\n"
                "⚠️ 重要格式要求：每个板块的标题必须严格以【一】、【二】、【三】开头，不要使用「板块一」或「### 一、」等其他格式。\n\n"
                "【一】关键判断：需要真人拍板的决策点\n"
                "从讨论中提炼 3-5 个无法用数据或逻辑自动解决的判断题，按影响力排序。\n"
                "每个判断必须包含四项：\n"
                "- **判断题**：用一句清晰的二选一或多选一表述（不是开放问题，而是必须做出选择的决策）\n"
                "- **各方论据摘要**：每个选项最强的 1-2 个论据，来自讨论中不同角色的观点\n"
                "- **判断依据建议**：可以用什么信息/实验/数据来辅助判断（但最终仍需人拍板）\n"
                "- **如果不判断会怎样**：悬而未决会卡住什么后续动作\n"
                "这些必须是 AI 替代不了的判断——涉及价值观、战略方向、组织文化、用户直觉等。\n\n"
                "【二】交给最强 AI 继续深化（可直接复制）\n"
                "写一段完整的 prompt，用户可以直接复制粘贴给 Claude / Opus 使用。这段 prompt 必须：\n"
                "- 开头说清楚这场策略讨论的核心问题和背景\n"
                "- 列出讨论中形成的 3 个核心洞察/立场，每个包含：核心论点、支撑逻辑、最大漏洞\n"
                "- 说明讨论中的关键分歧点和已达成的共识\n"
                "- 明确要求 AI 输出：**策略框架 + 验证路径**——基于这些洞察，设计一套决策框架，"
                "包含：在什么条件下选择哪条路、如何设计最小成本的验证实验、各路径的风险评估和退出机制\n"
                "- prompt 本身要自洽完整，不依赖外部文档就能让 AI 理解并执行\n\n"
                "【三】思维可视化（可直接复制给图像模型）\n"
                "为这场策略讨论生成 1-2 份视觉化 prompt，可直接交给图像生成模型。适合做成：\n"
                "（1）**策略地图/决策树**——将核心问题、分支路径、关键变量画成一张清晰的视觉图，"
                "用不同颜色区分已验证 vs 待验证的假设，标注关键决策节点\n"
                "（2）**未来场景对比**——如果选择路径 A vs 路径 B，6个月后的场景分别是什么样的？"
                "用具体的视觉场景描述，让人直观感受不同选择的后果差异"
            )
        else:
            print("[最终交付] 由 Kimi 生成：问对问题 + AI深化prompt + 情境视觉prompt...", flush=True)
            final_system = (
                "你是生活/个人话题脑暴的交付整理员。根据以下四轮讨论摘要，输出三个板块，分开写、标题明确。全文必须使用中文。"
                "可用 **加粗** 标记关键词，可用 - 列要点，段间留空行，提高可读性。\n\n"
                "⚠️ 重要格式要求：每个板块的标题必须严格以【一】、【二】、【三】开头，不要使用「板块一」或「### 一、」等其他格式。\n\n"
                "【一】去问对的人对的问题\n"
                "从讨论中提炼 2-3 个需要你（或相关的人）亲自判断的关键问题，按紧急度排序。\n"
                "每个问题必须包含四项：\n"
                "- **问谁**：具体的人（自己/家人/朋友/某领域专业人士），不要笼统\n"
                "- **拿这句话去问**：写成可以直接说出口的一句话，对方听到就能给你答案\n"
                "- **背景**：一两句话说清为什么问这个，如果你搜索到了有帮助的信息，附上给对方参考\n"
                "- **为什么不能跳过**：不想清楚这个会怎样\n"
                "这些必须是别人替不了你的判断——涉及个人价值观、生活优先级、对自己/身边人的了解等。\n\n"
                "【二】交给最强 AI 继续深化（可直接复制）\n"
                "写一段完整的 prompt，用户可以直接复制粘贴给 Claude / Opus 使用。这段 prompt 必须：\n"
                "- 开头说清楚话题背景和你想解决什么问题\n"
                "- 列出最终保留的方向（通常 3 个），每个方向的核心思路和为什么值得做\n"
                "- 说明已做的取舍（排除了什么、为什么）\n"
                "- 明确要求 AI 输出：**行动方案 + 风险对策**——每个方向的第一步（本周能做的）、检验标准（不是感觉）、"
                "最可能卡住的地方及应对办法、时间线建议\n"
                "- 最后让 AI 给出推荐：如果只能选一个方向先试，选哪个、为什么\n"
                "- prompt 本身要自洽完整，不依赖外部文档\n\n"
                "【三】生成视觉概念增强既视感（可直接复制给图像/视频模型）\n"
                "为最终保留的每个方向各写一份 prompt，可直接交给图像或视频生成模型。每份须包含：\n"
                "（1）**情境场景描述**——你在哪、在做什么、周围环境如何、光线氛围情绪，"
                "写得像一个电影分镜，让人看到画面就能感受到这个方向实现后的生活是什么样的\n"
                "（2）**关键时刻**——描述一个最能体现这个方向价值的瞬间，带有情感冲击力"
            )
        final_system += (
            "\n\n你拥有搜索工具。在生成交付物时，**必须**用搜索来提升质量：\n"
            "1. 【一】的问题要有数据支撑——搜索相关行业数据、竞品案例、市场趋势，附在「背景」里让被问的人能快速判断\n"
            "2. 【二】的 AI prompt 要包含真实上下文——如果讨论涉及具体市场/技术/趋势，搜索确认最新信息写进 prompt\n"
            "3. 【三】的视觉 prompt 可参考当前流行的视觉风格——搜索同类内容的热门视觉趋势\n"
            "3-5 次搜索足够，重点放在【一】的数据支撑上。\n\n"
            "⚠️ 最终输出中不要包含任何搜索引用标记（如 [web_search:0]{...} 或 [search_result:1] 等）。"
            "搜索结果应自然融入文字中，直接写出结论和数据即可，不要暴露工具调用痕迹。"
        )
        try:
            from core.agent import AgentLoop
            from core.tools import WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, FETCH_URL_TOOL
            agent = AgentLoop(
                provider="kimi", system=final_system, max_rounds=6, temperature=0.5,
                on_tool_call=lambda name, args: print(f"  🔍 [交付 fact-check] {name}: {str(args)[:80]}", flush=True),
            )
            agent.add_tools([WEB_SEARCH_TOOL, NEWS_SEARCH_TOOL, FETCH_URL_TOOL])
            result = agent.run(summary_input)
            final_output = result.content
            if result.tool_calls_made:
                print(f"  [最终交付] fact-check 搜索了 {len(result.tool_calls_made)} 次", flush=True)
        except Exception as e:
            print(f"  [最终交付] AgentLoop 失败({e}), 回退简单调用", flush=True)
            try:
                final_output = chat_completion(provider="kimi", system=final_system, user=summary_input).strip()
            except Exception as e2:
                print(f"[最终交付] 生成失败: {e2}", flush=True)
                final_output = ""

        if final_output:
            import re as _re_clean
            final_output = _re_clean.sub(
                r'\[(?:web_search|news_search|search_result|fetch_url|search)\s*[:\d]*\]\s*(?:\{[^}]*\}\s*)?',
                '', final_output
            )
            final_output = _re_clean.sub(r'(?:和|根据|参考|见|详见)\s*(?:的搜索结果[，,。]?\s*)', '', final_output)

            session_lines.append("## 最终交付")
            session_lines.append("")
            session_lines.append(final_output)
            session_lines.append("")

            _ordered_titles = [
                "🧑 去问对的人对的问题",
                "🤖 交给最强 AI 继续深化",
                "🎨 视觉概念 Prompt",
            ]
            _cards_sent = False

            import re as _re
            _sec_patterns = [
                _re.compile(r"(?:^|\n)\s*(?:#{1,4}\s*)?(?:【一】|板块一[：:]?|一[、：:])\s*", _re.MULTILINE),
                _re.compile(r"(?:^|\n)\s*(?:#{1,4}\s*)?(?:【二】|板块二[：:]?|二[、：:])\s*", _re.MULTILINE),
                _re.compile(r"(?:^|\n)\s*(?:#{1,4}\s*)?(?:【三】|板块三[：:]?|三[、：:])\s*", _re.MULTILINE),
            ]
            _sec_starts: list[tuple[int, int]] = []  # (section_index, char_pos)
            for idx, pat in enumerate(_sec_patterns):
                m = pat.search(final_output)
                if m:
                    _sec_starts.append((idx, m.start()))
            _sec_starts.sort(key=lambda x: x[1])

            sections = []
            for k, (idx, start_pos) in enumerate(_sec_starts):
                end_pos = _sec_starts[k + 1][1] if k + 1 < len(_sec_starts) else len(final_output)
                section_text = final_output[start_pos:end_pos].strip()
                if section_text:
                    title = _ordered_titles[idx] if idx < len(_ordered_titles) else f"最终交付 ({idx+1})"
                    sections.append((title, section_text))

            if len(sections) >= 2:
                for card_title, section_text in sections:
                    card_text = truncate_for_display(section_text)
                    _send_brainstorm_card(card_title, card_text, color="green", webhook_override=resolved_webhook)
                    time.sleep(FEISHU_INTERVAL)
                _cards_sent = True
                print(f"  [最终交付] 拆分为 {len(sections)} 张卡片发送", flush=True)

            if not _cards_sent:
                to_feishu = final_output if len(final_output) <= 8000 else final_output[:8000] + "\n\n[内容过长，完整交付请查看 session 文件]"
                _send_brainstorm_card("最终交付", to_feishu, color="green", webhook_override=resolved_webhook)
                time.sleep(FEISHU_INTERVAL)

    session_content = "\n".join(session_lines)
    path = save_session(session_content, ts)
    print("[保存] 会话已写入 " + str(path), flush=True)

    if is_v3:
        _send_brainstorm_card("脑暴结束", f"完整会话已保存至 `{path}`", color="green", webhook_override=resolved_webhook)
    else:
        _send_brainstorm_card("脑暴结束", f"完整会话与 Handoff Pack 已保存至 `{path}`", color="green", webhook_override=resolved_webhook)
    print("\n========== 脑暴结束 ==========", flush=True)
    return BrainstormResult(
        str(path),
        round_summaries=round_summaries,
        final_output=final_output,
        topic_refined=topic_refined,
    )


# ── CLI 入口 ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AIlarkteams 脑暴")
    parser.add_argument("--topic", required=True, help="脑暴主题")
    parser.add_argument("--context", default="", help="背景材料：文本，或文件/目录路径")
    parser.add_argument("--deliverables", default="", help="期望交付物")
    parser.add_argument("--no-refine", action="store_true", help="跳过 DeepSeek 主题优化")
    parser.add_argument("--brand", default="", help="指定品牌名（如 sky），留空则自动检测")
    args = parser.parse_args()
    run_brainstorm(
        topic=args.topic.strip(),
        context=load_context(args.context or ""),
        deliverables=(args.deliverables or "").strip(),
        no_refine=args.no_refine,
        brand=(args.brand or "").strip(),
    )


if __name__ == "__main__":
    main()
