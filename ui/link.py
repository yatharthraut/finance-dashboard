"""Plaid Link page: authorize TD, Amex, Discover and store access tokens.

Three ways to link, in order of preference:
  * Sandbox one-click — instant fake bank, for testing (sandbox env only).
  * Hosted Link — Plaid hosts the whole flow on its own domain, so a bank's
    OAuth redirect never has to come back to localhost. This is the path for
    real banks. You open a URL in a new tab, finish there, then we pull the
    public_token via /link/token/get.
  * Embedded widget + manual paste — legacy fallback for non-OAuth desktop use.
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from db import database as db
from utils.config import settings


def _exchange_and_store(public_token: str) -> None:
    from ingest import plaid_client

    access_token, item_id = plaid_client.exchange_public_token(public_token)
    institution = plaid_client.get_institution_name(access_token)
    db.save_access_token(item_id, access_token, institution)
    st.success(f"Linked: {institution or item_id}")


def render() -> None:
    st.subheader("Link accounts (Plaid)")

    if not settings.has_plaid:
        st.warning(
            "Plaid credentials are not set. Add `PLAID_CLIENT_ID`, "
            "`PLAID_SECRET`, and `PLAID_ENV` to your `.env`, then restart. "
            "The dashboard still works on mock data without this."
        )
        return

    # Legacy embedded-widget redirect handoff (?public_token=...).
    qp = st.query_params
    if "public_token" in qp:
        try:
            _exchange_and_store(qp["public_token"])
        except Exception as exc:
            st.error(f"Token exchange failed: {exc}")
        finally:
            del st.query_params["public_token"]

    st.caption(f"Environment: **{settings.plaid_env}**")

    # Currently linked items.
    tokens = db.get_access_tokens()
    st.markdown("#### Linked institutions")
    if tokens:
        for t in tokens:
            st.write(f"- {t['institution'] or t['item_id']}")
    else:
        st.caption("Nothing linked yet. Link an institution below.")

    if settings.plaid_env == "sandbox":
        _sandbox_section()

    _hosted_link_section()
    _legacy_section()
    _clear_data_section()


def _sandbox_section() -> None:
    st.divider()
    st.markdown("#### 🧪 Sandbox: add a test bank")
    st.caption(
        "Sandbox uses fake banks with synthetic transactions — perfect for "
        "verifying the pipeline. This button skips the widget entirely."
    )
    from ingest import plaid_client

    names = list(plaid_client.SANDBOX_INSTITUTIONS.keys())
    c1, c2 = st.columns([3, 1])
    with c1:
        choice = st.selectbox("Test institution", names)
    with c2:
        st.write("")
        st.write("")
        if st.button("Link test bank", use_container_width=True):
            try:
                inst_id = plaid_client.SANDBOX_INSTITUTIONS[choice]
                pt = plaid_client.create_sandbox_public_token(inst_id)
                _exchange_and_store(pt)
                st.rerun()
            except Exception as exc:
                st.error(f"Sandbox link failed: {exc}")


def _hosted_link_section() -> None:
    st.divider()
    st.markdown("#### 🔗 Connect a bank (Hosted Link)")
    st.caption(
        "Best for real banks (TD, Amex, Discover). Opens Plaid's hosted page in "
        "a new tab — Plaid handles the bank's OAuth login there, so nothing has "
        "to redirect back to localhost. Finish in that tab, then come back and "
        "click **I've finished** below."
    )
    from ingest import plaid_client

    if st.button("Start Hosted Link"):
        try:
            link_token, url = plaid_client.create_hosted_link()
            st.session_state["hosted_link_token"] = link_token
            st.session_state["hosted_link_url"] = url
        except Exception as exc:
            st.error(f"Could not start Hosted Link: {exc}")

    url = st.session_state.get("hosted_link_url")
    if url:
        st.link_button("Open Plaid Link in a new tab ↗", url)
        if st.button("I've finished — import linked accounts"):
            try:
                diag = plaid_client.get_link_diagnostics(
                    st.session_state["hosted_link_token"]
                )
                results = diag["results"]
                if results:
                    for r in results:
                        _exchange_and_store(r["public_token"])
                    st.session_state.pop("hosted_link_token", None)
                    st.session_state.pop("hosted_link_url", None)
                    st.success(
                        f"Imported {len(results)} institution(s). "
                        "Hit **Refresh** to sync transactions."
                    )
                    st.rerun()
                elif diag["exit_error"]:
                    e = diag["exit_error"]
                    st.error(
                        f"Link exited with an error:\n\n"
                        f"- **Type:** {e.get('error_type')}\n"
                        f"- **Code:** {e.get('error_code')}\n"
                        f"- **Message:** {e.get('error_message')}\n"
                        f"- **Shown to you:** {e.get('display_message')}"
                    )
                    if diag["events"]:
                        st.caption("Link events: " + " → ".join(diag["events"]))
                else:
                    st.warning(
                        "No completed link found yet. Finish in the other tab, "
                        "then click this again."
                    )
                    if diag["events"]:
                        st.caption("Link events: " + " → ".join(diag["events"]))
            except Exception as exc:
                st.error(f"Import failed: {exc}")


def _legacy_section() -> None:
    with st.expander("Other: embedded widget / paste a public_token"):
        st.caption(
            "Embedded widget works for non-OAuth banks on desktop. For OAuth "
            "banks it requires an HTTPS redirect URI — prefer Hosted Link above."
        )
        if st.button("Launch embedded widget"):
            try:
                from ingest import plaid_client

                link_token = plaid_client.create_link_token()
                _render_link_widget(link_token)
            except Exception as exc:
                st.error(f"Could not start Plaid Link: {exc}")

        pt = st.text_input("public_token (manual)")
        if st.button("Exchange & store") and pt:
            try:
                _exchange_and_store(pt)
                st.rerun()
            except Exception as exc:
                st.error(f"Exchange failed: {exc}")


def _clear_data_section() -> None:
    st.divider()
    with st.expander("⚠️ Clear local financial data"):
        st.caption(
            "Wipes accounts, transactions, and subscriptions from the local DB "
            "(e.g. to remove the seeded mock data before pulling real Plaid "
            "data). Linked institutions are kept so you don't have to re-link. "
            "Hit **Refresh** afterward to re-sync."
        )
        confirm = st.checkbox("Yes, delete the local financial data")
        if st.button("Clear data now", disabled=not confirm):
            db.reset_data(keep_tokens=True)
            st.success("Local financial data cleared. Use Refresh to re-sync.")
            st.rerun()


def _render_link_widget(link_token: str) -> None:
    html = f"""
    <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
    <button id="plaid-btn" style="padding:10px 16px;font-size:15px;cursor:pointer;">
      Open Plaid Link
    </button>
    <script>
      const handler = Plaid.create({{
        token: "{link_token}",
        onSuccess: (public_token, metadata) => {{
          const url = new URL(window.parent.location.href);
          url.searchParams.set("public_token", public_token);
          window.parent.location.href = url.toString();
        }},
        onExit: (err, metadata) => {{ console.log("exit", err, metadata); }},
      }});
      document.getElementById("plaid-btn").onclick = () => handler.open();
    </script>
    """
    components.html(html, height=80)
