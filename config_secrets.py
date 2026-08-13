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


def _parse_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file (no export/, no multiline)."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        normalized = normalize_secret_value(value)
        if normalized is not None:
            out[key] = normalized
    return out


def _merge_into_environ(
    values: dict[str, Any],
    *,
    overwrite_blank_env: bool,
) -> None:
    import os

    for key, value in values.items():
        normalized = normalize_secret_value(value)
        if not normalized:
            continue
        existing = os.getenv(key)
        if existing is not None and str(existing).strip():
            # Normalize already-present values (e.g. quoted Docker env_file entries).
            cleaned = normalize_secret_value(existing)
            if cleaned:
                os.environ[key] = cleaned
        elif overwrite_blank_env or existing is None:
            os.environ[key] = normalized


def load_local_secrets_into_environ(
    *,
    secrets_path: Path | None = None,
    overwrite_blank_env: bool = True,
) -> bool:
    """
    Load local secrets into ``os.environ``.

    Order:
    1. Root ``.env`` (primary for CapEigen API / Docker / CLI)
    2. Optional ``secrets.toml`` next to this module, or ``secrets_path`` (tests)

    Existing non-blank env vars are kept (but quote-normalized).
    Returns True when at least one file was loaded.
    """
    root = Path(__file__).resolve().parent
    loaded = False

    dotenv_path = root / ".env"
    if dotenv_path.exists():
        try:
            _merge_into_environ(_parse_dotenv(dotenv_path), overwrite_blank_env=overwrite_blank_env)
            loaded = True
        except Exception:
            pass

    path = secrets_path or (root / "secrets.toml")
    if path.exists():
        try:
            _merge_into_environ(_parse_secrets_toml(path), overwrite_blank_env=overwrite_blank_env)
            loaded = True
        except Exception:
            pass

    return loaded
