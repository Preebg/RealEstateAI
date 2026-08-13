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

    Raises ValueError with a clear message when resolution fails.
    """
    try:
        socket.getaddrinfo(hostname, None, socket.AF_INET)
    except socket.gaierror as exc:
        raise ValueError(
            f"{label} hostname {hostname!r} does not resolve on this machine ({exc}). "
            "Check DNS / VPN / SUPABASE_URL."
        ) from exc


def _parse_secrets_toml(path: Path) -> dict[str, Any]:
    """Parse a flat TOML secrets file into a dict of stringifiable values."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as secrets_file:
        return tomllib.load(secrets_file)


def load_local_secrets_into_environ(
    *,
    secrets_path: Path | None = None,
    overwrite_blank_env: bool = True,
) -> bool:
    """
    Optionally load a local TOML secrets file into ``os.environ``.

    Primary configuration is ``.env`` / process environment. When ``secrets_path``
    is provided (tests) or a ``secrets.toml`` exists next to this module, values
    fill blank env keys only.

    Returns True when a secrets file was found and parsed.
    """
    import os

    path = secrets_path or Path(__file__).resolve().parent / "secrets.toml"
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
