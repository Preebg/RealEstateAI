# knowledge_base.py
from __future__ import annotations

import os
import re
from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError

from app_logging import configure_logging, report_error
from authenticate import get_db_client, get_logged_in_user, in_streamlit_app
from finance import (
    normalize_monthly_insurance,
    normalize_percent_rate,
    normalize_tax_rate_percent,
)

log = configure_logging("knowledge_base")

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore[misc, assignment]


def is_valid_uuid(value: str | None) -> bool:
    """Return True when value is a well-formed UUID (Supabase auth user id)."""
    if not value or not str(value).strip():
        return False
    try:
        UUID(str(value).strip())
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _get_secret(name: str) -> str:
    """Resolve credentials from environment first, then Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value
    if st is not None and name in st.secrets:
        return str(st.secrets[name])
    raise EnvironmentError(
        f"{name} not set. Export it or add to Streamlit secrets."
    )


def get_admin_uid() -> str | None:
    """
    Admin UID — can read all harvested rows in addition to their own.
    Set ADMIN_USER_ID in Streamlit secrets or environment.
    """
    uid = os.getenv("ADMIN_USER_ID", "").strip()
    if uid:
        return uid if is_valid_uuid(uid) else None
    if st is not None and "ADMIN_USER_ID" in st.secrets:
        secret_uid = str(st.secrets["ADMIN_USER_ID"]).strip()
        return secret_uid if is_valid_uuid(secret_uid) else None
    return None


def get_client():
    """Returns a Supabase client (authenticated when user is logged in)."""
    return get_db_client()


def _resolve_user_id(user_id: str | None) -> str | None:
    if user_id and is_valid_uuid(user_id):
        return str(user_id).strip()
    if in_streamlit_app():
        user = get_logged_in_user()
        return user["id"] if user else None
    return None


def _fetch_canonical_properties() -> list[dict[str, Any]]:
    """Return all shared canonical property rows (one per address)."""
    if in_streamlit_app():
        from share_access import fetch_guest_portfolio, is_guest_viewer

        if is_guest_viewer():
            return fetch_guest_portfolio()

    supabase = get_client()
    try:
        response = supabase.table("properties").select("*").execute()
    except APIError as exc:
        report_error(log, "kb_canonical_fetch_failed", exc)
        return []
    return response.data or []


def _fetch_user_overrides_map(user_id: str) -> dict[str, dict[str, Any]]:
    """Map property_id -> override row for the given user."""
    if not is_valid_uuid(user_id):
        return {}
    supabase = get_client()
    try:
        response = (
            supabase.table("user_property_overrides")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
    except APIError as exc:
        report_error(log, "kb_override_fetch_failed", exc, user_id=user_id)
        return {}
    rows = response.data or []
    return {
        str(row["property_id"]): row
        for row in rows
        if row.get("property_id")
    }


def _merge_with_user_override(
    canonical: dict[str, Any],
    override: dict[str, Any] | None,
) -> dict[str, Any]:
    """Layer per-user assumptions on top of immutable canonical AI/property facts."""
    merged = _normalize_record_numerics(dict(canonical))
    if not override:
        return merged

    if override.get("rent") is not None:
        merged["rent"] = override["rent"]
    if override.get("maint_percent") is not None:
        merged["maint_percent"] = override["maint_percent"]
    if override.get("vacancy_rate") is not None:
        merged["user_vacancy_rate"] = override["vacancy_rate"]
    if override.get("management_fee") is not None:
        merged["user_management_fee"] = override["management_fee"]
    merged["is_outlier"] = bool(override.get("is_outlier"))
    merged["override_notes"] = override.get("override_notes") or ""
    merged["has_user_override"] = True
    merged["user_override_id"] = override.get("id")
    return merged


def _fetch_properties(user_id: str | None = None) -> list[dict[str, Any]]:
    """Canonical properties merged with the current user's overrides."""
    uid = _resolve_user_id(user_id)
    canonical_rows = _fetch_canonical_properties()
    if not uid:
        return [_normalize_record_numerics(row) for row in canonical_rows]

    overrides = _fetch_user_overrides_map(uid)
    merged: list[dict[str, Any]] = []
    for row in canonical_rows:
        prop_id = str(row.get("id", ""))
        merged.append(_merge_with_user_override(row, overrides.get(prop_id)))
    return merged


