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

## Phase 7 — Daily Text Report + Raspberry Pi Deployment

Run the whole thing on a **Raspberry Pi Zero** (low-power, always-on) so it both
**hosts the dashboard 24/7** and **texts a spending summary every morning**.

### 7a. Daily report job (runs 7:00 AM)

- New script `scripts/daily_report.py` that, in order:
  1. `sync.run_sync()` — pull fresh transactions/balances (Plaid, or file import)
  2. compute three numbers via `utils.analytics` (spend = money out, excluding
     transfers/income):
     - **Yesterday** — single-day total
     - **This week so far** — Monday → today
     - **This month** — 1st → today
  3. format a short message and send it (see 7b)
- Message format:
  ```
  💸 Spending update
  Yesterday:  $42.10
  This week:  $318.67
  This month: $1,904.33
  ```
- Optional extras to fold in later: top category yesterday, any new subscription
  detected, balance/credit-utilization warnings.

### 7b. Sending the text — pick a channel

- **Email-to-SMS gateway (free, recommended to start):** send an email via SMTP
  (e.g. a Gmail account + app password) to your carrier's gateway address and it
  arrives as a normal SMS. Examples:
  - Verizon `number@vtext.com` · AT&T `number@txt.att.net` · T-Mobile
    `number@tmomail.net`
  - Pros: $0. Cons: carrier-dependent, can be flaky / occasionally deprecated.
- **Twilio (paid, most reliable):** ~$1/mo number + ~$0.0079/SMS. Use the Twilio
  REST API with account SID/auth token and a from-number.
- **Push alternatives (free, not true SMS):** Telegram bot, `ntfy.sh`, or
  Pushover — simplest to set up, deliver to your phone as a push notification.
- New `.env` settings: chosen channel + credentials + recipient
  (e.g. `SMS_TO`, `SMTP_USER`/`SMTP_PASS`, or `TWILIO_*`).

### 7c. Scheduling on the Pi

- `cron` entry on the Pi (Pi OS is Linux):
  ```
  0 7 * * *  cd /home/pi/finance_dashboard && .venv/bin/python -m scripts.daily_report >> logs/daily.log 2>&1
  ```

### 7d. Keep the dashboard running on the Pi

- Run Streamlit as a **systemd service** so it auto-starts on boot and restarts
  on crash; reach it on the LAN at `http://raspberrypi.local:8501`.
- Pi Zero notes:
  - Prefer a **Pi Zero 2 W** (quad-core) over the original Zero W — Streamlit +
    pandas are heavy for a single core / 512 MB RAM. The dataset is tiny, so it
    works, but the original Zero W will feel sluggish.
  - Headless setup (SSH); store `.env` and `finance.db` on the Pi; never commit them.
  - The daily report job itself is lightweight and runs fine even on a Zero W.

---

## Suggested Build Order

1. Phase 1 + 2 skeleton with mock data (see the UI before wiring real accounts)
2. Plaid integration for TD, Amex, Discover
3. Subscription detection
4. Claude chat sidebar with PII scrubbing
5. Polish and cron
6. Daily text report + deploy to the Raspberry Pi (Phase 7)