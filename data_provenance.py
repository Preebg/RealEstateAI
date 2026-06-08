"""Data provenance and per-field confidence for property records."""

from __future__ import annotations

from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").replace("%", "").strip()
            return float(cleaned) if cleaned else default
        return float(value)
    except (TypeError, ValueError):
        return default

# SNR-style prior confidence: how trustworthy each field is as a "sensor reading"
# from listing scrapes (high = strong signal, low = noisy / inferred).
FIELD_BASE_CONFIDENCE: dict[str, float] = {
    "price": 0.90,
    "rent": 0.55,
    "tax_rate": 0.70,
    "taxes": 0.70,
    "insurance": 0.50,
    "hoa": 0.75,
    "maint_percent": 0.45,
    "predicted_value": 0.60,
    "location_score": 0.50,
    "vacancy_rate": 0.55,
    "management_fee": 0.55,
}

NORMALIZATION_HELPERS: dict[str, str] = {
    "insurance": "finance.normalize_monthly_insurance",
    "tax_rate": "finance.normalize_tax_rate_percent",
    "vacancy_rate": "finance.normalize_percent_rate",
    "management_fee": "finance.normalize_percent_rate",
    "maint_percent": "finance.normalize_percent_rate",
    "ai_vacancy_rate": "finance.normalize_percent_rate",
    "ai_management_fee": "finance.normalize_percent_rate",
}

SCORING_STAGES: list[dict[str, Any]] = [
    {
        "stage": "numeric_sanitize",
        "module": "engine._sanitize_synthesis_numerics",
        "inputs": list(NORMALIZATION_HELPERS.keys()) + ["price", "rent", "hoa"],
        "output": "canonical numerics",
    },
    {
        "stage": "appreciation_forecast",
        "module": "finance.calculate_10yr_appreciation",
        "inputs": ["predicted_value", "location_score", "market_city"],
        "outputs": ["forecast_rate", "appreciation_forecast", "forecast_value_p10", "forecast_value_p90"],
    },
    {
        "stage": "investment_analysis",
        "module": "finance.analyze_investment",
        "inputs": ["price", "rent", "tax_rate", "insurance", "hoa", "maint_percent"],
        "outputs": ["cap_rate", "cash_on_cash", "monthly_net_cash_flow"],
    },
    {
        "stage": "quantum_risk",
        "module": "quantum_portfolio.score_portfolio",
        "inputs": ["monthly_net_cash_flow", "forecast_rate", "location_score"],
        "outputs": ["quantum_risk_score"],
    },
]


def _clamp_confidence(value: float) -> float:
    return round(min(max(value, 0.0), 1.0), 2)


def compute_field_confidence(
    property_data: dict[str, Any],
    research: dict[str, Any] | None = None,
) -> dict[str, float]:
    """
    Estimate per-field confidence (0–1) from extraction quality signals.

    Mirrors an SNR view: listing price is a strong signal; rent from comps is noisy.
    """
    scores: dict[str, float] = {}

    price = _safe_float(property_data.get("price"))
    rent = _safe_float(property_data.get("rent") or property_data.get("original_ai_rent"))
    tax_rate = _safe_float(property_data.get("tax_rate"))

    price_conf = FIELD_BASE_CONFIDENCE["price"]
    if price <= 0:
        price_conf = 0.15
    elif research and _safe_float(research.get("price")) > 0:
        price_conf = min(price_conf + 0.05, 0.95)
    scores["price"] = _clamp_confidence(price_conf)

    rent_conf = FIELD_BASE_CONFIDENCE["rent"]
    stated_rent = 0.0
    rent_notes = ""
    if research:
        stated_rent = _safe_float(research.get("stated_gross_monthly_rent"))
        rent_notes = str(research.get("listing_rent_notes", "")).strip()
    if stated_rent > 0 or rent_notes:
        rent_conf = min(rent_conf + 0.30, 0.88)
    elif rent <= 0:
        rent_conf = 0.25
    sources = property_data.get("sources") or []
    if len(sources) >= 3:
        rent_conf = min(rent_conf + 0.05, 0.90)
    scores["rent"] = _clamp_confidence(rent_conf)

    tax_conf = FIELD_BASE_CONFIDENCE["tax_rate"]
    annual_taxes = _safe_float(research.get("taxes") if research else 0)
    if annual_taxes > 0 and price > 0:
        tax_conf = min(tax_conf + 0.10, 0.85)
    elif tax_rate <= 0:
        tax_conf = 0.30
    scores["tax_rate"] = _clamp_confidence(tax_conf)
    scores["taxes"] = scores["tax_rate"]

    insurance_conf = FIELD_BASE_CONFIDENCE["insurance"]
    if _safe_float(property_data.get("insurance")) <= 0:
        insurance_conf = 0.25
    scores["insurance"] = _clamp_confidence(insurance_conf)

    hoa_conf = FIELD_BASE_CONFIDENCE["hoa"]
    if research and _safe_float(research.get("hoa")) >= 0:
        hoa_conf = min(hoa_conf + 0.05, 0.85)
    scores["hoa"] = _clamp_confidence(hoa_conf)

    for key in ("maint_percent", "predicted_value", "location_score", "vacancy_rate", "management_fee"):
        scores[key] = _clamp_confidence(FIELD_BASE_CONFIDENCE[key])

    return scores


