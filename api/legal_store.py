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


def _normalize_date(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    text = str(value).strip()
    return text[:10] if text else None


def get_legal_acceptance(user_id: str) -> dict[str, Any] | None:
    """Return the user's latest acceptance row, or None."""
    uid = (user_id or "").strip()
    if not uid:
        return None
    try:
        response = (
            _data_client()
            .table("legal_acceptances")
            .select("user_id,privacy_effective_date,terms_effective_date,accepted_at")
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        report_error(log, "legal_acceptance_read_failed", exc, user_id=uid)
        return None
    rows = response.data or []
    if not rows:
        return None
    row = rows[0]
    accepted_at = row.get("accepted_at")
    if hasattr(accepted_at, "isoformat"):
        accepted_at = accepted_at.isoformat()
    return {
        "user_id": uid,
        "privacy_effective_date": _normalize_date(row.get("privacy_effective_date")),
        "terms_effective_date": _normalize_date(row.get("terms_effective_date")),
        "accepted_at": str(accepted_at) if accepted_at else None,
    }


def get_legal_acceptance_status(user_id: str) -> dict[str, Any]:
    """Compare stored acceptance to the current published Terms + Privacy dates."""
    privacy = get_legal_document("privacy")
    terms = get_legal_document("terms")
    current_privacy = str(privacy["effective_date"])
    current_terms = str(terms["effective_date"])
    acceptance = get_legal_acceptance(user_id)
    accepted_privacy = acceptance.get("privacy_effective_date") if acceptance else None
    accepted_terms = acceptance.get("terms_effective_date") if acceptance else None
    needs_acceptance = (
        accepted_privacy != current_privacy or accepted_terms != current_terms
    )
    return {
        "needs_acceptance": needs_acceptance,
        "privacy_effective_date": current_privacy,
        "terms_effective_date": current_terms,
        "accepted_privacy_effective_date": accepted_privacy,
        "accepted_terms_effective_date": accepted_terms,
        "accepted_at": acceptance.get("accepted_at") if acceptance else None,
        "privacy_title": privacy["title"],
        "terms_title": terms["title"],
    }


def save_legal_acceptance(user_id: str) -> dict[str, Any]:
    """Record acceptance of the currently published Terms + Privacy effective dates."""
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    privacy = get_legal_document("privacy")
    terms = get_legal_document("terms")
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "user_id": uid,
        "privacy_effective_date": str(privacy["effective_date"]),
        "terms_effective_date": str(terms["effective_date"]),
        "accepted_at": now,
    }
    try:
        (
            _data_client()
            .table("legal_acceptances")
            .upsert(row, on_conflict="user_id")
            .execute()
        )
    except APIError as exc:
        report_error(log, "legal_acceptance_save_failed", exc, user_id=uid)
        detail = str(getattr(exc, "message", None) or exc)
        lower = detail.lower()
        if (
            "legal_acceptances" in lower
            or "pgrst205" in lower
            or "schema cache" in lower
            or "does not exist" in lower
        ):
            raise RuntimeError(
                "Legal acceptance storage is not set up on this database. "
                "Apply docker/postgres/init/08_legal_acceptances.sql to local Postgres "
                "(existing volumes do not re-run init), then reload PostgREST."
            ) from exc
        raise RuntimeError("Could not save legal acceptance.") from exc
    except Exception as exc:  # noqa: BLE001
        report_error(log, "legal_acceptance_save_failed", exc, user_id=uid)
        raise RuntimeError("Could not save legal acceptance.") from exc
    return get_legal_acceptance_status(uid)
