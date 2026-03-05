# -*- coding: utf-8 -*-
"""调研模式 — Fact-Checked 深度研究"""
import streamlit as st

st.set_page_config(page_title="Research", page_icon="🔍", layout="wide")

from engine import all_keys_ready, run_research_engine, list_skills, build_skill_context
from i18n import t, output_lang_instruction

lang = st.session_state.get("lang", "zh")

if not all_keys_ready():
    st.warning(t("need_config", lang))
    st.stop()

st.title(t("rs_title", lang))
st.caption(t("rs_desc", lang))

with st.form("research_form"):
    question = st.text_area(t("rs_question", lang), placeholder=t("rs_question_ph", lang), height=80)
    context = st.text_area(t("rs_context", lang), placeholder=t("rs_context_ph", lang), height=60)

    skills = list_skills()
    skill_options = {s["file"]: s["title"] for s in skills}
    selected_skills = st.multiselect(
        t("skill_label", lang), options=list(skill_options.keys()),
        format_func=lambda x: skill_options.get(x, x), max_selections=3,
    ) if skills else []

    submitted = st.form_submit_button(t("rs_start", lang), type="primary", use_container_width=True)

if submitted and question.strip():
    skill_ctx = build_skill_context(selected_skills) if selected_skills else ""
    lang_instr = output_lang_instruction(lang)
    with st.status(t("rs_running", lang), expanded=True) as status:
        progress = st.empty()
        try:
            report = run_research_engine(
                question=question.strip(),
                context=context.strip() + lang_instr,
                skill_context=skill_ctx,
                progress_container=progress,
            )
            status.update(label=t("rs_done", lang), state="complete", expanded=False)
        except Exception as e:
            status.update(label=t("error", lang), state="error")
            st.error(f"{t('error', lang)}{e}")
            st.stop()
    st.session_state["research_result"] = report

report = st.session_state.get("research_result")
if report:
    st.divider()
    st.subheader(t("rs_result", lang))
    st.markdown(report)
    st.divider()
    with st.expander(t("rs_copy", lang)):
        st.code(report, language=None)
