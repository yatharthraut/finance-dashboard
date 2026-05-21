"""Real Plaid integration (Phase 2).

This module is imported lazily so the dashboard runs on mock data with neither
``plaid-python`` configured nor network access. Wire it up by:

  1. Filling PLAID_CLIENT_ID / PLAID_SECRET / PLAID_ENV in .env
  2. Running the "Link accounts" page (ui/link.py) to authorize each institution
     (TD, Amex card, Amex loan, Discover). That stores an access token per item.
  3. Hitting "Refresh" — ``sync.run_sync`` will route to ``sync_plaid``.

Uses the modern ``/transactions/sync`` cursor API and Plaid Personal Finance
Categories.
"""

from __future__ import annotations

from datetime import datetime, timezone

from utils.config import settings

_ENV_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


def _client():
    """Build a configured Plaid API client. Raises if SDK/keys are missing."""
    import plaid
    from plaid.api import plaid_api

    if not settings.has_plaid:
        raise RuntimeError("Plaid credentials are not set in .env")

    host = _ENV_HOSTS.get(settings.plaid_env, _ENV_HOSTS["sandbox"])
    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": settings.plaid_client_id,
            "secret": settings.plaid_secret,
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


# --------------------------------------------------------------------------- #
# Link flow
# --------------------------------------------------------------------------- #
def create_link_token(user_id: str = "local-user") -> str:
    """Create a Link token for the Plaid Link front-end widget."""
    from plaid.model.country_code import CountryCode
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import (
        LinkTokenCreateRequestUser,
    )
    from plaid.model.products import Products

    client = _client()
    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        # Liabilities is "optional" so banks that don't support it still link
        # (we just won't get credit-card detail from those).
        optional_products=[Products("liabilities")],
        client_name="Personal Finance Dashboard",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
    )
    return client.link_token_create(request).link_token


def create_hosted_link(user_id: str = "local-user") -> tuple[str, str]:
    """Create a Hosted Link session. Returns (link_token, hosted_link_url).

    Hosted Link is the right fit for a local app connecting real (OAuth) banks:
    Plaid hosts the whole flow on its own domain, so the bank's OAuth redirect
    never has to land on localhost. You open the returned URL in a browser,
    finish linking, and we retrieve the public_token via ``get_link_results``.
    """
    from plaid.model.country_code import CountryCode
    from plaid.model.link_token_create_hosted_link import LinkTokenCreateHostedLink
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import (
        LinkTokenCreateRequestUser,
    )
    from plaid.model.products import Products

    client = _client()
    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        optional_products=[Products("liabilities")],
        client_name="Personal Finance Dashboard",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id=user_id),
        hosted_link=LinkTokenCreateHostedLink(),
    )
    resp = client.link_token_create(request)
    return resp.link_token, resp.hosted_link_url


def get_link_diagnostics(link_token: str) -> dict:
    """Inspect a Hosted Link session via /link/token/get.

    Returns a dict with:
      * results:    list of {"public_token", "institution"} for completed items
      * exit_error: {error_type, error_code, error_message, display_message} if
                    the user hit an error / exited, else None
      * events:     ordered list of Link event names (for debugging)

    Empty results + no exit_error usually means the user hasn't finished yet.
    """
    from plaid.model.link_token_get_request import LinkTokenGetRequest

    client = _client()
    # validation off: the response can contain nulls the SDK would reject.
    resp = client.link_token_get(
        LinkTokenGetRequest(link_token=link_token), _check_return_type=False
    )
    info: dict = {"results": [], "exit_error": None, "events": []}
    for session in _g(resp, "link_sessions") or []:
        results = _g(session, "results")
        for r in (_g(results, "item_add_results") or []) if results else []:
            inst = _g(r, "institution")
            info["results"].append(
                {
                    "public_token": _g(r, "public_token"),
                    "institution": _g(inst, "name") if inst else None,
                }
            )
        # Older single-token success shape.
        success = _g(session, "on_success")
        pt = _g(success, "public_token") if success else None
        if pt and not info["results"]:
            info["results"].append({"public_token": pt, "institution": None})
        # Exit / error detail.
        ex = _g(session, "exit")
        err = _g(ex, "error") if ex else None
        if err:
            info["exit_error"] = {
                "error_type": _g(err, "error_type"),
                "error_code": _g(err, "error_code"),
                "error_message": _g(err, "error_message"),
                "display_message": _g(err, "display_message"),
            }
        for e in _g(session, "events") or []:
            name = _g(e, "event_name")
            if name:
                info["events"].append(str(name))
    return info


