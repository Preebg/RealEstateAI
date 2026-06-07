"""Supabase authentication (Google OAuth PKCE + email/password)."""

from __future__ import annotations

import base64
import hashlib
import os
import secrets
import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

from app_logging import configure_logging, report_error

log = configure_logging("authenticate")

_GOOGLE_G_LOGO_PATH = Path(__file__).resolve().parent / "assets" / "google-g-logo.png"


def _render_google_signin_button(oauth_url: str) -> None:
    """Google-branded sign-in control with the official-style G logo."""
    st.markdown(
        """
        <style>
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.google-signin-shell-marker) {
            background: #ffffff;
            border-color: #dadce0 !important;
            border-radius: 8px !important;
            box-shadow: 0 1px 2px rgba(60, 64, 67, 0.08);
            padding: 0.15rem 0.35rem 0.15rem 0.75rem !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.google-signin-shell-marker)
            div[data-testid="stLinkButton"] a {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            color: #3c4043 !important;
            font-weight: 500 !important;
            min-height: 40px !important;
            justify-content: center;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.google-signin-shell-marker)
            div[data-testid="stLinkButton"] a:hover {
            background: transparent !important;
            color: #202124 !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.google-signin-shell-marker)
            div[data-testid="stLinkButton"] a:active {
            color: #202124 !important;
        }
        div[data-testid="stVerticalBlockBorderWrapper"]:has(.google-signin-shell-marker)
            div[data-testid="stImage"] img {
            margin-top: 0.35rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        st.markdown('<span class="google-signin-shell-marker"></span>', unsafe_allow_html=True)
        logo_col, btn_col = st.columns([0.1, 0.9], gap="small", vertical_alignment="center")
        with logo_col:
            if _GOOGLE_G_LOGO_PATH.is_file():
                st.image(str(_GOOGLE_G_LOGO_PATH), width=22)
            else:
                st.markdown(
                    '<span style="display:inline-flex;width:22px;height:22px;align-items:center;'
                    'justify-content:center;border-radius:50%;background:#4285f4;color:#fff;'
                    'font-size:12px;font-weight:700;">G</span>',
                    unsafe_allow_html=True,
                )
        with btn_col:
            st.link_button(
                "Continue with Google",
                oauth_url,
                use_container_width=True,
                type="secondary",
                key="google_oauth_link",
            )


class StreamlitAuthStorage:
    """Persist Supabase Auth tokens/PKCE in st.session_state across reruns."""

    PREFIX = "sb_auth_storage_"

    def get_item(self, key: str) -> str | None:
        value = st.session_state.get(self.PREFIX + key)
        return str(value) if value is not None else None

    def set_item(self, key: str, value: str) -> None:
        st.session_state[self.PREFIX + key] = value

    def remove_item(self, key: str) -> None:
        st.session_state.pop(self.PREFIX + key, None)


def _get_secret(name: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception as exc:
        raise EnvironmentError(
            f"{name} not set. Add it to environment variables or Streamlit secrets."
        ) from exc


def _headless_mode() -> bool:
    """True for CLI harvester and other non-Streamlit runs."""
    if os.environ.get("STREAMLIT_RUNTIME_ENV"):
        return False
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx() is not None:
            return False
    except Exception:
        pass
    return True


def in_streamlit_app() -> bool:
    """True when code is executing inside a Streamlit app runtime."""
    return not _headless_mode()


def _get_optional_secret(name: str) -> str | None:
    """Return a secret when set; None if missing (no error)."""
    value = os.getenv(name)
    if value and str(value).strip():
        return str(value).strip()
    if not _headless_mode():
        try:
            if name in st.secrets:
                secret = str(st.secrets[name]).strip()
                return secret or None
        except Exception:
            pass
    return None


def get_supabase() -> Client:
    """Return a Supabase client with Streamlit-backed auth storage."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")

    if _headless_mode():
        return create_client(url, key)

    try:
        from supabase.lib.client_options import ClientOptions

        options = ClientOptions(storage=StreamlitAuthStorage())
        return create_client(url, key, options)
    except Exception:
        return create_client(url, key)


