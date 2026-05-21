# Personal Finance Dashboard — Build Plan

A local-hosted Streamlit dashboard that aggregates spending across TD Bank, Amex (card + personal loan), and Discover, detects subscriptions, and exposes an anonymized Claude chat sidebar for analysis.

---

## Key Constraints to Know Upfront

- **Plaid covers all accounts** (TD Bank, Amex card, Amex personal loan, Discover) — free in dev mode for up to 100 items, fine for personal use. Verify Amex personal loan appears as a Plaid item; if not, fall back to manual balance entry for the loan.
- **"Anonymous" Claude session** means you locally strip PII (account numbers, your name, merchant addresses, exact balances if you want) before sending context to the Anthropic API. The API itself doesn't train on your data, but PII stripping is still good hygiene.

---

## Phase 1 — Architecture & Setup (Day 1)

- **Stack:** Python, Streamlit, SQLite (local file DB), Plaid Python SDK, Anthropic Python SDK
- **Project structure:** `/ingest`, `/db`, `/ui`, `/chat`, `/utils`
- **Secrets:** stored in `.env` (Plaid client ID/secret, Anthropic key) — never commit
- **Schema:** one `transactions` table, one `accounts` table, one `subscriptions` table

## Phase 2 — Data Ingestion

- Plaid Link flow for TD, Amex card, Amex loan, Discover — a one-time Streamlit page to authorize each, store the access token locally
- Nightly (or on-demand) sync pulls transactions into SQLite
- Tag transfers (mortgage, insurance) with rules based on merchant/memo so they don't pollute "spending"

## Phase 3 — Dashboard Views

- **Top:** net cash flow this month, total spend, balances per account
- **Breakdown:** spending by category (Plaid auto-categorizes; user can override), bar chart by category, line chart by week
- **Account drill-down:** transactions table, filterable
- **Loan tracker:** Amex personal loan balance + payoff projection

## Phase 4 — Subscription Detection

- **Algorithm:** group by merchant, flag any merchant with 2+ charges within ±3 days of a monthly cadence at similar amounts
- **Auto-updating status:** recomputed each sync. If a merchant stops appearing for 35+ days, mark "canceled"
- **Display:** active subs, total monthly cost, last charge date, "likely canceled" section

## Phase 5 — Claude Chat Sidebar

- Streamlit sidebar with chat input, uses Anthropic API (`claude-sonnet-4-6` or `claude-opus-4-7`)
- Before each call: build a context string from the DB (spending totals, categories, sub list, anonymized transactions) and run it through a PII scrubber — regex for account numbers, your name from a config, addresses; replace merchants with category-only if you want extra paranoia
- **System prompt:** "You are a financial analyst with read-only access to the user's monthly summary. Help analyze spending, suggest cuts, answer questions."
- Toggle for "include transaction-level detail" vs "summary only"

## Phase 6 — Run Locally

- `streamlit run app.py` → localhost:8501
- Optional: schedule the sync with a cron job or a "Refresh" button in the UI

---

## Suggested Build Order

1. Phase 1 + 2 skeleton with mock data (see the UI before wiring real accounts)
2. Plaid integration for TD, Amex, Discover
3. Subscription detection
4. Claude chat sidebar with PII scrubbing
5. Polish and cron