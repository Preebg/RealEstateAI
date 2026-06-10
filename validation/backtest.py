"""Backtest predicted sale price and rent against ground-truth comps."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import Path
from typing import BinaryIO, TextIO

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "address",
    "actual_sale_price",
    "actual_monthly_rent",
    "analysis_date",
    "predicted_price",
    "predicted_rent",
]

_NUMERIC_COLUMNS = (
    "actual_sale_price",
    "actual_monthly_rent",
    "predicted_price",
    "predicted_rent",
)


class BacktestSchemaError(ValueError):
    """Raised when a CSV is missing required columns or has no usable rows."""


@dataclass(frozen=True)
class MetricSummary:
    """Error metrics for one target (price or rent)."""

    label: str
    n: int
    mape_pct: float | None
    rmse: float | None


@dataclass
class BacktestReport:
    """Full backtest output for CLI, tests, and Streamlit."""

    row_count: int
    price: MetricSummary
    rent: MetricSummary
    frame: pd.DataFrame = field(repr=False)
    calibration_figure: plt.Figure | None = field(default=None, repr=False)

    def as_text(self) -> str:
        lines = [
            f"Backtest rows: {self.row_count}",
            "",
            _format_metric_block(self.price),
            "",
            _format_metric_block(self.rent),
        ]
        return "\n".join(lines)


def _format_metric_block(metric: MetricSummary) -> str:
    if metric.n == 0:
        return f"{metric.label}: no rows with valid actual and predicted values"
    mape = f"{metric.mape_pct:.2f}%" if metric.mape_pct is not None else "n/a"
    rmse = f"${metric.rmse:,.0f}" if metric.rmse is not None else "n/a"
    return f"{metric.label} (n={metric.n})\n  MAPE: {mape}\n  RMSE: {rmse}"


def load_backtest_csv(source: str | Path | TextIO | BinaryIO) -> pd.DataFrame:
    """
    Load and validate a historical-comps CSV.

    Expected columns: address, actual_sale_price, actual_monthly_rent,
    analysis_date, predicted_price, predicted_rent.
    """
    if isinstance(source, (str, Path)):
        frame = pd.read_csv(source)
    else:
        frame = pd.read_csv(source)

    missing = [col for col in REQUIRED_COLUMNS if col not in frame.columns]
    if missing:
        raise BacktestSchemaError(
            f"CSV missing required columns: {', '.join(missing)}. "
            f"Expected: {', '.join(REQUIRED_COLUMNS)}"
        )

    cleaned = frame.loc[:, REQUIRED_COLUMNS].copy()
    for col in _NUMERIC_COLUMNS:
        cleaned[col] = pd.to_numeric(cleaned[col], errors="coerce")

    cleaned["analysis_date"] = pd.to_datetime(cleaned["analysis_date"], errors="coerce")
    cleaned["address"] = cleaned["address"].astype(str).str.strip()

    cleaned = cleaned[cleaned["address"].astype(bool)].reset_index(drop=True)
    if cleaned.empty:
        raise BacktestSchemaError("CSV contains no rows with a non-empty address.")

    return cleaned


def _metric_summary(
    actual: pd.Series,
    predicted: pd.Series,
    *,
    label: str,
) -> MetricSummary:
    mask = actual.notna() & predicted.notna() & (actual != 0)
    n = int(mask.sum())
    if n == 0:
        return MetricSummary(label=label, n=0, mape_pct=None, rmse=None)

    act = actual[mask].astype(float)
    pred = predicted[mask].astype(float)
    errors = pred - act
    mape_pct = float((errors.abs() / act.abs()).mean() * 100.0)
    rmse = float(np.sqrt((errors**2).mean()))
    return MetricSummary(label=label, n=n, mape_pct=mape_pct, rmse=rmse)


def compute_metrics(frame: pd.DataFrame) -> tuple[MetricSummary, MetricSummary]:
    """Return (price_metrics, rent_metrics) for a validated backtest frame."""
    price = _metric_summary(
        frame["actual_sale_price"],
        frame["predicted_price"],
        label="Sale price",
    )
    rent = _metric_summary(
        frame["actual_monthly_rent"],
        frame["predicted_rent"],
        label="Monthly rent",
    )
    return price, rent


def plot_calibration(
    frame: pd.DataFrame,
    *,
    title: str = "Predicted vs actual",
) -> plt.Figure:
    """Scatter plots of predicted vs actual price and rent with y=x reference."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    fig.suptitle(title)

    specs = (
        ("actual_sale_price", "predicted_price", "Sale price ($)", axes[0]),
        ("actual_monthly_rent", "predicted_rent", "Monthly rent ($)", axes[1]),
    )

    for actual_col, pred_col, axis_label, ax in specs:
        subset = frame[[actual_col, pred_col]].dropna()
        subset = subset[(subset[actual_col] != 0) & (subset[pred_col].notna())]
        if subset.empty:
            ax.set_title(f"{axis_label}\n(no data)")
            ax.set_xlabel(f"Actual {axis_label.lower()}")
            ax.set_ylabel(f"Predicted {axis_label.lower()}")
            continue

        x = subset[actual_col].astype(float)
        y = subset[pred_col].astype(float)
        ax.scatter(x, y, alpha=0.75, edgecolors="white", linewidths=0.5)

        lo = float(min(x.min(), y.min()))
        hi = float(max(x.max(), y.max()))
        pad = (hi - lo) * 0.05 if hi > lo else 1.0
        lim_lo, lim_hi = lo - pad, hi + pad
        ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], "--", color="#666666", linewidth=1)
        ax.set_xlim(lim_lo, lim_hi)
        ax.set_ylim(lim_lo, lim_hi)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(axis_label)
        ax.set_xlabel(f"Actual {axis_label.lower()}")
        ax.set_ylabel(f"Predicted {axis_label.lower()}")

    fig.tight_layout()
    return fig


