"""Read-only guest access via share links (no account required)."""

from __future__ import annotations

import datetime
import secrets
from typing import Any
from urllib.parse import urlencode, urlsplit

import streamlit as st
from postgrest.exceptions import APIError

from app_logging import configure_logging, report_error

log = configure_logging("share_access")

GUEST_SHARE_TOKEN_KEY = "guest_share_token"
GUEST_LANDING_ADDRESS_KEY = "guest_landing_address"


def _query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return str(value) if value is not None else None


def get_guest_share_token() -> str | None:
    """Active share token for this browser session, if any."""
    token = st.session_state.get(GUEST_SHARE_TOKEN_KEY)
    if token and str(token).strip():
        return str(token).strip()
    return None


def is_guest_viewer() -> bool:
    """True when the user entered via a valid share link (read-only, no account)."""
    return bool(get_guest_share_token())


def is_authenticated_or_guest() -> bool:
    from authenticate import get_logged_in_user

    return bool(get_logged_in_user()) or is_guest_viewer()


def _validate_share_token(token: str) -> dict[str, Any] | None:
    if not token or not str(token).strip():
        return None
    from authenticate import get_supabase

    supabase = get_supabase()
    try:
        response = supabase.rpc(
            "validate_share_token", {"p_token": str(token).strip()}
        ).execute()
    except APIError as exc:
        report_error(log, "share_validate_failed", exc, level="warning")
        return None
    payload = response.data
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not payload or not payload.get("valid"):
        return None
    return payload


def activate_guest_session_from_query() -> bool:
    """
    If ?share=TOKEN is present and valid, persist guest mode in session_state.
    Returns True when guest mode is active after this call.
    """
    from authenticate import get_logged_in_user

    if get_logged_in_user():
        st.session_state.pop(GUEST_SHARE_TOKEN_KEY, None)
        st.session_state.pop(GUEST_LANDING_ADDRESS_KEY, None)
        return False

    token = _query_param("share") or get_guest_share_token()
    if not token:
        return False

    meta = _validate_share_token(token)
    if not meta:
        st.session_state.pop(GUEST_SHARE_TOKEN_KEY, None)
        return False

    st.session_state[GUEST_SHARE_TOKEN_KEY] = str(token).strip()
    address = meta.get("address")
    if address and GUEST_LANDING_ADDRESS_KEY not in st.session_state:
        st.session_state[GUEST_LANDING_ADDRESS_KEY] = str(address)
    return True


def get_guest_landing_address() -> str | None:
    address = st.session_state.get(GUEST_LANDING_ADDRESS_KEY)
    if address and str(address).strip():
        return str(address).strip()
    return None


def consume_guest_landing_address() -> str | None:
    address = st.session_state.pop(GUEST_LANDING_ADDRESS_KEY, None)
    if address and str(address).strip():
        return str(address).strip()
    return None


def fetch_guest_portfolio() -> list[dict[str, Any]]:
    """Canonical properties visible to a guest share session."""
    token = get_guest_share_token()
    if not token:
        return []
    from authenticate import get_supabase

    supabase = get_supabase()
    try:
        response = supabase.rpc(
            "get_guest_portfolio", {"p_share_token": token}
        ).execute()
    except APIError as exc:
        report_error(log, "guest_portfolio_fetch_failed", exc)
        return []
    return response.data or []


def fetch_guest_property(
    *,
    property_id: str | None = None,
    address: str | None = None,
) -> dict[str, Any] | None:
    """Load one property for a guest, optionally with sharer's assumptions."""
    token = get_guest_share_token()
    if not token:
        return None
    from authenticate import get_supabase

    supabase = get_supabase()
    params: dict[str, Any] = {"p_share_token": token}
    if property_id:
        params["p_property_id"] = property_id
    if address:
        params["p_address"] = address
    try:
        response = supabase.rpc("get_guest_property", params).execute()
    except APIError as exc:
        report_error(log, "guest_property_fetch_failed", exc)
        return None
    payload = response.data
    if isinstance(payload, list):
        payload = payload[0] if payload else None
    if not payload or not payload.get("valid"):
        return None
    prop = payload.get("property")
    return prop if isinstance(prop, dict) else None


def save_share_comps_snapshot(
    share_token: str,
    property_id: str,
    property_data: dict[str, Any],
) -> bool:
    """Freeze comps on a share link so guests see the same table the sharer had."""
    comps = property_data.get("comps_analysis")
    if not isinstance(comps, dict) or not comps.get("comparable_properties"):
        return False

    from authenticate import get_authenticated_client

    client = get_authenticated_client()
    if client is None:
        return False

    params: dict[str, Any] = {
        "p_share_token": str(share_token).strip(),
        "p_property_id": str(property_id),
        "p_comps_analysis": comps,
    }
    if property_data.get("predicted_value") is not None:
        params["p_predicted_value"] = float(property_data["predicted_value"])
    if property_data.get("prediction_reasoning"):
        params["p_prediction_reasoning"] = str(property_data["prediction_reasoning"])

    try:
        response = client.rpc("save_share_comps_snapshot", params).execute()
    except APIError as exc:
        report_error(log, "share_comps_snapshot_failed", exc, property_id=property_id)
        return False
    return bool(response.data)


def create_property_share_link(
    property_id: str,
    *,
    include_assumptions: bool = True,
    expires_days: int = 30,
) -> str | None:
    """Create a share token for the logged-in user. Returns the opaque token."""
    from authenticate import get_authenticated_client, get_logged_in_user

    user = get_logged_in_user()
    if not user:
        return None

    client = get_authenticated_client()
    if client is None:
        return None

    token = secrets.token_urlsafe(32)
    expires_at: str | None = None
    if expires_days > 0:
        expires_at = (
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=expires_days)
        ).isoformat()

    row = {
        "share_token": token,
        "property_id": property_id,
        "created_by": user["id"],
        "include_assumptions": include_assumptions,
        "expires_at": expires_at,
    }
    try:
        client.table("property_shares").insert(row).execute()
    except APIError as exc:
        report_error(log, "share_create_failed", exc, property_id=property_id)
        return None
    log.info("share_created", property_id=property_id, created_by=user["id"])
    return token


def build_share_url(share_token: str) -> str:
    """Full URL a friend can open without signing in."""
    from authenticate import _current_app_url, _get_redirect_url

    base = _current_app_url() or _get_redirect_url()
    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else base
    query = urlencode({"share": share_token})
    return f"{origin}?{query}"


def render_guest_sidebar() -> None:
    """Sidebar for read-only guest viewers."""
    st.markdown("### 👀 Guest view")
    st.caption(
        "You're viewing a shared link. Browse properties read-only — "
        "sign in to save or run new analyses."
    )
    if st.button("Sign in for full access", key="guest_sign_in_cta", use_container_width=True):
        st.session_state.pop(GUEST_SHARE_TOKEN_KEY, None)
        if "share" in st.query_params:
            del st.query_params["share"]
        st.rerun()
