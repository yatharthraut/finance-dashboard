"""Claude chat, rendered in the Streamlit sidebar (Phase 5)."""

from __future__ import annotations

import streamlit as st

from chat import assistant
from utils.config import settings


def render() -> None:
    st.sidebar.divider()
    st.sidebar.markdown("### 💬 Ask Claude about your money")

    if not assistant.is_available():
        st.sidebar.info(
            "Add `ANTHROPIC_API_KEY` to your `.env` to enable the chat. "
            "Until then the dashboard works fully on its own."
        )
        return

    st.sidebar.caption(
        f"Model: `{settings.anthropic_model}` · queries your data live as needed"
    )

    if "chat" not in st.session_state:
        st.session_state.chat = []

    # Render history.
    for msg in st.session_state.chat:
        with st.sidebar.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.sidebar.button("Clear chat", use_container_width=True):
        st.session_state.chat = []
        st.rerun()

    prompt = st.sidebar.chat_input("e.g. Where can I cut spending?")
    if not prompt:
        return

    st.session_state.chat.append({"role": "user", "content": prompt})
    with st.sidebar.chat_message("user"):
        st.markdown(prompt)

    with st.sidebar.chat_message("assistant"):
        placeholder = st.empty()
        acc = ""
        try:
            for chunk in assistant.stream_reply(st.session_state.chat):
                acc += chunk
                placeholder.markdown(acc + "▌")
            placeholder.markdown(acc)
        except Exception as exc:  # surface API errors instead of crashing the app
            acc = f"⚠️ Chat error: {exc}"
            placeholder.markdown(acc)

    st.session_state.chat.append({"role": "assistant", "content": acc})
