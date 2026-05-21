"""Claude chat: build a scrubbed financial context, then call the Anthropic API.

The context is assembled from the same analytics functions the dashboard uses,
run through the PII scrubber, and prepended to the conversation as a system
prompt. Two detail levels are supported (the plan's toggle):
  * "summary"  — totals, category breakdown, subscription list only
  * "detailed" — also includes recent (scrubbed) transaction lines
"""

from __future__ import annotations

from datetime import date

from chat.scrubber import scrub, scrub_merchant
from db import database as db
from ingest import subscriptions as subs_mod
from utils import analytics
from utils.config import settings

SYSTEM_PROMPT = (
    "You are a financial analyst with read-only access to the user's monthly "
    "financial summary. The data has been anonymized: account numbers, names, "
    "and addresses are redacted. Help the user analyze spending, identify "
    "subscriptions worth cutting, and answer questions about their finances. "
    "Be concrete and cite the numbers from the context. If the context lacks "
    "the data needed to answer, say so plainly rather than guessing."
)


def build_context(detail: str = "summary", *, paranoid: bool = False) -> str:
    """Construct the scrubbed context block sent to Claude."""
    start, end = analytics.month_bounds()
    month_df = analytics.transactions_df(start=start, end=end)
    all_df = analytics.transactions_df()

    lines: list[str] = []
    lines.append(f"# Financial summary (as of {date.today().isoformat()})")
    lines.append("")

    # --- Accounts & balances ---
    lines.append("## Accounts")
    for a in db.get_accounts():
        bal = a["current_balance"]
        kind = a["subtype"] or a["type"]
        bits = [f"- {a['institution']} {kind}: balance ${bal:,.2f}"]
        if a["credit_limit"]:
            bits.append(f"(limit ${a['credit_limit']:,.0f})")
        lines.append(" ".join(bits))
    lines.append("")

    # --- This month's headline numbers ---
    lines.append("## This month")
    lines.append(f"- Income: ${analytics.total_income(month_df):,.2f}")
    lines.append(f"- Total spend: ${analytics.total_spend(month_df):,.2f}")
    lines.append(f"- Net cash flow: ${analytics.net_cash_flow(month_df):,.2f}")
    lines.append("")

    # --- Spending by category (this month) ---
    cat = analytics.spend_by_category(month_df)
    if not cat.empty:
        lines.append("## Spending by category (this month)")
        for _, row in cat.iterrows():
            lines.append(f"- {row['category']}: ${row['amount']:,.2f}")
        lines.append("")

    # --- Subscriptions ---
    active = [dict(s) for s in db.get_subscriptions(status="active")]
    if active:
        monthly = subs_mod.monthly_total(active)
        lines.append(f"## Active subscriptions (~${monthly:,.2f}/mo total)")
        for s in active:
            lines.append(
                f"- {scrub_merchant(s['merchant'])}: ${s['avg_amount']:,.2f} "
                f"every ~{s['cadence_days']} days (last {s['last_charge']})"
            )
        lines.append("")

    canceled = [dict(s) for s in db.get_subscriptions(status="likely_canceled")]
    if canceled:
        lines.append("## Likely canceled subscriptions")
        for s in canceled:
            lines.append(
                f"- {scrub_merchant(s['merchant'])}: was ${s['avg_amount']:,.2f}, "
                f"last seen {s['last_charge']}"
            )
        lines.append("")

    # --- Optional transaction-level detail ---
    if detail == "detailed" and not all_df.empty:
        recent = all_df.sort_values("date", ascending=False).head(50)
        lines.append("## Recent transactions (last 50)")
        for _, t in recent.iterrows():
            merchant = "[merchant]" if paranoid else scrub_merchant(t["merchant"])
            tag = " [transfer]" if t["is_transfer"] else ""
            lines.append(
                f"- {t['date'].date()} {merchant} ${t['amount']:,.2f} "
                f"({t['category']}){tag}"
            )
        lines.append("")

    context = "\n".join(lines)
    # Final safety pass over the whole block.
    return scrub(context, paranoid=paranoid)


def is_available() -> bool:
    return settings.has_anthropic


def stream_reply(messages: list[dict], detail: str = "summary", *, paranoid: bool = False):
    """Yield text chunks of Claude's reply.

    ``messages`` is a list of {"role": "user"|"assistant", "content": str}.
    Raises RuntimeError if no API key is configured.
    """
    if not settings.has_anthropic:
        raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")

    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)
    context = build_context(detail=detail, paranoid=paranoid)
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": context,
            # Cache the (large, stable) context block across turns.
            "cache_control": {"type": "ephemeral"},
        },
    ]

    with client.messages.stream(
        model=settings.anthropic_model,
        max_tokens=1024,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text
