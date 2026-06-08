from __future__ import annotations

import datetime
import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fpdf import FPDF


def _pdf_text(text: Any) -> str:
    """Encode text safely for FPDF (latin-1)."""
    return str(text or "").encode("latin-1", errors="replace").decode("latin-1")


def _ensure_page_space(pdf: FPDF, needed: float = 30) -> None:
    if pdf.get_y() + needed > 275:
        pdf.add_page()


def _build_quantum_risk_chart(quantum_risk: dict) -> bytes:
    """Bar chart of QAOA alignment scores by dimension."""
    labels = [
        "Cash Flow\nAlignment",
        "Appreciation\nAlignment",
        "Combined CF+App\n(Joint |1>)",
        "Overall\n(Cost-Based)",
    ]
    values = [
        quantum_risk["cashflow_success_pct"],
        quantum_risk["appreciation_success_pct"],
        quantum_risk["combined_wealth_success_pct"],
        quantum_risk["overall_success_pct"],
    ]
    colors = ["#3498db", "#9b59b6", "#2ecc71", "#e67e22"]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(labels, values, color=colors, edgecolor="#333333", linewidth=0.8)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Optimization Alignment (%)")
    ax.set_title("QAOA Alignment Analysis", fontsize=14, fontweight="bold")
    ax.axhline(50, color="#95a5a6", linestyle="--", linewidth=1, alpha=0.7)
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 2,
            f"{val:.1f}%",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _build_appreciation_forecast_chart(forecast: dict[str, Any]) -> bytes:
    """Line chart of 10-year median value path with uncertainty band."""
    start_year = datetime.datetime.now().year
    years = list(range(start_year, start_year + 11))
    values_p50 = forecast["value_schedule_p50"]
    values_p10 = forecast["value_schedule_p10"]
    values_p90 = forecast["value_schedule_p90"]

    fig, ax = plt.subplots(figsize=(7.5, 4))
    ax.fill_between(
        years,
        values_p10,
        values_p90,
        alpha=0.25,
        color="#2ecc71",
        label="10th-90th percentile",
    )
    ax.plot(
        years,
        values_p50,
        marker="o",
        color="#2ecc71",
        linewidth=2,
        label="Median forecast",
    )
    ax.set_title("10-Year Appreciation Forecast", fontsize=14, fontweight="bold")
    ax.set_xlabel("Year")
    ax.set_ylabel("Estimated Value ($)")
    ax.ticklabel_format(style="plain", axis="y")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, linestyle="--", alpha=0.4)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _write_section_header(pdf: FPDF, title: str) -> None:
    _ensure_page_space(pdf, 14)
    pdf.set_font("Times", "B", 12)
    pdf.set_fill_color(230, 230, 230)
    pdf.cell(0, 8, _pdf_text(title), ln=True, fill=True)
    pdf.ln(2)


def _write_comps_summary_metrics(
    pdf: FPDF,
    *,
    title: str,
    metrics: list[tuple[str, str]],
    summary: str = "",
) -> None:
    _write_section_header(pdf, title)
    pdf.set_font("Times", "", 10)
    for label, value in metrics:
        pdf.cell(0, 6, _pdf_text(f"{label}: {value}"), ln=True)
    if summary:
        pdf.ln(2)
        pdf.multi_cell(0, 5, _pdf_text(summary))
    pdf.ln(4)


def _write_comps_table(
    pdf: FPDF,
    rows: list[dict[str, str]],
    *,
    price_header: str,
) -> None:
    if not rows:
        pdf.set_font("Times", "I", 10)
        pdf.cell(0, 6, "No comparable records available.", ln=True)
        pdf.ln(4)
        return

    col_widths = (72, 28, 24, 20, 22, 24)
    headers = ("Address", price_header, "Date", "Sq Ft", "$/Sq Ft", "Dist (mi)")

    _ensure_page_space(pdf, 12 + 7 * len(rows))
    pdf.set_font("Times", "B", 9)
    pdf.set_fill_color(240, 240, 240)
    for header, width in zip(headers, col_widths):
        pdf.cell(width, 7, _pdf_text(header), border=1, fill=True)
    pdf.ln()

    pdf.set_font("Times", "", 8)
    for row in rows:
        _ensure_page_space(pdf, 8)
        values = (
            row.get("address", "-"),
            row.get("price", "-"),
            row.get("date", "-"),
            row.get("sqft", "-"),
            row.get("ppsf", "-"),
            row.get("distance", "-"),
        )
        for value, width in zip(values, col_widths):
            text = _pdf_text(value)
            if width == col_widths[0] and len(text) > 38:
                text = text[:35] + "..."
            pdf.cell(width, 7, text, border=1)
        pdf.ln()
    pdf.ln(4)