def exchange_public_token(public_token: str) -> tuple[str, str]:
    """Swap a Link public_token for a long-lived (access_token, item_id)."""
    from plaid.model.item_public_token_exchange_request import (
        ItemPublicTokenExchangeRequest,
    )

    client = _client()
    resp = client.item_public_token_exchange(
        ItemPublicTokenExchangeRequest(public_token=public_token)
    )
    return resp.access_token, resp.item_id


def get_institution_name(access_token: str) -> str | None:
    """Best-effort lookup of the institution name behind an item."""
    from plaid.model.country_code import CountryCode
    from plaid.model.institutions_get_by_id_request import (
        InstitutionsGetByIdRequest,
    )
    from plaid.model.item_get_request import ItemGetRequest

    client = _client()
    try:
        item = client.item_get(ItemGetRequest(access_token=access_token)).item
        inst = client.institutions_get_by_id(
            InstitutionsGetByIdRequest(
                institution_id=item.institution_id,
                country_codes=[CountryCode("US")],
            )
        ).institution
        return inst.name
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Sandbox shortcut
# --------------------------------------------------------------------------- #
# Stable Plaid sandbox test institutions. The transactions returned are
# synthetic but real-shaped, so they exercise the full ingest pipeline. The
# stored institution name comes from Plaid, so these labels are just hints.
SANDBOX_INSTITUTIONS = {
    "First Platypus Bank": "ins_109508",
    "First Gingham Credit Union": "ins_109509",
    "Tartan Bank": "ins_109510",
    "Houndstooth Bank": "ins_109511",
    "Tattersall Federal Credit Union": "ins_109512",
}
DEFAULT_SANDBOX_INSTITUTION = "ins_109508"


def create_sandbox_public_token(
    institution_id: str = DEFAULT_SANDBOX_INSTITUTION,
) -> str:
    """Mint a sandbox public_token directly, skipping the Link widget.

    Only valid when PLAID_ENV=sandbox. Lets us link a test bank with one click
    and verify the link -> exchange -> sync -> dashboard pipeline end to end.
    """
    from plaid.model.products import Products
    from plaid.model.sandbox_public_token_create_request import (
        SandboxPublicTokenCreateRequest,
    )

    client = _client()
    req = SandboxPublicTokenCreateRequest(
        institution_id=institution_id,
        initial_products=[Products("transactions"), Products("liabilities")],
    )
    return client.sandbox_public_token_create(req).public_token


