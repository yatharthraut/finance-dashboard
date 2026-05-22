"""SQLite schema definition.

Three tables, matching the plan:
  * accounts        — one row per Plaid account (or mock account)
  * transactions    — one row per transaction
  * subscriptions   — recomputed each sync by the detection algorithm

The ``access_token`` table is internal plumbing: it stores the per-item Plaid
access tokens so syncs can run without re-doing Link. It never holds money data.
"""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id      TEXT PRIMARY KEY,   -- Plaid account_id (or mock id)
    item_id         TEXT,               -- Plaid item this account belongs to
    institution     TEXT NOT NULL,      -- "TD Bank", "Amex", "Discover"
    name            TEXT NOT NULL,      -- account display name
    official_name   TEXT,
    mask            TEXT,               -- last 4 digits
    type            TEXT,               -- depository | credit | loan
    subtype         TEXT,               -- checking | credit card | personal loan ...
    current_balance REAL,
    available_balance REAL,
    credit_limit    REAL,               -- for credit accounts
    currency        TEXT DEFAULT 'USD',
    updated_at      TEXT,               -- ISO timestamp of last balance refresh
    -- Liabilities detail (credit cards), populated when the Liabilities
    -- product is available for the item. NULL otherwise.
    apr             REAL,               -- representative (purchase) APR %
    minimum_payment REAL,
    last_payment_amount REAL,
    last_payment_date TEXT,
    last_statement_balance REAL,
    last_statement_issue_date TEXT,
    next_payment_due_date TEXT,
    is_overdue      INTEGER
);

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  TEXT PRIMARY KEY,   -- Plaid transaction_id (or mock id)
    account_id      TEXT NOT NULL,
    date            TEXT NOT NULL,       -- ISO date (YYYY-MM-DD)
    amount          REAL NOT NULL,       -- Plaid convention: positive = money out
    merchant        TEXT,                -- normalized merchant name
    name            TEXT,                -- raw transaction description
    category        TEXT,                -- effective category (override or Plaid)
    plaid_category  TEXT,                -- original Plaid category (audit trail)
    category_override TEXT,              -- user-set category, if any
    pending         INTEGER DEFAULT 0,
    is_transfer     INTEGER DEFAULT 0,   -- tagged out of "spending" (mortgage etc.)
    currency        TEXT DEFAULT 'USD',
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_txn_merchant ON transactions(merchant);

CREATE TABLE IF NOT EXISTS subscriptions (
    merchant        TEXT PRIMARY KEY,    -- one detected subscription per merchant
    avg_amount      REAL NOT NULL,
    cadence_days    INTEGER,             -- detected interval (~30 for monthly)
    charge_count    INTEGER NOT NULL,
    first_charge    TEXT,
    last_charge     TEXT,
    status          TEXT NOT NULL,       -- 'active' | 'likely_canceled'
    category        TEXT,
    detected_at     TEXT
);

-- Manual user changes layered on top of auto-detection, re-applied each sync:
--   action 'add'     -> force this merchant to be a subscription
--   action 'exclude' -> never treat this merchant as a subscription
CREATE TABLE IF NOT EXISTS subscription_overrides (
    merchant     TEXT PRIMARY KEY,    -- matched case-insensitively
    action       TEXT NOT NULL,       -- 'add' | 'exclude'
    avg_amount   REAL,                -- optional, for manual adds
    cadence_days INTEGER,             -- optional, for manual adds
    category     TEXT,                -- optional, for manual adds
    created_at   TEXT
);

CREATE TABLE IF NOT EXISTS access_tokens (
    item_id         TEXT PRIMARY KEY,
    access_token    TEXT NOT NULL,
    institution     TEXT,
    cursor          TEXT,                -- Plaid transactions/sync cursor
    created_at      TEXT
);
"""
