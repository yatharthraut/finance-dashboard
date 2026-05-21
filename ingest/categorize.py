"""Category normalization and transfer-tagging rules.

Plaid's Personal Finance Categories are verbose (e.g.
``FOOD_AND_DRINK_FAST_FOOD``). We collapse them to a small, human set used in
the dashboard. We also decide which transactions are *transfers* — money
movements like mortgage payments, card payments, and insurance — so they don't
pollute the "spending" numbers, per the plan.
"""

from __future__ import annotations

import re

# Effective categories shown in the UI.
CATEGORIES = [
    "Groceries",
    "Dining",
    "Shopping",
    "Subscriptions",
    "Entertainment",
    "Transport",
    "Travel",
    "Utilities",
    "Health",
    "Housing",
    "Income",
    "Transfer",
    "Fees & Interest",
    "Other",
]

# Map Plaid PFC primary/detailed categories -> our buckets.
_PLAID_MAP = {
    "INCOME": "Income",
    "TRANSFER_IN": "Transfer",
    "TRANSFER_OUT": "Transfer",
    "LOAN_PAYMENTS": "Transfer",
    "BANK_FEES": "Fees & Interest",
    "ENTERTAINMENT": "Entertainment",
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Housing",
    "MEDICAL": "Health",
    "PERSONAL_CARE": "Health",
    "GENERAL_SERVICES": "Other",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
    "TRANSPORTATION": "Transport",
    "TRAVEL": "Travel",
    "RENT_AND_UTILITIES": "Utilities",
}


def from_plaid_category(primary: str | None, detailed: str | None = None) -> str:
    """Collapse a Plaid PFC code into our category set."""
    if detailed:
        d = detailed.upper()
        if "GROCERIES" in d:
            return "Groceries"
        if "SUBSCRIPTION" in d or "STREAMING" in d:
            return "Subscriptions"
    if primary:
        return _PLAID_MAP.get(primary.upper(), "Other")
    return "Other"


# --- Transfer tagging -------------------------------------------------------
# Merchant/memo patterns that should be excluded from "spending".
_TRANSFER_PATTERNS = [
    r"\bmortgage\b",
    r"\bescrow\b",
    r"\bins(urance)?\b",
    r"\bpayment\s*-?\s*thank\s*you\b",   # credit card payments
    r"\bonline payment\b",
    r"\bautopay\b",
    r"\bach (transfer|payment|debit|credit)\b",
    r"\btransfer\b",
    r"\bloan (pmt|payment)\b",
    r"\bcard payment\b",
    r"\bbalance transfer\b",
]
_TRANSFER_RE = re.compile("|".join(_TRANSFER_PATTERNS), re.IGNORECASE)


def is_transfer(name: str | None, merchant: str | None, plaid_category: str | None) -> bool:
    """Heuristic: True if this row is a transfer rather than discretionary spend."""
    if plaid_category and plaid_category.upper() in {
        "LOAN_PAYMENTS",
        "TRANSFER_IN",
        "TRANSFER_OUT",
    }:
        return True
    haystack = " ".join(filter(None, [name, merchant]))
    return bool(_TRANSFER_RE.search(haystack))
