"""SQLite connection management and CRUD helpers.

Every public function opens a short-lived connection via ``get_connection`` so
the module is safe to call from Streamlit's re-running script model. Rows come
back as ``sqlite3.Row`` (dict-like) for ergonomic access.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator

from db.schema import SCHEMA_SQL
from utils.config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yield a connection with foreign keys on and Row factory set."""
    conn = sqlite3.connect(settings.db_file)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after the first schema version; ensured on every init for
# databases created before they existed.
_ACCOUNT_MIGRATIONS = {
    "apr": "REAL",
    "minimum_payment": "REAL",
    "last_payment_amount": "REAL",
    "last_payment_date": "TEXT",
    "last_statement_balance": "REAL",
    "last_statement_issue_date": "TEXT",
    "next_payment_due_date": "TEXT",
    "is_overdue": "INTEGER",
}


def init_db() -> None:
    """Create tables if they don't exist, then apply column migrations.

    Safe to call repeatedly.
    """
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(accounts)")}
        for col, col_type in _ACCOUNT_MIGRATIONS.items():
            if col not in existing:
                conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} {col_type}")


def is_empty() -> bool:
    """True if there are no transactions yet (used to decide on mock seeding)."""
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM transactions").fetchone()
        return row["n"] == 0


def reset_data(*, keep_tokens: bool = True) -> None:
    """Wipe financial data (e.g. to clear mock data before going live).

    Keeps linked Plaid access tokens by default so you don't have to re-link.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM accounts")
        conn.execute("DELETE FROM subscriptions")
        if not keep_tokens:
            conn.execute("DELETE FROM access_tokens")


# --------------------------------------------------------------------------- #
# Accounts
# --------------------------------------------------------------------------- #
def upsert_accounts(accounts: Iterable[dict[str, Any]]) -> None:
    sql = """
        INSERT INTO accounts (
            account_id, item_id, institution, name, official_name, mask,
            type, subtype, current_balance, available_balance, credit_limit,
            currency, updated_at
        ) VALUES (
            :account_id, :item_id, :institution, :name, :official_name, :mask,
            :type, :subtype, :current_balance, :available_balance, :credit_limit,
            :currency, :updated_at
        )
        ON CONFLICT(account_id) DO UPDATE SET
            institution=excluded.institution,
            name=excluded.name,
            official_name=excluded.official_name,
            mask=excluded.mask,
            type=excluded.type,
            subtype=excluded.subtype,
            current_balance=excluded.current_balance,
            available_balance=excluded.available_balance,
            credit_limit=excluded.credit_limit,
            currency=excluded.currency,
            updated_at=excluded.updated_at;
    """
    rows = []
    for a in accounts:
        row = {
            "account_id": a["account_id"],
            "item_id": a.get("item_id"),
            "institution": a["institution"],
            "name": a["name"],
            "official_name": a.get("official_name"),
            "mask": a.get("mask"),
            "type": a.get("type"),
            "subtype": a.get("subtype"),
            "current_balance": a.get("current_balance"),
            "available_balance": a.get("available_balance"),
            "credit_limit": a.get("credit_limit"),
            "currency": a.get("currency", "USD"),
            "updated_at": a.get("updated_at") or _now_iso(),
        }
        rows.append(row)
    with get_connection() as conn:
        conn.executemany(sql, rows)


def get_accounts() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM accounts ORDER BY institution, name"
        ).fetchall()


def update_account_liabilities(account_id: str, fields: dict[str, Any]) -> None:
    """Update the liability columns for one account (only the keys provided)."""
    allowed = set(_ACCOUNT_MIGRATIONS)
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    sets = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "id": account_id}
    with get_connection() as conn:
        conn.execute(
            f"UPDATE accounts SET {sets} WHERE account_id = :id", params
        )


# --------------------------------------------------------------------------- #
# Transactions
# --------------------------------------------------------------------------- #
def upsert_transactions(txns: Iterable[dict[str, Any]]) -> int:
    """Insert/update transactions. Returns number of rows written.

    Preserves any existing user category override on conflict.
    """
    sql = """
        INSERT INTO transactions (
            transaction_id, account_id, date, amount, merchant, name,
            category, plaid_category, category_override, pending, is_transfer,
            currency
        ) VALUES (
            :transaction_id, :account_id, :date, :amount, :merchant, :name,
            :category, :plaid_category, :category_override, :pending, :is_transfer,
            :currency
        )
        ON CONFLICT(transaction_id) DO UPDATE SET
            account_id=excluded.account_id,
            date=excluded.date,
            amount=excluded.amount,
            merchant=excluded.merchant,
            name=excluded.name,
            plaid_category=excluded.plaid_category,
            pending=excluded.pending,
            is_transfer=excluded.is_transfer,
            currency=excluded.currency,
            -- keep the user override if set; otherwise refresh effective category
            category=COALESCE(transactions.category_override, excluded.category);
    """
    rows = []
    for t in txns:
        override = t.get("category_override")
        rows.append(
            {
                "transaction_id": t["transaction_id"],
                "account_id": t["account_id"],
                "date": t["date"],
                "amount": t["amount"],
                "merchant": t.get("merchant"),
                "name": t.get("name"),
                "category": override or t.get("category"),
                "plaid_category": t.get("plaid_category") or t.get("category"),
                "category_override": override,
                "pending": int(t.get("pending", 0)),
                "is_transfer": int(t.get("is_transfer", 0)),
                "currency": t.get("currency", "USD"),
            }
        )
    with get_connection() as conn:
        conn.executemany(sql, rows)
        return len(rows)


def get_transactions(
    *,
    start: str | None = None,
    end: str | None = None,
    account_id: str | None = None,
    include_transfers: bool = True,
) -> list[sqlite3.Row]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if start:
        clauses.append("date >= :start")
        params["start"] = start
    if end:
        clauses.append("date <= :end")
        params["end"] = end
    if account_id:
        clauses.append("account_id = :account_id")
        params["account_id"] = account_id
    if not include_transfers:
        clauses.append("is_transfer = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT t.*, a.institution, a.name AS account_name, a.mask
        FROM transactions t
        JOIN accounts a ON a.account_id = t.account_id
        {where}
        ORDER BY t.date DESC, t.transaction_id
    """
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


