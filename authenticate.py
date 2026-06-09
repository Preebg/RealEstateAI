"""Supabase authentication (Google OAuth + email/password)."""

from __future__ import annotations

import os
import secrets
import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx
import streamlit as st
from postgrest.exceptions import APIError
from supabase import Client, create_client

from app_logging import configure_logging, report_error
from legal import APP_NAME, get_privacy_policy_text, get_terms_of_service_text

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


def _get_google_web_client_id() -> str | None:
    """
    Google **Web application** OAuth client ID for app sign-in.

    Use the same Web client configured in Supabase → Authentication → Google.
    The Desktop client (Gmail pipeline) is a different credential type.
    """
    return _get_optional_secret("GOOGLE_WEB_CLIENT_ID")


def _get_google_web_client_secret() -> str | None:
    """Secret for the Web OAuth client (not the Desktop Gmail client)."""
    return _get_optional_secret("GOOGLE_WEB_CLIENT_SECRET")


def _store_google_signin_state(state: str, nonce: str, redirect_uri: str) -> None:
    """Persist OAuth state in Supabase so callbacks survive Streamlit session resets."""
    supabase = get_supabase()
    try:
        supabase.rpc(
            "store_oauth_pkce",
            {
                "p_session_id": state,
                "p_code_verifier": nonce,
                # Reused column: must match authorize + token exchange redirect_uri.
                "p_code_challenge": redirect_uri,
            },
        ).execute()
    except APIError as exc:
        report_error(log, "google_signin_state_store_failed", exc, level="warning")
        raise


def _consume_google_signin_state(state: str) -> tuple[str, str] | None:
    """Load nonce + redirect_uri saved for a Google OAuth state value."""
    supabase = get_supabase()
    response = supabase.rpc("consume_oauth_pkce", {"p_session_id": state}).execute()
    rows = response.data or []
    if not rows:
        return None
    row = rows[0]
    nonce = str(row.get("code_verifier") or "")
    redirect_uri = str(row.get("code_challenge") or "")
    if not nonce or not redirect_uri:
        return None
    return nonce, redirect_uri


def _google_redirect_uri_setup_hint(redirect_uri: str) -> str:
    client_id = _get_google_web_client_id() or "your-web-client-id"
    return (
        f"Add this **Authorized redirect URI** on your Google **Web** OAuth client "
        f"(`{client_id}`): `{redirect_uri}`\n\n"
        "Google Cloud Console → APIs & Services → Credentials → Web client → "
        "Authorized redirect URIs. It must match exactly (no trailing slash)."
    )


def build_google_signin_url(redirect_uri: str) -> str:
    """
    Full-page Google OAuth URL (not Supabase /authorize).

    Redirect URI is the Streamlit app origin so Google shows your app domain on
    the consent screen instead of ``*.supabase.co``.
    """
    client_id = _get_google_web_client_id()
    if not client_id:
        raise EnvironmentError(
            "GOOGLE_WEB_CLIENT_ID not set. Add your Web OAuth client ID to secrets."
        )

    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    _store_google_signin_state(state, nonce, redirect_uri)

    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"


def _exchange_google_auth_code(code: str, redirect_uri: str) -> dict[str, Any]:
    client_id = _get_google_web_client_id()
    client_secret = _get_google_web_client_secret()
    if not client_id or not client_secret:
        raise EnvironmentError(
            "Google Web OAuth credentials missing. Set GOOGLE_WEB_CLIENT_ID and "
            "GOOGLE_WEB_CLIENT_SECRET in secrets."
        )

    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=20.0,
    )
    if response.status_code >= 400:
        raise ValueError(response.text)
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("Google token endpoint returned an unexpected response.")
    return payload


def process_google_signin_callback() -> bool:
    """Handle Google redirect callback and open a Supabase session."""
    oauth_error = _query_param("error")
    if oauth_error:
        description = _query_param("error_description") or oauth_error
        redirect_uri = _get_redirect_url()
        if oauth_error == "redirect_uri_mismatch" or "redirect_uri" in description.lower():
            st.error(
                "Google rejected the redirect URI for this app. "
                + _google_redirect_uri_setup_hint(redirect_uri)
            )
        else:
            st.error(f"Google sign-in was cancelled or failed: {description}")
        _clear_oauth_query_params()
        return True

    code = _query_param("code")
    state = _query_param("state")
    if not code or not state:
        return False

    signin_state = _consume_google_signin_state(state)
    if not signin_state:
        st.warning(
            "Sign-in session expired or was already used. "
            "Click **Continue with Google** to try again."
        )
        _clear_oauth_query_params()
        return True

    nonce, redirect_uri = signin_state
    with st.spinner("Completing Google sign-in..."):
        supabase = get_supabase()
        try:
            tokens = _exchange_google_auth_code(code, redirect_uri)
            id_token = tokens.get("id_token")
            if not id_token:
                raise ValueError("Google did not return an ID token.")

            response = supabase.auth.sign_in_with_id_token(
                {"provider": "google", "token": str(id_token), "nonce": nonce}
            )
            if response.session:
                _persist_session(response.session)
            else:
                st.error("Google sign-in did not return a session. Please try again.")
        except (APIError, ValueError, TypeError) as exc:
            report_error(log, "google_signin_exchange_failed", exc)
            message = str(exc)
            if "redirect_uri_mismatch" in message.lower():
                st.error(
                    "Google token exchange failed: redirect URI mismatch. "
                    + _google_redirect_uri_setup_hint(redirect_uri)
                )
            else:
                st.error(f"Sign-in failed: {exc}")
        finally:
            _clear_oauth_query_params()

    return True


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


