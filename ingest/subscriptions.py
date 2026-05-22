"""Subscription detection (Phase 4).

Algorithm, per the plan:
  * group transactions by merchant
  * flag a merchant as a subscription if it has 2+ charges at *similar amounts*
    on a recurring cadence (weekly / monthly / quarterly / annual, +/- a few days)
  * if the merchant has not charged in 35+ days, mark it "likely_canceled"

Two signals must both hold, which is what keeps variable merchants (groceries,
gas, restaurants) out of the list:
  1. amounts are tight — most charges within ~8% of the median
  2. the gaps between those charges line up with a real billing period, and a
     *majority* of gaps match the same period

Recomputed from scratch on each sync (the DB row is replaced wholesale).
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from datetime import date, datetime

# Recurring periods we recognize: (canonical days, +/- tolerance).
PERIODS = [
    (7, 2),     # weekly
    (14, 2),    # biweekly
    (30, 4),    # monthly (covers 26-34 day real-world months)
    (60, 5),    # bimonthly / a skipped monthly charge
    (90, 6),    # quarterly
    (180, 10),  # semiannual
    (365, 12),  # annual
]

AMOUNT_TOLERANCE = 0.08        # charges within 8% of the median count as "same"
CANCEL_GRACE_DAYS = 5          # grace past the expected next charge before canceling
MIN_CHARGES = 2
MONTHLY_DAYS = 30
# For a monthly sub this yields the plan's "35+ days silent => canceled" rule.


def _parse(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()


def _match_period(gap: int) -> int | None:
    """Return the canonical period a gap matches, or None."""
    best = None
    best_dist = math.inf
    for period, tol in PERIODS:
        dist = abs(gap - period)
        if dist <= tol and dist < best_dist:
            best, best_dist = period, dist
    return best


def detect(transactions: list[dict], *, today: date | None = None) -> list[dict]:
    """Return a list of subscription dicts ready for ``replace_subscriptions``.

    ``transactions`` rows need at least: merchant, amount, date, category.
    Only positive amounts (money out) that aren't transfers are considered.
    """
    today = today or date.today()

    by_merchant: dict[str, list[dict]] = defaultdict(list)
    for t in transactions:
        merchant = (t.get("merchant") or "").strip()
        amount = t.get("amount") or 0
        if not merchant or amount <= 0 or t.get("is_transfer"):
            continue
        by_merchant[merchant].append(t)

    subs: list[dict] = []
    for merchant, charges in by_merchant.items():
        if len(charges) < MIN_CHARGES:
            continue

        # 1) A real subscription bills the *same amount* repeatedly. Require the
        #    most common exact (to-the-cent) amount to recur at least MIN_CHARGES
        #    times. Variable merchants (groceries, gas, dining) effectively never
        #    repeat an exact amount, so this is what keeps them out of the list.
        exact = Counter(round(c["amount"], 2) for c in charges)
        modal_amount, modal_count = exact.most_common(1)[0]
        if modal_amount <= 0 or modal_count < MIN_CHARGES:
            continue

        # Gather charges at (or within a small tolerance of) that recurring price.
        consistent = sorted(
            (
                c for c in charges
                if abs(c["amount"] - modal_amount) <= AMOUNT_TOLERANCE * modal_amount
            ),
            key=lambda c: c["date"],
        )
        if len(consistent) < MIN_CHARGES:
            continue

        # 2) Cadence: gaps between consecutive consistent charges must line up
        #    with one recurring period for the majority of gaps.
        dates = [_parse(c["date"]) for c in consistent]
        gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
        matched = [p for p in (_match_period(g) for g in gaps) if p is not None]
        if not matched:
            continue

        dominant, dom_count = Counter(matched).most_common(1)[0]
        # Require a majority of gaps to share the dominant period.
        if dom_count < math.ceil(len(gaps) / 2):
            continue

        last_charge = dates[-1]
        days_since = (today - last_charge).days
        # Silent past the expected next charge (+grace) => likely canceled.
        # Scaling to the cadence keeps quarterly/annual subs from false-canceling.
        cancel_window = dominant + CANCEL_GRACE_DAYS
        status = "likely_canceled" if days_since > cancel_window else "active"

        subs.append(
            {
                "merchant": merchant,
                "avg_amount": round(statistics.mean(c["amount"] for c in consistent), 2),
                "cadence_days": dominant,
                "charge_count": len(consistent),
                "first_charge": dates[0].isoformat(),
                "last_charge": last_charge.isoformat(),
                "status": status,
                "category": consistent[-1].get("category") or "Subscriptions",
            }
        )

    subs.sort(key=lambda s: s["avg_amount"], reverse=True)
    return subs


def _manual_sub(override: dict, txns: list[dict], today: date) -> dict:
    """Build a subscription row for a manually-added merchant.

    Stats are computed from the merchant's actual transactions when available
    (works for recurring transfers, which auto-detection skips), falling back to
    the values supplied in the override.
    """
    amounts = [abs(t["amount"]) for t in txns if t.get("amount") is not None]
    dates = sorted(_parse(t["date"]) for t in txns if t.get("date"))
    cadence = override.get("cadence_days") or MONTHLY_DAYS

    avg = override.get("avg_amount")
    if not avg:
        avg = round(statistics.median(amounts), 2) if amounts else 0.0

    if dates:
        first, last = dates[0].isoformat(), dates[-1].isoformat()
        days_since = (today - dates[-1]).days
        status = "likely_canceled" if days_since > cadence + CANCEL_GRACE_DAYS else "active"
    else:
        first = last = today.isoformat()
        status = "active"

    return {
        "merchant": override["merchant"],
        "avg_amount": round(avg, 2),
        "cadence_days": cadence,
        "charge_count": len(txns),
        "first_charge": first,
        "last_charge": last,
        "status": status,
        "category": override.get("category") or "Subscriptions",
    }


def apply_overrides(
    subs: list[dict],
    transactions: list[dict],
    overrides: list[dict],
    *,
    today: date | None = None,
) -> list[dict]:
    """Layer manual changes over auto-detected subscriptions.

    'exclude' overrides drop a merchant; 'add' overrides force one in (with stats
    derived from its transactions). Merchant matching is case-insensitive.
    """
    today = today or date.today()
    excluded = {o["merchant"].strip().lower() for o in overrides if o["action"] == "exclude"}
    adds = [o for o in overrides if o["action"] == "add"]

    result = [s for s in subs if s["merchant"].strip().lower() not in excluded]
    present = {s["merchant"].strip().lower() for s in result}

    by_merchant: dict[str, list[dict]] = defaultdict(list)
    for t in transactions:
        m = (t.get("merchant") or "").strip().lower()
        if m:
            by_merchant[m].append(t)

    for o in adds:
        key = o["merchant"].strip().lower()
        if key in present:  # already detected — don't duplicate
            continue
        result.append(_manual_sub(o, by_merchant.get(key, []), today))
        present.add(key)

    result.sort(key=lambda s: s["avg_amount"], reverse=True)
    return result


def monthly_total(subs: list[dict]) -> float:
    """Sum of active subscription costs normalized to a monthly (30-day) figure."""
    total = 0.0
    for s in subs:
        if s["status"] != "active":
            continue
        cadence = s.get("cadence_days") or MONTHLY_DAYS
        total += s["avg_amount"] * (MONTHLY_DAYS / max(cadence, 1))
    return round(total, 2)
