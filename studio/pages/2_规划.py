# -*- coding: utf-8 -*-
"""规划模式 — 六步理性规划引擎"""
import re
import streamlit as st

st.set_page_config(page_title="Planning", page_icon="📋", layout="wide")

from engine import all_keys_ready, run_planning_engine, list_skills, build_skill_context
from i18n import t, output_lang_instruction

lang = st.session_state.get("lang", "zh")

if not all_keys_ready():
    st.warning(t("need_config", lang))
    st.stop()

st.title(t("pl_title", lang))
st.caption(t("pl_desc", lang))

with st.form("planning_form"):
    topic = st.text_area(t("pl_topic", lang), placeholder=t("pl_topic_ph", lang), height=80)
    context = st.text_area(t("pl_context", lang), placeholder=t("pl_context_ph", lang), height=80)

    col1, col2 = st.columns([1, 1])
    with col1:
        mode_options = ["完整规划", "快速模式", "分析模式", "方案模式", "执行模式"]
        mode_en = {"完整规划": "Full Plan", "快速模式": "Quick", "分析模式": "Analysis", "方案模式": "Solutions", "执行模式": "Execution"}
        mode = st.selectbox(
            t("pl_mode", lang), mode_options,
            format_func=lambda x: mode_en.get(x, x) if lang == "en" else x,
        )
    with col2:
        skills = list_skills()
        skill_options = {s["file"]: s["title"] for s in skills}
        selected_skills = st.multiselect(
            t("skill_label", lang), options=list(skill_options.keys()),
            format_func=lambda x: skill_options.get(x, x), max_selections=3,
        ) if skills else []

    submitted = st.form_submit_button(t("pl_start", lang), type="primary", use_container_width=True)

if submitted and topic.strip():
    skill_ctx = build_skill_context(selected_skills) if selected_skills else ""
    lang_instr = output_lang_instruction(lang)
    with st.status(t("pl_running", lang), expanded=True) as status:
        progress = st.empty()
        try:
            result = run_planning_engine(
                topic=topic.strip(),
                context=context.strip() + lang_instr,
                mode=mode,
                skill_context=skill_ctx,
                progress_container=progress,
            )
            status.update(label=t("pl_done", lang), state="complete", expanded=False)
        except Exception as e:
            status.update(label=t("error", lang), state="error")
            st.error(f"{t('error', lang)}{e}")
            st.stop()
    st.session_state["planning_result"] = result

result = st.session_state.get("planning_result")
if result:
    st.divider()
    st.subheader(t("pl_result", lang))
    step_outputs = result.get("step_outputs", [])
    session = result.get("session_content", "")

    if step_outputs:
        step_prefix = "Step" if lang == "en" else "第 {n} 步"
        for step_num, step_name, step_output in step_outputs:
            label = f"Step {step_num}: {step_name}" if lang == "en" else f"第 {step_num} 步：{step_name}"
            with st.expander(label, expanded=(step_num == len(step_outputs))):
                st.markdown(step_output)

    if session:
        summary_match = re.search(r"## 规划摘要\s*\n(.*?)(?=\n## |\Z)", session, re.DOTALL)
        if summary_match:
            st.divider()
            st.subheader(t("pl_summary", lang))
            summary = summary_match.group(1).strip()
            st.markdown(summary)
            st.divider()
            st.caption(t("copy_hint", lang))
            st.code(summary, language=None)

    with st.expander(t("full_log", lang)):
        if session:
            st.code(session[:50000], language="markdown")
        st.caption(f"{t('full_file', lang)}`{result['session_path']}`")