def _origin_from_request_headers() -> str:
    """Best-effort app origin when ``st.context.url`` is unavailable."""
    try:
        headers = st.context.headers
        host = headers.get("Host") or headers.get("host")
        if not host:
            return ""
        proto = (
            headers.get("X-Forwarded-Proto")
            or headers.get("x-forwarded-proto")
            or "https"
        )
        return _normalize_app_url(f"{proto}://{host}")
    except Exception:
        return ""


def _current_app_url() -> str:
    """Origin of the page the user is actually visiting."""
    if _headless_mode():
        return ""

    try:
        app_url = st.context.url
        if app_url:
            return _normalize_app_url(str(app_url))
    except KeyError as exc:
        # Streamlit 1.58+ can raise when page metadata lacks url_pathname
        # (common on the login screen with hidden st.navigation).
        log.warning("context_url_key_error", key=str(exc))
    except Exception as exc:
        log.warning("context_url_failed", error=str(exc))

    return _origin_from_request_headers()


def _configured_redirect_url() -> str | None:
    for key in ("OAUTH_REDIRECT_URL", "APP_URL"):
        explicit = os.getenv(key)
        if explicit and str(explicit).strip():
            return _normalize_app_url(explicit)
        if not _headless_mode():
            value = _get_optional_secret(key)
            if value:
                return _normalize_app_url(value)
    return None


def _get_redirect_url() -> str:
    """OAuth redirect URI — must match Google Web OAuth authorized redirect URIs."""
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
                f"`OAUTH_REDIRECT_URL = \"{context_url}\"` and add `{context_url}` as an "
                f"Authorized redirect URI on your Google Web OAuth client."
            )
        return (
            f"**Google sign-in is misconfigured.** `OAUTH_REDIRECT_URL` (`{configured}`) "
            f"does not match this app (`{context_url}`). Update Streamlit secrets and your "
            f"Google Web OAuth redirect URIs."
        )

    if not configured and not _is_localhost_url(context_url):
        return (
            f"For Google sign-in on Streamlit Cloud, set "
            f"`OAUTH_REDIRECT_URL = \"{context_url}\"` in app secrets and add `{context_url}` "
            f"as an Authorized redirect URI on your Google Web OAuth client."
        )
    return None


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
    for key in ("code", "state", "error", "error_description", "scope"):
        _clear_query_param(key)
    if not keep_handoff:
        _clear_query_param("auth_handoff")


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
    st.session_state.pop("google_signin_url", None)
    log.info("oauth_handoff_restored", handoff_id=handoff_id[:8] + "…")
    return True


def _persist_session(session: Any) -> None:
    st.session_state["sb_access_token"] = session.access_token
    st.session_state["sb_refresh_token"] = session.refresh_token
    st.session_state["user"] = {
        "id": str(session.user.id),
        "email": session.user.email or "",
    }
    st.session_state.pop("google_signin_url", None)


def _clear_auth_state() -> None:
    for key in list(st.session_state.keys()):
        if (
            key
            in (
                "user",
                "sb_access_token",
                "sb_refresh_token",
                "google_signin_url",
                "google_signin_redirect",
            )
            or str(key).startswith(StreamlitAuthStorage.PREFIX)
        ):
            st.session_state.pop(key, None)


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


def _mark_legal_document_opened(document_key: str) -> None:
    """Track that the user opened a legal popup (compliance audit trail)."""
    st.session_state[f"{document_key}_viewed"] = True
    st.session_state[f"{document_key}_opened_at"] = (
        datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    )


def _legal_documents_viewed() -> bool:
    return bool(
        st.session_state.get("terms_viewed") and st.session_state.get("privacy_viewed")
    )


@st.dialog("Terms of Service", width="large")
def _show_terms_dialog() -> None:
    """Same-page modal popup for must-read Terms of Service."""
    _mark_legal_document_opened("terms")
    with st.container(height=350):
        st.markdown(get_terms_of_service_text())
    st.caption("Scroll to review all sections before agreeing.")
    if st.button("Close", use_container_width=True, key="terms_dialog_close"):
        st.rerun()


