"""Overview view: headline cash-flow numbers + per-account balances."""

from __future__ import annotations

from datetime import date

import streamlit as st

from utils import analytics


def _prev_month(d: date) -> date:
    return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)


def render() -> None:
    st.subheader("This month at a glance")

    start, end = analytics.month_bounds()
    df = analytics.transactions_df(start=start, end=end)

    prev_start, prev_end = analytics.month_bounds(_prev_month(date.today()))
    prev_df = analytics.transactions_df(start=prev_start, end=prev_end)

    spend = analytics.total_spend(df)
    income = analytics.total_income(df)
    net = analytics.net_cash_flow(df)
    prev_spend = analytics.total_spend(prev_df)

    c1, c2, c3 = st.columns(3)
    c1.metric("Income", f"${income:,.0f}")
    spend_delta = spend - prev_spend
    c2.metric(
        "Total spend",
        f"${spend:,.0f}",
        delta=f"{spend_delta:+,.0f} vs last mo",
        delta_color="inverse",  # more spending is "bad"
    )
    c3.metric("Net cash flow", f"${net:,.0f}", delta_color="normal")

    st.divider()
    st.subheader("Account balances")

    accounts = analytics.accounts_df()
    if accounts.empty:
        st.info("No accounts yet. Use the sidebar **Refresh** to load data.")
        return

    cols = st.columns(min(len(accounts), 4))
    for i, (_, a) in enumerate(accounts.iterrows()):
        with cols[i % len(cols)]:
            label = f"{a['institution']} · {a['mask'] or ''}"
            bal = a["current_balance"] or 0.0
            sub = a["subtype"] or a["type"] or ""
            if a["type"] in ("credit", "loan"):
                st.metric(label, f"-${bal:,.0f}", help=f"{sub} (amount owed)")
            else:
                st.metric(label, f"${bal:,.0f}", help=sub)

    # Spend by account this month.
    by_acct = analytics.spend_by_account(df)
    if not by_acct.empty:
        st.divider()
        st.subheader("Where this month's spending happened")
        st.bar_chart(by_acct, x="account_name", y="amount", horizontal=True)
