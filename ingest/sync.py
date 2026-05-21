"""Sync orchestration: pull data -> write to DB -> recompute subscriptions.

This is the single entry point the UI's "Refresh" button and any cron job call.
It works today with mock data and is wired so that, once Plaid access tokens
exist in the DB, real syncing kicks in automatically.
"""

from __future__ import annotations

from dataclasses import dataclass

from db import database as db
from ingest import mock_data, subscriptions
from ingest.categorize import is_transfer
from utils.config import settings


@dataclass
class SyncResult:
    source: str            # "mock" | "plaid"
    accounts: int
    transactions: int
    subscriptions: int
    message: str = ""


def _retag_and_detect() -> int:
    """Recompute subscriptions from everything currently in the DB."""
    rows = [dict(r) for r in db.get_transactions()]
    subs = subscriptions.detect(rows)
    db.replace_subscriptions(subs)
    return len(subs)


def sync_mock() -> SyncResult:
    """Seed/refresh the DB from the deterministic mock generator."""
    db.init_db()
    accounts, txns = mock_data.generate()
    db.upsert_accounts(accounts)
    n = db.upsert_transactions(txns)
    n_subs = _retag_and_detect()
    return SyncResult("mock", len(accounts), n, n_subs, "Loaded mock data.")


def sync_plaid() -> SyncResult:
    """Pull real data for every stored Plaid item, then detect subscriptions."""
    # Imported lazily so the app runs without plaid-python installed/configured.
    from ingest import plaid_client

    db.init_db()
    tokens = db.get_access_tokens()
    if not tokens:
        return SyncResult("plaid", 0, 0, 0, "No linked Plaid items yet.")

    total_accounts = 0
    total_txns = 0
    for tok in tokens:
        accounts, txns, cursor = plaid_client.sync_item(
            access_token=tok["access_token"],
            cursor=tok["cursor"],
        )
        # Apply transfer tagging consistently with mock data.
        for t in txns:
            t["is_transfer"] = int(
                is_transfer(t.get("name"), t.get("merchant"), t.get("plaid_category"))
            )
        db.upsert_accounts(accounts)
        total_txns += db.upsert_transactions(txns)
        total_accounts += len(accounts)
        if cursor:
            db.update_cursor(tok["item_id"], cursor)

        # Enrich credit cards with Liabilities detail (APR, due date, etc.).
        # No-op for items/institutions that don't support the product.
        for account_id, fields in plaid_client.fetch_liabilities(
            tok["access_token"]
        ).items():
            db.update_account_liabilities(account_id, fields)

    n_subs = _retag_and_detect()
    return SyncResult(
        "plaid", total_accounts, total_txns, n_subs, "Synced linked accounts."
    )


def run_sync() -> SyncResult:
    """Pick the right source: real Plaid if linked, else mock (if enabled).

    With USE_MOCK_DATA=0 and nothing linked yet, this is a no-op rather than
    silently re-seeding mock data — so a Refresh before linking doesn't bounce
    you back to fake data.
    """
    db.init_db()
    has_tokens = bool(db.get_access_tokens())
    if settings.has_plaid and has_tokens:
        return sync_plaid()
    if settings.use_mock_data:
        return sync_mock()
    return SyncResult(
        "none", 0, 0, 0,
        "No bank linked yet — use the Link tab to connect a bank.",
    )


def ensure_seeded() -> None:
    """On first run, populate the DB so the UI is never empty."""
    db.init_db()
    if db.is_empty():
        if settings.has_plaid and db.get_access_tokens():
            sync_plaid()
        elif settings.use_mock_data:
            sync_mock()
