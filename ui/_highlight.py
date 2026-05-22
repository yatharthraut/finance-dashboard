"""Shared helper to highlight detected-subscription rows in transaction tables.

A transaction is treated as a subscription if its merchant matches one of the
merchants in the ``subscriptions`` table (case-insensitive). Used by every table
that lists individual transactions so the styling is consistent.
"""

from __future__ import annotations

import pandas as pd

from db import database as db

# Soft amber tint; subtle on both light and dark themes.
_HIGHLIGHT = "background-color: rgba(255, 196, 0, 0.22)"


def subscription_merchants() -> set[str]:
    """Normalized set of merchant names that are detected subscriptions."""
    return {
        s["merchant"].strip().lower()
        for s in db.get_subscriptions()
        if s["merchant"]
    }


def is_subscription(merchant_series: pd.Series, subs: set[str]) -> pd.Series:
    """Boolean Series: True where the row's merchant is a subscription."""
    return merchant_series.fillna("").str.strip().str.lower().isin(subs)


def style_subscription_rows(display: pd.DataFrame, is_sub: pd.Series):
    """Return a pandas Styler that shades subscription rows.

    ``is_sub`` must share ``display``'s index.
    """
    def _row(row):
        shade = _HIGHLIGHT if bool(is_sub.get(row.name, False)) else ""
        return [shade] * len(row)

    return display.style.apply(_row, axis=1)
