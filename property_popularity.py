"""In-app property viewership and Property of the Day selection."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from postgrest.exceptions import APIError

from app_logging import configure_logging, report_error
from authenticate import get_db_client, get_service_client
from engine import safe_float
from knowledge_base import get_kb_raw_data, is_valid_uuid
from viewer_timezone import validate_timezone_name

log = configure_logging("property_popularity")

GOOD_NEIGHBORHOOD_LOCATION_SCORE = 7.0
LOW_RISK_QUANTUM_SUCCESS_PCT = 55.0
PROPERTY_OF_DAY_ROTATION = 7

_featured_cache: dict[date, dict[str, Any] | None] = {}


def _data_client() -> Any:
    return get_service_client() or get_db_client()


def monthly_cash_flow(prop: dict[str, Any]) -> float | None:
    """Net monthly cash flow stored on a catalog row."""
    raw = prop.get("monthly_net_cash_flow")
    if raw is None:
        raw = prop.get("monthly_cash_flow")
    if raw is None:
        return None
    return safe_float(raw)


def has_positive_cash_flow(prop: dict[str, Any]) -> bool:
    cash_flow = monthly_cash_flow(prop)
    return cash_flow is not None and cash_flow > 0


def quantum_success_pct(prop: dict[str, Any]) -> float | None:
    """Stored quantum_risk_score is overall success % (higher = lower risk)."""
    raw = prop.get("quantum_risk_score")
    if raw is None:
        raw = prop.get("quantum_success")
    if raw is None:
        return None
    return safe_float(raw)


def location_score_value(prop: dict[str, Any]) -> float | None:
    raw = prop.get("location_score")
    if raw is None:
        return None
    return safe_float(raw)


def property_of_day_score(prop: dict[str, Any]) -> float | None:
    """
    Rank a listing for Property of the Day.

    Requires positive cash flow. Higher quantum success (lower risk) and a
    stronger neighborhood/location score rank higher. Location is a bonus,
    not a hard filter.
    """
    if not has_positive_cash_flow(prop):
        return None
    cash_flow = monthly_cash_flow(prop) or 0.0
    quantum = quantum_success_pct(prop) or 0.0
    location = location_score_value(prop) or 0.0
    location_bonus = (
        30.0
        if location >= GOOD_NEIGHBORHOOD_LOCATION_SCORE
        else location * 2.0
    )
    cash_flow_part = min(max(cash_flow, 0.0), 2500.0) / 25.0
    return round(quantum + location_bonus + cash_flow_part, 4)


def _catalog_id(prop: dict[str, Any]) -> str | None:
    pid = prop.get("id") or prop.get("property_id")
    text = str(pid).strip() if pid is not None else ""
    return text if is_valid_uuid(text) else None


def select_property_of_the_day(
    properties: list[dict[str, Any]],
    feature_date: date,
) -> dict[str, Any] | None:
    """Pick one educational highlight for ``feature_date`` (deterministic)."""
    eligible = [prop for prop in properties if property_of_day_score(prop) is not None]
    if not eligible:
        return None

    low_risk = [
        prop
        for prop in eligible
        if (quantum_success_pct(prop) or 0.0) >= LOW_RISK_QUANTUM_SUCCESS_PCT
    ]
    pool = low_risk or eligible
    good_neighborhood = [
        prop
        for prop in pool
        if (location_score_value(prop) or 0.0) >= GOOD_NEIGHBORHOOD_LOCATION_SCORE
    ]
    if good_neighborhood:
        pool = good_neighborhood

    ranked = sorted(
        pool,
        key=lambda prop: (
            property_of_day_score(prop) or 0.0,
            _catalog_id(prop) or "",
        ),
        reverse=True,
    )
    top = ranked[:PROPERTY_OF_DAY_ROTATION]
    index = feature_date.toordinal() % len(top)
    return top[index]


def property_of_day_reasons(prop: dict[str, Any]) -> list[str]:
    """Short bullets explaining why this listing was highlighted."""
    reasons: list[str] = []
    cash_flow = monthly_cash_flow(prop)
    if cash_flow is not None and cash_flow > 0:
        reasons.append("Positive estimated monthly cash flow")
    quantum = quantum_success_pct(prop)
    if quantum is not None and quantum >= LOW_RISK_QUANTUM_SUCCESS_PCT:
        reasons.append("Lower simulated risk (strong quantum alignment)")
    elif quantum is not None:
        reasons.append("Included in today's cash-flowing shortlist")
    location = location_score_value(prop)
    if location is not None and location >= GOOD_NEIGHBORHOOD_LOCATION_SCORE:
        reasons.append("Strong neighborhood / location score")
    return reasons


def featured_property_for_date(feature_date: date) -> dict[str, Any] | None:
    """Resolve today's highlight from the active catalog (cached per UTC date)."""
    cached = _featured_cache.get(feature_date)
    if feature_date in _featured_cache:
        return cached
    raw = get_kb_raw_data()
    rows = [prop for prop in raw.values() if isinstance(prop, dict)]
    selected = select_property_of_the_day(rows, feature_date)
    _featured_cache[feature_date] = selected
    if len(_featured_cache) > 3:
        oldest = min(_featured_cache)
        if oldest != feature_date:
            _featured_cache.pop(oldest, None)
    return selected


