"""Account drill-down: filterable transactions table with category override."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db import database as db
from ingest.categorize import CATEGORIES
from ui import _highlight
from utils import analytics


def render() -> None:
    st.subheader("Transactions")

    accounts = analytics.accounts_df()
    if accounts.empty:
        st.info("No accounts yet. Use the sidebar **Refresh** to load data.")
        return

    # Loan accounts (e.g. the Amex personal loan) belong in the Loan tab, not in
    # the spending/transactions view — exclude them here.
    loan_ids = set(accounts.loc[accounts["type"] == "loan", "account_id"])
    accounts = accounts[accounts["type"] != "loan"]

    # --- Filters ---
    f1, f2, f3 = st.columns([2, 2, 3])
    with f1:
        acct_labels = {"All accounts": None} | {
            f"{r['institution']} · {r['name']} ({r['mask']})": r["account_id"]
            for _, r in accounts.iterrows()
        }
        acct_choice = st.selectbox("Account", list(acct_labels.keys()))
        account_id = acct_labels[acct_choice]

    df = analytics.transactions_df()
    if df.empty:
        st.info("No transactions yet.")
        return
    if loan_ids:
        df = df[~df["account_id"].isin(loan_ids)]

    with f2:
        cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
        cat_choice = st.selectbox("Category", cats)
    with f3:
        search = st.text_input("Search merchant / description")

    show_transfers = st.checkbox("Include transfers", value=False)

    # --- Apply filters ---
    view = df.copy()
    if account_id:
        view = view[view["account_id"] == account_id]
    if cat_choice != "All":
        view = view[view["category"] == cat_choice]
    if not show_transfers:
        view = view[~view["is_transfer"]]
    if search:
        s = search.lower()
        view = view[
            view["merchant"].str.lower().str.contains(s, na=False)
            | view["name"].str.lower().str.contains(s, na=False)
        ]

    st.caption(f"{len(view):,} transactions · ${view.loc[view['amount'] > 0, 'amount'].sum():,.2f} out")

    subs = _highlight.subscription_merchants()
    is_sub = _highlight.is_subscription(view["merchant"], subs)
    if is_sub.any():
        st.caption("🟡 Shaded rows are detected subscriptions.")

    display = view[
        ["date", "merchant", "name", "category", "amount", "account_name", "is_transfer"]
    ].copy()
    display["date"] = display["date"].dt.date
    display = display.rename(
        columns={
            "date": "Date",
            "merchant": "Merchant",
            "name": "Description",
            "category": "Category",
            "amount": "Amount",
            "account_name": "Account",
            "is_transfer": "Transfer",
        }
    )
    st.dataframe(
        _highlight.style_subscription_rows(display, is_sub),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Transfer": st.column_config.CheckboxColumn(),
        },
    )

    # --- Recategorize a transaction ---
    with st.expander("Re-categorize a transaction"):
        if view.empty:
            st.caption("Nothing to edit in the current filter.")
            return
        opts = {
            f"{r['date'].date()} · {r['merchant']} · ${r['amount']:.2f}": r["transaction_id"]
            for _, r in view.head(200).iterrows()
        }
        pick = st.selectbox("Transaction", list(opts.keys()))
        new_cat = st.selectbox("New category", CATEGORIES)
        if st.button("Save category"):
            db.set_category_override(opts[pick], new_cat)
            st.success(f"Updated to {new_cat}.")
            st.rerun()