def _normalize_app_url(url: str) -> str:
    """Canonical app origin for OAuth redirects (no path/query/trailing slash)."""
    cleaned = url.strip().rstrip("/")
    if not cleaned:
        return cleaned
    # st.context.url may include ?query on Streamlit Cloud; keep origin only.
    from urllib.parse import urlsplit

    parts = urlsplit(cleaned)
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return cleaned


def _is_localhost_url(url: str) -> bool:
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _current_app_url() -> str:
    """Origin of the page the user is actually visiting."""
    if _headless_mode():
        return ""
    return _normalize_app_url(str(st.context.url))


def _configured_redirect_url() -> str | None:
    explicit = os.getenv("OAUTH_REDIRECT_URL")
    if explicit and str(explicit).strip():
        return _normalize_app_url(explicit)
    if not _headless_mode() and "OAUTH_REDIRECT_URL" in st.secrets:
        value = str(st.secrets["OAUTH_REDIRECT_URL"]).strip()
        if value:
            return _normalize_app_url(value)
    return None


def _get_redirect_url() -> str:
    """OAuth redirect URL — must match Supabase Auth redirect allow-list."""
    context_url = _current_app_url()
    configured = _configured_redirect_url()

    # Streamlit Cloud secrets are often copied from dev with localhost here.
    # Prefer the live app URL so Google returns to the page the user opened.
    if configured:
        if _is_localhost_url(configured) and context_url and not _is_localhost_url(
            context_url
        ):
            log.warning(
                "oauth_redirect_ignored_localhost",
                configured=configured,
                context_url=context_url,
            )
            return context_url
        return configured

    if context_url:
        return context_url
    return "http://localhost:8501"


def _oauth_redirect_config_warning() -> str | None:
    """Explain redirect misconfiguration before the user starts Google sign-in."""
    if _headless_mode():
        return None

    context_url = _current_app_url()
    configured = _configured_redirect_url()
    if not context_url:
        return None

    if configured and configured != context_url:
        if _is_localhost_url(configured):
            return (
                f"**Google sign-in is misconfigured.** `OAUTH_REDIRECT_URL` is set to "
                f"`{configured}`, but this app runs at `{context_url}`. After Google "
                f"approves access, the browser is sent to localhost instead of back here. "
                f"Update Streamlit Cloud secrets to "
                f"`OAUTH_REDIRECT_URL = \"{context_url}\"` and add `{context_url}` under "
                f"Supabase → Authentication → URL Configuration → Redirect URLs."
            )
        return (
            f"**Google sign-in is misconfigured.** `OAUTH_REDIRECT_URL` (`{configured}`) "
            f"does not match this app (`{context_url}`). Update Streamlit secrets and the "
            f"Supabase redirect allow-list."
        )

    if not configured and not _is_localhost_url(context_url):
        return (
            f"For Google sign-in on Streamlit Cloud, set "
            f"`OAUTH_REDIRECT_URL = \"{context_url}\"` in app secrets and add `{context_url}` "
            f"to Supabase → Authentication → URL Configuration → Redirect URLs."
        )
    return None


def _get_pkce_session_id() -> str:
    """Stable id for this OAuth attempt; echoed in redirect_to as pkce_sid."""
    sid = st.session_state.get("pkce_session_id")
    if not sid:
        sid = secrets.token_urlsafe(32)
        st.session_state["pkce_session_id"] = sid
    return sid


def _redirect_url_with_pkce_sid() -> str:
    """Redirect URL including pkce_sid so callback can load verifier from Supabase."""
    base = _get_redirect_url()
    sid = _get_pkce_session_id()
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}pkce_sid={sid}"


def _generate_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for OAuth PKCE."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def _encode_verifier_state(code_verifier: str) -> str:
    """Encode verifier into OAuth state (survives full-page redirect)."""
    return base64.urlsafe_b64encode(code_verifier.encode("utf-8")).decode().rstrip("=")