def _sales_comps_pdf_rows(comps_analysis: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for comp in comps_analysis.get("comparable_properties") or []:
        sqft = comp.get("square_footage")
        price = float(comp.get("sale_price") or 0)
        ppsf = f"${price / sqft:,.0f}" if sqft and sqft > 0 and price > 0 else "-"
        rows.append(
            {
                "address": str(comp.get("address") or "-"),
                "price": f"${price:,.0f}" if price > 0 else "-",
                "date": str(comp.get("sale_date") or "-"),
                "sqft": f"{sqft:,}" if sqft else "-",
                "ppsf": ppsf,
                "distance": str(comp.get("distance_miles") or "-"),
            }
        )
    return rows


def _rent_comps_pdf_rows(rent_comps_analysis: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rental in rent_comps_analysis.get("comparable_rentals") or []:
        sqft = rental.get("square_footage")
        rent = float(rental.get("monthly_rent") or 0)
        rpsf = f"${rent / sqft:,.2f}" if sqft and sqft > 0 and rent > 0 else "-"
        rows.append(
            {
                "address": str(rental.get("address") or "-"),
                "price": f"${rent:,.0f}/mo" if rent > 0 else "-",
                "date": str(rental.get("lease_date") or "-"),
                "sqft": f"{sqft:,}" if sqft else "-",
                "ppsf": rpsf,
                "distance": str(rental.get("distance_miles") or "-"),
            }
        )
    return rows


def generate_property_pdf(
    address,
    property_info,
    metrics,
    table_data,
    params,
    location_score,
    quantum_risk=None,
    forecast_display: dict[str, Any] | None = None,
):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    pdf.set_font("Times", "B", 16)
    pdf.cell(0, 10, "Property Analysis Report", ln=True, align="C")
    pdf.set_font("Times", "", 12)
    pdf.cell(0, 10, _pdf_text(f"Address: {address}"), ln=True, align="C")
    pdf.ln(5)

    _write_section_header(pdf, "Investment Parameters")
    pdf.set_font("Times", "", 10)
    param_lines = [f"{label}: {value}" for label, value in params.items()]
    pdf.multi_cell(0, 5, _pdf_text("  |  ".join(param_lines)))
    pdf.ln(4)

    _write_section_header(pdf, "Property Summary")
    pdf.set_font("Times", "", 10)
    pdf.multi_cell(0, 5, _pdf_text(property_info.get("summary", "No summary available.")))
    pdf.ln(4)

    comps_analysis = property_info.get("comps_analysis")
    if isinstance(comps_analysis, dict) and comps_analysis.get("comparable_properties"):
        market_value = comps_analysis.get("comp_suggested_value")
        sales_metrics = [
            ("Market Value (Comps)", f"${float(market_value):,.0f}" if market_value else "-"),
            ("Median Comp Sale", f"${float(comps_analysis.get('median_sale_price') or 0):,.0f}"),
            ("List Price", f"${float(comps_analysis.get('list_price') or 0):,.0f}"),
        ]
        _write_comps_summary_metrics(
            pdf,
            title="Comparable Sales",
            metrics=sales_metrics,
            summary=str(comps_analysis.get("summary") or ""),
        )
        _write_comps_table(pdf, _sales_comps_pdf_rows(comps_analysis), price_header="Sale Price")

    rent_comps_analysis = property_info.get("rent_comps_analysis")
    if isinstance(rent_comps_analysis, dict) and rent_comps_analysis.get("comparable_rentals"):
        rent_metrics = [
            (
                "Comp-Implied Rent",
                f"${float(rent_comps_analysis.get('comp_suggested_rent') or 0):,.0f}/mo",
            ),
            (
                "Median Comp Rent",
                f"${float(rent_comps_analysis.get('median_monthly_rent') or 0):,.0f}/mo",
            ),
            (
                "AI / Listing Rent",
                f"${float(rent_comps_analysis.get('subject_rent') or 0):,.0f}/mo",
            ),
        ]
        gap = rent_comps_analysis.get("rent_vs_comps_pct")
        if gap is not None:
            rent_metrics.append(("Rent vs Comps", f"{gap:+.1f}%"))
        _write_comps_summary_metrics(
            pdf,
            title="Comparable Rentals",
            metrics=rent_metrics,
            summary=str(rent_comps_analysis.get("summary") or ""),
        )
        _write_comps_table(
            pdf, _rent_comps_pdf_rows(rent_comps_analysis), price_header="Monthly Rent"
        )

    if isinstance(forecast_display, dict) and forecast_display.get("value_schedule_p50"):
        _write_section_header(pdf, "10-Year Appreciation Forecast")
        pdf.set_font("Times", "", 10)
        end_year = datetime.datetime.now().year + 10
        pdf.cell(
            0,
            6,
            _pdf_text(
                f"Median estimated value in {end_year}: "
                f"${forecast_display['future_value_p50']:,.2f}"
            ),
            ln=True,
        )
        pdf.cell(
            0,
            6,
            _pdf_text(
                f"Uncertainty band (10th-90th): "
                f"${forecast_display['future_value_p10']:,.0f} - "
                f"${forecast_display['future_value_p90']:,.0f}"
            ),
            ln=True,
        )
        pdf.cell(
            0,
            6,
            _pdf_text(f"Expected annual growth: {forecast_display['annual_rate']:.2f}%"),
            ln=True,
        )
        pdf.ln(3)
        _ensure_page_space(pdf, 90)
        forecast_png = _build_appreciation_forecast_chart(forecast_display)
        pdf.image(io.BytesIO(forecast_png), x=10, w=190)
        pdf.ln(5)

    if quantum_risk:
        _write_section_header(pdf, "QAOA Alignment Analysis")
        pdf.set_font("Times", "", 10)
        pdf.multi_cell(
            0,
            5,
            "Scores from a QAOA quantum simulation measuring optimization alignment with "
            "your investment targets. These are not predictions of market performance.",
        )
        pdf.ln(2)
        pdf.cell(
            0,
            6,
            f"Cash Flow Alignment: {quantum_risk['cashflow_success_pct']:.1f}%",
            ln=True,
        )
        pdf.cell(
            0,
            6,
            f"Appreciation Alignment: {quantum_risk['appreciation_success_pct']:.1f}%",
            ln=True,
        )
        pdf.cell(
            0,
            6,
            f"Combined CF+App Alignment: {quantum_risk['combined_wealth_success_pct']:.1f}%",
            ln=True,
        )
        pdf.cell(
            0,
            6,
            f"Overall Alignment: {quantum_risk['overall_success_pct']:.1f}%",
            ln=True,
        )
        pdf.ln(3)
        _ensure_page_space(pdf, 90)
        chart_png = _build_quantum_risk_chart(quantum_risk)
        pdf.image(io.BytesIO(chart_png), x=10, w=190)
        pdf.ln(5)

    _write_section_header(pdf, "Monthly Cash Flow Breakdown")
    pdf.set_font("Times", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(95, 8, "Description", border=1, fill=True)
    pdf.cell(45, 8, "Monthly Amount", border=1, ln=True, fill=True)
    pdf.set_font("Times", "", 10)
    for i in range(len(table_data["Description"])):
        _ensure_page_space(pdf, 10)
        pdf.cell(95, 8, _pdf_text(table_data["Description"][i]), border=1)
        pdf.cell(45, 8, _pdf_text(table_data["Amount"][i]), border=1, ln=True)
    pdf.ln(6)

    _ensure_page_space(pdf, 20)
    pdf.set_font("Times", "B", 12)
    pdf.cell(0, 8, _pdf_text(f"Location Score: {location_score}/10"), ln=True)
    pdf.set_font("Times", "I", 9)
    pdf.multi_cell(
        0,
        5,
        "Weighted analysis of local appreciation trends, school ratings, and neighborhood factors.",
    )
    pdf.ln(4)

    _write_section_header(pdf, "Final Projections")
    pdf.set_font("Times", "", 11)
    for label, value in metrics.items():
        pdf.cell(0, 7, _pdf_text(f"{label}: {value}"), ln=True)

    pdf.set_font("Times", "I", 8)
    pdf.ln(5)
    pdf.multi_cell(
        0,
        4,
        _pdf_text(
            f"Report generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}. "
            "Comps and forecasts are AI-assisted estimates. "
            "Quantum alignment scores are educational simulations, not financial guarantees."
        ),
    )

    return bytes(pdf.output())
