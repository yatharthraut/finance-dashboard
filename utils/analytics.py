"""Pure analytics over the transactions/accounts/subscriptions tables.

Returns plain Python / pandas objects so both the Streamlit views and the Claude
context builder can reuse the exact same numbers. No Streamlit imports here.

Sign convention (inherited from Plaid): a transaction ``amount`` is positive
when money leaves the account (spend) and negative when money arrives (income).
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime

import pandas as pd

from db import database as db


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def transactions_df(
    start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    rows = db.get_transactions(start=start, end=end)
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["is_transfer"] = df["is_transfer"].astype(bool)
    return df


def accounts_df() -> pd.DataFrame:
    rows = db.get_accounts()
    return pd.DataFrame([dict(r) for r in rows])


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #
def month_bounds(d: date | None = None) -> tuple[str, str]:
    d = d or date.today()
    last_day = monthrange(d.year, d.month)[1]
    return date(d.year, d.month, 1).isoformat(), date(d.year, d.month, last_day).isoformat()


# --------------------------------------------------------------------------- #
# Spending helpers — operate on a transactions DataFrame
# --------------------------------------------------------------------------- #
def _spend_mask(df: pd.DataFrame) -> pd.Series:
    """Real discretionary/bill spend: money out, not a transfer, not income."""
    return (~df["is_transfer"]) & (df["amount"] > 0) & (df["category"] != "Income")


def _income_mask(df: pd.DataFrame) -> pd.Series:
    return (~df["is_transfer"]) & (df["amount"] < 0)


def total_spend(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return float(df.loc[_spend_mask(df), "amount"].sum())


def total_income(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return float(-df.loc[_income_mask(df), "amount"].sum())


def net_cash_flow(df: pd.DataFrame) -> float:
    return round(total_income(df) - total_spend(df), 2)


def spend_by_category(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["category", "amount"])
    s = df.loc[_spend_mask(df)].groupby("category")["amount"].sum()
    out = s.sort_values(ascending=False).reset_index()
    out["amount"] = out["amount"].round(2)
    return out


def spend_by_week(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["week", "amount"])
    spend = df.loc[_spend_mask(df)].copy()
    if spend.empty:
        return pd.DataFrame(columns=["week", "amount"])
    spend["week"] = spend["date"].dt.to_period("W").apply(lambda p: p.start_time)
    out = spend.groupby("week")["amount"].sum().round(2).reset_index()
    return out


def spend_by_account(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["account_name", "amount"])
    s = df.loc[_spend_mask(df)].groupby("account_name")["amount"].sum()
    return s.sort_values(ascending=False).round(2).reset_index()


def top_merchants(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["merchant", "amount"])
    s = df.loc[_spend_mask(df)].groupby("merchant")["amount"].sum()
    out = s.sort_values(ascending=False).head(n).round(2).reset_index()
    return out


# --------------------------------------------------------------------------- #
# Loan payoff projection
# --------------------------------------------------------------------------- #
def loan_payoff(
    balance: float, monthly_payment: float, annual_rate: float = 0.13
) -> dict:
    """Project months-to-payoff and total interest for a fixed monthly payment.

    ``annual_rate`` is a default APR estimate for an Amex personal loan; expose
    it in the UI so the user can adjust. Returns a schedule-summary dict.
    """
    if monthly_payment <= 0 or balance <= 0:
        return {"months": 0, "total_interest": 0.0, "payoff_date": None, "schedule": []}

    r = annual_rate / 12.0
    bal = balance
    months = 0
    total_interest = 0.0
    schedule = []
    # Cap iterations so a too-small payment can't loop forever.
    while bal > 0 and months < 600:
        interest = bal * r
        principal = monthly_payment - interest
        if principal <= 0:
            # Payment doesn't cover interest -> never pays off.
            return {
                "months": None,
                "total_interest": None,
                "payoff_date": None,
                "schedule": [],
                "note": "Monthly payment is too low to cover interest.",
            }
        bal = max(0.0, bal - principal)
        total_interest += interest
        months += 1
        schedule.append({"month": months, "balance": round(bal, 2)})

    today = date.today()
    pay_year = today.year + (today.month - 1 + months) // 12
    pay_month = (today.month - 1 + months) % 12 + 1
    payoff_date = date(pay_year, pay_month, 1)

    return {
        "months": months,
        "total_interest": round(total_interest, 2),
        "payoff_date": payoff_date.isoformat(),
        "schedule": schedule,
    }


def detect_monthly_loan_payment(loan_account_id: str) -> float:
    """Infer the recurring loan payment from transfer transactions, if any."""
    rows = db.get_transactions()
    payments = [
        r["amount"]
        for r in rows
        if r["is_transfer"]
        and r["amount"] > 0
        and r["merchant"]
        and "loan" in (r["merchant"] or "").lower()
    ]
    if not payments:
        return 0.0
    # Use the most common / median payment amount.
    payments.sort()
    return round(payments[len(payments) // 2], 2)
