# -*- coding: utf-8 -*-
"""AI 创意工作站 — 主页 & 设置"""
import os
import streamlit as st

st.set_page_config(
    page_title="AI Creative Studio",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

from engine import (
    MODEL_SLOTS, PRESETS, check_keys, save_env, load_env,
    all_keys_ready, detect_preset,
)
from i18n import t

# ── 侧边栏：语言 + 状态 ─────────────────────────────────────
with st.sidebar:
    lang = st.radio(
        "Language / 语言",
        ["zh", "en"],
        format_func=lambda x: "中文" if x == "zh" else "English",
        horizontal=True,
        key="lang",
    )
    st.markdown(f"### {t('app_title', lang)}")
    st.caption(t("app_subtitle", lang))
    st.divider()
    status = check_keys()
    ready = sum(status.values())
    total = len(status)
    if ready == total:
        st.success(f"✓ {t('models_ready', lang)}（{ready}/{total}）")
    else:
        st.warning(f"⚠ {t('models_need', lang, n=total - ready)}")

# ── 主页头部 ─────────────────────────────────────────────────
st.markdown(
    f"<h1 style='margin-bottom:0'>{t('app_title', lang)}</h1>"
    f"<p style='color:#6B7280; font-size:1.1rem; margin-top:0.25rem'>"
    f"{t('app_desc', lang)}</p>",
    unsafe_allow_html=True,
)

# ── 模式卡片 ─────────────────────────────────────────────────
modes = [
    ("💡", t("mode_inspire", lang), t("mode_inspire_d", lang)),
    ("📋", t("mode_plan", lang), t("mode_plan_d", lang)),
    ("🎨", t("mode_create", lang), t("mode_create_d", lang)),
    ("🔍", t("mode_research", lang), t("mode_research_d", lang)),
]

cols = st.columns(4, gap="medium")
for i, (icon, title, desc) in enumerate(modes):
    with cols[i]:
        with st.container(border=True):
            st.markdown(
                f"<div style='text-align:center; font-size:2rem; margin-bottom:0.25rem'>{icon}</div>"
                f"<div style='text-align:center; font-weight:600; font-size:1.05rem'>{title}</div>"
                f"<div style='text-align:center; color:#6B7280; font-size:0.82rem; margin-top:0.25rem'>{desc}</div>",
                unsafe_allow_html=True,
            )

st.divider()

# ── 模型配置 ─────────────────────────────────────────────────
st.markdown(
    f"<h3 style='margin-bottom:0.25rem'>{t('model_config', lang)}</h3>"
    f"<p style='color:#6B7280; font-size:0.9rem; margin-top:0'>"
    f"{t('model_config_desc', lang)}</p>",
    unsafe_allow_html=True,
)

env = load_env()
preset_names = list(PRESETS.keys())

SLOT_LABELS = {
    "primary": (t("primary_model", lang), t("primary_desc", lang)),
    "creative": (t("creative_model", lang), t("creative_desc", lang)),
    "longctx": (t("longctx_model", lang), t("longctx_desc", lang)),
}

# ── 快速配置 ─────────────────────────────────────────────────
with st.container(border=True):
    st.markdown(f"**{t('quick_setup', lang)}**")

    qc1, qc2 = st.columns([1, 2])
    with qc1:
        quick_preset = st.selectbox(
            t("provider", lang),
            preset_names,
            key="quick_preset",
            label_visibility="collapsed",
        )
    with qc2:
        quick_key = st.text_input(
            "API Key",
            type="password",
            key="quick_key",
            placeholder=f"{quick_preset} API Key",
            label_visibility="collapsed",
        )

    pcfg = PRESETS[quick_preset]
    st.caption(f"Base URL: `{pcfg['url']}`  ·  Model: `{pcfg['model']}`")

    if st.button(t("one_click", lang), type="primary", use_container_width=True):
        if not quick_key.strip():
            st.error(t("fill_key", lang))
        else:
            try:
                updates = {}
                for slot in MODEL_SLOTS:
                    updates[slot["env_key"]] = quick_key.strip()
                    updates[slot["env_url"]] = pcfg["url"]
                    updates[slot["env_model"]] = pcfg["model"]
                save_env(updates)
                st.success(f"{t('one_click_done', lang)}{quick_preset}")
                st.rerun()
            except Exception as e:
                st.error(f"{t('save_fail', lang)}{e}")

# ── 当前状态 ─────────────────────────────────────────────────
st.markdown(f"##### {t('current_status', lang)}")
scols = st.columns(3, gap="medium")
for i, slot in enumerate(MODEL_SLOTS):
    with scols[i]:
        key_ok = bool(os.environ.get(slot["env_key"], "").strip())
        cur_url = os.environ.get(slot["env_url"], "")
        cur_model = os.environ.get(slot["env_model"], "") or "—"
        provider = detect_preset(cur_url) if cur_url else t("not_configured", lang)
        label, desc = SLOT_LABELS[slot["name"]]
        icon = "✅" if key_ok else "⬜"
        with st.container(border=True):
            st.markdown(
                f"{icon} **{label}**"
                f"<br><span style='color:#6B7280; font-size:0.85rem'>{desc}</span>"
                f"<br><span style='font-size:0.85rem'>"
                f"{t('provider', lang)}: {provider}　Model: <code>{cur_model}</code></span>",
                unsafe_allow_html=True,
            )

# ── 高级配置 ─────────────────────────────────────────────────
with st.expander(t("advanced", lang)):
    with st.form("advanced_form"):
        adv_cols = st.columns(3, gap="medium")
        for i, slot in enumerate(MODEL_SLOTS):
            with adv_cols[i]:
                label, desc = SLOT_LABELS[slot["name"]]
                st.markdown(f"**{label}**")
                st.caption(desc)
                st.text_input("Base URL", value=env.get(slot["env_url"], ""), key=f"adv_url_{i}", placeholder="https://...")
                st.text_input("API Key", value=env.get(slot["env_key"], ""), type="password", key=f"adv_key_{i}", placeholder="sk-...")
                st.text_input("Model", value=env.get(slot["env_model"], ""), key=f"adv_model_{i}", placeholder="model-name")
        st.divider()
        st.text_input("Tavily API Key", value=env.get("TAVILY_API_KEY", ""), type="password", key="adv_tavily", placeholder="tvly-...")
        if st.form_submit_button(t("save_advanced", lang), use_container_width=True):
            try:
                updates = {}
                for j, s in enumerate(MODEL_SLOTS):
                    for suffix, env_k in [("url", s["env_url"]), ("key", s["env_key"]), ("model", s["env_model"])]:
                        val = st.session_state.get(f"adv_{suffix}_{j}", "")
                        if val.strip():
                            updates[env_k] = val.strip()
                tavily = st.session_state.get("adv_tavily", "")
                if tavily.strip():
                    updates["TAVILY_API_KEY"] = tavily.strip()
                save_env(updates)
                st.success(t("saved", lang))
                st.rerun()
            except Exception as e:
                st.error(f"{t('save_fail', lang)}{e}")

# ── 底部 ─────────────────────────────────────────────────────
if not all_keys_ready():
    st.info(t("not_ready", lang))
else:
    st.success(t("all_ready", lang))