def _extraction_stage(
    property_data: dict[str, Any],
    research: dict[str, Any] | None,
) -> dict[str, Any]:
    if research:
        return {
            "stage": "research_property",
            "model": "gemma-4-31b-it (search grounding)",
            "fields": {
                "price": {
                    "raw_value": _safe_float(research.get("price")),
                    "source": "listing list price / MLS headline",
                },
                "taxes": {
                    "raw_value": _safe_float(research.get("taxes")),
                    "source": "county assessor / listing tax line",
                },
                "hoa": {
                    "raw_value": _safe_float(research.get("hoa")),
                    "source": "listing HOA fee",
                },
                "stated_gross_monthly_rent": {
                    "raw_value": _safe_float(research.get("stated_gross_monthly_rent")),
                    "source": "listing description rent/income language",
                    "notes": str(research.get("listing_rent_notes", "")).strip(),
                },
                "year_built": research.get("year_built"),
                "square_footage": research.get("square_footage"),
                "property_condition": research.get("property_condition"),
                "property_type": research.get("property_type"),
            },
        }

    return {
        "stage": "researcher_agent + analyzer_agent",
        "model": "gemma-4-31b-it → synthesis model",
        "fields": {
            "price": {
                "raw_value": _safe_float(property_data.get("price")),
                "source": "cross-referenced listing scrapes (≥3 sources requested)",
            },
            "rent": {
                "raw_value": _safe_float(property_data.get("rent")),
                "source": "listing rent/income or Rent Zestimate / comps",
            },
            "tax_rate": {
                "raw_value": _safe_float(property_data.get("tax_rate")),
                "source": "annual tax ÷ price (synthesis)",
            },
            "insurance": {
                "raw_value": _safe_float(property_data.get("insurance")),
                "source": "listing or zip-level estimate",
            },
            "hoa": {
                "raw_value": _safe_float(property_data.get("hoa")),
                "source": "listing HOA line",
            },
        },
    }


def _normalization_stage(property_data: dict[str, Any]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for field, helper in NORMALIZATION_HELPERS.items():
        if field not in property_data and field.replace("ai_", "") not in property_data:
            continue
        value = property_data.get(field)
        if value is None:
            continue
        steps.append(
            {
                "field": field,
                "helper": helper,
                "normalized_value": value,
                "note": _normalization_note(field, value),
            }
        )
    if _safe_float(property_data.get("price")) > 0 and _safe_float(property_data.get("tax_rate")) > 0:
        steps.append(
            {
                "field": "monthly_taxes",
                "helper": "finance.calculate_operating_expenses",
                "normalized_value": round(
                    (_safe_float(property_data["tax_rate"]) / 100.0)
                    * _safe_float(property_data["price"])
                    / 12.0,
                    2,
                ),
                "note": "tax_rate (%) × price / 12 → monthly property tax",
            }
        )
    return steps


def _normalization_note(field: str, value: Any) -> str:
    if field == "insurance" and _safe_float(value) < 400:
        return "value ≤ $400 threshold → treated as monthly premium"
    if field == "insurance":
        return "value > $400 threshold → annual premium ÷ 12"
    if field == "tax_rate":
        return "decimal rates (e.g. 0.034) scaled to percent (3.4%)"
    if field in ("vacancy_rate", "management_fee", "maint_percent", "ai_vacancy_rate", "ai_management_fee"):
        return "decimal fees (e.g. 0.06) scaled to percent (6%) when in (0, 1)"
    return "passed through finance helper"


def build_data_provenance(
    property_data: dict[str, Any],
    research: dict[str, Any] | None = None,
    *,
    pipeline: str = "underwriter_ui",
) -> dict[str, Any]:
    """Build optional provenance block: sources → extraction → normalization → scoring."""
    sources = property_data.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]

    return {
        "signal_chain": [
            "source_urls",
            "extraction_fields",
            "normalization",
            "scoring",
        ],
        "source_urls": list(dict.fromkeys(str(s) for s in sources if s)),
        "extraction": _extraction_stage(property_data, research),
        "normalization": _normalization_stage(property_data),
        "scoring": SCORING_STAGES,
        "pipeline": pipeline,
    }


def attach_data_provenance(
    property_data: dict[str, Any],
    research: dict[str, Any] | None = None,
    *,
    pipeline: str = "underwriter_ui",
) -> dict[str, Any]:
    """Attach confidence_score and data_provenance to a property record in place."""
    property_data["confidence_score"] = compute_field_confidence(property_data, research)
    property_data["data_provenance"] = build_data_provenance(
        property_data, research, pipeline=pipeline
    )
    return property_data


def ensure_data_provenance(property_data: dict[str, Any]) -> dict[str, Any]:
    """Backfill provenance for cached records that predate this feature."""
    if property_data.get("confidence_score") and property_data.get("data_provenance"):
        return property_data
    return attach_data_provenance(property_data)


def confidence_label(score: float) -> str:
    """Human-readable band for UI badges."""
    if score >= 0.80:
        return "High"
    if score >= 0.60:
        return "Medium"
    if score >= 0.40:
        return "Low"
    return "Very Low"


def confidence_badge_color(score: float) -> str:
    if score >= 0.80:
        return "#1b7f3a"
    if score >= 0.60:
        return "#b8860b"
    if score >= 0.40:
        return "#c45c00"
    return "#a31d1d"