def _decode_verifier_state(state: str) -> str | None:
    """Decode verifier from OAuth state query param."""
    if not state:
        return None
    try:
        pad = "=" * (-len(state) % 4)
        decoded = base64.urlsafe_b64decode(state + pad).decode("utf-8")
        if len(decoded) >= 43:
            return decoded
    except Exception:
        pass
    return None


def _save_pending_pkce(code_verifier: str, code_challenge: str = "") -> None:
    """Persist PKCE verifier in Supabase (survives Streamlit session reset on redirect)."""
    sid = _get_pkce_session_id()
    supabase = get_supabase()
    try:
        supabase.rpc(
            "store_oauth_pkce",
            {
                "p_session_id": sid,
                "p_code_verifier": code_verifier,
                "p_code_challenge": code_challenge or "",
            },
        ).execute()
    except APIError as exc:
        report_error(log, "pkce_store_failed", exc, pkce_session_id=sid[:8] + "…")
        raise
    st.session_state["pkce_code_verifier"] = code_verifier
    log.info("pkce_stored", pkce_session_id=sid[:8] + "…")


def _load_pending_pkce() -> dict[str, Any] | None:
    """Load and consume PKCE material from Supabase using pkce_sid."""
    sid = _query_param("pkce_sid") or st.session_state.get("pkce_session_id")
    if not sid:
        return None

    supabase = get_supabase()
    response = supabase.rpc("consume_oauth_pkce", {"p_session_id": sid}).execute()
    rows = response.data or []
    if not rows:
        log.warning("pkce_not_found", pkce_session_id=str(sid)[:8] + "…")
        return None

    row = rows[0]
    return {
        "code_verifier": row.get("code_verifier"),
        "code_challenge": row.get("code_challenge") or "",
    }


def _clear_pending_pkce() -> None:
    """Remove pending PKCE row if still present."""
    sid = st.session_state.get("pkce_session_id") or _query_param("pkce_sid")
    if not sid:
        return
    supabase = get_supabase()
    supabase.rpc("consume_oauth_pkce", {"p_session_id": sid}).execute()
    st.session_state.pop("pkce_session_id", None)


def _query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return str(value) if value is not None else None


def _clear_query_param(name: str) -> None:
    if name in st.query_params:
        del st.query_params[name]


def _clear_oauth_query_params(*, keep_handoff: bool = False) -> None:
    """Remove OAuth callback params so the user can retry cleanly."""
    for key in (
        "code",
        "state",
        "error",
        "error_description",
        "pkce_verifier",
        "pkce_sid",
    ):
        _clear_query_param(key)
    if not keep_handoff:
        _clear_query_param("auth_handoff")


def _extract_verifier_from_auth_client(supabase: Client) -> str | None:
    """Read PKCE verifier the Supabase SDK stored when starting OAuth."""
    storage = getattr(supabase.auth, "_storage", None)
    if storage is None:
        return None

    candidates = ["code_verifier", "pkce_code_verifier"]
    storage_key = getattr(supabase.auth, "_storage_key", "")
    if storage_key:
        candidates.insert(0, f"{storage_key}-code-verifier")

    for key in candidates:
        try:
            value = storage.get_item(key)
            if value:
                return str(value)
        except Exception:
            continue

    for key, value in st.session_state.items():
        if "code-verifier" in str(key).lower():
            return str(value)
    return None


def _read_pkce_verifier(supabase: Client | None = None) -> str | None:
    """
    Read PKCE verifier — Supabase first (survives redirect), then session/SDK.
    """
    pending = _load_pending_pkce()
    if pending and pending.get("code_verifier"):
        verifier = str(pending["code_verifier"])
        st.session_state["pkce_code_verifier"] = verifier
        return verifier

    if st.session_state.get("pkce_code_verifier"):
        return str(st.session_state["pkce_code_verifier"])

    pkce_param = _query_param("pkce_verifier")
    if pkce_param:
        st.session_state["pkce_code_verifier"] = pkce_param
        return pkce_param

    if supabase is not None:
        sdk_verifier = _extract_verifier_from_auth_client(supabase)
        if sdk_verifier:
            return sdk_verifier

    return None


