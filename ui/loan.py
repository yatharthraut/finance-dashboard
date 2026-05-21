"""Loan tracker: Amex personal loan balance + payoff projection."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from utils import analytics


def render() -> None:
    st.subheader("Loan tracker")

    accounts = analytics.accounts_df()
    if accounts.empty:
        st.info("No accounts yet. Use the sidebar **Refresh** to load data.")
        return

    loans = accounts[accounts["type"] == "loan"]
    if loans.empty:
        st.info("No loan accounts detected.")
        return

    # Pick a loan (usually just the Amex personal loan).
    labels = {
        f"{r['institution']} · {r['name']} ({r['mask']})": r for _, r in loans.iterrows()
    }
    choice = st.selectbox("Loan account", list(labels.keys()))
    loan = labels[choice]
    balance = float(loan["current_balance"] or 0.0)

    detected_payment = analytics.detect_monthly_loan_payment(loan["account_id"])

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Current balance", f"${balance:,.2f}")
    with c2:
        payment = st.number_input(
            "Monthly payment",
            min_value=0.0,
            value=float(detected_payment or 325.0),
            step=25.0,
            help="Auto-detected from your transfers; adjust to model scenarios.",
        )
    with c3:
        apr = st.slider("Estimated APR (%)", 0.0, 30.0, 13.0, 0.5) / 100.0

    proj = analytics.loan_payoff(balance, payment, apr)

    if proj.get("months") is None:
        st.error(proj.get("note", "Payment too low to ever pay off the loan."))
        return
    if proj["months"] == 0:
        st.success("Loan is paid off. 🎉")
        return

    m1, m2, m3 = st.columns(3)
    m1.metric("Months to payoff", proj["months"])
    m2.metric("Payoff date", proj["payoff_date"])
    m3.metric("Total interest", f"${proj['total_interest']:,.2f}")

    sched = pd.DataFrame(proj["schedule"])
    if not sched.empty:
        st.markdown("**Projected balance over time**")
        st.line_chart(sched, x="month", y="balance")

    # Scenario hint: what an extra $100/mo does.
    faster = analytics.loan_payoff(balance, payment + 100, apr)
    if faster.get("months") and faster["months"] < proj["months"]:
        saved_months = proj["months"] - faster["months"]
        saved_int = proj["total_interest"] - faster["total_interest"]
        st.info(
            f"Paying **$100 more/month** would clear it {saved_months} months "
            f"sooner and save ~${saved_int:,.0f} in interest."
        )
