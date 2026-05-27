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

-- AI-export view: one clean, flat row per transaction joined to its account.
-- Safe to hand to an LLM — no identifiers or masks, normalized values:
--   * dropped: account_id, item_id, transaction_id, account mask
--   * single effective `category` (override > plaid > 'Other')
--   * `flow` = spend | income | transfer (so sign/transfer are unambiguous)
--   * text trimmed; merchant falls back to the description when missing
-- Rebuilt on every init so it always matches the latest schema.
DROP VIEW IF EXISTS ai_export;
CREATE VIEW ai_export AS
SELECT
    t.date                                              AS date,
    TRIM(COALESCE(NULLIF(TRIM(t.merchant), ''), t.name)) AS merchant,
    TRIM(t.name)                                        AS description,
    t.amount                                            AS amount,
    CASE
        WHEN t.is_transfer = 1 THEN 'transfer'
        WHEN t.amount < 0      THEN 'income'
        ELSE 'spend'
    END                                                 AS flow,
    COALESCE(t.category_override, t.category, t.plaid_category, 'Other') AS category,
    t.pending                                           AS pending,
    t.currency                                          AS currency,
    a.institution                                       AS account_institution,
    TRIM(a.name)                                        AS account_name,
    a.official_name                                     AS account_official_name,
    a.type                                              AS account_type,
    a.subtype                                           AS account_subtype,
    a.current_balance                                   AS account_balance,
    a.available_balance                                 AS account_available_balance,
    a.credit_limit                                      AS account_credit_limit,
    a.apr                                               AS account_apr,
    a.minimum_payment                                   AS account_minimum_payment,
    a.last_payment_amount                               AS account_last_payment_amount,
    a.last_payment_date                                 AS account_last_payment_date,
    a.last_statement_balance                            AS account_last_statement_balance,
    a.last_statement_issue_date                         AS account_last_statement_issue_date,
    a.next_payment_due_date                             AS account_next_payment_due_date,
    a.is_overdue                                        AS account_is_overdue,
    a.currency                                          AS account_currency,
    a.updated_at                                        AS account_updated_at
FROM transactions t
JOIN accounts a ON a.account_id = t.account_id
ORDER BY t.date DESC;

-- ---------------------------------------------------------------------------
-- Token-optimized views. Prefer these over ai_export for LLM context: the
-- aggregates answer most questions in a fraction of the tokens, and the split
-- accounts/transactions views avoid repeating account columns on every row.
-- ---------------------------------------------------------------------------

-- One row per account (no per-transaction repetition, no ids/mask).
DROP VIEW IF EXISTS ai_accounts;
CREATE VIEW ai_accounts AS
SELECT
    institution                AS account,
    TRIM(name)                 AS name,
    type                       AS type,
    subtype                    AS subtype,
    current_balance            AS balance,
    available_balance          AS available_balance,
    credit_limit               AS credit_limit,
    apr                        AS apr,
    minimum_payment            AS minimum_payment,
    last_payment_amount        AS last_payment_amount,
    last_payment_date          AS last_payment_date,
    last_statement_balance     AS last_statement_balance,
    last_statement_issue_date  AS last_statement_issue_date,
    next_payment_due_date      AS next_payment_due_date,
    is_overdue                 AS is_overdue,
    currency                   AS currency
FROM accounts;

-- Lean transaction rows: account shown as a short label, not 18 columns.
DROP VIEW IF EXISTS ai_transactions;
CREATE VIEW ai_transactions AS
SELECT
    t.date                                              AS date,
    TRIM(COALESCE(NULLIF(TRIM(t.merchant), ''), t.name)) AS merchant,
    t.amount                                            AS amount,
    CASE
        WHEN t.is_transfer = 1 THEN 'transfer'
        WHEN t.amount < 0      THEN 'income'
        ELSE 'spend'
    END                                                 AS flow,
    COALESCE(t.category_override, t.category, t.plaid_category, 'Other') AS category,
    a.institution || ' ' || COALESCE(a.subtype, a.type) AS account
FROM transactions t
JOIN accounts a ON a.account_id = t.account_id
ORDER BY t.date DESC;

-- Per-month income / spend / net (collapses 382 rows into a handful).
DROP VIEW IF EXISTS ai_monthly_summary;
CREATE VIEW ai_monthly_summary AS
SELECT
    strftime('%Y-%m', date) AS month,
    ROUND(SUM(CASE WHEN is_transfer = 0 AND amount < 0 THEN -amount ELSE 0 END), 2) AS income,
    ROUND(SUM(CASE WHEN is_transfer = 0 AND amount > 0
                   AND COALESCE(category_override, category, plaid_category, 'Other') != 'Income'
              THEN amount ELSE 0 END), 2) AS spend,
    COUNT(*) AS txn_count
FROM transactions
GROUP BY month
ORDER BY month DESC;

-- Spend by month x category — the highest-value summary for an LLM.
DROP VIEW IF EXISTS ai_category_monthly;
CREATE VIEW ai_category_monthly AS
SELECT
    strftime('%Y-%m', date) AS month,
    COALESCE(category_override, category, plaid_category, 'Other') AS category,
    ROUND(SUM(amount), 2) AS spend,
    COUNT(*)              AS txn_count
FROM transactions
WHERE is_transfer = 0
  AND amount > 0
  AND COALESCE(category_override, category, plaid_category, 'Other') != 'Income'
GROUP BY month, category
ORDER BY month DESC, spend DESC;

-- Clean subscription list (detected + manual), no internal columns.
DROP VIEW IF EXISTS ai_subscriptions;
CREATE VIEW ai_subscriptions AS
SELECT
    merchant,
    avg_amount,
    cadence_days,
    status,
    last_charge,
    category
FROM subscriptions
ORDER BY avg_amount DESC;
"""