def _peek_auth_handoff(handoff_id: str) -> dict[str, Any] | None:
    """Read stored OAuth session without deleting it (survives Streamlit reruns)."""
    supabase = get_supabase()
    try:
        response = supabase.rpc(
            "peek_oauth_auth_handoff", {"p_handoff_id": handoff_id}
        ).execute()
    except APIError as exc:
        details = getattr(exc, "args", [{}])
        code = details[0].get("code") if details and isinstance(details[0], dict) else ""
        if code == "PGRST202" or "peek_oauth_auth_handoff" in str(exc).lower():
            return _consume_auth_handoff_row(handoff_id)
        report_error(log, "oauth_handoff_peek_failed", exc, level="warning")
        return None

    rows = response.data or []
    return rows[0] if rows else None


def _consume_auth_handoff_row(handoff_id: str) -> dict[str, Any] | None:
    """Legacy one-time handoff read (pre-peek migration)."""
    supabase = get_supabase()
    try:
        response = supabase.rpc(
            "consume_oauth_auth_handoff", {"p_handoff_id": handoff_id}
        ).execute()
    except APIError as exc:
        report_error(log, "oauth_handoff_consume_failed", exc, level="warning")
        return None

    rows = response.data or []
    return rows[0] if rows else None


def _consume_auth_handoff(handoff_id: str) -> None:
    """Delete a stored OAuth handoff (logout / explicit cleanup)."""
    supabase = get_supabase()
    try:
        supabase.rpc(
            "consume_oauth_auth_handoff", {"p_handoff_id": handoff_id}
        ).execute()
    except APIError:
        pass


def _save_auth_handoff(handoff_id: str, session: Any) -> None:
    """Persist completed OAuth session for post-redirect recovery on Streamlit Cloud."""
    supabase = get_supabase()
    supabase.rpc(
        "store_oauth_auth_handoff",
        {
            "p_handoff_id": handoff_id,
            "p_access_token": session.access_token,
            "p_refresh_token": session.refresh_token or "",
            "p_user_id": session.user.id,
            "p_user_email": session.user.email or "",
        },
    ).execute()
    log.info("oauth_handoff_stored", handoff_id=handoff_id[:8] + "…")


def _restore_auth_handoff() -> bool:
    """
    Recover session tokens after OAuth redirect when Streamlit session_state reset.
    Returns True when a handoff was applied and auth state was restored.
    """
    handoff_id = _query_param("auth_handoff")
    if not handoff_id:
        return False

    if get_logged_in_user():
        return False

    row = _peek_auth_handoff(handoff_id)
    if not row:
        log.warning("oauth_handoff_not_found", handoff_id=handoff_id[:8] + "…")
        return False

    st.session_state["sb_access_token"] = row.get("access_token")
    st.session_state["sb_refresh_token"] = row.get("refresh_token") or ""
    st.session_state["user"] = {
        "id": str(row.get("user_id")),
        "email": row.get("user_email") or "",
    }
    st.session_state.pop("google_oauth_url", None)
    log.info("oauth_handoff_restored", handoff_id=handoff_id[:8] + "…")
    return True


def _persist_session(session: Any) -> None:
    st.session_state["sb_access_token"] = session.access_token
    st.session_state["sb_refresh_token"] = session.refresh_token
    st.session_state["user"] = {
        "id": str(session.user.id),
        "email": session.user.email or "",
    }
    st.session_state.pop("pkce_code_verifier", None)
    st.session_state.pop("google_oauth_url", None)
    _clear_pending_pkce()


def _clear_auth_state() -> None:
    for key in list(st.session_state.keys()):
        if (
            key
            in (
                "user",
                "sb_access_token",
                "sb_refresh_token",
                "pkce_code_verifier",
                "google_oauth_url",
            )
            or str(key).startswith(StreamlitAuthStorage.PREFIX)
        ):
            st.session_state.pop(key, None)
    _clear_pending_pkce()


