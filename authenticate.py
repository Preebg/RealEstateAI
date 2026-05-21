"""Supabase authentication (Google OAuth PKCE + email/password)."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import streamlit as st
from supabase import Client, create_client

# Survives full-page OAuth redirect when Streamlit session_state is wiped.
_PKCE_PENDING_FILE = Path(__file__).resolve().parent / ".streamlit" / "oauth_pkce_pending.json"
_PKCE_TTL_SECONDS = 900  # 15 minutes


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


def get_supabase() -> Client:
    """Return a Supabase client with Streamlit-backed auth storage."""
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_KEY")

    try:
        from supabase.lib.client_options import ClientOptions

        options = ClientOptions(storage=StreamlitAuthStorage())
        return create_client(url, key, options)
    except Exception:
        return create_client(url, key)


def _get_redirect_url() -> str:
    """OAuth redirect URL — must match Supabase Auth redirect allow-list."""
    explicit = os.getenv("OAUTH_REDIRECT_URL")
    if explicit:
        return explicit.rstrip("/")
    try:
        return str(st.secrets["OAUTH_REDIRECT_URL"]).rstrip("/")
    except Exception:
        pass
    try:
        base = str(st.context.url).rstrip("/")
        if base:
            return base
    except Exception:
        pass
    return "http://localhost:8501"


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
    """Write PKCE verifier to disk so callback survives Streamlit session reset."""
    _PKCE_PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "code_verifier": code_verifier,
        "code_challenge": code_challenge,
        "created_at": time.time(),
    }
    _PKCE_PENDING_FILE.write_text(json.dumps(payload), encoding="utf-8")
    st.session_state["pkce_code_verifier"] = code_verifier


def _load_pending_pkce() -> dict[str, Any] | None:
    """Load PKCE material written before the Google redirect."""
    if not _PKCE_PENDING_FILE.exists():
        return None
    try:
        data = json.loads(_PKCE_PENDING_FILE.read_text(encoding="utf-8"))
        created = float(data.get("created_at", 0))
        if time.time() - created > _PKCE_TTL_SECONDS:
            _clear_pending_pkce()
            return None
        return data
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _clear_pending_pkce() -> None:
    try:
        if _PKCE_PENDING_FILE.exists():
            _PKCE_PENDING_FILE.unlink()
    except OSError:
        pass


def _query_param(name: str) -> str | None:
    value = st.query_params.get(name)
    if isinstance(value, list):
        return value[0] if value else None
    return str(value) if value is not None else None


def _clear_oauth_query_params() -> None:
    """Remove OAuth callback params so the user can retry cleanly."""
    for key in ("code", "state", "error", "error_description", "pkce_verifier"):
        if key in st.query_params:
            del st.query_params[key]


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
    Read PKCE verifier — disk file first (survives redirect), then session/SDK.
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


def _persist_session(session: Any) -> None:
    st.session_state["sb_access_token"] = session.access_token
    st.session_state["sb_refresh_token"] = session.refresh_token
    st.session_state["user"] = {
        "id": session.user.id,
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
            _persist_session(response.session)
            _clear_oauth_query_params()
            st.rerun()
        except Exception as exc:
            st.error(f"Sign-in failed: {exc}")
            _clear_oauth_query_params()
            _clear_pending_pkce()

    return True


def login_with_google() -> str:
    """
    Build Google OAuth URL with PKCE.
    Let Supabase manage OAuth `state` (CSRF) — do not pass a custom state value.
    Persist the code_verifier to disk for the post-redirect callback.
    """
    redirect_to = _get_redirect_url()
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
    except Exception:
        pass

    # Fallback: manual authorize URL (no custom state — that causes "state is invalid").
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
    if response.session:
        _persist_session(response.session)
        return True, "Account created. You are now signed in."

    return True, (
        "Account created. Check your email to confirm your address, then log in."
    )


def get_logged_in_user() -> dict[str, str] | None:
    """Return {'id': uid, 'email': email} for the current session, or None."""
    user = st.session_state.get("user")
    if not user or not user.get("id"):
        return None
    return {"id": user["id"], "email": user.get("email", "")}


def logout() -> None:
    """Sign out and clear Streamlit session auth state."""
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
    if "user" in st.session_state:
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
        _clear_auth_state()


def get_authenticated_client() -> Client | None:
    """Supabase client with the logged-in user's JWT (required for RLS)."""
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


def get_db_client() -> Client:
    """Prefer authenticated client; fall back to anon (RLS may block)."""
    auth_client = get_authenticated_client()
    return auth_client if auth_client is not None else get_supabase()


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
    restore_session_from_tokens()

    if get_logged_in_user():
        return True

    left, center, right = st.columns([1, 1.2, 1])
    with center:
        st.markdown("## 🏠 AI Property Analyzer")
        st.caption("Sign in to access your private knowledge base and run analyses.")

        login_tab, signup_tab = st.tabs(["Log in", "Sign up"])

        with login_tab:
            st.markdown("##### Sign in with Google")

            try:
                if not st.session_state.get("google_oauth_url"):
                    st.session_state["google_oauth_url"] = login_with_google()
                oauth_url = st.session_state["google_oauth_url"]
                st.link_button(
                    "Continue with Google",
                    oauth_url,
                    type="primary",
                    use_container_width=True,
                    help="Opens Google sign-in in this browser tab.",
                )
                if st.button("Refresh Google sign-in link", use_container_width=True):
                    st.session_state.pop("google_oauth_url", None)
                    st.session_state.pop("pkce_code_verifier", None)
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
            signup_email = st.text_input(
                "Email", key="auth_signup_email", placeholder="you@email.com"
            )
            signup_password = st.text_input(
                "Password", type="password", key="auth_signup_password"
            )
            signup_confirm = st.text_input(
                "Confirm password", type="password", key="auth_signup_confirm"
            )

            if st.button(
                "Create account",
                type="primary",
                use_container_width=True,
                key="auth_signup_btn",
            ):
                if not signup_email or not signup_password:
                    st.warning("Enter an email and password.")
                elif signup_password != signup_confirm:
                    st.warning("Passwords do not match.")
                elif len(signup_password) < 6:
                    st.warning("Password must be at least 6 characters.")
                else:
                    try:
                        _, message = sign_up_with_email(signup_email, signup_password)
                        st.success(message)
                        if get_logged_in_user():
                            st.rerun()
                    except Exception as exc:
                        st.error(f"Sign-up failed: {exc}")

            st.caption("Already have an account? Use the **Log in** tab.")

    return False
