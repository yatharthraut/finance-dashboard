"""AI Scratch Space tab: ask for charts/tables in plain English; AI builds them.

The model returns chart specs (via chat.visualize) and this view renders each
with Altair / st.dataframe. Results accumulate so you can build several.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from chat import assistant, visualize

_MARKS = {"line": "mark_line", "bar": "mark_bar", "area": "mark_area", "scatter": "mark_point"}

EXAMPLES = (
    "- *Line chart of dining spend per day, this month vs last month*\n"
    "- *Bar chart of spending by category this month*\n"
    "- *Table of my top 10 merchants by total spend*"
)


def _alt_axis(df: pd.DataFrame, col: str):
    s = df[col]
    if pd.api.types.is_datetime64_any_dtype(s):
        return alt.X(col, type="temporal")
    if pd.api.types.is_numeric_dtype(s):
        return alt.X(col, type="quantitative")
    return alt.X(col)


def _render_artifact(art: dict) -> None:
    df = art["df"]
    t = art["chart_type"]
    st.markdown(f"**{art['title']}**")
    if art.get("explanation"):
        st.caption(art["explanation"])

    if t == "table":
        st.dataframe(df, hide_index=True, use_container_width=True)
    elif t == "metric":
        st.metric(art["title"], df.iloc[0, 0])
    else:
        x, y, color = art.get("x"), art.get("y"), art.get("color")
        if not x or not y or x not in df.columns or y not in df.columns:
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            enc = {"x": _alt_axis(df, x), "y": alt.Y(y, type="quantitative")}
            if color and color in df.columns:
                enc["color"] = alt.Color(color)
            mark = _MARKS.get(t, "mark_line")
            base = getattr(alt.Chart(df), mark)
            chart = (base(point=True) if t == "line" else base()).encode(**enc)
            st.altair_chart(chart, use_container_width=True)

    with st.expander("SQL"):
        st.code(art["sql"], language="sql")


def render() -> None:
    st.subheader("🧪 AI Scratch Space")
    st.caption("Describe a chart or table and the AI builds it live from your data.")

    if not assistant.is_available():
        st.info("Add `ANTHROPIC_API_KEY` to your `.env` to enable this.")
        return

    st.markdown(EXAMPLES)

    if "scratch" not in st.session_state:
        st.session_state.scratch = []

    with st.form("scratch_form", clear_on_submit=True):
        request = st.text_input(
            "What do you want to see?",
            placeholder="Line chart of dining spend per day, this month vs last month",
        )
        submitted = st.form_submit_button("Generate")

    if submitted and request.strip():
        try:
            with st.spinner("Building…"):
                text, artifacts = visualize.generate(request.strip())
            st.session_state.scratch.insert(
                0, {"request": request.strip(), "text": text, "artifacts": artifacts}
            )
        except Exception as exc:
            st.error(f"Couldn't build that: {exc}")

    if st.session_state.scratch:
        if st.button("Clear scratch space"):
            st.session_state.scratch = []
            st.rerun()

    for item in st.session_state.scratch:
        with st.container(border=True):
            st.markdown(f"🗨️ **{item['request']}**")
            for art in item["artifacts"]:
                _render_artifact(art)
            if not item["artifacts"]:
                st.caption("No chart produced for this one.")
            if item["text"]:
                st.markdown(item["text"])
