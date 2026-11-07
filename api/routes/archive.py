"""Admin archived-properties browse and dataset export."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from postgrest.exceptions import APIError

from api.deps import AdminUser
from api.schemas import ArchivedPropertiesListResponse
from knowledge_base import iter_archived_dataset_rows, list_archived_properties

router = APIRouter(tags=["archive"])

_EXPORT_FIELDNAMES = (
    "dataset_source",
    "id",
    "address",
    "zip_code",
    "state_code",
    "market_city",
    "price",
    "predicted_value",
    "year_built",
    "square_footage",
    "rent",
    "original_ai_rent",
    "tax_rate",
    "hoa",
    "insurance",
    "maint_percent",
    "original_ai_maint",
    "location_score",
    "quantum_risk_score",
    "appreciation_forecast",
    "forecast_rate",
    "forecast_growth",
    "ai_vacancy_rate",
    "ai_management_fee",
    "monthly_net_cash_flow",
    "property_label",
    "property_category",
    "property_condition",
    "strategy_tag",
    "listing_status",
    "days_on_market",
    "latitude",
    "longitude",
    "is_turnkey",
    "from_kb",
    "timestamp",
    "archived_at",
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True, default=str)
    return str(value)


def _csv_stream(
    *,
    include_active: bool,
    q: str | None,
) -> Iterator[str]:
    """Yield CSV text in chunks so the browser starts receiving data immediately."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=_EXPORT_FIELDNAMES,
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    for row in iter_archived_dataset_rows(
        include_active=include_active,
        q=q,
    ):
        writer.writerow({key: _cell(row.get(key)) for key in _EXPORT_FIELDNAMES})
        chunk = buffer.getvalue()
        if chunk:
            yield chunk
            buffer.seek(0)
            buffer.truncate(0)


@router.get("/api/admin/archived-properties", response_model=ArchivedPropertiesListResponse)
def admin_list_archived_properties(
    _admin: AdminUser,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    q: str = Query("", max_length=200),
) -> ArchivedPropertiesListResponse:
    try:
        rows, total = list_archived_properties(limit=limit, offset=offset, q=q or None)
    except APIError as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not load archived properties from the database.",
        ) from exc
    return ArchivedPropertiesListResponse(
        properties=rows,
        total=total,
        limit=limit,
        offset=offset,
        q=(q or "").strip() or None,
    )


@router.get("/api/admin/archived-properties/export")
def admin_export_archived_dataset(
    _admin: AdminUser,
    include_active: bool = Query(
        False,
        description="Also include live catalog rows (last ~30 days) in the CSV.",
    ),
    q: str = Query("", max_length=200),
) -> StreamingResponse:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    scope = "archived-plus-active" if include_active else "archived"
    filename = f"capeigen-dataset-{scope}-{stamp}.csv"
    return StreamingResponse(
        _csv_stream(include_active=include_active, q=q or None),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
