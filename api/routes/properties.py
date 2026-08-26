"""Property search, portfolio, save, and bookmark routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.deps import AdminUser, CurrentUser, UserClient
from api.schemas import (
    AddressSearchResponse,
    AdminPropertyMetricsUpdate,
    BookmarkRequest,
    PropertyOfDayResponse,
    PropertyViewRequest,
    PropertyViewResponse,
    SaveOverrideRequest,
)
from knowledge_base import (
    delete_canonical_property_by_id,
    enrich_property_for_ui,
    get_kb_raw_data,
    get_user_saved_properties,
    invalidate_kb_cache,
    is_valid_uuid,
    lookup_catalog_property,
    save_knowledge_base,
    save_property_to_user_account,
    save_user_property_override,
    search_kb_addresses,
    unsave_property_from_user_account,
    update_canonical_property_metrics,
)
from property_popularity import claim_property_of_the_day, record_property_view

router = APIRouter(tags=["properties"])


def _iso_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        return str(iso())
    text = str(value).strip()
    return text or None


def _portfolio_list_item(prop: dict[str, Any]) -> dict[str, Any]:
    """Shape a catalog row for the Home/Compare map (local Postgres or hosted)."""
    pid = prop.get("id") or prop.get("property_id")
    added_at = _iso_timestamp(prop.get("timestamp") or prop.get("added_at"))
    sqft = prop.get("square_footage") if prop.get("square_footage") is not None else prop.get("sqft")
    rent = prop.get("rent") or prop.get("original_ai_rent") or prop.get("estimated_rent")
    cash_flow = prop.get("monthly_net_cash_flow")
    if cash_flow is None:
        cash_flow = prop.get("monthly_cash_flow")
    return {
        "id": str(pid) if pid else None,
        "address": prop.get("address"),
        "price": prop.get("price"),
        "predicted_value": prop.get("predicted_value"),
        "latitude": prop.get("latitude"),
        "longitude": prop.get("longitude"),
        "beds": prop.get("beds"),
        "baths": prop.get("baths"),
        "sqft": sqft,
        "square_footage": sqft,
        "location_score": prop.get("location_score"),
        "rent": rent,
        "original_ai_rent": prop.get("original_ai_rent"),
        "year_built": prop.get("year_built"),
        "monthly_cash_flow": cash_flow,
        "monthly_net_cash_flow": cash_flow,
        "market_city": prop.get("market_city"),
        "state_code": prop.get("state_code"),
        "forecast_rate": prop.get("forecast_rate"),
        "quantum_success": prop.get("quantum_risk_score"),
        "quantum_risk_score": prop.get("quantum_risk_score"),
        "app_view_count": int(prop.get("app_view_count") or 0),
        "primary_image_url": prop.get("primary_image_url"),
        "strategy": (
            prop.get("strategy")
            or prop.get("strategy_tag")
            or prop.get("property_label")
            or prop.get("property_category")
        ),
        "strategy_tag": prop.get("strategy_tag"),
        "property_label": prop.get("property_label"),
        "property_category": prop.get("property_category"),
        "timestamp": added_at,
        "added_at": added_at,
    }


@router.get("/api/properties/search", response_model=AddressSearchResponse)
def search_addresses(
    user: CurrentUser,
    q: str = Query("", min_length=0),
    limit: int = Query(12, ge=1, le=50),
) -> AddressSearchResponse:
    addresses = search_kb_addresses(q, user_id=user["id"], limit=limit)
    return AddressSearchResponse(addresses=addresses)


@router.get("/api/portfolio")
def portfolio(user: CurrentUser) -> dict[str, Any]:
    # Harvester writes in another process; skip the in-memory KB cache so a
    # browser refresh after harvest shows the new local Postgres rows.
    invalidate_kb_cache()
    raw = get_kb_raw_data(user_id=user["id"])
    items: list[dict[str, Any]] = []
    for _key, prop in raw.items():
        if not isinstance(prop, dict):
            continue
        items.append(_portfolio_list_item(prop))
    items.sort(key=lambda row: str(row.get("added_at") or ""), reverse=True)
    return {"properties": items, "count": len(items)}


@router.get("/api/properties/detail")
def property_detail(
    user: CurrentUser,
    id: str | None = Query(default=None),
    address: str | None = Query(default=None),
) -> dict[str, Any]:
    pid = (id or "").strip() or None
    addr = (address or "").strip() or None
    if not pid and not addr:
        raise HTTPException(status_code=400, detail="id or address is required")
    record = lookup_catalog_property(
        property_id=pid,
        address=addr,
        user_id=user["id"],
    )
    if not record:
        raise HTTPException(status_code=404, detail="Property not found")
    rent = record.get("rent") or record.get("original_ai_rent")
    enriched = enrich_property_for_ui(dict(record))
    return {
        **enriched,
        "from_kb": True,
        "property_id": enriched.get("id"),
        "rent": rent if rent is not None else enriched.get("rent"),
        "sqft": enriched.get("square_footage") or enriched.get("sqft"),
        "strategy": (
            enriched.get("strategy_tag")
            or enriched.get("property_label")
            or enriched.get("property_category")
            or enriched.get("strategy")
        ),
    }


@router.get("/api/properties/saved")
def saved_properties(user: CurrentUser) -> dict[str, Any]:
    rows = get_user_saved_properties(user_id=user["id"])
    return {"properties": rows, "count": len(rows)}


@router.post("/api/properties/override")
def save_override(
    body: SaveOverrideRequest,
    user: CurrentUser,
    _client: UserClient,
) -> dict[str, Any]:
    if body.save_canonical and body.property_data:
        save_knowledge_base(
            body.property_data,
            user["id"],
            show_errors=False,
            save_override=True,
        )
        return {"ok": True, "mode": "canonical_and_override"}

    override_data: dict[str, Any] = {
        "is_outlier": body.is_outlier,
        "override_notes": body.override_notes,
    }
    if body.rent is not None:
        override_data["rent"] = body.rent
    if body.maint_percent is not None:
        override_data["maint_percent"] = body.maint_percent
    if body.vacancy_rate is not None:
        override_data["vacancy_rate"] = body.vacancy_rate
    if body.management_fee is not None:
        override_data["management_fee"] = body.management_fee

    result = save_user_property_override(
        user["id"],
        body.property_id,
        override_data,
        address=body.address,
        show_errors=False,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Failed to save override")
    return {"ok": True, "mode": "override"}


@router.post("/api/properties/bookmark")
def bookmark_property(
    body: BookmarkRequest,
    user: CurrentUser,
    _client: UserClient,
) -> dict[str, Any]:
    property_id = save_property_to_user_account(
        user["id"],
        property_id=body.property_id,
        property_data=body.property_data,
        show_errors=False,
    )
    if not property_id:
        raise HTTPException(status_code=400, detail="Failed to bookmark property")
    return {"ok": True, "property_id": property_id}


@router.delete("/api/properties/bookmark")
def unbookmark_property(
    user: CurrentUser,
    _client: UserClient,
    property_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    ok = unsave_property_from_user_account(
        user["id"],
        property_id,
        show_errors=False,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to remove bookmark")
    return {"ok": True}


@router.post("/api/properties/view", response_model=PropertyViewResponse)
def record_view(body: PropertyViewRequest, user: CurrentUser) -> PropertyViewResponse:
    property_id = str(body.property_id or "").strip()
    if not is_valid_uuid(property_id):
        raise HTTPException(status_code=400, detail="A valid property id is required")
    try:
        count = record_property_view(user["id"], property_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return PropertyViewResponse(property_id=property_id, app_view_count=count)


@router.get("/api/property-of-the-day", response_model=PropertyOfDayResponse)
def property_of_the_day(
    user: CurrentUser,
    tz: str | None = Query(default=None, max_length=80),
) -> PropertyOfDayResponse:
    try:
        payload = claim_property_of_the_day(user["id"], timezone_name=tz)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    featured = payload.get("property")
    shaped = _portfolio_list_item(featured) if isinstance(featured, dict) else None
    if shaped and featured:
        reasons = payload.get("reasons") or []
        shaped["reasons"] = reasons
        shaped["summary"] = featured.get("summary")
    return PropertyOfDayResponse(
        show=bool(payload.get("show")),
        feature_date=str(payload.get("feature_date") or ""),
        viewer_date=str(payload.get("viewer_date") or ""),
        property=shaped,
        reasons=list(payload.get("reasons") or []),
    )


@router.patch("/api/admin/properties/{property_id}")
def admin_update_property_metrics(
    property_id: str,
    body: AdminPropertyMetricsUpdate,
    _admin: AdminUser,
) -> dict[str, Any]:
    if not is_valid_uuid(property_id):
        raise HTTPException(status_code=400, detail="A valid property id is required")
    updates = body.model_dump(exclude_unset=True)
    recalculate = bool(updates.pop("recalculate_cash_flow", True))
    if not updates:
        raise HTTPException(status_code=400, detail="No metric values provided")
    record = update_canonical_property_metrics(
        property_id,
        updates,
        recalculate_cash_flow=recalculate,
    )
    if not record:
        raise HTTPException(status_code=404, detail="Property not found or update failed")
    return {"ok": True, "property": record}


@router.delete("/api/admin/properties/{property_id}")
def admin_delete_property(
    property_id: str,
    _admin: AdminUser,
) -> dict[str, Any]:
    if not is_valid_uuid(property_id):
        raise HTTPException(status_code=400, detail="A valid property id is required")
    ok = delete_canonical_property_by_id(property_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Property not found or could not be removed")
    return {"ok": True, "property_id": property_id}