@st.dialog("Privacy Policy", width="large")
def _show_privacy_dialog() -> None:
    """Same-page modal popup for must-read Privacy Policy."""
    _mark_legal_document_opened("privacy")
    with st.container(height=350):
        st.markdown(get_privacy_policy_text())
    st.caption("Scroll to review all sections before agreeing.")
    if st.button("Close", use_container_width=True, key="privacy_dialog_close"):
        st.rerun()


_AUTH_LEGAL_LINK_STYLE = """
<style>
div:has(> .auth-legal-links-marker) button[data-testid="baseButton-secondary"] {
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
div:has(> .auth-legal-links-marker) button[data-testid="baseButton-secondary"] p {
  color: inherit!important;
  text-decoration: inherit!important;
  margin: 0!important;
}
</style>
"""


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
    process_google_signin_callback()
    _restore_auth_handoff()
    restore_session_from_tokens()

    if get_logged_in_user():
        return True

    left, center, right = st.columns([1, 1.2, 1])
    with center:
        st.markdown(f"## 🏠 {APP_NAME}")
        st.caption("Sign in to access your private knowledge base and run analyses.")

        login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

        with login_tab:
            st.markdown("##### Sign in with Google")

            redirect_warning = _oauth_redirect_config_warning()
            if redirect_warning:
                st.warning(redirect_warning)

            try:
                if not _get_google_web_client_id():
                    st.error(
                        "Google sign-in is not configured. Add `GOOGLE_WEB_CLIENT_ID` to secrets."
                    )
                elif not _get_google_web_client_secret():
                    st.error(
                        "Google sign-in needs `GOOGLE_WEB_CLIENT_SECRET` in Streamlit secrets. "
                        "In Google Cloud Console → Credentials → your **Web** OAuth client "
                        f"(`{_get_google_web_client_id()}`), copy **Client secret** into "
                        "`.streamlit/secrets.toml` and Streamlit Cloud secrets. "
                        "Do not use `GOOGLE_CLIENT_SECRET` (that is the Desktop Gmail client)."
                    )
                else:
                    redirect_to = _get_redirect_url()
                    cached_redirect = st.session_state.get("google_signin_redirect")
                    if (
                        not st.session_state.get("google_signin_url")
                        or cached_redirect != redirect_to
                    ):
                        st.session_state["google_signin_redirect"] = redirect_to
                        st.session_state["google_signin_url"] = build_google_signin_url(
                            redirect_to
                        )
                    _render_google_signin_button(st.session_state["google_signin_url"])
                    st.caption(
                        "You will return here automatically after Google approves access."
                    )
                    if not _is_localhost_url(redirect_to):
                        with st.expander("Google OAuth setup (admin)", expanded=False):
                            st.markdown(_google_redirect_uri_setup_hint(redirect_to))
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
            if "privacy_viewed" not in st.session_state:
                st.session_state["privacy_viewed"] = False

            # Track interaction (non-empty inputs or checkbox changes).
            if signup_email or signup_password or signup_confirm:
                st.session_state["signup_has_interacted"] = True

            row_cb, row_space, row_text, row_links = st.columns(
                [0.06, 0.015, 0.42, 0.505], gap="small"
            )
            with row_cb:
                agreed = st.checkbox(
                    "agree",
                    key="policy_agreed",
                    disabled=not _legal_documents_viewed(),
                    label_visibility="collapsed",
                )
            with row_space:
                st.empty()
            with row_text:
                st.markdown(
                    '<p class="auth-agreement-text">I have read and agree to the&nbsp;</p>',
                    unsafe_allow_html=True,
                )
            with row_links:
                st.markdown(
                    f'{_AUTH_LEGAL_LINK_STYLE}<div class="auth-legal-links-marker"></div>',
                    unsafe_allow_html=True,
                )
                link_cols = st.columns(2, gap="small")
                with link_cols[0]:
                    if st.button(
                        "Terms of Service",
                        key="open_terms_modal",
                        type="secondary",
                        help="Open Terms of Service",
                    ):
                        _show_terms_dialog()
                with link_cols[1]:
                    if st.button(
                        "Privacy Policy",
                        key="open_privacy_modal",
                        type="secondary",
                        help="Open Privacy Policy",
                    ):
                        _show_privacy_dialog()

            if not _legal_documents_viewed():
                missing = []
                if not st.session_state["terms_viewed"]:
                    missing.append("Terms of Service")
                if not st.session_state["privacy_viewed"]:
                    missing.append("Privacy Policy")
                st.caption(
                    "Open "
                    + " and ".join(f"**{name}**" for name in missing)
                    + " to enable agreement."
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