def _oauth_handoff_id() -> str:
    """Stable id echoed in redirect_to and reused for post-login handoff."""
    return _query_param("pkce_sid") or _get_pkce_session_id()


def process_auth_callback() -> bool:
    """
    Handle OAuth callback query params.
    Returns True when callback was processed (success or error shown).
    """
    oauth_error = _query_param("error")
    if oauth_error:
        description = _query_param("error_description") or oauth_error
        st.error(f"Google sign-in was cancelled or failed: {description}")
        _clear_oauth_query_params()
        _clear_pending_pkce()
        return True

    code = _query_param("code")
    if not code:
        return False

    with st.spinner("Completing Google sign-in..."):
        supabase = get_supabase()
        code_verifier = _read_pkce_verifier(supabase)
        if not code_verifier:
            st.warning(
                "Could not verify sign-in session. Click **Refresh Google sign-in link**, "
                "then **Continue with Google** again."
            )
            return True

        try:
            response = supabase.auth.exchange_code_for_session(
                {"auth_code": code, "code_verifier": code_verifier}
            )
            handoff_id = _oauth_handoff_id()
            _save_auth_handoff(handoff_id, response.session)
            _persist_session(response.session)
            # Keep auth_handoff in the URL so reruns / fresh Streamlit sessions can recover.
            st.query_params["auth_handoff"] = handoff_id
            _clear_oauth_query_params(keep_handoff=True)
        except (APIError, ValueError, TypeError) as exc:
            report_error(log, "oauth_exchange_failed", exc)
            st.error(f"Sign-in failed: {exc}")
            _clear_oauth_query_params()
            _clear_pending_pkce()

    return True


def login_with_google() -> str:
    """
    Build Google OAuth URL with PKCE.
    Let Supabase manage OAuth `state` (CSRF) — do not pass a custom state value.
    Persist the code_verifier in Supabase for the post-redirect callback.
    """
    redirect_to = _redirect_url_with_pkce_sid()
    supabase = get_supabase()

    # SDK flow: Supabase generates valid state + PKCE and returns the authorize URL.
    try:
        response = supabase.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {"redirect_to": redirect_to},
            }
        )
        if response.url:
            verifier = _extract_verifier_from_auth_client(supabase)
            if verifier:
                _save_pending_pkce(verifier)
                return response.url
            log.warning("oauth_verifier_not_extracted")
    except (APIError, ValueError, TypeError) as exc:
        report_error(log, "oauth_sign_in_sdk_failed", exc, level="warning")

    # Fallback: manual authorize URL when SDK path fails or verifier was not persisted.
    code_verifier, code_challenge = _generate_pkce_pair()
    _save_pending_pkce(code_verifier, code_challenge)

    supabase_url = _get_secret("SUPABASE_URL").rstrip("/")
    api_key = _get_secret("SUPABASE_KEY")
    query = urlencode(
        {
            "provider": "google",
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "apikey": api_key,
        }
    )
    return f"{supabase_url}/auth/v1/authorize?{query}"


def sign_in_with_email(email: str, password: str) -> None:
    """Email/password login."""
    supabase = get_supabase()
    response = supabase.auth.sign_in_with_password(
        {"email": email.strip(), "password": password}
    )
    if response.session:
        _persist_session(response.session)


def sign_up_with_email(email: str, password: str) -> tuple[bool, str]:
    """Email/password registration."""
    supabase = get_supabase()
    response = supabase.auth.sign_up(
        {"email": email.strip(), "password": password}
    )
    try:
        user = getattr(response, "user", None) or getattr(getattr(response, "session", None), "user", None)
        if user and getattr(user, "id", None):
            # Best-effort write for compliance auditing. Requires a `profiles` table
            # keyed by `id` (auth user id) with `email` and `policy_accepted_at`.
            accepted_at = st.session_state.get("policy_accepted_at")
            if accepted_at:
                supabase.table("profiles").upsert(
                    {
                        "id": user.id,
                        "email": email.strip(),
                        "policy_accepted_at": accepted_at,
                    },
                    on_conflict="id",
                ).execute()
    except Exception:
        # Don't block account creation if profile upsert fails.
        pass
    if response.session:
        _persist_session(response.session)
        return True, "Account created. You are now signed in."

    return True, (
        "Account created. Check your email to confirm your address, then log in."
    )


