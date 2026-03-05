# -*- coding: utf-8 -*-
"""灵感模式 — 5 个 AI 角色四轮脑暴"""
import re
import streamlit as st

st.set_page_config(page_title="Inspiration", page_icon="💡", layout="wide")

from engine import all_keys_ready, run_brainstorm_engine, list_skills, build_skill_context
from i18n import t, output_lang_instruction

lang = st.session_state.get("lang", "zh")

if not all_keys_ready():
    st.warning(t("need_config", lang))
    st.stop()

st.title(t("bs_title", lang))
st.caption(t("bs_desc", lang))

with st.form("brainstorm_form"):
    topic = st.text_area(t("bs_topic", lang), placeholder=t("bs_topic_ph", lang), height=80)
    context = st.text_area(t("bs_context", lang), placeholder=t("bs_context_ph", lang), height=80)

    col1, col2 = st.columns([1, 1])
    with col1:
        type_labels = {
            "auto": "🔮 " + ("自动识别" if lang == "zh" else "Auto-detect"),
            "campaign": "📣 " + ("营销活动" if lang == "zh" else "Campaign"),
            "project": "🛠 " + ("项目产品" if lang == "zh" else "Project"),
            "strategy": "♟ " + ("策略探讨" if lang == "zh" else "Strategy"),
            "explore": "🌱 " + ("生活个人" if lang == "zh" else "Personal"),
        }
        topic_type = st.selectbox(t("bs_type", lang), list(type_labels.keys()), format_func=lambda x: type_labels[x])
    with col2:
        skills = list_skills()
        skill_options = {s["file"]: s["title"] for s in skills}
        selected_skills = st.multiselect(
            t("skill_label", lang), options=list(skill_options.keys()),
            format_func=lambda x: skill_options.get(x, x), max_selections=3,
            help=t("skill_help", lang),
        ) if skills else []

    submitted = st.form_submit_button(t("bs_start", lang), type="primary", use_container_width=True)

if submitted and topic.strip():
    skill_ctx = build_skill_context(selected_skills) if selected_skills else ""
    lang_instr = output_lang_instruction(lang)
    with st.status(t("bs_running", lang), expanded=True) as status:
        progress = st.empty()
        try:
            result = run_brainstorm_engine(
                topic=topic.strip(),
                context=context.strip() + lang_instr,
                topic_type=topic_type,
                skill_context=skill_ctx,
                progress_container=progress,
            )
            status.update(label=t("bs_done", lang), state="complete", expanded=False)
        except Exception as e:
            status.update(label=t("error", lang), state="error")
            st.error(f"{t('error', lang)}{e}")
            st.stop()
    st.session_state["brainstorm_result"] = result

result = st.session_state.get("brainstorm_result")
if result:
    st.divider()
    st.subheader(t("bs_result", lang))
    session = result["session_content"]

    inventory = ""
    inv_match = re.search(r"## 创意全清单\s*\n(.*?)(?=\n## |\n---|\Z)", session, re.DOTALL)
    if inv_match:
        inventory = inv_match.group(1).strip()

    delivery = ""
    del_match = re.search(r"## 最终交付\s*\n(.*?)(?=\n## |\Z)", session, re.DOTALL)
    if del_match:
        delivery = del_match.group(1).strip()

    tabs = st.tabs([t("bs_inventory", lang), t("bs_delivery", lang), f"📄 {t('full_log', lang)}"])

    with tabs[0]:
        if inventory:
            st.markdown(inventory)
            st.divider()
            st.code(inventory, language=None)
        else:
            st.info("—")

    with tabs[1]:
        if delivery:
            sections = re.split(r"(?=【[一二三]】)", delivery)
            sections = [s.strip() for s in sections if s.strip()]
            for sec in sections:
                title_match = re.match(r"(【[一二三]】[^\n]+)", sec)
                title = title_match.group(1) if title_match else "—"
                with st.expander(title, expanded=True):
                    st.markdown(sec)
                    st.divider()
                    st.caption(t("copy_hint", lang))
                    st.code(sec, language=None)
        else:
            st.info("—")

    with tabs[2]:
        if session:
            st.code(session[:50000], language="markdown")
        st.caption(f"{t('full_file', lang)}`{result['session_path']}`")
