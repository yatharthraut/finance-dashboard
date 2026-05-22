"""Accounts tab: per-source drill-down, defaulting to the current open statement.

Pick a connected account (source) from the dropdown to see only its
transactions. By default we show the **current open statement** — everything
since the account's last statement was issued (from Plaid Liabilities). Accounts
without statement data (e.g. checking/savings) fall back to month-to-date.
"""

from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from ui import _highlight
from utils import analytics


def _valid(v) -> bool:
    return v not in (None, "") and not (isinstance(v, float) and pd.isna(v))


def _open_statement_start(acct) -> pd.Timestamp | None:
    """Last statement issue date as a Timestamp, or None if unavailable."""
    raw = acct.get("last_statement_issue_date")
    if not _valid(raw):
        return None
    try:
        ts = pd.to_datetime(raw)
    except (ValueError, TypeError):
        return None
    return None if pd.isna(ts) else ts


def _selected_categories(state) -> list[str]:
    """Extract clicked categories from an Altair chart selection state."""
    if not state:
        return []
    selection = state.get("selection") if isinstance(state, dict) else None
    pts = selection.get("pick") if isinstance(selection, dict) else None
    if not pts:
        return []
    cats: list[str] = []
    if isinstance(pts, list):
        cats = [p["category"] for p in pts if isinstance(p, dict) and p.get("category")]
    elif isinstance(pts, dict):  # field -> list of values shape
        v = pts.get("category", [])
        cats = v if isinstance(v, list) else [v]
    return cats


def render() -> None:
    st.subheader("Accounts")

    accounts = analytics.accounts_df()
    if accounts.empty:
        st.info("No accounts yet. Use the sidebar **Refresh** to load data.")
        return

    # Loans live in the Loan tab — keep them out of this source list.
    accounts = accounts[accounts["type"] != "loan"]
    if accounts.empty:
        st.info("No non-loan accounts to show. Loans are in the **Loan** tab.")
        return

    # Source dropdown — one entry per connected account.
    labels: dict[str, str] = {}
    for _, a in accounts.iterrows():
        mask = a["mask"] if isinstance(a["mask"], str) and a["mask"] else "----"
        labels[f"{a['institution']} · {a['name']} ····{mask}"] = a["account_id"]
    choice = st.selectbox("Source", list(labels.keys()))
    account_id = labels[choice]
    acct = accounts[accounts["account_id"] == account_id].iloc[0]

    # Determine the current open-statement window.
    stmt_start = _open_statement_start(acct)
    if stmt_start is not None:
        stmt_label = f"Current open statement (since {stmt_start.date()})"
        caption = f"Last statement issued **{stmt_start.date()}**"
        due = acct.get("next_payment_due_date")
        if _valid(due):
            caption += f" · payment due **{due}**"
    else:
        # No statement metadata (depository / non-liabilities) -> month-to-date.
        mstart, _ = analytics.month_bounds()
        stmt_start = pd.to_datetime(mstart)
        stmt_label = f"Current open statement (month to date, since {stmt_start.date()})"
        caption = "No statement date from the bank — showing this month so far."

    mode = st.radio("Show", [stmt_label, "All transactions"], horizontal=True)
    st.caption(caption)

    # Load this account's transactions, then apply the statement filter.
    df = analytics.transactions_df()
    if not df.empty:
        df = df[df["account_id"] == account_id]
    if mode != "All transactions" and not df.empty:
        df = df[df["date"] > stmt_start]  # open statement = after the last close

    # Account header.
    bal = acct["current_balance"]
    charges = float(df.loc[df["amount"] > 0, "amount"].sum()) if not df.empty else 0.0
    credits = float(-df.loc[df["amount"] < 0, "amount"].sum()) if not df.empty else 0.0
    m = st.columns(3)
    m[0].metric("Current balance", f"${bal:,.2f}" if pd.notna(bal) else "—")
    m[1].metric("Charges (shown)", f"${charges:,.2f}")
    m[2].metric("Payments / credits (shown)", f"${credits:,.2f}")

    if df.empty:
        st.info("No transactions in this period.")
        return

    # Category filter driven by clicking the pie below. Read the selection from
    # the chart's session_state key *before* rendering the table (the chart is
    # drawn after the table, but its state persists across the rerun a click
    # triggers).
    chart_key = f"cat_pie_{account_id}"
    selected_cats = _selected_categories(st.session_state.get(chart_key))

    # Transactions table.
    hide_payments = st.checkbox("Hide payments", value=False)
    table_df = df[~df["is_transfer"]] if hide_payments else df
    if selected_cats:
        table_df = table_df[table_df["category"].isin(selected_cats)]

    head = st.columns([4, 1])
    with head[0]:
        if selected_cats:
            st.caption(
                f"Filtered to **{', '.join(selected_cats)}** · "
                f"{len(table_df):,} transactions"
            )
        else:
            st.caption(f"{len(table_df):,} transactions")
    with head[1]:
        if selected_cats and st.button("Clear filter", use_container_width=True):
            st.session_state.pop(chart_key, None)
            st.rerun()

    sorted_df = table_df.sort_values("date", ascending=False)
    subs = _highlight.subscription_merchants()
    is_sub = _highlight.is_subscription(sorted_df["merchant"], subs)
    if is_sub.any():
        st.caption("🟡 Shaded rows are detected subscriptions.")

    display = sorted_df[
        ["date", "merchant", "name", "category", "amount", "is_transfer"]
    ].copy()
    display["date"] = display["date"].dt.date
    display = display.rename(
        columns={
            "date": "Date",
            "merchant": "Merchant",
            "name": "Description",
            "category": "Category",
            "amount": "Amount",
            "is_transfer": "Payment",
        }
    )
    st.dataframe(
        _highlight.style_subscription_rows(display, is_sub),
        hide_index=True,
        use_container_width=True,
        column_config={
            "Amount": st.column_config.NumberColumn(format="$%.2f"),
            "Payment": st.column_config.CheckboxColumn(),
        },
    )

    # Spending by category (pie) — click a slice to filter the table above.
    # Spend excludes payments/transfers and income, so it reflects real outgoing
    # spend regardless of the toggle above.
    st.divider()
    st.markdown("**Spending by category** — click a slice to filter the table above")
    cat = analytics.spend_by_category(df)
    if cat.empty:
        st.caption("No category spending in this period.")
    else:
        pick = alt.selection_point(fields=["category"], name="pick")
        pie = (
            alt.Chart(cat)
            .mark_arc()
            .encode(
                theta=alt.Theta("amount:Q", stack=True),
                color=alt.Color("category:N", title="Category"),
                opacity=alt.condition(pick, alt.value(1.0), alt.value(0.35)),
                tooltip=[
                    alt.Tooltip("category:N", title="Category"),
                    alt.Tooltip("amount:Q", title="Spent", format="$,.2f"),
                ],
            )
            .add_params(pick)
        )

        total = float(cat["amount"].sum())
        pct = cat.assign(pct=(cat["amount"] / total * 100).round(1)).rename(
            columns={"category": "Category", "amount": "Spent", "pct": "%"}
        )

        col_pie, col_pct = st.columns([3, 2])
        with col_pie:
            st.altair_chart(
                pie, use_container_width=True, on_select="rerun", key=chart_key
            )
        with col_pct:
            st.dataframe(
                pct[["Category", "%", "Spent"]],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "%": st.column_config.NumberColumn(format="%.1f%%"),
                    "Spent": st.column_config.NumberColumn(format="$%.2f"),
                },
            )