def get_logged_in_user() -> dict[str, str] | None:
    """Return {'id': uid, 'email': email} for the current session, or None."""
    if _headless_mode():
        return None
    user = st.session_state.get("user")
    if not user or not user.get("id"):
        return None
    return {"id": user["id"], "email": user.get("email", "")}


def logout() -> None:
    """Sign out and clear Streamlit session auth state."""
    handoff_id = _query_param("auth_handoff")
    if handoff_id:
        _consume_auth_handoff(handoff_id)

    supabase = get_supabase()
    try:
        access = st.session_state.get("sb_access_token")
        refresh = st.session_state.get("sb_refresh_token")
        if access:
            supabase.auth.set_session(access, refresh or "")
            supabase.auth.sign_out()
    except Exception:
        pass

    _clear_auth_state()
    _clear_oauth_query_params()
    st.rerun()


def restore_session_from_tokens() -> None:
    """Re-hydrate user from saved tokens when not handling OAuth callback."""
    if get_logged_in_user():
        return

    access = st.session_state.get("sb_access_token")
    refresh = st.session_state.get("sb_refresh_token")
    if not access:
        return

    supabase = get_supabase()
    try:
        supabase.auth.set_session(access, refresh or "")
        user_response = supabase.auth.get_user()
        if user_response and user_response.user:
            st.session_state["user"] = {
                "id": user_response.user.id,
                "email": user_response.user.email or "",
            }
    except Exception:
        # Keep auth_handoff recovery available when Streamlit resets session_state.
        if not _query_param("auth_handoff"):
            _clear_auth_state()


def get_authenticated_client() -> Client | None:
    """Supabase client with the logged-in user's JWT (required for RLS)."""
    if _headless_mode():
        return None
    access = st.session_state.get("sb_access_token")
    refresh = st.session_state.get("sb_refresh_token")
    if not access:
        return None

    client = get_supabase()
    try:
        client.auth.set_session(access, refresh or "")
        return client
    except Exception:
        return None


