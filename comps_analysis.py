"""Comparable sales research and valuation cross-check for subject properties."""

from __future__ import annotations

import datetime
from statistics import median
from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        if isinstance(value, str):
            cleaned = value.replace("$", "").replace(",", "").replace("%", "").strip()
            return float(cleaned) if cleaned else default
        return float(value)
    except (TypeError, ValueError):
        return default

MIN_COMPS_FOR_SUMMARY = 2
UNDERVALUATION_THRESHOLD_PCT = 8.0


def normalize_comp_record(raw: Any) -> dict[str, Any] | None:
    """Normalize one comparable sale record from LLM JSON."""
    if not isinstance(raw, dict):
        return None

    sale_price = safe_float(raw.get("sale_price"))
    if sale_price <= 0:
        return None

    sqft = int(safe_float(raw.get("square_footage")))
    return {
        "address": str(raw.get("address") or "Unknown").strip() or "Unknown",
        "sale_price": sale_price,
        "sale_date": str(raw.get("sale_date") or "").strip(),
        "square_footage": sqft if sqft > 0 else None,
        "bedrooms": _optional_int(raw.get("bedrooms")),
        "bathrooms": _optional_float(raw.get("bathrooms")),
        "property_type": str(raw.get("property_type") or "").strip(),
        "distance_miles": _optional_float(raw.get("distance_miles")),
        "comparison_notes": str(raw.get("comparison_notes") or "").strip(),
        "source_url": str(raw.get("source_url") or "").strip(),
    }


def _optional_int(value: Any) -> int | None:
    parsed = int(safe_float(value))
    return parsed if parsed > 0 else None


def _optional_float(value: Any) -> float | None:
    parsed = safe_float(value)
    return parsed if parsed > 0 else None


def normalize_comps_payload(data: Any) -> dict[str, Any]:
    """Normalize comps agent JSON into a stable structure."""
    if not isinstance(data, dict):
        return {
            "comparable_properties": [],
            "market_summary": "",
        }

    comps: list[dict[str, Any]] = []
    for item in data.get("comparable_properties") or []:
        normalized = normalize_comp_record(item)
        if normalized:
            comps.append(normalized)

    return {
        "comparable_properties": comps,
        "market_summary": str(data.get("market_summary") or "").strip(),
    }


def _median_price_per_sqft(comps: list[dict[str, Any]]) -> float | None:
    rates: list[float] = []
    for comp in comps:
        sqft = comp.get("square_footage")
        price = safe_float(comp.get("sale_price"))
        if sqft and sqft > 0 and price > 0:
            rates.append(price / sqft)
    if not rates:
        return None
    return float(median(rates))


def _pct_gap(subject: float, benchmark: float) -> float | None:
    if subject <= 0 or benchmark <= 0:
        return None
    return round((subject - benchmark) / benchmark * 100, 1)