def clear_featured_cache() -> None:
    """Test helper."""
    _featured_cache.clear()


def record_property_view(user_id: str, property_id: str) -> int:
    """Count a unique in-app view. Repeat views by the same user do not increment."""
    uid = str(user_id or "").strip()
    pid = str(property_id or "").strip()
    if not is_valid_uuid(uid) or not is_valid_uuid(pid):
        raise ValueError("A valid user id and property id are required.")
    client = _data_client()
    try:
        response = client.rpc(
            "record_property_app_view",
            {"p_user_id": uid, "p_property_id": pid},
        ).execute()
    except Exception as exc:  # noqa: BLE001
        report_error(log, "record_property_view_rpc_failed", exc, property_id=pid)
        raise RuntimeError("Could not record property view.") from exc
    count = response.data
    if isinstance(count, int):
        return max(count, 0)
    if isinstance(count, float):
        return max(int(count), 0)
    if isinstance(count, list) and count:
        return max(int(count[0] or 0), 0)
    return 0


def _impression_exists(user_id: str, shown_on: date) -> bool:
    client = _data_client()
    try:
        response = (
            client.table("property_of_day_impressions")
            .select("user_id")
            .eq("user_id", user_id)
            .eq("shown_on", shown_on.isoformat())
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        report_error(log, "property_of_day_impression_lookup_failed", exc)
        return False
    return bool(response.data)


def _insert_impression(user_id: str, shown_on: date, property_id: str | None) -> bool:
    """Return True when this is the first claim for that user/day."""
    client = _data_client()
    row: dict[str, Any] = {
        "user_id": user_id,
        "shown_on": shown_on.isoformat(),
        "shown_at": datetime.now(timezone.utc).isoformat(),
    }
    if property_id:
        row["property_id"] = property_id
    try:
        client.table("property_of_day_impressions").insert(row).execute()
        return True
    except APIError as exc:
        message = str(exc).lower()
        if "duplicate" in message or "unique" in message or "23505" in message:
            return False
        report_error(log, "property_of_day_impression_insert_failed", exc)
        return False
    except Exception as exc:  # noqa: BLE001
        report_error(log, "property_of_day_impression_insert_failed", exc)
        return False


def claim_property_of_the_day(
    user_id: str,
    *,
    timezone_name: str | None = None,
) -> dict[str, Any]:
    """
    First authenticated visit of the viewer's local day claims the popup.

    The featured listing itself is chosen from the UTC date so everyone sees
    the same Property of the Day.
    """
    uid = str(user_id or "").strip()
    if not is_valid_uuid(uid):
        raise ValueError("A valid user id is required.")

    tz = ZoneInfo(validate_timezone_name(timezone_name))
    local_today = datetime.now(tz).date()
    feature_date = datetime.now(timezone.utc).date()
    featured = featured_property_for_date(feature_date)
    featured_id = _catalog_id(featured) if featured else None

    already_shown = _impression_exists(uid, local_today)
    show = False
    if not already_shown and featured is not None:
        show = _insert_impression(uid, local_today, featured_id)

    return {
        "show": show,
        "feature_date": feature_date.isoformat(),
        "viewer_date": local_today.isoformat(),
        "property": featured,
        "reasons": property_of_day_reasons(featured) if featured else [],
    }
