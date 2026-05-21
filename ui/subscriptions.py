"""Subscriptions view: active subs, monthly cost, likely-canceled section."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db import database as db
from ingest import subscriptions as subs_mod


def _to_df(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])


def render() -> None:
    st.subheader("Subscriptions")

    active = [dict(r) for r in db.get_subscriptions(status="active")]
    canceled = [dict(r) for r in db.get_subscriptions(status="likely_canceled")]

    if not active and not canceled:
        st.info(
            "No subscriptions detected yet. Use the sidebar **Refresh** to "
            "ingest data and run detection."
        )
        return

    monthly = subs_mod.monthly_total(active)
    c1, c2 = st.columns(2)
    c1.metric("Active subscriptions", len(active))
    c2.metric("Est. monthly cost", f"${monthly:,.2f}", help="Normalized to 30 days")
    st.caption(f"That's about **${monthly * 12:,.0f}/year**.")

    st.divider()
    st.markdown("### Active")
    if active:
        df = _to_df(active)[
            ["merchant", "avg_amount", "cadence_days", "last_charge", "category", "charge_count"]
        ].rename(
            columns={
                "merchant": "Merchant",
                "avg_amount": "Amount",
                "cadence_days": "Every (days)",
                "last_charge": "Last charge",
                "category": "Category",
                "charge_count": "Charges seen",
            }
        )
        st.dataframe(
            df,
            hide_index=True,
            use_container_width=True,
            column_config={"Amount": st.column_config.NumberColumn(format="$%.2f")},
        )
    else:
        st.caption("No active subscriptions.")

    st.divider()
    st.markdown("### Likely canceled")
    st.caption("Merchants that stopped charging for 35+ days.")
    if canceled:
        df = _to_df(canceled)[
            ["merchant", "avg_amount", "last_charge", "category"]
        ].rename(
            columns={
                "merchant": "Merchant",
                "avg_amount": "Was",
                "last_charge": "Last seen",
                "category": "Category",
            }
        )
        st.dataframe(
            df,
            hide_index=True,
            use_container_width=True,
            column_config={"Was": st.column_config.NumberColumn(format="$%.2f")},
        )
    else:
        st.caption("None — every detected subscription is still active.")