def get_service_client() -> Client | None:
    """
    Service-role client for trusted headless jobs (harvester, backfill scripts).

    Uses SUPABASE_SERVICE_ROLE_KEY — never expose this key in the Streamlit UI.
    """
    key = _get_optional_secret("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        return None
    url = _get_secret("SUPABASE_URL")
    return create_client(url, key)


def get_db_client() -> Client:
    """Prefer authenticated session; in headless mode prefer service role; else anon."""
    auth_client = get_authenticated_client()
    if auth_client is not None:
        return auth_client
    if _headless_mode():
        service_client = get_service_client()
        if service_client is not None:
            return service_client
    return get_supabase()


def get_signup_policy_text() -> str:
    """Privacy Policy copy shown in the sign-up terms popup."""
    return """
### Privacy Policy & Legal Disclosures (Must Read)

**Effective date:** {effective_date}

#### 1) What this app is
This application is an AI-assisted, educational real-estate analysis tool. It may generate estimates, summaries, and risk-style scores based on user inputs and third-party information. It is **not** a broker, lender, or financial advisor.

#### 2) Data we collect
When you create an account or use the app, we may collect:
- **Account data**: email address and Supabase user identifier (UID)
- **Usage data**: properties you analyze and any values you save to your Knowledge Base
- **Generated outputs**: AI summaries, forecasts, and simulated “quantum” scores

We do **not** sell personal information.

#### 3) How we use data
We use your data to:
- authenticate you and protect your Knowledge Base,
- generate analyses you request,
- store properties you save for later retrieval.

#### 4) Sharing
We may share data with:
- **Supabase** (database + authentication provider),
- **AI model providers** used for analysis (only the inputs needed to produce the requested output).

#### 5) Security & retention
We apply reasonable security practices; however, no system is perfectly secure. Your saved Knowledge Base entries are retained until you delete them or we retire the service.

#### 6) AI + “Quantum” simulation disclosure (NY, TX, CA)
This app may display **quantum-probabilistic scores** or similar risk-style outputs. These are **simulations** derived from mathematical transforms of user inputs and/or model outputs. They are **not guarantees** and should not be interpreted as predictions of future performance.

If you are located in **New York (NY)**, **Texas (TX)**, or **California (CA)**, you acknowledge:
- the tool is **educational** and may produce erroneous or biased results,
- AI outputs may be incomplete, outdated, or incorrect,
- any “quantum” outputs are a simulation and **not** a financial promise.

#### 7) Your choices
You can stop using the app at any time. If you want your data removed, contact the operator of this portfolio project.

#### 8) Acceptance
By creating an account, you confirm you have read and agree to this Privacy Policy and the AI/Quantum disclosures above.
""".format(
        effective_date=datetime.date.today().isoformat()
    ).strip()


def _mark_terms_opened() -> None:
    """Track that the user opened the terms popup (compliance audit trail)."""
    st.session_state["terms_viewed"] = True
    st.session_state["terms_opened_at"] = (
        datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )


@st.dialog("Privacy Policy & Terms", width="large")
def _show_terms_dialog(policy_text: str) -> None:
    """Same-page modal popup for must-read policy text."""
    _mark_terms_opened()
    with st.container(height=350):
        st.markdown(policy_text)
    st.caption("Scroll to review all sections before agreeing.")
    if st.button("Close", use_container_width=True, key="terms_dialog_close"):
        st.rerun()


def render_auth_sidebar() -> None:
    """Sidebar block: email + Logout when signed in."""
    user = get_logged_in_user()
    if not user:
        return

    st.markdown("### Account")
    st.caption(user["email"])
    if st.button("Logout", key="logout_btn", use_container_width=True):
        logout()


def render_login_page() -> bool:
    """
    Full login / sign-up screen.
    Returns True when the user is authenticated.
    """
    process_auth_callback()
    _restore_auth_handoff()
    restore_session_from_tokens()

    if get_logged_in_user():
        return True

    handoff_id = _query_param("auth_handoff")
    if handoff_id:
        st.warning(
            "Google sign-in could not be completed in this browser session. "
            "Click **Refresh Google sign-in link**, then **Continue with Google** again."
        )

    left, center, right = st.columns([1, 1.2, 1])
    with center:
        st.markdown("## 🏠 AI Property Analyzer")
        st.caption("Sign in to access your private knowledge base and run analyses.")

        login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

        with login_tab:
            st.markdown("##### Sign in with Google")

            redirect_warning = _oauth_redirect_config_warning()
            if redirect_warning:
                st.warning(redirect_warning)

            try:
                redirect_to = _redirect_url_with_pkce_sid()
                cached_redirect = st.session_state.get("google_oauth_redirect")
                if (
                    not st.session_state.get("google_oauth_url")
                    or cached_redirect != redirect_to
                ):
                    st.session_state["google_oauth_redirect"] = redirect_to
                    st.session_state["google_oauth_url"] = login_with_google()
                oauth_url = st.session_state["google_oauth_url"]
                _render_google_signin_button(oauth_url)
                if st.button("Refresh Google sign-in link", use_container_width=True):
                    st.session_state.pop("google_oauth_url", None)
                    st.session_state.pop("google_oauth_redirect", None)
                    st.session_state.pop("pkce_code_verifier", None)
                    st.session_state.pop("pkce_session_id", None)
                    _clear_pending_pkce()
                    st.rerun()
                st.caption(
                    "You will return here automatically after Google approves access."
                )
            except Exception as exc:
                st.error(f"Google sign-in is unavailable: {exc}")

            st.divider()
            st.markdown("##### Or use email and password")

            login_email = st.text_input(
                "Email", key="auth_login_email", placeholder="you@email.com"
            )
            login_password = st.text_input(
                "Password", type="password", key="auth_login_password"
            )

            if st.button("Log in", use_container_width=True, key="auth_login_btn"):
                if not login_email or not login_password:
                    st.warning("Enter your email and password.")
                else:
                    try:
                        sign_in_with_email(login_email, login_password)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Login failed: {exc}")

        with signup_tab:
            policy_text = get_signup_policy_text()

            signup_email = st.text_input(
                "Email", key="auth_signup_email", placeholder="you@email.com"
            )
            signup_password = st.text_input(
                "Password", type="password", key="auth_signup_password"
            )
            signup_confirm = st.text_input(
                "Confirm password", type="password", key="auth_signup_confirm"
            )

            if "signup_has_interacted" not in st.session_state:
                st.session_state["signup_has_interacted"] = False
            if "terms_viewed" not in st.session_state:
                st.session_state["terms_viewed"] = False

            # Track interaction (non-empty inputs or checkbox changes).
            if signup_email or signup_password or signup_confirm:
                st.session_state["signup_has_interacted"] = True

            row_cb, row_space, row_text, row_link = st.columns(
                [0.06, 0.015, 0.56, 0.385], gap="small"
            )
            with row_cb:
                agreed = st.checkbox(
                    "agree",
                    key="policy_agreed",
                    disabled=not st.session_state["terms_viewed"],
                    label_visibility="collapsed",
                )
            with row_space:
                st.empty()
            with row_text:
                st.markdown(
                    '<p class="auth-agreement-text">I have read and agree to the&nbsp;</p>',
                    unsafe_allow_html=True,
                )
            with row_link:
                st.markdown(
                    """
<style>
button[data-testid="baseButton-secondary"][arial-label="Open terms popup"]{
  padding: 0!important;
  margin: 0!important;
  min-height: unset!important;
  height: auto!important;
  border: none!important;
  box-shadow: none!important;
  background: transparent!important;
  color: var(--primary-color)!important;
  font-size: 1rem!important;
  font-weight: 400!important;
  text-decoration: underline!important;
  line-height: 1.25!important;
  margin-top: 0.42rem!important;
}
button[data-testid="baseButton-secondary"][arial-label="Open terms popup"] p{
  color: inherit!important;
  text-decoration: inherit!important;
  margin: 0!important;
}
</style>
                    """,
                    unsafe_allow_html=True,
                )

                term_pressed = st.button(
                    "terms",
                    key="open_terms_modal",
                    type="secondary",
                )
                if term_pressed:
                    _show_terms_dialog(policy_text)

            if not st.session_state["terms_viewed"]:
                st.caption(
                    'Click **terms** to open the Privacy Policy popup and enable agreement.'
                )

            if agreed:
                st.session_state["signup_has_interacted"] = True

            create_disabled = not bool(agreed)

            if st.button(
                "Create account",
                type="primary",
                use_container_width=True,
                key="auth_signup_btn",
                disabled=create_disabled,
            ):
                st.session_state["signup_has_interacted"] = True
                if not signup_email or not signup_password:
                    st.warning("Enter an email and password.")
                elif signup_password != signup_confirm:
                    st.warning("Passwords do not match.")
                elif len(signup_password) < 6:
                    st.warning("Password must be at least 6 characters.")
                else:
                    try:
                        # Record acceptance time for compliance logging (profiles table).
                        st.session_state["policy_accepted_at"] = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
                        _, message = sign_up_with_email(signup_email, signup_password)
                        st.success(message)
                        if get_logged_in_user():
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Sign-up failed: {exc}")

            st.caption("Already have an account? Use the **Log in** tab.")

    return False


def render_auth_page(*, allow_guest: bool = True) -> bool:
    """
    Login / sign-up gate for app entry.
    Returns True when authenticated or in a valid guest share session.
    """
    if allow_guest:
        from share_access import activate_guest_session_from_query, is_guest_viewer

        if activate_guest_session_from_query() or is_guest_viewer():
            return True
    return render_login_page()