def run_backtest(
    source: str | Path | TextIO | BinaryIO,
    *,
    make_plot: bool = True,
) -> BacktestReport:
    """Load CSV, compute metrics, and optionally build calibration plots."""
    frame = load_backtest_csv(source)
    price, rent = compute_metrics(frame)
    figure = plot_calibration(frame) if make_plot else None
    return BacktestReport(
        row_count=len(frame),
        price=price,
        rent=rent,
        frame=frame,
        calibration_figure=figure,
    )


def save_report(report: BacktestReport, output_dir: str | Path) -> Path:
    """Write metrics text and calibration PNG to output_dir."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    metrics_path = out / "backtest_metrics.txt"
    metrics_path.write_text(report.as_text(), encoding="utf-8")

    if report.calibration_figure is not None:
        plot_path = out / "calibration_plot.png"
        report.calibration_figure.savefig(plot_path, dpi=150, bbox_inches="tight")

    return out


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backtest predicted price/rent against ground-truth historical comps.",
    )
    parser.add_argument(
        "csv",
        type=Path,
        help="Path to CSV with columns: " + ", ".join(REQUIRED_COLUMNS),
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=None,
        help="Directory for backtest_metrics.txt and calibration_plot.png",
    )
    parser.add_argument(
        "--no-plot",
        action="store_true",
        help="Skip calibration plot generation",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    args = _build_arg_parser().parse_args(argv)

    if not args.csv.is_file():
        print(f"File not found: {args.csv}", file=sys.stderr)
        return 1

    try:
        report = run_backtest(args.csv, make_plot=not args.no_plot)
    except BacktestSchemaError as exc:
        print(f"Invalid backtest CSV: {exc}", file=sys.stderr)
        return 1

    print(report.as_text())

    if args.output_dir is not None:
        save_report(report, args.output_dir)
        print(f"\nWrote report to {args.output_dir.resolve()}")

    if report.calibration_figure is not None:
        plt.close(report.calibration_figure)

    return 0


def render_backtest_page() -> None:
    """Streamlit UI for uploading a comps CSV and viewing metrics."""
    import streamlit as st

    from authenticate import get_logged_in_user
    from knowledge_base import get_admin_uid
    from ui_theme import render_page_hero

    render_page_hero(
        "Model Validation",
        "Measure prediction accuracy against historical comps — MAPE, RMSE, and calibration plots.",
    )

    user = get_logged_in_user()
    admin_uid = get_admin_uid()
    if admin_uid and (not user or user["id"] != admin_uid):
        st.warning(
            "This page is intended for the project admin. "
            "You can still run backtests locally via "
            "`python -m validation.backtest path/to/comps.csv`."
        )

    with st.expander("CSV schema", expanded=False):
        st.markdown(
            "Required columns (one row per comp):\n\n"
            "| Column | Description |\n"
            "|--------|-------------|\n"
            "| `address` | Property identifier (anonymize for sharing) |\n"
            "| `actual_sale_price` | Closed sale price or appraised value ($) |\n"
            "| `actual_monthly_rent` | Observed or lease rent ($/mo) |\n"
            "| `analysis_date` | Date you ran the model (YYYY-MM-DD) |\n"
            "| `predicted_price` | Model sale-price estimate at analysis time |\n"
            "| `predicted_rent` | Model rent estimate at analysis time |"
        )
        st.code(", ".join(REQUIRED_COLUMNS))

    fixture_path = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "backtest_sample.csv"
    if fixture_path.is_file():
        with st.expander("Load sample fixture (for demo)", expanded=False):
            if st.button("Use sample fixture data"):
                st.session_state["_backtest_fixture_bytes"] = fixture_path.read_bytes()
                st.rerun()

    uploaded = st.file_uploader("Historical comps CSV", type=["csv"])
    fixture_bytes = st.session_state.pop("_backtest_fixture_bytes", None)
    source = uploaded
    if source is None and fixture_bytes:
        source = BytesIO(fixture_bytes)

    if source is None:
        st.info("Upload a CSV or load the sample fixture to run a backtest.")
        return

    try:
        report = run_backtest(source, make_plot=True)
    except BacktestSchemaError as exc:
        st.error(str(exc))
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Comps", report.row_count)
    if report.price.mape_pct is not None:
        col2.metric("Price MAPE", f"{report.price.mape_pct:.1f}%")
    if report.rent.mape_pct is not None:
        col3.metric("Rent MAPE", f"{report.rent.mape_pct:.1f}%")

    m1, m2 = st.columns(2)
    with m1:
        st.subheader("Sale price")
        if report.price.n:
            st.write(f"**MAPE:** {report.price.mape_pct:.2f}%")
            st.write(f"**RMSE:** ${report.price.rmse:,.0f}")
            st.caption(f"{report.price.n} comps with valid price pairs")
        else:
            st.caption("No valid price pairs.")
    with m2:
        st.subheader("Monthly rent")
        if report.rent.n:
            st.write(f"**MAPE:** {report.rent.mape_pct:.2f}%")
            st.write(f"**RMSE:** ${report.rent.rmse:,.0f}")
            st.caption(f"{report.rent.n} comps with valid rent pairs")
        else:
            st.caption("No valid rent pairs.")

    if report.calibration_figure is not None:
        st.subheader("Calibration plots")
        st.pyplot(report.calibration_figure, clear_figure=True)

    with st.expander("Preview data"):
        st.dataframe(report.frame, use_container_width=True)

    metrics_csv = StringIO()
    metrics_csv.write("metric,n,mape_pct,rmse\n")
    for metric in (report.price, report.rent):
        mape = "" if metric.mape_pct is None else f"{metric.mape_pct:.4f}"
        rmse = "" if metric.rmse is None else f"{metric.rmse:.4f}"
        metrics_csv.write(f"{metric.label},{metric.n},{mape},{rmse}\n")
    st.download_button(
        "Download metrics summary (CSV)",
        data=metrics_csv.getvalue(),
        file_name="backtest_metrics.csv",
        mime="text/csv",
    )


def _running_under_streamlit() -> bool:
    import os

    return bool(os.environ.get("STREAMLIT_RUNTIME_ENV"))


if __name__ == "__main__":
    if _running_under_streamlit():
        import streamlit as st

        st.set_page_config(page_title="Model Backtest", page_icon="📊", layout="wide")
        render_backtest_page()
    else:
        raise SystemExit(main())