def get_property_id_by_address(address: str) -> str | None:
    """Resolve canonical property UUID from address."""
    if not address or not str(address).strip():
        return None
    key = normalize_address_key(address)
    for row in _fetch_canonical_properties():
        if normalize_address_key(str(row.get("address", ""))) == key:
            pid = row.get("id")
            return str(pid) if pid else None
    return None


def get_kb_raw_data(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """Fetch properties keyed by normalized address for reliable lookup."""
    rows = _fetch_properties(user_id)
    if not rows:
        return {}
    return {
        normalize_address_key(item["address"]): item
        for item in rows
        if item.get("address")
    }


def lookup_property(address: str, user_id: str | None = None) -> dict[str, Any] | None:
    """Instant Pull: return a cached property for this address if it exists."""
    if not address or not address.strip():
        return None

    if in_streamlit_app():
        from share_access import fetch_guest_property, is_guest_viewer

        if is_guest_viewer():
            hit = fetch_guest_property(address=address)
            if hit:
                record = _normalize_record_numerics(hit)
                record["from_kb"] = True
                return record
            return None

    data = get_kb_raw_data(user_id)
    hit = data.get(normalize_address_key(address))
    if hit:
        record = _normalize_record_numerics(hit)
        record["from_kb"] = True
        return record
    return None


RENT_OUTLIER_DEVIATION_PCT = 50.0

USER_OVERRIDE_COLUMNS = (
    "rent",
    "maint_percent",
    "vacancy_rate",
    "management_fee",
    "is_outlier",
    "override_notes",
)

CANONICAL_PROPERTY_COLUMNS = (
    "address",
    "user_id",
    "zip_code",
    "state_code",
    "price",
    "year_built",
    "tax_rate",
    "hoa",
    "insurance",
    "summary",
    "predicted_value",
    "prediction_reasoning",
    "location_score",
    "property_label",
    "property_category",
    "from_kb",
    "quantum_risk_score",
    "sources",
    "market_city",
    "square_footage",
    "property_condition",
    "appreciation_forecast",
    "forecast_rate",
    "forecast_growth",
    "ai_vacancy_rate",
    "ai_management_fee",
    "monthly_net_cash_flow",
    "original_ai_rent",
    "original_ai_maint",
)


def normalize_address_key(address: str) -> str:
    """Canonical address key for duplicate detection."""
    return " ".join(str(address or "").strip().lower().split())


_ZIPCODE_PATTERN = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def parse_zipcode_from_address(address: str | None) -> str | None:
    """
    Extract a 5-digit US ZIP code from a property address string.

    Examples:
        "123 Main St, Rochester, NY 14607" -> "14607"
        "456 Oak Ave, Syracuse, NY 13202-1234" -> "13202"
    """
    if not address or not str(address).strip():
        return None
    matches = _ZIPCODE_PATTERN.findall(str(address))
    if not matches:
        return None
    return matches[-1]


def _apply_zipcode_from_address(payload: dict[str, Any]) -> None:
    """Populate zip_code on save when it can be parsed from the address."""
    address = payload.get("address")
    if not address:
        return
    zip_code = parse_zipcode_from_address(str(address))
    if zip_code:
        payload["zip_code"] = zip_code


def get_scanned_addresses(user_id: str | None = None) -> set[str]:
    """Return normalized addresses in the shared canonical catalog."""
    _ = user_id  # canonical catalog is shared across users
    return {
        normalize_address_key(row["address"])
        for row in _fetch_canonical_properties()
        if row.get("address")
    }


def is_property_already_scanned(address: str, user_id: str | None = None) -> bool:
    """True when this address already exists in the KB for the scoped user."""
    if not address or not str(address).strip():
        return False
    return normalize_address_key(address) in get_scanned_addresses(user_id)


def get_ai_baseline_rent(record: dict[str, Any]) -> float:
    """AI-suggested monthly rent (falls back to saved rent for legacy rows)."""
    if record.get("original_ai_rent") is not None:
        try:
            return float(record["original_ai_rent"])
        except (TypeError, ValueError):
            pass
    try:
        return float(record.get("rent") or 0)
    except (TypeError, ValueError):
        return 0.0


def get_ai_baseline_maint(record: dict[str, Any]) -> float:
    """AI-suggested maintenance % (falls back to saved maint for legacy rows)."""
    if record.get("original_ai_maint") is not None:
        try:
            return float(record["original_ai_maint"])
        except (TypeError, ValueError):
            pass
    try:
        return float(record.get("maint_percent") or 0)
    except (TypeError, ValueError):
        return 0.0


def get_official_rent(record: dict[str, Any]) -> float | None:
    """User-confirmed rent when it differs from the AI baseline."""
    if not record.get("has_user_override") or record.get("rent") is None:
        return None
    official = float(record["rent"])
    ai = get_ai_baseline_rent(record)
    if abs(official - ai) < 0.01:
        return None
    return official


def get_effective_display_rent(record: dict[str, Any]) -> float:
    """Rent for sliders: saved user override, else AI baseline."""
    if record.get("has_user_override") and record.get("rent") is not None:
        try:
            return float(record["rent"])
        except (TypeError, ValueError):
            pass
    return get_ai_baseline_rent(record)


def get_effective_display_maint(record: dict[str, Any]) -> float:
    """Maintenance % for sliders: saved user override, else AI baseline."""
    if record.get("has_user_override") and record.get("maint_percent") is not None:
        try:
            return float(record["maint_percent"])
        except (TypeError, ValueError):
            pass
    return get_ai_baseline_maint(record)


def get_effective_display_vacancy(record: dict[str, Any]) -> float:
    """Vacancy reserve % for sliders."""
    if record.get("user_vacancy_rate") is not None:
        try:
            return float(record["user_vacancy_rate"])
        except (TypeError, ValueError):
            pass
    try:
        return float(record.get("ai_vacancy_rate") or 5.0)
    except (TypeError, ValueError):
        return 5.0


def get_effective_display_management_fee(record: dict[str, Any]) -> float:
    """Management fee % for sliders."""
    if record.get("user_management_fee") is not None:
        try:
            return float(record["user_management_fee"])
        except (TypeError, ValueError):
            pass
    try:
        return float(record.get("ai_management_fee") or 10.0)
    except (TypeError, ValueError):
        return 10.0


def user_has_override_changes(
    record: dict[str, Any],
    *,
    rent: float,
    maint_percent: float,
    vacancy_rate: float,
    management_fee: float,
) -> bool:
    """True when slider values differ from AI baselines."""
    if abs(rent - get_ai_baseline_rent(record)) > 0.01:
        return True
    if abs(maint_percent - get_ai_baseline_maint(record)) > 0.01:
        return True
    if abs(vacancy_rate - float(record.get("ai_vacancy_rate") or 5.0)) > 0.01:
        return True
    if abs(management_fee - float(record.get("ai_management_fee") or 10.0)) > 0.01:
        return True
    return False


def _normalize_record_numerics(record: dict[str, Any]) -> dict[str, Any]:
    """Apply read-time normalization for legacy or malformed stored values."""
    normalized = dict(record)
    if normalized.get("insurance") is not None:
        try:
            normalized["insurance"] = normalize_monthly_insurance(
                float(normalized["insurance"])
            )
        except (TypeError, ValueError):
            pass
    if normalized.get("tax_rate") is not None:
        try:
            normalized["tax_rate"] = normalize_tax_rate_percent(
                float(normalized["tax_rate"])
            )
        except (TypeError, ValueError):
            pass
    for fee_key in ("ai_vacancy_rate", "ai_management_fee"):
        if normalized.get(fee_key) is not None:
            try:
                normalized[fee_key] = normalize_percent_rate(float(normalized[fee_key]))
            except (TypeError, ValueError):
                pass
    if normalized.get("maint_percent") is not None:
        try:
            normalized["maint_percent"] = normalize_percent_rate(
                float(normalized["maint_percent"])
            )
        except (TypeError, ValueError):
            pass
    return normalized


def compute_rent_deviation_pct(ai_rent: float, user_rent: float) -> float:
    """Percent absolute difference between AI rent and user-adjusted rent."""
    ai = float(ai_rent or 0)
    user = float(user_rent or 0)
    if ai <= 0:
        return 100.0 if user != 0 else 0.0
    return abs(user - ai) / ai * 100.0


def is_rent_outlier(
    ai_rent: float,
    user_rent: float,
    *,
    threshold_pct: float = RENT_OUTLIER_DEVIATION_PCT,
) -> bool:
    return compute_rent_deviation_pct(ai_rent, user_rent) > threshold_pct


def _clean_numeric(payload: dict[str, Any], keys: list[str]) -> None:
    for key in keys:
        if key not in payload:
            continue
        val = str(payload[key]).replace("$", "").replace(",", "").strip()
        if not val:
            payload[key] = 0.0
            continue
        try:
            payload[key] = float(val)
        except (ValueError, TypeError):
            payload[key] = 0.0


def _prepare_canonical_payload(property_data: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Normalize and filter fields for the shared properties table."""
    payload = property_data.copy()
    payload["user_id"] = user_id

    for key in USER_OVERRIDE_COLUMNS:
        payload.pop(key, None)

    _clean_numeric(
        payload,
        [
            "price",
            "original_ai_rent",
            "original_ai_maint",
            "tax_rate",
            "location_score",
            "predicted_value",
            "quantum_risk_score",
            "square_footage",
            "appreciation_forecast",
            "forecast_rate",
            "forecast_growth",
            "ai_vacancy_rate",
            "ai_management_fee",
            "monthly_net_cash_flow",
            "insurance",
            "hoa",
        ],
    )

    if payload.get("insurance") is not None:
        payload["insurance"] = normalize_monthly_insurance(float(payload["insurance"]))
    if payload.get("tax_rate") is not None:
        payload["tax_rate"] = normalize_tax_rate_percent(float(payload["tax_rate"]))
    for fee_key in ("ai_vacancy_rate", "ai_management_fee"):
        if payload.get(fee_key) is not None:
            payload[fee_key] = normalize_percent_rate(float(payload[fee_key]))

    payload.setdefault("from_kb", False)

    if "year" in payload and "year_built" not in payload:
        payload["year_built"] = payload.pop("year")

    _apply_zipcode_from_address(payload)
    return {k: v for k, v in payload.items() if k in CANONICAL_PROPERTY_COLUMNS}


def save_canonical_property(
    property_data: dict[str, Any],
    user_id: str,
    *,
    show_errors: bool = True,
) -> Any:
    """Upsert shared property facts (AI baselines + harvest metadata)."""
    if in_streamlit_app():
        from share_access import is_guest_viewer

        if is_guest_viewer():
            if show_errors and st is not None:
                st.error("Sign in to save properties to the database.")
            return None

    if not user_id or not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")

    supabase = get_client()
    filtered_payload = _prepare_canonical_payload(property_data, user_id)

    try:
        response = (
            supabase.table("properties")
            .upsert(filtered_payload, on_conflict="address")
            .execute()
        )
    except APIError as exc:
        report_error(
            log,
            "kb_canonical_save_failed",
            exc,
            user_id=user_id,
            address=filtered_payload.get("address"),
        )
        if show_errors and st is not None:
            st.error(f"Failed to save property to Supabase: {exc}")
        return None

    log.info(
        "kb_canonical_save_success",
        user_id=user_id,
        address=filtered_payload.get("address"),
    )
    return response


def save_user_property_override(
    user_id: str,
    property_id: str,
    override_data: dict[str, Any],
    *,
    show_errors: bool = True,
) -> Any:
    """Upsert per-user underwriting assumptions for a canonical property."""
    if in_streamlit_app():
        from share_access import is_guest_viewer

        if is_guest_viewer():
            if show_errors and st is not None:
                st.error("Sign in to save your assumptions.")
            return None

    if not user_id or not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")
    if not property_id or not is_valid_uuid(property_id):
        raise ValueError(f"property_id must be a valid UUID, got: {property_id!r}")

    payload: dict[str, Any] = {
        "user_id": user_id,
        "property_id": property_id,
    }

    _clean_numeric(
        override_data,
        ["rent", "maint_percent", "vacancy_rate", "management_fee"],
    )
    for key in ("rent", "maint_percent", "vacancy_rate", "management_fee"):
        if key in override_data and override_data[key] is not None:
            value = float(override_data[key])
            if key in ("vacancy_rate", "management_fee"):
                value = normalize_percent_rate(value)
            elif key == "maint_percent":
                value = normalize_percent_rate(value)
            payload[key] = value

    payload["is_outlier"] = bool(override_data.get("is_outlier", False))
    payload["override_notes"] = str(override_data.get("override_notes") or "")

    supabase = get_client()
    try:
        response = (
            supabase.table("user_property_overrides")
            .upsert(payload, on_conflict="user_id,property_id")
            .execute()
        )
    except APIError as exc:
        report_error(
            log,
            "kb_override_save_failed",
            exc,
            user_id=user_id,
            property_id=property_id,
        )
        if show_errors and st is not None:
            st.error(f"Failed to save your assumptions: {exc}")
        return None

    log.info(
        "kb_override_save_success",
        user_id=user_id,
        property_id=property_id,
    )
    return response


def save_knowledge_base(
    property_data: dict[str, Any],
    user_id: str,
    *,
    show_errors: bool = True,
    save_override: bool = True,
):
    """
    Save canonical property facts and optionally the current user's overrides.

    Canonical rows are stored under the admin UID when configured so the catalog
    is shared; user-specific slider values go to user_property_overrides.
    """
    if not user_id:
        raise ValueError("user_id is required to save a property.")
    if not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")

    canonical_uid = get_admin_uid() or user_id
    canonical_response = save_canonical_property(
        property_data,
        user_id=canonical_uid,
        show_errors=show_errors,
    )
    if canonical_response is None:
        return None

    if not save_override:
        return canonical_response

    address = property_data.get("address")
    property_id = get_property_id_by_address(str(address or ""))
    if not property_id and canonical_response.data:
        row = canonical_response.data[0]
        if row.get("id"):
            property_id = str(row["id"])

    if not property_id:
        log.warning("kb_override_skipped", reason="missing_property_id", address=address)
        return canonical_response

    override_response = save_user_property_override(
        user_id,
        property_id,
        property_data,
        show_errors=show_errors,
    )
    return override_response or canonical_response


MAX_SAVED_PROPERTIES = 20


def count_user_saved_properties(user_id: str | None) -> int:
    """Number of properties bookmarked on the user's account."""
    if not user_id or not is_valid_uuid(user_id):
        return 0
    return len(_fetch_user_saved_rows(user_id))


def _fetch_user_saved_rows(user_id: str) -> list[dict[str, Any]]:
    """Return bookmark rows for the user, newest first."""
    if not is_valid_uuid(user_id):
        return []
    supabase = get_client()
    try:
        response = (
            supabase.table("user_saved_properties")
            .select("*")
            .eq("user_id", user_id)
            .order("saved_at", desc=True)
            .execute()
        )
    except APIError as exc:
        report_error(log, "kb_saved_fetch_failed", exc, user_id=user_id)
        return []
    return response.data or []


def is_property_saved_for_user(user_id: str, property_id: str | None) -> bool:
    """True when the user has bookmarked this canonical property."""
    if not is_valid_uuid(user_id) or not property_id or not is_valid_uuid(property_id):
        return False
    supabase = get_client()
    try:
        response = (
            supabase.table("user_saved_properties")
            .select("id")
            .eq("user_id", user_id)
            .eq("property_id", property_id)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        report_error(
            log,
            "kb_saved_lookup_failed",
            exc,
            user_id=user_id,
            property_id=property_id,
        )
        return False
    return bool(response.data)


def save_property_to_user_account(
    user_id: str,
    *,
    property_id: str | None = None,
    property_data: dict[str, Any] | None = None,
    override_payload: dict[str, Any] | None = None,
    show_errors: bool = True,
) -> str | None:
    """
    Bookmark a property on the user's account for later revisit.

    Ensures a canonical KB row exists when property_data is supplied.
    Optionally persists underwriting overrides. Returns property_id on success.
    """
    if in_streamlit_app():
        from share_access import is_guest_viewer

        if is_guest_viewer():
            if show_errors and st is not None:
                st.error("Sign in to save properties to your account.")
            return None

    if not user_id or not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")

    resolved_id = str(property_id).strip() if property_id else None
    if resolved_id and not is_valid_uuid(resolved_id):
        resolved_id = None

    if property_data and not resolved_id:
        payload = dict(property_data)
        if override_payload:
            payload.update(override_payload)
        kb_result = save_knowledge_base(
            payload,
            user_id,
            show_errors=show_errors,
            save_override=bool(override_payload),
        )
        if kb_result is None:
            return None
        address = payload.get("address")
        resolved_id = get_property_id_by_address(str(address or ""))
        if not resolved_id and getattr(kb_result, "data", None):
            row = kb_result.data[0]
            if row.get("id"):
                resolved_id = str(row["id"])
    elif resolved_id and override_payload:
        if save_user_property_override(
            user_id,
            resolved_id,
            override_payload,
            show_errors=show_errors,
        ) is None:
            return None

    if not resolved_id and property_data:
        resolved_id = get_property_id_by_address(str(property_data.get("address") or ""))

    if not resolved_id:
        if show_errors and st is not None:
            st.error("Could not resolve property ID for this address.")
        return None

    if not is_property_saved_for_user(user_id, resolved_id):
        if count_user_saved_properties(user_id) >= MAX_SAVED_PROPERTIES:
            if show_errors and st is not None:
                st.error(
                    f"You can save at most {MAX_SAVED_PROPERTIES} properties. "
                    "Remove one from your saved list to add another."
                )
            return None

    supabase = get_client()
    try:
        supabase.table("user_saved_properties").upsert(
            {"user_id": user_id, "property_id": resolved_id},
            on_conflict="user_id,property_id",
        ).execute()
    except APIError as exc:
        report_error(
            log,
            "kb_saved_upsert_failed",
            exc,
            user_id=user_id,
            property_id=resolved_id,
        )
        if show_errors and st is not None:
            st.error(f"Failed to save property to your account: {exc}")
        return None

    log.info(
        "kb_saved_upsert_success",
        user_id=user_id,
        property_id=resolved_id,
    )
    return resolved_id


def unsave_property_from_user_account(
    user_id: str,
    property_id: str,
    *,
    show_errors: bool = True,
) -> bool:
    """Remove a bookmarked property from the user's account."""
    if in_streamlit_app():
        from share_access import is_guest_viewer

        if is_guest_viewer():
            if show_errors and st is not None:
                st.error("Sign in to manage saved properties.")
            return False

    if not user_id or not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")
    if not property_id or not is_valid_uuid(property_id):
        raise ValueError(f"property_id must be a valid UUID, got: {property_id!r}")

    supabase = get_client()
    try:
        supabase.table("user_saved_properties").delete().eq(
            "user_id", user_id
        ).eq("property_id", property_id).execute()
    except APIError as exc:
        report_error(
            log,
            "kb_saved_delete_failed",
            exc,
            user_id=user_id,
            property_id=property_id,
        )
        if show_errors and st is not None:
            st.error(f"Failed to remove saved property: {exc}")
        return False

    log.info(
        "kb_saved_delete_success",
        user_id=user_id,
        property_id=property_id,
    )
    return True


def clear_all_saved_properties_from_user_account(
    user_id: str,
    *,
    show_errors: bool = True,
) -> bool:
    """Remove every bookmarked property from the user's account."""
    if in_streamlit_app():
        from share_access import is_guest_viewer

        if is_guest_viewer():
            if show_errors and st is not None:
                st.error("Sign in to manage saved properties.")
            return False

    if not user_id or not is_valid_uuid(user_id):
        raise ValueError(f"user_id must be a valid UUID, got: {user_id!r}")

    supabase = get_client()
    try:
        supabase.table("user_saved_properties").delete().eq(
            "user_id", user_id
        ).execute()
    except APIError as exc:
        report_error(log, "kb_saved_clear_all_failed", exc, user_id=user_id)
        if show_errors and st is not None:
            st.error(f"Failed to clear saved properties: {exc}")
        return False

    log.info("kb_saved_clear_all_success", user_id=user_id)
    return True


def get_user_saved_properties(user_id: str | None = None) -> list[dict[str, Any]]:
    """Bookmarked properties merged with the user's underwriting overrides."""
    uid = _resolve_user_id(user_id)
    if not uid:
        return []

    saved_rows = _fetch_user_saved_rows(uid)
    if not saved_rows:
        return []

    props_by_id = {
        str(row["id"]): row for row in _fetch_properties(uid) if row.get("id")
    }
    results: list[dict[str, Any]] = []
    for saved in saved_rows:
        prop_id = str(saved.get("property_id") or "")
        canonical = props_by_id.get(prop_id)
        if not canonical:
            continue
        enriched = dict(canonical)
        enriched["saved_at"] = saved.get("saved_at")
        enriched["user_saved_id"] = saved.get("id")
        results.append(enriched)
    return results


def render_user_saved_properties_sidebar() -> None:
    """Sidebar list of bookmarked properties — click to reload or remove."""
    if not in_streamlit_app() or st is None:
        return

    from portfolio_map_page import invalidate_portfolio_cache
    from property_nav import navigate_to_individual_search

    user = get_logged_in_user()
    if not user:
        return

    saved = get_user_saved_properties(user["id"])
    with st.expander("⭐ My Saved Properties", expanded=bool(saved)):
        if not saved:
            st.caption("Analyze a property and use **Save to My Account** to revisit it later.")
            st.caption(f"You can save up to {MAX_SAVED_PROPERTIES} properties.")
            return

        st.caption(f"{len(saved)} of {MAX_SAVED_PROPERTIES} saved")

        for prop in saved:
            addr = str(prop.get("address") or "Unknown address")
            price = prop.get("price")
            label = f"{addr}"
            if price is not None:
                try:
                    label = f"{addr} — ${float(price):,.0f}"
                except (TypeError, ValueError):
                    pass
            prop_id = str(prop.get("id") or "")
            key_suffix = str(prop.get("user_saved_id") or prop_id)
            load_col, remove_col = st.columns([6, 1])
            with load_col:
                if st.button(
                    label, key=f"saved_load_{key_suffix}", use_container_width=True
                ):
                    navigate_to_individual_search(addr)
            with remove_col:
                if st.button(
                    "✕",
                    key=f"saved_remove_{key_suffix}",
                    help="Remove from saved list",
                ):
                    if prop_id and unsave_property_from_user_account(
                        user["id"], prop_id, show_errors=True
                    ):
                        invalidate_portfolio_cache()
                        st.toast(f"Removed {addr}", icon="🗑️")
                        st.rerun()

        if st.session_state.get("confirm_clear_saved"):
            st.warning(f"Remove all {len(saved)} saved properties?")
            yes_col, no_col = st.columns(2)
            with yes_col:
                if st.button("Yes, clear all", key="saved_clear_confirm", type="primary"):
                    if clear_all_saved_properties_from_user_account(user["id"]):
                        invalidate_portfolio_cache()
                        st.session_state.pop("confirm_clear_saved", None)
                        st.toast("Cleared all saved properties", icon="🗑️")
                        st.rerun()
            with no_col:
                if st.button("Cancel", key="saved_clear_cancel"):
                    st.session_state.pop("confirm_clear_saved", None)
                    st.rerun()
        elif st.button("Clear all saved properties", key="saved_clear_init"):
            st.session_state["confirm_clear_saved"] = True
            st.rerun()


def save_harvest_property(
    property_data: dict[str, Any], user_id: str | None = None
) -> Any:
    """
    Persist a harvested property (Stage 3 output + quantum score).
    AI rent/maint go to original_ai_* columns; official rent/maint are left
    unset until a user confirms overrides in the underwriter.
    """
    uid = _resolve_user_id(user_id) or get_admin_uid()
    if not uid:
        log.warning("harvest_save_skipped", reason="no_user_id")
        return None

    payload = property_data.copy()
    payload.setdefault("from_kb", True)
    payload.setdefault("property_category", payload.get("property_label", ""))

    ai_rent = payload.pop("rent", None)
    ai_maint = payload.pop("maint_percent", None)
    if ai_rent is not None:
        payload["original_ai_rent"] = ai_rent
    if ai_maint is not None:
        payload["original_ai_maint"] = ai_maint

    return save_canonical_property(payload, user_id=uid, show_errors=False)


def get_kb_context(user_id: str | None = None) -> str:
    """Pull recent examples and scanned addresses for the LLM (scoped to user)."""
    rows = _fetch_properties(user_id)
    if not rows:
        return ""

    context = "\n--- RECENT ANALYSES ---\n"
    for item in rows[:3]:
        market = item.get("market_city") or "Unknown"
        context += (
            f"Address: {item['address']} | Market: {market} | "
            f"Predicted: {item.get('predicted_value')}\n"
        )

    scanned = [str(item["address"]) for item in rows if item.get("address")]
    if scanned:
        context += "\n--- ALREADY SCANNED (skip rediscovery / re-underwriting) ---\n"
        for addr in scanned[:50]:
            context += f"- {addr}\n"
        if len(scanned) > 50:
            context += f"- ... and {len(scanned) - 50} more\n"
    return context


def _infer_market_city(record: dict[str, Any]) -> str | None:
    from engine import DISCOVERY_MARKET_KEYS, _match_market_from_text

    explicit = record.get("market_city")
    if explicit in DISCOVERY_MARKET_KEYS:
        return explicit
    address = str(record.get("address", ""))
    matched = _match_market_from_text(address)
    return matched or None


def get_market_pulse(user_id: str | None = None) -> dict[str, dict[str, Any]]:
    """
    Aggregate per-metro stats for UI 'Market Pulse'.
    """
    from engine import DISCOVERY_MARKET_KEYS

    empty = {
        "count": 0,
        "avg_price": 0.0,
        "avg_quantum": 0.0,
        "avg_rent": 0.0,
        "top_label": "—",
    }
    pulse = {city: dict(empty) for city in sorted(DISCOVERY_MARKET_KEYS)}
    buckets: dict[str, list[dict[str, Any]]] = {city: [] for city in DISCOVERY_MARKET_KEYS}

    raw = get_kb_raw_data(user_id)
    for record in raw.values():
        city = _infer_market_city(record)
        if city in buckets:
            buckets[city].append(record)

    for city, records in buckets.items():
        if not records:
            continue
        prices = [float(r.get("price") or 0) for r in records]
        quantums = [float(r.get("quantum_risk_score") or 0) for r in records]
        rents = [
            float(get_official_rent(r) or get_ai_baseline_rent(r))
            for r in records
        ]
        labels = [
            str(r.get("property_label") or "") for r in records if r.get("property_label")
        ]

        pulse[city] = {
            "count": len(records),
            "avg_price": sum(prices) / len(prices) if prices else 0.0,
            "avg_quantum": sum(quantums) / len(quantums) if quantums else 0.0,
            "avg_rent": sum(rents) / len(rents) if rents else 0.0,
            "top_label": max(set(labels), key=labels.count) if labels else "—",
        }

    return pulse


def get_telemetry_stats(user_id: str | None = None) -> dict[str, Any]:
    """
    HITL accuracy: mean absolute error between original_ai_rent and user override rent.
    """
    uid = _resolve_user_id(user_id)
    if not uid:
        return {
            "mae_rent": None,
            "sample_count": 0,
            "outlier_count": 0,
            "skipped_no_baseline": 0,
            "total_rows": 0,
        }

    canonical_by_id = {
        str(row["id"]): row for row in _fetch_canonical_properties() if row.get("id")
    }
    overrides = _fetch_user_overrides_map(uid)

    errors: list[float] = []
    outlier_count = 0
    skipped_no_baseline = 0

    for prop_id, override in overrides.items():
        if override.get("is_outlier"):
            outlier_count += 1
            continue
        canonical = canonical_by_id.get(prop_id)
        if not canonical:
            skipped_no_baseline += 1
            continue
        ai_rent = canonical.get("original_ai_rent")
        final_rent = override.get("rent")
        if ai_rent is None or final_rent is None:
            skipped_no_baseline += 1
            continue
        try:
            errors.append(abs(float(final_rent) - float(ai_rent)))
        except (TypeError, ValueError):
            skipped_no_baseline += 1

    sample_count = len(errors)
    mae_rent = sum(errors) / sample_count if sample_count else None

    return {
        "mae_rent": mae_rent,
        "sample_count": sample_count,
        "outlier_count": outlier_count,
        "skipped_no_baseline": skipped_no_baseline,
        "total_rows": len(overrides),
    }


from authenticate import render_auth_page  # noqa: E402 — re-export for legacy imports


__all__ = [
    "RENT_OUTLIER_DEVIATION_PCT",
    "compute_rent_deviation_pct",
    "is_rent_outlier",
    "is_valid_uuid",
    "normalize_address_key",
    "parse_zipcode_from_address",
    "get_scanned_addresses",
    "is_property_already_scanned",
    "get_ai_baseline_rent",
    "get_ai_baseline_maint",
    "get_official_rent",
    "get_effective_display_rent",
    "get_effective_display_maint",
    "get_effective_display_vacancy",
    "get_effective_display_management_fee",
    "user_has_override_changes",
    "get_property_id_by_address",
    "get_client",
    "get_admin_uid",
    "get_kb_raw_data",
    "lookup_property",
    "save_canonical_property",
    "save_user_property_override",
    "save_knowledge_base",
    "MAX_SAVED_PROPERTIES",
    "count_user_saved_properties",
    "is_property_saved_for_user",
    "save_property_to_user_account",
    "unsave_property_from_user_account",
    "clear_all_saved_properties_from_user_account",
    "get_user_saved_properties",
    "render_user_saved_properties_sidebar",
    "save_harvest_property",
    "get_kb_context",
    "get_market_pulse",
    "get_telemetry_stats",
    "render_auth_page",
]
