"""Load and save admin-editable Terms and Privacy documents."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from postgrest.exceptions import APIError

from authenticate import get_db_client, get_service_client
from app_logging import configure_logging, report_error
from legal import LEGAL_SLUGS, default_legal_document

log = configure_logging("legal_documents")


def _data_client() -> Any:
    return get_service_client() or get_db_client()


def _normalize_slug(slug: str) -> str:
    key = (slug or "").strip().lower()
    if key not in LEGAL_SLUGS:
        raise ValueError("Unknown legal document. Use 'terms' or 'privacy'.")
    return key


def _row_to_document(row: dict[str, Any], *, slug: str) -> dict[str, Any]:
    fallback = default_legal_document(slug)
    effective = row.get("effective_date") or fallback["effective_date"]
    if hasattr(effective, "isoformat"):
        effective = effective.isoformat()
    updated = row.get("updated_at")
    if hasattr(updated, "isoformat"):
        updated = updated.isoformat()
    return {
        "slug": slug,
        "title": str(row.get("title") or fallback["title"]),
        "body": str(row.get("body") or fallback["body"]),
        "effective_date": str(effective),
        "updated_at": str(updated) if updated else None,
        "updated_by": str(row["updated_by"]) if row.get("updated_by") else None,
        "is_default": False,
    }


def get_legal_document(slug: str) -> dict[str, Any]:
    """Return the published document, or built-in copy when none is stored."""
    key = _normalize_slug(slug)
    fallback = default_legal_document(key)
    try:
        response = (
            _data_client()
            .table("legal_documents")
            .select("slug,title,body,effective_date,updated_at,updated_by")
            .eq("slug", key)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        report_error(log, "legal_document_read_failed", exc, slug=key)
        return {**fallback, "updated_at": None, "updated_by": None, "is_default": True}
    rows = response.data or []
    if not rows:
        return {**fallback, "updated_at": None, "updated_by": None, "is_default": True}
    return _row_to_document(rows[0], slug=key)


def save_legal_document(
    slug: str,
    *,
    body: str,
    title: str | None = None,
    effective_date: str | None = None,
    updated_by: str | None = None,
) -> dict[str, Any]:
    """Upsert Terms or Privacy. Empty body is rejected."""
    key = _normalize_slug(slug)
    fallback = default_legal_document(key)
    cleaned = (body or "").strip()
    if len(cleaned) < 40:
        raise ValueError("Legal text is too short.")
    heading = (title or "").strip() or fallback["title"]
    raw_date = (effective_date or "").strip() or date.today().isoformat()
    try:
        parsed = date.fromisoformat(raw_date)
    except ValueError as exc:
        raise ValueError("Effective date must be YYYY-MM-DD.") from exc
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "slug": key,
        "title": heading[:120],
        "body": cleaned,
        "effective_date": parsed.isoformat(),
        "updated_at": now,
        "updated_by": (updated_by or "")[:200] or None,
    }
    try:
        (
            _data_client()
            .table("legal_documents")
            .upsert(row, on_conflict="slug")
            .execute()
        )
    except APIError as exc:
        report_error(log, "legal_document_save_failed", exc, slug=key)
        raise RuntimeError("Could not save legal document.") from exc
    return get_legal_document(key)
