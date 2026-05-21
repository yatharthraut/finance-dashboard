"""Breakdown view: spending by category (bar) + weekly trend (line)."""

from __future__ import annotations

import streamlit as st

from utils import analytics


def render() -> None:
    st.subheader("Spending breakdown")

    # Date range control — default to the trailing ~3 months of data.
    full = analytics.transactions_df()
    if full.empty:
        st.info("No transactions yet. Use the sidebar **Refresh** to load data.")
        return

    min_d = full["date"].min().date()
    max_d = full["date"].max().date()
    rng = st.date_input(
        "Date range",
        value=(min_d, max_d),
        min_value=min_d,
        max_value=max_d,
    )
    if isinstance(rng, tuple) and len(rng) == 2:
        start, end = rng[0].isoformat(), rng[1].isoformat()
    else:
        start, end = min_d.isoformat(), max_d.isoformat()

    df = analytics.transactions_df(start=start, end=end)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**By category**")
        cat = analytics.spend_by_category(df)
        if cat.empty:
            st.caption("No spending in range.")
        else:
            st.bar_chart(cat, x="category", y="amount", horizontal=True)

    with col2:
        st.markdown("**Top merchants**")
        merch = analytics.top_merchants(df, n=10)
        if merch.empty:
            st.caption("No spending in range.")
        else:
            st.bar_chart(merch, x="merchant", y="amount", horizontal=True)

    st.divider()
    st.markdown("**Weekly spending trend**")
    weekly = analytics.spend_by_week(df)
    if weekly.empty:
        st.caption("No spending in range.")
    else:
        st.line_chart(weekly, x="week", y="amount")

    # Category table with share of total.
    cat = analytics.spend_by_category(df)
    if not cat.empty:
        total = cat["amount"].sum()
        cat = cat.assign(share=(cat["amount"] / total * 100).round(1))
        cat = cat.rename(
            columns={"category": "Category", "amount": "Spend ($)", "share": "Share (%)"}
        )
        st.dataframe(cat, hide_index=True, use_container_width=True)
