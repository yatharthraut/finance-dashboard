"""Build the daily spending summary (yesterday / this week / this month).

Spend = money out, excluding transfers and income — the same definition the
dashboard uses (utils.analytics.total_spend).
"""

from __future__ import annotations

from datetime import date, timedelta

from utils import analytics


def _spend(start: date, end: date) -> float:
    df = analytics.transactions_df(start=start.isoformat(), end=end.isoformat())
    return analytics.total_spend(df)


def build_report(today: date | None = None) -> dict:
    """Return {yesterday, week, month, text} for the daily message."""
    today = today or date.today()
    yesterday = today - timedelta(days=1)
    monday = today - timedelta(days=today.weekday())   # week so far: Mon -> today
    first_of_month = today.replace(day=1)

    y = _spend(yesterday, yesterday)
    w = _spend(monday, today)
    m = _spend(first_of_month, today)

    text = (
        "Spending update\n"
        f"Yesterday:  ${y:,.2f}\n"
        f"This week:  ${w:,.2f}\n"
        f"This month: ${m:,.2f}"
    )
    return {"yesterday": y, "week": w, "month": m, "text": text}