def _date_str(d) -> str | None:
    if d is None:
        return None
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _g(obj, key, default=None):
    """Read ``key`` from a plaid model or a raw dict (validation-off responses)."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _pick_apr(aprs) -> float | None:
    """Choose a representative APR — purchase APR if present, else the first."""
    if not aprs:
        return None
    for a in aprs:
        if str(_g(a, "apr_type", "")).lower() == "purchase_apr":
            return _g(a, "apr_percentage")
    return _g(aprs[0], "apr_percentage")


def fetch_liabilities(access_token: str) -> dict[str, dict]:
    """Return credit-card liability detail keyed by account_id.

    Empty dict if the institution/item doesn't support Liabilities. Only credit
    cards are mapped (Plaid Liabilities also covers student loans & mortgages,
    but those aren't in scope here; personal loans aren't supported by Plaid).

    We pass ``_check_return_type=False`` because the SDK does strict response
    validation and will reject the *entire* payload if any field is null where it
    expects a string (e.g. a sandbox mortgage's null ``account_number``). With
    checking off, the response comes back as plain dicts, so we parse defensively.
    """
    from plaid.model.liabilities_get_request import LiabilitiesGetRequest

    client = _client()
    try:
        resp = client.liabilities_get(
            LiabilitiesGetRequest(access_token=access_token),
            _check_return_type=False,
        )
    except Exception:
        return {}  # product not available for this item — fine, skip silently

    liabilities = _g(resp, "liabilities")
    credits = _g(liabilities, "credit") if liabilities else None
    out: dict[str, dict] = {}
    for c in credits or []:
        account_id = _g(c, "account_id")
        if not account_id:
            continue
        overdue = _g(c, "is_overdue")
        out[account_id] = {
            "apr": _pick_apr(_g(c, "aprs") or []),
            "minimum_payment": _g(c, "minimum_payment_amount"),
            "last_payment_amount": _g(c, "last_payment_amount"),
            "last_payment_date": _date_str(_g(c, "last_payment_date")),
            "last_statement_balance": _g(c, "last_statement_balance"),
            "last_statement_issue_date": _date_str(_g(c, "last_statement_issue_date")),
            "next_payment_due_date": _date_str(_g(c, "next_payment_due_date")),
            "is_overdue": None if overdue is None else int(bool(overdue)),
        }
    return out


# --------------------------------------------------------------------------- #
# Data pulls
# --------------------------------------------------------------------------- #
def _fetch_accounts(client, access_token: str, institution: str | None) -> list[dict]:
    from plaid.model.accounts_get_request import AccountsGetRequest

    resp = client.accounts_get(AccountsGetRequest(access_token=access_token))
    item_id = resp.item.item_id
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = []
    for a in resp.accounts:
        bal = a.balances
        out.append(
            {
                "account_id": a.account_id,
                "item_id": item_id,
                "institution": institution or "Unknown",
                "name": a.name,
                "official_name": a.official_name,
                "mask": a.mask,
                "type": str(a.type),
                "subtype": str(a.subtype) if a.subtype else None,
                "current_balance": bal.current,
                "available_balance": bal.available,
                "credit_limit": bal.limit,
                "currency": bal.iso_currency_code or "USD",
                "updated_at": now,
            }
        )
    return out


def _map_txn(t) -> dict:
    pfc = getattr(t, "personal_finance_category", None)
    primary = getattr(pfc, "primary", None) if pfc else None
    detailed = getattr(pfc, "detailed", None) if pfc else None
    from ingest.categorize import from_plaid_category

    return {
        "transaction_id": t.transaction_id,
        "account_id": t.account_id,
        "date": t.date.isoformat() if hasattr(t.date, "isoformat") else str(t.date),
        "amount": t.amount,  # Plaid: positive = money out
        "merchant": t.merchant_name or t.name,
        "name": t.name,
        "category": from_plaid_category(primary, detailed),
        "plaid_category": primary,
        "category_override": None,
        "pending": int(bool(t.pending)),
        "is_transfer": 0,  # set by sync layer via shared rules
        "currency": t.iso_currency_code or "USD",
    }


def _sync_once(client, access_token: str, cursor: str) -> tuple[list[dict], str]:
    """Drain all pages of transactions/sync from ``cursor``. Returns (txns, cursor)."""
    from plaid.model.transactions_sync_request import TransactionsSyncRequest

    added: list[dict] = []
    next_cursor = cursor
    has_more = True
    while has_more:
        req = TransactionsSyncRequest(access_token=access_token)
        if next_cursor:
            req.cursor = next_cursor
        resp = client.transactions_sync(req)
        added.extend(_map_txn(t) for t in resp.added)
        added.extend(_map_txn(t) for t in resp.modified)
        next_cursor = resp.next_cursor
        has_more = resp.has_more
    return added, next_cursor


def sync_item(
    access_token: str,
    cursor: str | None,
    *,
    max_wait_seconds: int = 30,
) -> tuple[list[dict], list[dict], str]:
    """Pull accounts + incremental transactions for one item.

    Returns (accounts, transactions, next_cursor). Removed transactions are
    ignored here for simplicity; a fuller build would delete them.

    On the *initial* sync (no cursor) Plaid often returns an empty result while
    it prepares the first transaction pull. Rather than require a webhook
    endpoint, we poll for a short window until data arrives.
    """
    import time

    client = _client()
    institution = get_institution_name(access_token)
    accounts = _fetch_accounts(client, access_token, institution)

    next_cursor = cursor or ""
    added, next_cursor = _sync_once(client, access_token, next_cursor)

    # Initial sync that came back empty: poll until transactions are ready.
    if not cursor and not added:
        deadline = time.monotonic() + max_wait_seconds
        while not added and time.monotonic() < deadline:
            time.sleep(2)
            more, next_cursor = _sync_once(client, access_token, next_cursor)
            added.extend(more)

    return accounts, added, next_cursor