def evaluate_comps_against_subject(
    comps_payload: dict[str, Any],
    subject: dict[str, Any],
    *,
    undervaluation_threshold_pct: float = UNDERVALUATION_THRESHOLD_PCT,
) -> dict[str, Any]:
    """
    Compare list price and predicted value against comp medians.

    Returns a summary dict suitable for storage on property_data["comps_analysis"].
    """
    comps = list(comps_payload.get("comparable_properties") or [])
    list_price = safe_float(subject.get("price"))
    predicted_value = safe_float(subject.get("predicted_value")) or list_price
    subject_sqft = int(safe_float(subject.get("square_footage")))

    sale_prices = [safe_float(c.get("sale_price")) for c in comps if safe_float(c.get("sale_price")) > 0]
    median_sale_price = float(median(sale_prices)) if sale_prices else 0.0
    median_ppsf = _median_price_per_sqft(comps)

    comp_suggested_value = 0.0
    if median_ppsf and subject_sqft > 0:
        comp_suggested_value = round(median_ppsf * subject_sqft)
    elif median_sale_price > 0:
        comp_suggested_value = round(median_sale_price)

    benchmark = comp_suggested_value or median_sale_price
    list_gap_pct = _pct_gap(list_price, benchmark) if benchmark > 0 else None
    predicted_gap_pct = _pct_gap(predicted_value, benchmark) if benchmark > 0 else None

    is_undervalued = False
    if benchmark > 0 and len(sale_prices) >= MIN_COMPS_FOR_SUMMARY:
        for gap in (list_gap_pct, predicted_gap_pct):
            if gap is not None and gap <= -undervaluation_threshold_pct:
                is_undervalued = True
                break

    summary_parts: list[str] = []
    if len(sale_prices) < MIN_COMPS_FOR_SUMMARY:
        summary_parts.append(
            f"Only {len(sale_prices)} valid comp(s) found — need at least "
            f"{MIN_COMPS_FOR_SUMMARY} for a reliable cross-check."
        )
    elif benchmark > 0:
        summary_parts.append(
            f"Median comp sale: ${median_sale_price:,.0f}"
            + (f" (${median_ppsf:,.0f}/sqft)" if median_ppsf else "")
            + f". Comp-implied value: ${comp_suggested_value:,.0f}."
        )
        if is_undervalued:
            summary_parts.append(
                "List price or AI predicted value appears below nearby comparable sales."
            )
        else:
            summary_parts.append("Valuation is broadly aligned with area comps.")

    market_summary = str(comps_payload.get("market_summary") or "").strip()
    if market_summary:
        summary_parts.append(market_summary)

    return {
        "comparable_properties": comps,
        "comp_count": len(comps),
        "median_sale_price": median_sale_price,
        "median_price_per_sqft": median_ppsf,
        "comp_suggested_value": comp_suggested_value,
        "list_price": list_price,
        "predicted_value": predicted_value,
        "list_vs_comps_pct": list_gap_pct,
        "predicted_vs_comps_pct": predicted_gap_pct,
        "is_undervalued": is_undervalued,
        "undervaluation_threshold_pct": undervaluation_threshold_pct,
        "market_summary": market_summary,
        "summary": " ".join(summary_parts).strip(),
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def resolve_market_value(property_data: dict[str, Any]) -> float:
    """Return comp-implied value when enough comps exist, else predicted or list price."""
    comps = property_data.get("comps_analysis")
    if isinstance(comps, dict) and int(comps.get("comp_count") or 0) >= MIN_COMPS_FOR_SUMMARY:
        comp_value = safe_float(comps.get("comp_suggested_value"))
        if comp_value > 0:
            return comp_value
    predicted = safe_float(property_data.get("predicted_value"))
    if predicted > 0:
        return predicted
    return safe_float(property_data.get("price"))


def evaluate_offer_success(
    offer_amount: float,
    market_value: float,
    list_price: float,
) -> dict[str, Any]:
    """
    Estimate deal success: how favorable is this offer vs comp-implied market value.

    Higher scores mean the offer is at or below market value (better buy).
    """
    if market_value <= 0:
        market_value = list_price
    if offer_amount <= 0 or market_value <= 0:
        return {
            "success_pct": None,
            "offer_vs_market_pct": None,
            "market_value": market_value,
            "message": "Enter an offer amount to see deal success probability.",
        }

    offer_vs_market_pct = round((offer_amount - market_value) / market_value * 100, 1)
    ratio = offer_amount / market_value

    if ratio <= 0.90:
        success = 95.0
    elif ratio <= 1.0:
        success = 95.0 - (ratio - 0.90) / 0.10 * 15.0
    elif ratio <= 1.05:
        success = 80.0 - (ratio - 1.0) / 0.05 * 30.0
    elif ratio <= 1.15:
        success = 50.0 - (ratio - 1.05) / 0.10 * 35.0
    else:
        success = max(5.0, 15.0 - (ratio - 1.15) * 50.0)

    if list_price > 0 and offer_amount <= list_price and market_value > list_price:
        discount_pct = (market_value - list_price) / market_value * 100
        success = min(98.0, success + discount_pct * 0.4)

    if offer_vs_market_pct <= -5:
        message = (
            f"Offer is {abs(offer_vs_market_pct):.1f}% below comp-implied market value "
            "— strong deal potential."
        )
    elif offer_vs_market_pct <= 0:
        message = "Offer is at or slightly below comp-implied market value."
    elif offer_vs_market_pct <= 5:
        message = (
            f"Offer is {offer_vs_market_pct:.1f}% above comp-implied value "
            "— moderate risk of overpaying."
        )
    else:
        message = (
            f"Offer is {offer_vs_market_pct:.1f}% above comp-implied value "
            "— likely overpaying."
        )

    return {
        "success_pct": round(success, 1),
        "offer_vs_market_pct": offer_vs_market_pct,
        "market_value": market_value,
        "message": message,
    }


def apply_comp_implied_market_value(
    property_data: dict[str, Any],
    comps_analysis: dict[str, Any],
) -> bool:
    """
    Set predicted_value to comp-implied value when enough comps exist.

    Returns True when predicted_value was updated.
    """
    comp_count = int(comps_analysis.get("comp_count") or 0)
    if comp_count < MIN_COMPS_FOR_SUMMARY:
        return False

    suggested = safe_float(comps_analysis.get("comp_suggested_value"))
    if suggested <= 0:
        suggested = safe_float(comps_analysis.get("median_sale_price"))
    if suggested <= 0:
        return False

    current = safe_float(property_data.get("predicted_value"))
    if current <= 0:
        current = safe_float(property_data.get("price"))

    rounded = round(suggested)
    property_data["predicted_value"] = rounded
    property_data["market_value"] = rounded

    if abs(suggested - current) > 0.01:
        prior = str(property_data.get("prediction_reasoning") or "").strip()
        median_price = safe_float(comps_analysis.get("median_sale_price"))
        adjustment_note = (
            f"Market value set to ${rounded:,.0f} from {comp_count} area comps "
            f"(median sale ${median_price:,.0f})."
        )
        property_data["prediction_reasoning"] = (
            f"{prior} {adjustment_note}".strip() if prior else adjustment_note
        )

    property_data["comps_adjusted_predicted_value"] = True
    return True


def apply_comps_valuation_adjustment(
    property_data: dict[str, Any],
    comps_analysis: dict[str, Any],
    *,
    min_adjustment_pct: float = 5.0,
) -> bool:
    """Backward-compatible alias — always applies comp-implied value when comps qualify."""
    _ = min_adjustment_pct
    return apply_comp_implied_market_value(property_data, comps_analysis)
