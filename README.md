# Personal Finance Dashboard

A local-hosted Streamlit dashboard that aggregates spending across **TD Bank**,
**Amex** (card + personal loan), and **Discover**, detects subscriptions, and
exposes an **anonymized Claude chat sidebar** for analysis.

Everything runs locally against a SQLite file. It works out-of-the-box on
realistic **mock data** — no Plaid or Anthropic keys required to explore the UI.

---

## Quick start

```powershell
# 1. (recommended) create a virtual env
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. install dependencies
pip install -r requirements.txt

# 3. (optional) configure secrets — skip to run on mock data
copy .env.example .env   # then edit .env

# 4. run
streamlit run app.py     # -> http://localhost:8501
```

On first launch the app seeds ~6 months of mock transactions so every view,
the subscription detector, and the loan tracker have something to show.

---

## Configuration (`.env`)

| Variable            | Purpose                                                        |
|---------------------|----------------------------------------------------------------|
| `PLAID_CLIENT_ID`   | Plaid app client id (leave blank to stay on mock data)         |
| `PLAID_SECRET`      | Plaid secret for the chosen environment                        |
| `PLAID_ENV`         | `sandbox` \| `development` \| `production`                      |
| `ANTHROPIC_API_KEY` | Enables the Claude chat sidebar                                 |
| `ANTHROPIC_MODEL`   | `claude-sonnet-4-6` (default) or `claude-opus-4-7`             |
| `USER_NAME`         | Comma-separated names the PII scrubber redacts                  |
| `DB_PATH`           | SQLite file path (default `finance.db`)                        |
| `USE_MOCK_DATA`     | `1` to seed mock data when no Plaid items are linked            |

Secrets live only in `.env`, which is git-ignored. Never commit it.

---

## Wiring real accounts (Plaid)

### Sandbox (test, free, no approval)

1. Set `PLAID_ENV=sandbox` and your **Sandbox** secret in `.env`, restart.
2. **Link** tab → *🧪 Sandbox: add a test bank* → **Link test bank** (one click,
   no widget). Then *Clear local financial data* and **🔄 Refresh**.

### Production (your real TD / Amex / Discover)

1. In the Plaid dashboard, you start on the **Trial plan** (free, real data, up
   to 10 connected Items, most institutions incl. OAuth banks). No approval or
   billing needed to begin; you only pay after exceeding the free tier and
   getting full Production access.
2. Set `PLAID_ENV=production` and your **Production** secret in `.env`, restart.
3. **Link** tab → *🔗 Connect a bank (Hosted Link)* → **Start Hosted Link** →
   open the URL in a new tab → finish the bank login there (Plaid hosts the
   OAuth, so nothing redirects to localhost) → back in the app, click
   *I've finished — import linked accounts*. Repeat per bank.
4. *Clear local financial data*, then **🔄 Refresh data**.
   - If the Amex **personal loan** doesn't surface as a Plaid item, the loan
     tracker still works with a manually entered balance.

> Why Hosted Link for production? Real banks use OAuth, whose redirect URIs must
> be HTTPS — painful on localhost. Hosted Link runs the whole flow on Plaid's
> domain and we retrieve the token via `/link/token/get`, so no local HTTPS or
> redirect plumbing is needed.

---

## How it works

```
ingest/   Plaid client, mock generator, transfer tagging, subscription detection, sync
db/       SQLite schema + access helpers (accounts, transactions, subscriptions)
utils/    config (.env), analytics (all spending math)
chat/     PII scrubber + Claude context builder / streaming client
ui/       Streamlit views: overview, breakdown, accounts, subscriptions, cards, loan, link, chat
app.py    entry point (tabs + sidebar chat)
```

- **Spending sign convention** (from Plaid): a transaction `amount` is positive
  when money leaves the account, negative when it arrives.
- **Transfers** (mortgage, insurance, card/loan payments) are auto-tagged and
  excluded from spending totals so they don't pollute the breakdown.
- **Subscription detection**: groups by merchant, flags any with 2+ charges on a
  ~monthly cadence (±3 days) at similar amounts; marks "likely canceled" after
  35 days with no charge. Recomputed on every sync.
- **Cards (Liabilities)**: when items are linked with Plaid's Liabilities
  product, credit cards show APR, minimum payment, statement balance, and due
  date alongside utilization. Personal loans aren't covered by Liabilities, so
  the Loan tracker uses the balance + an adjustable APR instead.
- **Claude chat**: builds a summary (optionally with recent transactions) from
  the same analytics the dashboard uses, runs it through the PII scrubber, then
  sends it as a cached system prompt. Account numbers, names, and addresses are
  redacted; an "extra paranoid" toggle hides merchant names too.

---

## Refreshing on a schedule

The sidebar **Refresh** button runs a full sync on demand. To automate it,
schedule `python -c "from ingest import sync; print(sync.run_sync())"` with
Windows Task Scheduler (or cron on other platforms).

---

## Notes

- Pinned dependency versions in `requirements.txt` are known-good; bump as needed.
- The Anthropic API does not train on your inputs, but PII scrubbing is applied
  regardless as defense-in-depth.
