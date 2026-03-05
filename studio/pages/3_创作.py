# -*- coding: utf-8 -*-
"""创作模式 — 选题 + 素材 Prompt（含分镜）+ 执行 Brief"""
import streamlit as st

st.set_page_config(page_title="Creation", page_icon="🎨", layout="wide")

from engine import all_keys_ready, run_creative_engine, list_skills, build_skill_context
from i18n import t, output_lang_instruction

lang = st.session_state.get("lang", "zh")

if not all_keys_ready():
    st.warning(t("need_config", lang))
    st.stop()

st.title(t("cr_title", lang))
st.caption(t("cr_desc", lang))

with st.form("creative_form"):
    topic = st.text_area(t("cr_topic", lang), placeholder=t("cr_topic_ph", lang), height=80)

    col1, col2, col3 = st.columns(3)
    with col1:
        brand = st.text_input(t("cr_brand", lang), placeholder="e.g. Heytea")
    with col2:
        platforms = ["抖音", "小红书", "视频号", "B站", "通用"] if lang == "zh" else ["TikTok", "Xiaohongshu", "WeChat Video", "Bilibili", "General"]
        platform = st.selectbox(t("cr_platform", lang), platforms)
    with col3:
        duration = st.selectbox(t("cr_duration", lang), ["≤10s", "15s", "30s", "60s"])

    skills = list_skills()
    skill_options = {s["file"]: s["title"] for s in skills}
    selected_skills = st.multiselect(
        t("skill_label", lang), options=list(skill_options.keys()),
        format_func=lambda x: skill_options.get(x, x), max_selections=3,
    ) if skills else []

    submitted = st.form_submit_button(t("cr_start", lang), type="primary", use_container_width=True)

if submitted and topic.strip():
    skill_ctx = build_skill_context(selected_skills) if selected_skills else ""
    lang_instr = output_lang_instruction(lang)
    full_topic = topic.strip()
    if lang_instr:
        full_topic += lang_instr
    with st.status(t("cr_running", lang), expanded=True) as status:
        progress = st.empty()
        try:
            result = run_creative_engine(
                topic=full_topic,
                brand=brand.strip(),
                platform=platform,
                duration=duration,
                skill_context=skill_ctx,
                progress_container=progress,
            )
            status.update(label=t("cr_done", lang), state="complete", expanded=False)
        except Exception as e:
            status.update(label=t("error", lang), state="error")
            st.error(f"{t('error', lang)}{e}")
            st.stop()
    st.session_state["creative_result"] = result

result = st.session_state.get("creative_result")
if result:
    st.divider()
    st.subheader(t("cr_result", lang))
    tabs = st.tabs([t("cr_ideas", lang), t("cr_prompt", lang), t("cr_brief", lang), t("cr_handoff", lang)])

    with tabs[0]:
        st.markdown(result["ideas"])
    with tabs[1]:
        st.markdown(result["creative_prompt"])
        st.divider()
        st.caption(t("copy_hint", lang))
        st.code(result["creative_prompt"], language=None)
    with tabs[2]:
        st.markdown(result["brief"])
        st.divider()
        st.caption(t("copy_hint", lang))
        st.code(result["brief"], language=None)
    with tabs[3]:
        st.markdown(result["handoff"])
        st.divider()
        st.caption(t("copy_hint", lang))
        st.code(result["handoff"], language=None)
