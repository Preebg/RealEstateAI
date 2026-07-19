"""Model validation (backtest) API."""

from __future__ import annotations

import base64
from io import BytesIO

import matplotlib.pyplot as plt
from fastapi import APIRouter, File, HTTPException, UploadFile

from api.deps import AdminUser
from api.schemas import ValidationMetricsResponse
from validation.backtest import BacktestSchemaError, run_backtest

router = APIRouter(tags=["validation"])


@router.post("/api/validation/backtest", response_model=ValidationMetricsResponse)
async def backtest_csv(
    _admin: AdminUser,
    file: UploadFile = File(...),
) -> ValidationMetricsResponse:
    raw = await file.read()
    try:
        report = run_backtest(BytesIO(raw), make_plot=True)
    except BacktestSchemaError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    plot_b64: str | None = None
    if report.calibration_figure is not None:
        buf = BytesIO()
        report.calibration_figure.savefig(buf, format="png", dpi=120, bbox_inches="tight")
        plot_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        plt.close(report.calibration_figure)

    return ValidationMetricsResponse(
        row_count=report.row_count,
        price_label=report.price.label,
        price_n=report.price.n,
        price_mape_pct=report.price.mape_pct,
        price_rmse=report.price.rmse,
        rent_label=report.rent.label,
        rent_n=report.rent.n,
        rent_mape_pct=report.rent.mape_pct,
        rent_rmse=report.rent.rmse,
        report_text=report.as_text(),
        calibration_png_base64=plot_b64,
    )
