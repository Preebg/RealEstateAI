"""PDF export and compare routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from api.deps import CurrentUser
from api.schemas import CompareRequest, CompareResponse, PdfRequest
from knowledge_base import lookup_property
from pdf_generator import generate_property_pdf, pdf_content_disposition
from comparison_metrics import build_property_comparison_metrics

router = APIRouter(tags=["exports"])


@router.post("/api/pdf")
def generate_pdf(body: PdfRequest, _user: CurrentUser) -> Response:
    try:
        pdf_bytes = generate_property_pdf(
            body.address,
            body.property_info,
            body.metrics,
            body.table_data,
            body.params,
            body.location_score,
            quantum_risk=body.quantum_risk,
            forecast_display=body.forecast_display,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}") from exc

    filename_header = pdf_content_disposition(body.address)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": filename_header},
    )


@router.post("/api/compare", response_model=CompareResponse)
def compare_properties(body: CompareRequest, user: CurrentUser) -> CompareResponse:
    metrics: list[dict[str, Any]] = []
    properties: list[dict[str, Any]] = []
    for address in body.addresses:
        prop = lookup_property(address, user_id=user["id"])
        if not prop:
            continue
        prop = dict(prop)
        prop["address"] = address
        properties.append(prop)
        metrics.append(
            build_property_comparison_metrics(
                prop,
                down_payment_pct=body.down_payment_pct,
                interest_rate=body.interest_rate,
                loan_term=body.loan_term,
                closing_costs_pct=body.closing_costs_pct,
            )
        )
    if not metrics:
        raise HTTPException(status_code=404, detail="No matching properties found")
    return CompareResponse(properties=properties, metrics=metrics)
