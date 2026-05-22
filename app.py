"""Personal Finance Dashboard — Streamlit entry point.

Run with:  streamlit run app.py   ->  http://localhost:8501

Aggregates spending across TD Bank, Amex (card + personal loan), and Discover,
detects subscriptions, and exposes an anonymized Claude chat sidebar.
"""

from __future__ import annotations

import streamlit as st

from db import database as db
from ingest import sync
from ui import account_detail, accounts, breakdown, cards, chat_sidebar, link, loan, overview
from ui import subscriptions as subs_view
from utils.config import settings

st.set_page_config(
    page_title="Finance Dashboard",
    page_icon="💸",
    layout="wide",
    initial_sidebar_state="expanded",
)


@st.cache_resource
def _bootstrap() -> None:
    """Initialize the DB and seed mock data once per server process."""
    db.init_db()
    sync.ensure_seeded()


def _sidebar_controls() -> None:
    st.sidebar.title("💸 Finance Dashboard")

    # Data source status.
    if settings.has_plaid and db.get_access_tokens():
        st.sidebar.success("Source: Plaid (live)")
    elif settings.use_mock_data:
        st.sidebar.info("Source: mock data")
    else:
        st.sidebar.warning("No data source configured")

    if st.sidebar.button("🔄 Refresh data", use_container_width=True):
        with st.spinner("Syncing..."):
            result = sync.run_sync()
        st.sidebar.success(
            f"{result.message} {result.transactions} txns, "
            f"{result.subscriptions} subs."
        )
        st.rerun()


def main() -> None:
    _bootstrap()
    _sidebar_controls()

    tabs = st.tabs(
        ["Overview", "Breakdown", "All Transactions", "Accounts",
         "Subscriptions", "Cards", "Loan", "Link"]
    )
    with tabs[0]:
        overview.render()
    with tabs[1]:
        breakdown.render()
    with tabs[2]:
        accounts.render()          # All Transactions (filterable, all sources)
    with tabs[3]:
        account_detail.render()    # Accounts (per-source, open statement)
    with tabs[4]:
        subs_view.render()
    with tabs[5]:
        cards.render()
    with tabs[6]:
        loan.render()
    with tabs[7]:
        link.render()

    # Claude chat lives in the sidebar, per the plan.
    chat_sidebar.render()


if __name__ == "__main__":
    main()
