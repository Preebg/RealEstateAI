"""Analysis job and finance recalculation routes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException

from api.deps import CurrentUser, OptionalUser
from api.jobs import (
    create_job,
    get_job,
    job_to_dict,
    mark_job_error,
    seed_job_from_analysis,
    update_finance_context,
)
from api.schemas import (
    AnalysisJobResponse,
    AnalysisStartRequest,
    AnalysisStartResponse,
    FinanceRecalcRequest,
    FinanceRecalcResponse,
)
from engine import safe_float
from services.property_analysis_flow import (
    AnalysisError,
    run_finance_analysis,
    start_property_analysis,
)

router = APIRouter(tags=["analysis"])
_start_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis-start")


def _authorize_job(job_id: str, user_id: str | None) -> Any:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    if job.user_id and user_id and job.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not allowed to access this job")
    return job


def _run_start(job_id: str, address: str, guest_mode: bool, user_id: str | None) -> None:
    from api.jobs import get_job as _get

    job = _get(job_id)
    if job is None:
        return
    try:
        result = start_property_analysis(
            address, guest_mode=guest_mode, user_id=user_id
        )
        seed_job_from_analysis(
            job,
            property_data=result["property_data"],
            from_kb=bool(result.get("from_kb")),
            guest_mode=guest_mode,
        )
    except AnalysisError as exc:
        mark_job_error(job, str(exc))
    except Exception as exc:  # noqa: BLE001
        mark_job_error(job, f"Analysis failed: {exc}")


@router.post("/api/analysis/start", response_model=AnalysisStartResponse)
def start_analysis(
    body: AnalysisStartRequest,
    user: CurrentUser,
) -> AnalysisStartResponse:
    address = body.address.strip()
    if not address:
        raise HTTPException(status_code=400, detail="Address is required")

    user_id = user["id"]
    job = create_job(
        address=address,
        user_id=user_id,
        guest_mode=False,
    )
    job.status = "running"
    _start_executor.submit(_run_start, job.job_id, address, False, user_id)

    return AnalysisStartResponse(
        job_id=job.job_id,
        status=job.status,
        deferred_tasks=[],
        deferred_tasks_total=0,
    )


@router.get("/api/analysis/{job_id}", response_model=AnalysisJobResponse)
def get_analysis(job_id: str, user: OptionalUser) -> AnalysisJobResponse:
    job = _authorize_job(job_id, user["id"] if user else None)
    payload = job_to_dict(job)
    return AnalysisJobResponse(**payload)


@router.post("/api/finance/recalc", response_model=FinanceRecalcResponse)
def recalc_finance(
    body: FinanceRecalcRequest,
    user: CurrentUser,
) -> FinanceRecalcResponse:
    finance = run_finance_analysis(
        price=body.price,
        down_payment_pct=body.down_payment_pct,
        interest_rate=body.interest_rate,
        loan_term=body.loan_term,
        closing_costs_pct=body.closing_costs_pct,
        tax_rate=body.tax_rate,
        monthly_insurance=body.monthly_insurance,
        monthly_hoa=body.monthly_hoa,
        maint_percent=body.maint_percent,
        monthly_rent=body.monthly_rent,
        vacancy_reserve_pct=body.vacancy_reserve_pct,
        management_fee_pct=body.management_fee_pct,
    )

    requeued = False
    if body.job_id:
        location_score = (
            body.location_score
            if body.location_score is not None
            else 5.0
        )
        forecast_rate = body.forecast_rate if body.forecast_rate is not None else 0.0
        # Ensure job exists / belongs to user
        _authorize_job(body.job_id, user["id"])
        requeued = update_finance_context(
            body.job_id,
            monthly_net_cash_flow=safe_float(finance["monthly_net_cash_flow"]),
            forecast_rate=safe_float(forecast_rate),
            location_score=safe_float(location_score),
        )

    return FinanceRecalcResponse(finance=finance, quantum_requeued=requeued)
