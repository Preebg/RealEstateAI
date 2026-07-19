"""Property search, portfolio, save, and bookmark routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from api.deps import CurrentUser, UserClient
from api.schemas import (
    AddressSearchResponse,
    BookmarkRequest,
    SaveOverrideRequest,
)
from knowledge_base import (
    get_kb_raw_data,
    get_user_saved_properties,
    save_knowledge_base,
    save_property_to_user_account,
    save_user_property_override,
    search_kb_addresses,
    unsave_property_from_user_account,
)

router = APIRouter(tags=["properties"])


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
    raw = get_kb_raw_data(user_id=user["id"])
    items: list[dict[str, Any]] = []
    for _key, prop in raw.items():
        if not isinstance(prop, dict):
            continue
        items.append(
            {
                "address": prop.get("address"),
                "price": prop.get("price"),
                "predicted_value": prop.get("predicted_value"),
                "latitude": prop.get("latitude"),
                "longitude": prop.get("longitude"),
                "beds": prop.get("beds"),
                "baths": prop.get("baths"),
                "sqft": prop.get("sqft"),
                "location_score": prop.get("location_score"),
                "rent": prop.get("rent") or prop.get("estimated_rent"),
                "strategy": prop.get("strategy"),
                "id": prop.get("id") or prop.get("property_id"),
            }
        )
    return {"properties": items, "count": len(items)}


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
