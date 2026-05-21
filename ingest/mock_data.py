"""Deterministic mock data so the dashboard is fully usable with no Plaid keys.

Generates ~6 months of accounts + transactions across the four real-world
accounts named in the plan:
  * TD Bank — checking + savings (depository)
  * Amex — credit card
  * Amex — personal loan
  * Discover — credit card

Amounts follow the Plaid convention: positive = money OUT (spend / payment),
negative = money IN (income / deposit). The generator deliberately seeds
recurring subscriptions, a monthly mortgage transfer, and a salary so the
subscription detector and transfer tagging have something to find.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from ingest.categorize import from_plaid_category, is_transfer

SEED = 42
MONTHS_OF_HISTORY = 6

# ---- Account definitions --------------------------------------------------
ACCOUNTS = [
    {
        "account_id": "mock_td_checking",
        "item_id": "mock_item_td",
        "institution": "TD Bank",
        "name": "TD Convenience Checking",
        "official_name": "TD CONVENIENCE CHECKING",
        "mask": "4471",
        "type": "depository",
        "subtype": "checking",
        "current_balance": 4820.55,
        "available_balance": 4820.55,
        "credit_limit": None,
    },
    {
        "account_id": "mock_td_savings",
        "item_id": "mock_item_td",
        "institution": "TD Bank",
        "name": "TD Simple Savings",
        "official_name": "TD SIMPLE SAVINGS",
        "mask": "9920",
        "type": "depository",
        "subtype": "savings",
        "current_balance": 15200.00,
        "available_balance": 15200.00,
        "credit_limit": None,
    },
    {
        "account_id": "mock_amex_card",
        "item_id": "mock_item_amex_card",
        "institution": "Amex",
        "name": "Amex Blue Cash",
        "official_name": "AMERICAN EXPRESS BLUE CASH EVERYDAY",
        "mask": "1008",
        "type": "credit",
        "subtype": "credit card",
        "current_balance": 1340.22,   # amount owed
        "available_balance": None,
        "credit_limit": 12000.00,
    },
    {
        "account_id": "mock_amex_loan",
        "item_id": "mock_item_amex_loan",
        "institution": "Amex",
        "name": "Amex Personal Loan",
        "official_name": "AMERICAN EXPRESS PERSONAL LOAN",
        "mask": "5532",
        "type": "loan",
        "subtype": "personal loan",
        "current_balance": 8650.00,   # remaining principal
        "available_balance": None,
        "credit_limit": None,
    },
    {
        "account_id": "mock_discover",
        "item_id": "mock_item_discover",
        "institution": "Discover",
        "name": "Discover it Card",
        "official_name": "DISCOVER IT CASHBACK",
        "mask": "7781",
        "type": "credit",
        "subtype": "credit card",
        "current_balance": 612.40,
        "available_balance": None,
        "credit_limit": 9500.00,
    },
]

# ---- Recurring subscriptions (merchant, amount, day-of-month, plaid cat) ----
SUBSCRIPTIONS = [
    ("Netflix", 15.49, 4, "ENTERTAINMENT", "ENTERTAINMENT_STREAMING"),
    ("Spotify", 11.99, 9, "ENTERTAINMENT", "ENTERTAINMENT_STREAMING"),
    ("Amazon Prime", 14.99, 17, "GENERAL_MERCHANDISE", "GENERAL_MERCHANDISE_SUBSCRIPTION"),
    ("Adobe Creative Cloud", 54.99, 22, "GENERAL_SERVICES", "GENERAL_SERVICES_SUBSCRIPTION"),
    ("Planet Fitness", 24.99, 1, "PERSONAL_CARE", "PERSONAL_CARE_GYMS_AND_FITNESS"),
    ("New York Times", 17.00, 12, "ENTERTAINMENT", "ENTERTAINMENT_SUBSCRIPTION"),
    ("iCloud+", 2.99, 14, "GENERAL_SERVICES", "GENERAL_SERVICES_SUBSCRIPTION"),
]

# A subscription the user "canceled" ~2 months ago (stops appearing).
CANCELED_SUB = ("Hulu", 17.99, 7, "ENTERTAINMENT", "ENTERTAINMENT_STREAMING")

# ---- One-off / variable merchants by category -----------------------------
VARIABLE_MERCHANTS = {
    ("Whole Foods Market", "FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES"): (40, 160),
    ("Trader Joe's", "FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES"): (25, 110),
    ("Costco", "FOOD_AND_DRINK", "FOOD_AND_DRINK_GROCERIES"): (80, 320),
    ("Starbucks", "FOOD_AND_DRINK", "FOOD_AND_DRINK_COFFEE"): (5, 18),
    ("Chipotle", "FOOD_AND_DRINK", "FOOD_AND_DRINK_FAST_FOOD"): (11, 28),
    ("DoorDash", "FOOD_AND_DRINK", "FOOD_AND_DRINK_RESTAURANT"): (22, 65),
    ("Shell", "TRANSPORTATION", "TRANSPORTATION_GAS"): (35, 75),
    ("Uber", "TRANSPORTATION", "TRANSPORTATION_TAXIS_AND_RIDE_SHARES"): (9, 42),
    ("Amazon", "GENERAL_MERCHANDISE", "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES"): (12, 140),
    ("Target", "GENERAL_MERCHANDISE", "GENERAL_MERCHANDISE_SUPERSTORES"): (20, 130),
    ("Home Depot", "HOME_IMPROVEMENT", "HOME_IMPROVEMENT_HARDWARE"): (15, 200),
    ("CVS Pharmacy", "MEDICAL", "MEDICAL_PHARMACIES_AND_SUPPLEMENTS"): (8, 60),
    ("Delta Air Lines", "TRAVEL", "TRAVEL_FLIGHTS"): (180, 520),
}

# Credit accounts that carry day-to-day spending.
SPENDING_ACCOUNTS = ["mock_amex_card", "mock_discover"]


def _rng() -> random.Random:
    return random.Random(SEED)


def _txn_id(*parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return "mock_" + hashlib.md5(raw.encode()).hexdigest()[:16]


def _month_starts(months: int) -> list[date]:
    """Return the first-of-month dates for the trailing ``months`` months."""
    today = date.today()
    starts = []
    y, m = today.year, today.month
    for _ in range(months):
        starts.append(date(y, m, 1))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    return sorted(starts)


def _make_txn(rng, account_id, d, amount, merchant, name, primary, detailed):
    plaid_cat = primary
    transfer = is_transfer(name, merchant, plaid_cat)
    category = "Transfer" if transfer else from_plaid_category(primary, detailed)
    if not transfer and detailed and (
        "SUBSCRIPTION" in detailed or "STREAMING" in detailed or "GYMS" in detailed
    ):
        category = "Subscriptions"
    return {
        "transaction_id": _txn_id(account_id, d.isoformat(), merchant, amount),
        "account_id": account_id,
        "date": d.isoformat(),
        "amount": round(amount, 2),
        "merchant": merchant,
        "name": name,
        "category": category,
        "plaid_category": plaid_cat,
        "category_override": None,
        "pending": 0,
        "is_transfer": int(transfer),
        "currency": "USD",
    }


def generate() -> tuple[list[dict], list[dict]]:
    """Return (accounts, transactions) ready for the DB upsert helpers."""
    rng = _rng()
    txns: list[dict] = []
    months = _month_starts(MONTHS_OF_HISTORY)
    today = date.today()

    def day_in_month(start: date, dom: int) -> date | None:
        try:
            d = start.replace(day=dom)
        except ValueError:
            return None
        return d if d <= today else None

    for start in months:
        # --- Salary: twice a month into TD checking (income = negative) ---
        for dom in (1, 15):
            d = day_in_month(start, dom)
            if d:
                txns.append(
                    _make_txn(
                        rng, "mock_td_checking", d, -2650.00,
                        "Acme Corp Payroll", "ACME CORP DIRECT DEP PAYROLL",
                        "INCOME", "INCOME_WAGES",
                    )
                )

        # --- Mortgage: monthly transfer out of checking ---
        d = day_in_month(start, 3)
        if d:
            txns.append(
                _make_txn(
                    rng, "mock_td_checking", d, 1875.00,
                    "Wells Fargo Home Mortgage", "WF HOME MTG ONLINE PAYMENT",
                    "LOAN_PAYMENTS", "LOAN_PAYMENTS_MORTGAGE_PAYMENT",
                )
            )

        # --- Auto insurance: monthly transfer ---
        d = day_in_month(start, 8)
        if d:
            txns.append(
                _make_txn(
                    rng, "mock_td_checking", d, 142.30,
                    "Geico", "GEICO AUTO INSURANCE PAYMENT",
                    "GENERAL_SERVICES", "GENERAL_SERVICES_INSURANCE",
                )
            )

        # --- Amex personal loan payment: monthly transfer ---
        d = day_in_month(start, 18)
        if d:
            txns.append(
                _make_txn(
                    rng, "mock_td_checking", d, 325.00,
                    "Amex Loan", "AMEX PERSONAL LOAN AUTOPAY",
                    "LOAN_PAYMENTS", "LOAN_PAYMENTS_PERSONAL_LOAN_PAYMENT",
                )
            )

        # --- Credit card payments (transfers) ---
        for acct, amt, dom in (
            ("mock_td_checking", 1300.00, 20),
            ("mock_td_checking", 580.00, 24),
        ):
            d = day_in_month(start, dom)
            if d:
                merchant = "Amex" if dom == 20 else "Discover"
                txns.append(
                    _make_txn(
                        rng, acct, d, amt, f"{merchant} Payment",
                        f"{merchant.upper()} ONLINE PAYMENT - THANK YOU",
                        "TRANSFER_OUT", "TRANSFER_OUT_ACCOUNT_TRANSFER",
                    )
                )

        # --- Active subscriptions on the Amex card ---
        for merchant, amt, dom, primary, detailed in SUBSCRIPTIONS:
            d = day_in_month(start, dom)
            if d:
                txns.append(
                    _make_txn(
                        rng, "mock_amex_card", d, amt, merchant,
                        f"{merchant.upper()} RECURRING", primary, detailed,
                    )
                )

        # --- Canceled subscription: only appears in the older months ---
        cancel_cutoff = today - timedelta(days=70)
        if start < cancel_cutoff:
            merchant, amt, dom, primary, detailed = CANCELED_SUB
            d = day_in_month(start, dom)
            if d:
                txns.append(
                    _make_txn(
                        rng, "mock_discover", d, amt, merchant,
                        f"{merchant.upper()} RECURRING", primary, detailed,
                    )
                )

        # --- Variable discretionary spend across the month ---
        n_purchases = rng.randint(28, 45)
        for _ in range(n_purchases):
            (merchant, primary, detailed), (lo, hi) = rng.choice(
                list(VARIABLE_MERCHANTS.items())
            )
            dom = rng.randint(1, 28)
            d = day_in_month(start, dom)
            if not d:
                continue
            amt = rng.uniform(lo, hi)
            acct = rng.choice(SPENDING_ACCOUNTS)
            txns.append(
                _make_txn(
                    rng, acct, d, amt, merchant,
                    f"{merchant.upper()} #{rng.randint(100, 999)}",
                    primary, detailed,
                )
            )

    return ACCOUNTS, txns
