"""CapEigen property analysis PDF — ReportLab layout with brand color and charts."""

from __future__ import annotations

import datetime
import io
import re
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from legal import APP_NAME, APP_TAGLINE

INDIGO = HexColor("#4f46e5")
INDIGO_DARK = HexColor("#312e81")
SURFACE = HexColor("#eef2ff")
PAGE_BG = HexColor("#f8fafc")
TEXT = HexColor("#1a1a2e")
MUTED = HexColor("#64748b")
BORDER = HexColor("#e0e4ef")
GREEN = HexColor("#059669")
ROSE = HexColor("#e11d48")
AMBER = HexColor("#d97706")

_FONT = "Helvetica"
_FONT_BOLD = "Helvetica-Bold"
_FONTS_READY = False


def pdf_download_filename(address: str | None) -> str:
    """Safe download name: ``CapEigen - 123 Main St, Austin, TX.pdf``."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", str(address or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "property"
    if len(cleaned) > 80:
        cleaned = cleaned[:80].rstrip(" .")
    return f"{APP_NAME} - {cleaned}.pdf"


def pdf_content_disposition(address: str | None) -> str:
    """RFC 5987 Content-Disposition so browsers keep the address in the filename."""
    from urllib.parse import quote

    filename = pdf_download_filename(address)
    ascii_name = (
        filename.encode("ascii", "ignore").decode("ascii").replace('"', "")
        or f"{APP_NAME}-property.pdf"
    )
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(filename)}'


def _init_fonts() -> None:
    """Prefer DejaVu Sans (bundled with matplotlib) for a modern Unicode face."""
    global _FONT, _FONT_BOLD, _FONTS_READY
    if _FONTS_READY:
        return
    try:
        from matplotlib import font_manager

        regular = Path(font_manager.findfont("DejaVu Sans"))
        bold = regular.with_name("DejaVuSans-Bold.ttf")
        if regular.exists():
            pdfmetrics.registerFont(TTFont("CapSans", str(regular)))
            _FONT = "CapSans"
        if bold.exists():
            pdfmetrics.registerFont(TTFont("CapSans-Bold", str(bold)))
            _FONT_BOLD = "CapSans-Bold"
        elif _FONT == "CapSans":
            _FONT_BOLD = "CapSans"
    except Exception:
        _FONT = "Helvetica"
        _FONT_BOLD = "Helvetica-Bold"
    _FONTS_READY = True


def _styles() -> dict[str, ParagraphStyle]:
    _init_fonts()
    return {
        "brand": ParagraphStyle(
            "brand",
            fontName=_FONT_BOLD,
            fontSize=14,
            leading=18,
            textColor=white,
            alignment=TA_LEFT,
        ),
        "hero": ParagraphStyle(
            "hero",
            fontName=_FONT_BOLD,
            fontSize=18,
            leading=22,
            textColor=white,
            alignment=TA_LEFT,
        ),
        "hero_sub": ParagraphStyle(
            "hero_sub",
            fontName=_FONT,
            fontSize=9,
            leading=12,
            textColor=HexColor("#c7d2fe"),
        ),
        "section": ParagraphStyle(
            "section",
            fontName=_FONT_BOLD,
            fontSize=12,
            leading=16,
            textColor=INDIGO_DARK,
            spaceBefore=10,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=_FONT,
            fontSize=9.5,
            leading=13,
            textColor=TEXT,
        ),
        "muted": ParagraphStyle(
            "muted",
            fontName=_FONT,
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
        ),
        "kpi_label": ParagraphStyle(
            "kpi_label",
            fontName=_FONT,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
        ),
        "kpi_value": ParagraphStyle(
            "kpi_value",
            fontName=_FONT_BOLD,
            fontSize=13,
            leading=16,
            textColor=INDIGO_DARK,
        ),
        "th": ParagraphStyle(
            "th",
            fontName=_FONT_BOLD,
            fontSize=8,
            leading=10,
            textColor=white,
        ),
        "td": ParagraphStyle(
            "td",
            fontName=_FONT,
            fontSize=8,
            leading=10,
            textColor=TEXT,
        ),
        "td_right": ParagraphStyle(
            "td_right",
            fontName=_FONT,
            fontSize=8,
            leading=10,
            textColor=TEXT,
            alignment=TA_RIGHT,
        ),
        "param_label": ParagraphStyle(
            "param_label",
            fontName=_FONT,
            fontSize=7.5,
            leading=9,
            textColor=MUTED,
        ),
        "param_value": ParagraphStyle(
            "param_value",
            fontName=_FONT_BOLD,
            fontSize=9,
            leading=12,
            textColor=TEXT,
        ),
        "footer": ParagraphStyle(
            "footer",
            fontName=_FONT,
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
    }


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "")), style)


def _parse_money(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text in {"—", "-", "n/a", "N/A"}:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _as_breakdown_table(table_data: Any) -> dict[str, list[Any]]:
    """Normalize cash-flow rows to {Description, Amount} lists."""
    if isinstance(table_data, dict):
        descriptions = list(
            table_data.get("Description") or table_data.get("description") or []
        )
        amounts = list(table_data.get("Amount") or table_data.get("amount") or [])
        if len(amounts) < len(descriptions):
            amounts.extend([""] * (len(descriptions) - len(amounts)))
        return {"Description": descriptions, "Amount": amounts}
    if isinstance(table_data, list):
        descriptions: list[Any] = []
        amounts: list[Any] = []
        for row in table_data:
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                descriptions.append(row[0])
                amounts.append(row[1])
        return {"Description": descriptions, "Amount": amounts}
    return {"Description": [], "Amount": []}


def _quantum_chart_ready(quantum_risk: Any) -> dict[str, Any] | None:
    if not isinstance(quantum_risk, dict):
        return None
    required = (
        "cashflow_success_pct",
        "appreciation_success_pct",
        "combined_wealth_success_pct",
        "overall_success_pct",
    )
    if not all(isinstance(quantum_risk.get(key), (int, float)) for key in required):
        return None
    return quantum_risk


def _style_axes(ax: Any) -> None:
    ax.set_facecolor("#f8fafc")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e0e4ef")
    ax.spines["bottom"].set_color("#e0e4ef")
    ax.tick_params(colors="#64748b", labelsize=8)
    ax.grid(axis="x", linestyle="--", alpha=0.45, color="#cbd5e1")
    ax.set_axisbelow(True)


def _fig_png(fig: Any, *, width: float = 7.4, height: float = 3.05) -> bytes:
    fig.patch.set_facecolor("white")
    fig.set_size_inches(width, height)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


def _chart_image(png: bytes, *, height: float = 2.7 * inch) -> Image:
    img = Image(io.BytesIO(png), width=7.15 * inch, height=height)
    img.hAlign = "CENTER"
    return img


def _build_cashflow_chart(table: dict[str, list[Any]]) -> bytes | None:
    labels: list[str] = []
    values: list[float] = []
    colors: list[str] = []
    for desc, amt in zip(table["Description"], table["Amount"]):
        parsed = _parse_money(amt)
        if parsed is None:
            continue
        name = str(desc)
        if "total" in name.lower():
            continue
        short = (
            name.replace(" (P&I)", "")
            .replace(" (CapEx)", "")
            .replace("Gross monthly ", "")
            .replace("Gross Monthly ", "")
        )
        labels.append(short)
        values.append(parsed)
        low = name.lower()
        if "cash flow" in low:
            colors.append("#059669" if parsed >= 0 else "#e11d48")
        elif "rent" in low:
            colors.append("#4f46e5")
        else:
            colors.append("#fb7185")
    if len(values) < 2:
        return None

    fig, ax = plt.subplots()
    y = list(range(len(labels)))
    ax.barh(y, values, color=colors, height=0.62, zorder=3)
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.axvline(0, color="#94a3b8", linewidth=0.8)
    ax.set_xlabel("Monthly amount ($)")
    ax.set_title("Monthly cash flow mix", fontsize=11, color="#312e81", loc="left", pad=8)
    _style_axes(ax)
    ax.invert_yaxis()
    return _fig_png(fig, height=max(2.4, 0.38 * len(labels) + 1.1))


def _build_quantum_risk_chart(quantum_risk: dict) -> bytes:
    labels = ["Cash flow", "Appreciation", "Combined", "Overall"]
    values = [
        float(quantum_risk["cashflow_success_pct"]),
        float(quantum_risk["appreciation_success_pct"]),
        float(quantum_risk["combined_wealth_success_pct"]),
        float(quantum_risk["overall_success_pct"]),
    ]
    colors = ["#4f46e5", "#7c3aed", "#0d9488", "#d97706"]
    fig, ax = plt.subplots()
    bars = ax.bar(labels, values, color=colors, width=0.62, zorder=3)
    ax.set_ylim(0, 100)
    ax.axhline(50, color="#94a3b8", linestyle="--", linewidth=1, alpha=0.8)
    ax.set_ylabel("Alignment (%)")
    ax.set_title("QAOA alignment", fontsize=11, color="#312e81", loc="left", pad=8)
    _style_axes(ax)
    ax.grid(axis="y", linestyle="--", alpha=0.45, color="#cbd5e1")
    ax.grid(axis="x", visible=False)
    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 1.8,
            f"{val:.0f}%",
            ha="center",
            va="bottom",
            fontsize=8,
            color="#312e81",
            fontweight="bold",
        )
    return _fig_png(fig, height=2.85)


def _build_appreciation_forecast_chart(forecast: dict[str, Any]) -> bytes:
    start_year = datetime.datetime.now().year
    years = list(range(start_year, start_year + 11))
    values_p50 = forecast["value_schedule_p50"]
    values_p10 = forecast["value_schedule_p10"]
    values_p90 = forecast["value_schedule_p90"]
    fig, ax = plt.subplots()
    ax.fill_between(
        years, values_p10, values_p90, alpha=0.22, color="#4f46e5", label="10th–90th band"
    )
    ax.plot(years, values_p50, color="#4f46e5", linewidth=2.4, marker="o", markersize=4, label="Median")
    ax.set_title("10-year value forecast", fontsize=11, color="#312e81", loc="left", pad=8)
    ax.set_xlabel("Year")
    ax.set_ylabel("Estimated value ($)")
    ax.ticklabel_format(style="plain", axis="y")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _style_axes(ax)
    ax.grid(True, linestyle="--", alpha=0.4, color="#cbd5e1")
    return _fig_png(fig, height=3.0)


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


def _draw_brand_mark(canvas: Any, x: float, y: float, size: float = 12) -> None:
    canvas.setFillColor(white)
    canvas.roundRect(x, y, size, size, 2.2, fill=1, stroke=0)
    canvas.setFillColor(INDIGO)
    canvas.setFont(_FONT_BOLD, size * 0.72)
    canvas.drawCentredString(x + size / 2.0, y + size * 0.22, "C")


def _draw_page(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    width, height = letter
    canvas.setFillColor(PAGE_BG)
    canvas.rect(0, 0, width, height, fill=1, stroke=0)
    canvas.setFillColor(INDIGO)
    canvas.rect(0, height - 28, width, 28, fill=1, stroke=0)
    _draw_brand_mark(canvas, 36, height - 22, 12)
    canvas.setFillColor(white)
    canvas.setFont(_FONT_BOLD, 10)
    canvas.drawString(54, height - 18, APP_NAME)
    canvas.setFont(_FONT, 8)
    canvas.drawRightString(width - 36, height - 18, "Confidential analysis")
    canvas.setFillColor(INDIGO)
    canvas.rect(0, 0, width, 22, fill=1, stroke=0)
    canvas.setFillColor(white)
    canvas.setFont(_FONT, 7.5)
    canvas.drawString(36, 8, f"Prepared by {APP_NAME}")
    canvas.drawRightString(width - 36, 8, f"Page {doc.page}")
    canvas.restoreState()


def _hero(address: str, styles: dict[str, ParagraphStyle]) -> Table:
    inner = Table(
        [
            [_p(APP_NAME, styles["brand"])],
            [_p(APP_TAGLINE, styles["hero_sub"])],
            [_p(address or "Address unavailable", styles["hero"])],
        ],
        colWidths=[7.15 * inch],
    )
    inner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), INDIGO_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 14),
                ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                ("TOPPADDING", (0, 0), (0, 0), 12),
                ("BOTTOMPADDING", (0, -1), (-1, -1), 14),
                ("TOPPADDING", (0, 1), (-1, 1), 1),
                ("TOPPADDING", (0, 2), (-1, 2), 8),
            ]
        )
    )
    return inner


def _kpi_row(items: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    cards = []
    accents = [INDIGO, HexColor("#0d9488"), HexColor("#7c3aed"), AMBER]
    width = 7.15 * inch / max(len(items), 1)
    for i, (label, value) in enumerate(items):
        card = Table(
            [[_p(label.upper(), styles["kpi_label"])], [_p(value, styles["kpi_value"])]],
            colWidths=[width - 8],
        )
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
                    ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                    ("LINEABOVE", (0, 0), (-1, 0), 3, accents[i % len(accents)]),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        cards.append(card)
    row = Table([cards], colWidths=[width] * len(cards))
    row.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return row


def _params_grid(params: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table | None:
    items = [(str(k), str(v)) for k, v in params.items()]
    if not items:
        return None
    cells: list[list[Any]] = []
    row: list[Any] = []
    for label, value in items:
        cell = Table(
            [[_p(label, styles["param_label"])], [_p(value, styles["param_value"])]],
            colWidths=[1.7 * inch],
        )
        cell.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), white),
                    ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        row.append(cell)
        if len(row) == 4:
            cells.append(row)
            row = []
    if row:
        while len(row) < 4:
            row.append("")
        cells.append(row)
    grid = Table(cells, colWidths=[1.7875 * inch] * 4)
    grid.setStyle(
        TableStyle(
            [
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return grid


def _data_table(
    headers: list[str],
    rows: list[list[str]],
    styles: dict[str, ParagraphStyle],
    *,
    col_widths: list[float],
    emphasize_last: bool = False,
    amount_col: int | None = None,
) -> Table:
    header = [_p(h, styles["th"]) for h in headers]
    body: list[list[Any]] = [header]
    for row in rows:
        formatted = []
        for i, cell in enumerate(row):
            style = styles["td_right"] if i == amount_col else styles["td"]
            formatted.append(_p(cell, style))
        body.append(formatted)
    table = Table(body, colWidths=col_widths, repeatRows=1)
    commands: list[tuple[Any, ...]] = [
        ("BACKGROUND", (0, 0), (-1, 0), INDIGO),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
        ("BACKGROUND", (0, 1), (-1, -1), white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]
    if emphasize_last and len(body) > 1:
        commands.append(("BACKGROUND", (0, -1), (-1, -1), SURFACE))
        commands.append(("FONTNAME", (0, -1), (-1, -1), _FONT_BOLD))
    if amount_col is not None:
        for idx, row in enumerate(rows, start=1):
            parsed = _parse_money(row[amount_col]) if amount_col < len(row) else None
            if parsed is None:
                continue
            color = GREEN if parsed >= 0 and "cash flow" in str(row[0]).lower() else None
            if parsed < 0 or str(row[amount_col]).strip().startswith("-"):
                color = ROSE
            elif "rent" in str(row[0]).lower():
                color = INDIGO
            if color:
                commands.append(("TEXTCOLOR", (amount_col, idx), (amount_col, idx), color))
    table.setStyle(TableStyle(commands))
    return table


def _format_year_built(property_info: dict[str, Any]) -> str | None:
    """4-digit construction year from listing facts, if trustworthy."""
    for key in ("year_built", "year"):
        raw = property_info.get(key)
        if raw in (None, "", 0):
            continue
        try:
            year = int(float(raw))
        except (TypeError, ValueError):
            continue
        if year >= 1800:
            return str(year)
    return None


def _params_with_year_built(
    params: dict[str, Any], property_info: dict[str, Any]
) -> dict[str, Any]:
    year_built = _format_year_built(property_info)
    if not year_built:
        return params
    if any(str(key).strip().lower() == "year built" for key in params):
        return params
    merged = dict(params)
    merged["Year built"] = year_built
    return merged


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
    _init_fonts()
    styles = _styles()
    table_data = _as_breakdown_table(table_data)
    quantum_risk = _quantum_chart_ready(quantum_risk)
    if not isinstance(params, dict):
        params = {}
    if not isinstance(metrics, dict):
        metrics = {}
    if not isinstance(property_info, dict):
        property_info = {}
    params = _params_with_year_built(params, property_info)

    story: list[Any] = []
    story.append(_hero(str(address or ""), styles))
    story.append(Spacer(1, 12))

    kpi_items = [(str(k), str(v)) for k, v in list(metrics.items())[:3]]
    kpi_items.append(("Location score", f"{location_score}/10"))
    story.append(_kpi_row(kpi_items[:4], styles))
    story.append(Spacer(1, 12))

    story.append(_p("Underwriting assumptions", styles["section"]))
    grid = _params_grid(params, styles)
    if grid:
        story.append(grid)
    else:
        story.append(_p("Default underwriting assumptions.", styles["muted"]))

    summary = property_info.get("summary") or "No summary available."
    story.append(_p("Property summary", styles["section"]))
    summary_table = Table([[_p(summary, styles["body"])]], colWidths=[7.15 * inch])
    summary_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), white),
                ("BOX", (0, 0), (-1, -1), 0.4, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(summary_table)

    story.append(_p("Monthly cash flow", styles["section"]))
    cash_png = _build_cashflow_chart(table_data)
    if cash_png:
        story.append(_chart_image(cash_png, height=2.55 * inch))
        story.append(Spacer(1, 8))
    breakdown_rows = [
        [str(table_data["Description"][i]), str(table_data["Amount"][i])]
        for i in range(len(table_data["Description"]))
    ]
    if breakdown_rows:
        story.append(
            _data_table(
                ["Description", "Monthly amount"],
                breakdown_rows,
                styles,
                col_widths=[4.85 * inch, 2.3 * inch],
                emphasize_last=True,
                amount_col=1,
            )
        )

    comps_analysis = property_info.get("comps_analysis")
    if isinstance(comps_analysis, dict) and comps_analysis.get("comparable_properties"):
        story.append(_p("Comparable sales", styles["section"]))
        market_value = comps_analysis.get("comp_suggested_value")
        story.append(
            _kpi_row(
                [
                    (
                        "Market value",
                        f"${float(market_value):,.0f}" if market_value else "-",
                    ),
                    (
                        "Median sale",
                        f"${float(comps_analysis.get('median_sale_price') or 0):,.0f}",
                    ),
                    (
                        "List price",
                        f"${float(comps_analysis.get('list_price') or 0):,.0f}",
                    ),
                ],
                styles,
            )
        )
        if comps_analysis.get("summary"):
            story.append(Spacer(1, 6))
            story.append(_p(str(comps_analysis.get("summary")), styles["muted"]))
        story.append(Spacer(1, 6))
        comp_rows = [
            [r["address"], r["price"], r["date"], r["sqft"], r["ppsf"], r["distance"]]
            for r in _sales_comps_pdf_rows(comps_analysis)
        ]
        if comp_rows:
            story.append(
                _data_table(
                    ["Address", "Sale price", "Date", "Sq ft", "$/sq ft", "Miles"],
                    comp_rows,
                    styles,
                    col_widths=[2.35 * inch, 1.05 * inch, 0.85 * inch, 0.8 * inch, 0.9 * inch, 0.8 * inch],
                )
            )

    rent_comps_analysis = property_info.get("rent_comps_analysis")
    if isinstance(rent_comps_analysis, dict) and rent_comps_analysis.get("comparable_rentals"):
        story.append(_p("Comparable rentals", styles["section"]))
        rent_kpis = [
            (
                "Comp-implied rent",
                f"${float(rent_comps_analysis.get('comp_suggested_rent') or 0):,.0f}/mo",
            ),
            (
                "Median rent",
                f"${float(rent_comps_analysis.get('median_monthly_rent') or 0):,.0f}/mo",
            ),
            (
                "Subject rent",
                f"${float(rent_comps_analysis.get('subject_rent') or 0):,.0f}/mo",
            ),
        ]
        gap = rent_comps_analysis.get("rent_vs_comps_pct")
        if gap is not None:
            rent_kpis.append(("Vs comps", f"{float(gap):+.1f}%"))
        story.append(_kpi_row(rent_kpis[:4], styles))
        if rent_comps_analysis.get("summary"):
            story.append(Spacer(1, 6))
            story.append(_p(str(rent_comps_analysis.get("summary")), styles["muted"]))
        story.append(Spacer(1, 6))
        rent_rows = [
            [r["address"], r["price"], r["date"], r["sqft"], r["ppsf"], r["distance"]]
            for r in _rent_comps_pdf_rows(rent_comps_analysis)
        ]
        if rent_rows:
            story.append(
                _data_table(
                    ["Address", "Rent", "Date", "Sq ft", "$/sq ft", "Miles"],
                    rent_rows,
                    styles,
                    col_widths=[2.35 * inch, 1.05 * inch, 0.85 * inch, 0.8 * inch, 0.9 * inch, 0.8 * inch],
                )
            )

    if isinstance(forecast_display, dict) and forecast_display.get("value_schedule_p50"):
        story.append(_p("10-year appreciation forecast", styles["section"]))
        end_year = datetime.datetime.now().year + 10
        story.append(
            _kpi_row(
                [
                    (
                        f"Median {end_year}",
                        f"${float(forecast_display['future_value_p50']):,.0f}",
                    ),
                    (
                        "10th–90th band",
                        f"${float(forecast_display['future_value_p10']):,.0f} – ${float(forecast_display['future_value_p90']):,.0f}",
                    ),
                    (
                        "Annual growth",
                        f"{float(forecast_display['annual_rate']):.2f}%",
                    ),
                ],
                styles,
            )
        )
        story.append(Spacer(1, 8))
        story.append(KeepTogether([_chart_image(_build_appreciation_forecast_chart(forecast_display), height=2.85 * inch)]))

    if quantum_risk:
        story.append(_p("QAOA alignment", styles["section"]))
        story.append(
            _p(
                "Educational simulation of how this deal aligns with cash-flow, appreciation, "
                "and combined wealth targets. Not a prediction of market performance.",
                styles["muted"],
            )
        )
        story.append(Spacer(1, 6))
        story.append(
            _kpi_row(
                [
                    ("Cash flow", f"{quantum_risk['cashflow_success_pct']:.0f}%"),
                    ("Appreciation", f"{quantum_risk['appreciation_success_pct']:.0f}%"),
                    ("Combined", f"{quantum_risk['combined_wealth_success_pct']:.0f}%"),
                    ("Overall", f"{quantum_risk['overall_success_pct']:.0f}%"),
                ],
                styles,
            )
        )
        story.append(Spacer(1, 8))
        story.append(KeepTogether([_chart_image(_build_quantum_risk_chart(quantum_risk), height=2.7 * inch)]))

    extra_metrics = list(metrics.items())[3:]
    if extra_metrics:
        story.append(_p("Additional projections", styles["section"]))
        extra_rows = [[str(k), str(v)] for k, v in extra_metrics]
        story.append(
            _data_table(
                ["Metric", "Value"],
                extra_rows,
                styles,
                col_widths=[4.85 * inch, 2.3 * inch],
                amount_col=1,
            )
        )

    story.append(Spacer(1, 14))
    story.append(
        _p(
            f"Prepared by {APP_NAME}. Report generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}. "
            "Comps and forecasts are AI-assisted estimates. "
            "Quantum alignment scores are educational simulations, not financial guarantees.",
            styles["footer"],
        )
    )

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.55 * inch,
        rightMargin=0.55 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.45 * inch,
        title=f"{APP_NAME} — {address}",
        author=APP_NAME,
        creator=f"{APP_NAME} Property Analysis",
        subject=f"{APP_NAME} investment analysis for {address}",
    )
    doc.build(story, onFirstPage=_draw_page, onLaterPages=_draw_page)
    return buf.getvalue()