def set_category_override(transaction_id: str, category: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE transactions
            SET category_override = :cat, category = :cat
            WHERE transaction_id = :id
            """,
            {"cat": category, "id": transaction_id},
        )


def distinct_categories() -> list[str]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT category FROM transactions "
            "WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #
def replace_subscriptions(subs: Iterable[dict[str, Any]]) -> None:
    """Subscriptions are fully recomputed each sync, so we wipe and reinsert."""
    sql = """
        INSERT INTO subscriptions (
            merchant, avg_amount, cadence_days, charge_count,
            first_charge, last_charge, status, category, detected_at
        ) VALUES (
            :merchant, :avg_amount, :cadence_days, :charge_count,
            :first_charge, :last_charge, :status, :category, :detected_at
        )
    """
    now = _now_iso()
    rows = [{**s, "detected_at": now} for s in subs]
    with get_connection() as conn:
        conn.execute("DELETE FROM subscriptions")
        if rows:
            conn.executemany(sql, rows)


def get_subscriptions(status: str | None = None) -> list[sqlite3.Row]:
    sql = "SELECT * FROM subscriptions"
    params: dict[str, Any] = {}
    if status:
        sql += " WHERE status = :status"
        params["status"] = status
    sql += " ORDER BY avg_amount DESC"
    with get_connection() as conn:
        return conn.execute(sql, params).fetchall()


# --------------------------------------------------------------------------- #
# Access tokens (Plaid plumbing)
# --------------------------------------------------------------------------- #
def save_access_token(
    item_id: str, access_token: str, institution: str | None = None
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO access_tokens (item_id, access_token, institution, created_at)
            VALUES (:item_id, :token, :inst, :created)
            ON CONFLICT(item_id) DO UPDATE SET
                access_token=excluded.access_token,
                institution=excluded.institution
            """,
            {
                "item_id": item_id,
                "token": access_token,
                "inst": institution,
                "created": _now_iso(),
            },
        )


def get_access_tokens() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM access_tokens").fetchall()


def update_cursor(item_id: str, cursor: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE access_tokens SET cursor = :c WHERE item_id = :id",
            {"c": cursor, "id": item_id},
        )
