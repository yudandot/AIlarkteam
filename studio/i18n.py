# -*- coding: utf-8 -*-
"""studio/i18n.py — 中英文翻译"""
from __future__ import annotations

T: dict[str, dict[str, str]] = {
    # ── 通用 ──
    "app_title":        {"zh": "⚡ AI 创意工作站", "en": "⚡ AI Creative Studio"},
    "app_subtitle":     {"zh": "灵感 · 规划 · 创作 · 调研", "en": "Inspire · Plan · Create · Research"},
    "app_desc":         {"zh": "四种模式，帮团队高效获取灵感、做调研、出方案、交作业。", "en": "Four modes to help your team brainstorm, plan, create, and research."},
    "models_ready":     {"zh": "模型已就绪", "en": "Models ready"},
    "models_need":      {"zh": "还需配置 {n} 个模型", "en": "{n} model(s) need config"},
    "save":             {"zh": "保存配置", "en": "Save"},
    "saved":            {"zh": "已保存！", "en": "Saved!"},
    "save_fail":        {"zh": "保存失败：", "en": "Save failed: "},
    "fill_key":         {"zh": "请先填写 API Key", "en": "Please enter an API Key first"},
    "need_config":      {"zh": "请先在主页配置模型。", "en": "Please configure models on the home page first."},
    "all_ready":        {"zh": "所有模型已就绪，从左侧菜单选择模式开始使用。", "en": "All models ready. Choose a mode from the sidebar."},
    "not_ready":        {"zh": "请先配置模型，然后从左侧菜单选择模式开始使用。", "en": "Please configure models, then choose a mode from the sidebar."},
    "copy_hint":        {"zh": "点击右上角复制", "en": "Click top-right to copy"},
    "full_log":         {"zh": "完整日志", "en": "Full Log"},
    "full_file":        {"zh": "完整文件：", "en": "Full file: "},
    "error":            {"zh": "运行出错：", "en": "Error: "},
    "lang_label":       {"zh": "语言 / Language", "en": "Language / 语言"},

    # ── 模型配置 ──
    "model_config":     {"zh": "模型配置", "en": "Model Configuration"},
    "model_config_desc": {"zh": "支持所有 OpenAI 兼容 API（DeepSeek、Gemini、GPT-4o、通义千问等）。三个插槽可以填同一个。", "en": "Supports any OpenAI-compatible API (DeepSeek, Gemini, GPT-4o, etc.). All three slots can use the same provider."},
    "quick_setup":      {"zh": "快速配置 — 一个 Key 配齐所有模型", "en": "Quick Setup — One Key for All Models"},
    "provider":         {"zh": "服务商", "en": "Provider"},
    "one_click":        {"zh": "一键配置所有模型", "en": "Configure All Models"},
    "one_click_done":   {"zh": "已保存！三个模型全部设为 ", "en": "Saved! All models set to "},
    "current_status":   {"zh": "当前状态", "en": "Current Status"},
    "not_configured":   {"zh": "未配置", "en": "Not configured"},
    "advanced":         {"zh": "高级配置 — 分别设置每个模型", "en": "Advanced — Configure Each Model"},
    "save_advanced":    {"zh": "保存高级配置", "en": "Save Advanced Config"},
    "primary_model":    {"zh": "主力模型", "en": "Primary Model"},
    "primary_desc":     {"zh": "规划、分析、逻辑推理", "en": "Planning, analysis, logic"},
    "creative_model":   {"zh": "创意模型", "en": "Creative Model"},
    "creative_desc":    {"zh": "脑暴中的创意发散角色", "en": "Creative roles in brainstorm"},
    "longctx_model":    {"zh": "长文本模型", "en": "Long-Context Model"},
    "longctx_desc":     {"zh": "素材交付、长文本处理", "en": "Deliverables, long-text processing"},

    # ── 模式名 ──
    "mode_inspire":     {"zh": "灵感", "en": "Inspire"},
    "mode_plan":        {"zh": "规划", "en": "Plan"},
    "mode_create":      {"zh": "创作", "en": "Create"},
    "mode_research":    {"zh": "调研", "en": "Research"},
    "mode_inspire_d":   {"zh": "5 个 AI 角色四轮脑暴，产出创意全清单 + AI 深化 Prompt", "en": "5 AI roles brainstorm in 4 rounds, producing a full idea inventory + AI handoff prompt"},
    "mode_plan_d":      {"zh": "六步理性规划，从问题定义到可执行方案", "en": "6-step rational planning, from problem definition to action plan"},
    "mode_create_d":    {"zh": "选题 → 分镜 Prompt → 执行 Brief，一站式创作", "en": "Topic → Storyboard Prompt → Exec Brief, all-in-one creation"},
    "mode_research_d":  {"zh": "Fact-Checked 深度研究，多来源交叉验证", "en": "Fact-checked deep research with multi-source verification"},

    # ── 灵感页 ──
    "bs_title":         {"zh": "💡 灵感模式", "en": "💡 Inspiration Mode"},
    "bs_desc":          {"zh": "5 个 AI 角色（芝麻仁·核桃仁·杏仁·瓜子仁·松子仁）四轮结构化讨论，帮你发散思维、收敛方向。", "en": "5 AI roles engage in 4 rounds of structured discussion to diverge ideas and converge on directions."},
    "bs_topic":         {"zh": "脑暴主题", "en": "Brainstorm Topic"},
    "bs_topic_ph":      {"zh": "例：如何让品牌在抖音上破圈？", "en": "e.g. How to make the brand go viral on TikTok?"},
    "bs_context":       {"zh": "背景材料（选填）", "en": "Background (optional)"},
    "bs_context_ph":    {"zh": "相关背景、约束条件、目标受众、预算等", "en": "Constraints, target audience, budget, etc."},
    "bs_type":          {"zh": "话题类型", "en": "Topic Type"},
    "bs_start":         {"zh": "开始脑暴", "en": "Start Brainstorm"},
    "bs_running":       {"zh": "正在进行脑暴讨论…", "en": "Brainstorming in progress..."},
    "bs_done":          {"zh": "脑暴完成", "en": "Brainstorm Complete"},
    "bs_result":        {"zh": "脑暴结果", "en": "Brainstorm Results"},
    "bs_inventory":     {"zh": "📋 创意全清单", "en": "📋 Full Idea Inventory"},
    "bs_delivery":      {"zh": "📦 最终交付", "en": "📦 Final Deliverables"},

    # ── 规划页 ──
    "pl_title":         {"zh": "📋 规划模式", "en": "📋 Planning Mode"},
    "pl_desc":          {"zh": "六步理性规划：问题定义 → 现状分析 → 方案生成 → 评估矩阵 → 执行计划 → 反馈机制", "en": "6-step planning: Problem Definition → Situation Analysis → Solutions → Evaluation → Action Plan → Feedback"},
    "pl_topic":         {"zh": "规划主题", "en": "Planning Topic"},
    "pl_topic_ph":      {"zh": "例：Q3 品牌增长策略 / 新产品 0-1 冷启动方案", "en": "e.g. Q3 brand growth strategy / New product cold start plan"},
    "pl_context":       {"zh": "背景材料（选填）", "en": "Background (optional)"},
    "pl_context_ph":    {"zh": "当前状态、资源约束、已有信息等", "en": "Current status, resource constraints, existing info"},
    "pl_mode":          {"zh": "规划模式", "en": "Planning Mode"},
    "pl_start":         {"zh": "开始规划", "en": "Start Planning"},
    "pl_running":       {"zh": "正在进行结构化规划…", "en": "Structured planning in progress..."},
    "pl_done":          {"zh": "规划完成", "en": "Planning Complete"},
    "pl_result":        {"zh": "规划结果", "en": "Planning Results"},
    "pl_summary":       {"zh": "规划摘要", "en": "Planning Summary"},

    # ── 创作页 ──
    "cr_title":         {"zh": "🎨 创作模式", "en": "🎨 Creation Mode"},
    "cr_desc":          {"zh": "选题思考 → 素材 Prompt（含分镜规则）→ 执行 Brief，一站式 AI 内容创作。", "en": "Topic ideation → Storyboard Prompt → Exec Brief, all-in-one AI content creation."},
    "cr_topic":         {"zh": "创作需求", "en": "Creative Brief"},
    "cr_topic_ph":      {"zh": "例：给某茶饮品牌拍一条抖音种草视频，突出春日限定新品", "en": "e.g. Create a TikTok video for a tea brand featuring a spring limited edition"},
    "cr_brand":         {"zh": "品牌名称（选填）", "en": "Brand (optional)"},
    "cr_platform":      {"zh": "目标平台", "en": "Platform"},
    "cr_duration":      {"zh": "内容时长", "en": "Duration"},
    "cr_start":         {"zh": "开始创作", "en": "Start Creating"},
    "cr_running":       {"zh": "正在进行 AI 创作…", "en": "AI creation in progress..."},
    "cr_done":          {"zh": "创作完成", "en": "Creation Complete"},
    "cr_result":        {"zh": "创作结果", "en": "Creation Results"},
    "cr_ideas":         {"zh": "💡 选题方向", "en": "💡 Topic Ideas"},
    "cr_prompt":        {"zh": "🎬 素材 Prompt（含分镜）", "en": "🎬 Visual Prompt (w/ Storyboard)"},
    "cr_brief":         {"zh": "📄 执行 Brief", "en": "📄 Exec Brief"},
    "cr_handoff":       {"zh": "🤖 AI 深化 Prompt", "en": "🤖 AI Handoff Prompt"},

    # ── 调研页 ──
    "rs_title":         {"zh": "🔍 调研模式", "en": "🔍 Research Mode"},
    "rs_desc":          {"zh": "Fact-Checked 深度研究：多来源交叉验证、证据分级、机制分析，输出可信的调研报告。", "en": "Fact-checked deep research: multi-source verification, evidence grading, mechanism analysis."},
    "rs_question":      {"zh": "调研问题", "en": "Research Question"},
    "rs_question_ph":   {"zh": "例：Character.ai 为什么增长这么快？", "en": "e.g. Why is Character.ai growing so fast?"},
    "rs_context":       {"zh": "补充背景（选填）", "en": "Additional context (optional)"},
    "rs_context_ph":    {"zh": "已知信息、特别关注的角度等", "en": "Known info, angles of interest, etc."},
    "rs_start":         {"zh": "开始调研", "en": "Start Research"},
    "rs_running":       {"zh": "正在深度调研（多轮搜索 + Fact-Check）…", "en": "Deep research in progress (multi-round search + fact-check)..."},
    "rs_done":          {"zh": "调研完成", "en": "Research Complete"},
    "rs_result":        {"zh": "调研报告", "en": "Research Report"},
    "rs_copy":          {"zh": "复制完整报告", "en": "Copy Full Report"},

    # ── Skills ──
    "skill_label":      {"zh": "参考知识（选填，最多 3 个）", "en": "Reference Knowledge (optional, max 3)"},
    "skill_help":       {"zh": "从 CN MKT 知识库中选择相关模块作为背景", "en": "Select modules from CN MKT knowledge base as context"},
}


def t(key: str, lang: str = "zh", **kwargs) -> str:
    """获取翻译文本。支持 {var} 占位符。"""
    entry = T.get(key, {})
    text = entry.get(lang, entry.get("zh", key))
    if kwargs:
        text = text.format(**kwargs)
    return text


def output_lang_instruction(lang: str) -> str:
    """生成 AI 输出语言指令，附加到 context 中。"""
    if lang == "en":
        return (
            "\n\nIMPORTANT LANGUAGE INSTRUCTION: "
            "All your output MUST be in English. "
            "Do not output any Chinese text in your final response."
        )
    return ""
