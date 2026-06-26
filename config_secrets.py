"""Normalize secrets and validate network endpoints for headless CLI runs."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def normalize_secret_value(value: Any) -> str | None:
    """Strip whitespace, BOM, and matching quote wrappers from a secret value."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).strip().lstrip("\ufeff")
    if not text:
        return None
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()
    return text or None


def normalize_supabase_url(url: str) -> str:
    """Return a canonical Supabase REST URL suitable for create_client."""
    cleaned = normalize_secret_value(url)
    if not cleaned:
        raise ValueError("SUPABASE_URL is empty")

    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            "SUPABASE_URL must look like https://<project-ref>.supabase.co "
            f"(got {cleaned!r})"
        )
    if parsed.username or parsed.password:
        raise ValueError(
            "SUPABASE_URL must be the REST API URL, not a Postgres connection string."
        )

    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def resolve_hostname(hostname: str, *, label: str) -> None:
    """
    Verify DNS can resolve hostname on this machine.

    Tries IPv4 first (common fix on Windows harvest hosts with broken IPv6 DNS).
    """
    host = hostname.strip().rstrip(".")
    if not host:
        raise ValueError(f"{label} hostname is empty")

    last_error: socket.gaierror | None = None
    for family in (socket.AF_INET, socket.AF_UNSPEC):
        try:
            socket.getaddrinfo(host, None, family, socket.SOCK_STREAM)
            return
        except socket.gaierror as exc:
            last_error = exc

    raise OSError(
        f"DNS lookup failed for {label} host {host!r} (getaddrinfo: {last_error}). "
        "On the harvest machine, confirm internet access, DNS settings, firewall, "
        "and that SUPABASE_URL in .streamlit/secrets.toml has no extra quotes or spaces."
    ) from last_error


def verify_https_endpoint(url: str, *, label: str) -> str:
    """Normalize an HTTPS URL and confirm its hostname resolves."""
    cleaned = normalize_secret_value(url)
    if not cleaned:
        raise ValueError(f"{label} is empty")

    parsed = urlparse(cleaned)
    hostname = parsed.hostname
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError(f"{label} must be a valid http(s) URL (got {cleaned!r})")

    resolve_hostname(hostname, label=label)
    return cleaned.rstrip("/")


def _parse_secrets_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as secrets_file:
        try:
            import tomllib

            return tomllib.load(secrets_file)
        except ImportError:
            import tomli

            return tomli.load(secrets_file)


def load_streamlit_secrets_into_environ(
    *,
    secrets_path: Path | None = None,
    overwrite_blank_env: bool = True,
) -> bool:
    """
    Load .streamlit/secrets.toml into os.environ for headless CLI runs.

    Returns True when a secrets file was found and parsed.
    """
    import os

    path = secrets_path or Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not path.exists():
        return False

    try:
        secrets = _parse_secrets_toml(path)
    except Exception:
        return False

    for key, value in secrets.items():
        normalized = normalize_secret_value(value)
        if not normalized:
            continue
        existing = os.getenv(key)
        if existing is not None and str(existing).strip():
            os.environ[key] = normalize_secret_value(existing) or str(existing).strip()
        elif overwrite_blank_env or existing is None:
            os.environ[key] = normalized
    return True
