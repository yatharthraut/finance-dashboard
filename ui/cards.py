"""Credit-card view: balances, utilization, and Liabilities detail.

APR / minimum payment / statement / due-date fields come from the Plaid
Liabilities product and are only populated for items where it's available; they
show as "—" otherwise (e.g. mock or sandbox-without-liabilities data).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import analytics


def _money(v) -> str:
    return f"${v:,.2f}" if v not in (None, "") and not pd.isna(v) else "—"


def _date(v) -> str:
    return str(v) if v not in (None, "") and not pd.isna(v) else "—"


def render() -> None:
    st.subheader("Credit cards")

    accounts = analytics.accounts_df()
    if accounts.empty:
        st.info("No accounts yet. Use the sidebar **Refresh** to load data.")
        return

    cards = accounts[accounts["type"] == "credit"]
    if cards.empty:
        st.info("No credit cards linked.")
        return

    has_liab = cards["apr"].notna().any() if "apr" in cards.columns else False
    if not has_liab:
        st.caption(
            "Tip: link cards with the **Liabilities** product to see APR, "
            "minimum payment, and statement due dates here."
        )

    # Portfolio totals.
    total_balance = cards["current_balance"].fillna(0).sum()
    total_limit = cards["credit_limit"].fillna(0).sum()
    util = (total_balance / total_limit * 100) if total_limit else None
    c1, c2, c3 = st.columns(3)
    c1.metric("Total card debt", _money(total_balance))
    c2.metric("Total limit", _money(total_limit))
    c3.metric("Overall utilization", f"{util:.0f}%" if util is not None else "—")

    st.divider()

    for _, c in cards.iterrows():
        with st.container(border=True):
            mask = c["mask"] or "----"
            st.markdown(f"**{c['institution']} · {c['name']}**  ····{mask}")

            balance = c["current_balance"] or 0.0
            limit = c["credit_limit"] or 0.0
            card_util = (balance / limit * 100) if limit else None
            apr = c.get("apr")

            m = st.columns(4)
            m[0].metric("Balance", _money(balance))
            m[1].metric("Limit", _money(limit) if limit else "—")
            m[2].metric(
                "Utilization", f"{card_util:.0f}%" if card_util is not None else "—"
            )
            m[3].metric("APR", f"{apr:.2f}%" if apr not in (None, "") and not pd.isna(apr) else "—")

            if card_util is not None:
                st.progress(min(card_util / 100, 1.0))
                if card_util >= 30:
                    st.caption("⚠️ Utilization above 30% can weigh on your credit score.")

            # Liabilities detail row.
            d = st.columns(4)
            d[0].metric("Min payment", _money(c.get("minimum_payment")))
            d[1].metric("Statement balance", _money(c.get("last_statement_balance")))
            d[2].metric("Payment due", _date(c.get("next_payment_due_date")))
            d[3].metric("Last payment", _money(c.get("last_payment_amount")))

            overdue = c.get("is_overdue")
            if overdue not in (None, "") and not pd.isna(overdue) and int(overdue) == 1:
                st.error("This card is reported **overdue**.")
