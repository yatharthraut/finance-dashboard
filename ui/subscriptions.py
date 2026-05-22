"""Subscriptions view: active subs, monthly cost, likely-canceled, and manual edits."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db import database as db
from ingest import subscriptions as subs_mod, sync
from ingest.categorize import CATEGORIES


def _to_df(rows) -> pd.DataFrame:
    return pd.DataFrame([dict(r) for r in rows])


def render() -> None:
    st.subheader("Subscriptions")

    active = [dict(r) for r in db.get_subscriptions(status="active")]
    canceled = [dict(r) for r in db.get_subscriptions(status="likely_canceled")]

    if not active and not canceled:
        st.info(
            "No subscriptions detected yet. Use the sidebar **Refresh** to ingest "
            "data — or add one manually below."
        )
    else:
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
        st.caption("Merchants that stopped charging past their expected cadence.")
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

    st.divider()
    _manage(active + canceled)


def _manage(current: list[dict]) -> None:
    st.markdown("### ✏️ Manage subscriptions")
    st.caption(
        "Manual changes are saved and re-applied on every sync, so they survive "
        "re-detection."
    )

    # --- Add manually (e.g. recurring TD Bank transfers) ---
    with st.expander("➕ Add a subscription manually"):
        merchants = db.distinct_merchants()
        if not merchants:
            st.caption("No transactions yet to pick a merchant from.")
        else:
            with st.form("add_sub", clear_on_submit=True):
                merchant = st.selectbox(
                    "Merchant",
                    merchants,
                    help="Pick the merchant of the recurring charge/transfer.",
                )
                col1, col2 = st.columns(2)
                amount = col1.number_input(
                    "Amount (0 = auto from transactions)", min_value=0.0, step=1.0, value=0.0
                )
                cadence = col2.number_input(
                    "Every (days)", min_value=1, value=30, step=1
                )
                default_cat = CATEGORIES.index("Subscriptions") if "Subscriptions" in CATEGORIES else 0
                category = st.selectbox("Category", CATEGORIES, index=default_cat)
                if st.form_submit_button("Add subscription"):
                    db.add_subscription_override(
                        merchant,
                        "add",
                        avg_amount=amount or None,
                        cadence_days=int(cadence),
                        category=category,
                    )
                    sync.recompute_subscriptions()
                    st.success(f"Added **{merchant}** as a subscription.")
                    st.rerun()

    # --- Remove (exclude) detected/added subscriptions ---
    with st.expander("➖ Remove a subscription"):
        names = sorted({s["merchant"] for s in current})
        if not names:
            st.caption("Nothing to remove.")
        else:
            to_remove = st.multiselect(
                "Select subscriptions to remove (e.g. false positives)", names
            )
            if st.button("Remove selected", disabled=not to_remove):
                for m in to_remove:
                    db.add_subscription_override(m, "exclude")
                sync.recompute_subscriptions()
                st.success(f"Removed {len(to_remove)} subscription(s).")
                st.rerun()

    # --- Review / undo manual changes ---
    overrides = [dict(o) for o in db.get_subscription_overrides()]
    if overrides:
        with st.expander(f"🛠 Manual changes ({len(overrides)})"):
            for o in overrides:
                verb = "Added" if o["action"] == "add" else "Excluded"
                cols = st.columns([4, 1])
                cols[0].write(f"**{verb}:** {o['merchant']}")
                if cols[1].button("Undo", key=f"undo_{o['merchant']}"):
                    db.remove_subscription_override(o["merchant"])
                    sync.recompute_subscriptions()
                    st.rerun()
