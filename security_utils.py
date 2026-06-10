"""Shared security helpers (HTML escaping, log redaction)."""

from __future__ import annotations

from html import escape

_SENSITIVE_LOG_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "share_token",
        "password",
        "api_key",
        "apikey",
        "authorization",
        "sb_access_token",
        "sb_refresh_token",
        "code_verifier",
        "p_access_token",
        "p_refresh_token",
        "supabase_service_role_key",
        "gemini_api_key",
    }
)


def escape_html(text: object) -> str:
    """Escape user-controlled text for safe embedding in HTML."""
    if text is None:
        return ""
    return escape(str(text), quote=True)


def redact_log_context(context: dict[str, object]) -> dict[str, object]:
    """Mask secrets before structured logging or Sentry extras."""
    redacted: dict[str, object] = {}
    for key, value in context.items():
        lowered = str(key).lower()
        if lowered in _SENSITIVE_LOG_KEYS or lowered.endswith("_token"):
            redacted[key] = "[redacted]"
        else:
            redacted[key] = value
    return redacted
