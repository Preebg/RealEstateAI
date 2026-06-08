"""Comparable rental research and rent cross-check for subject properties."""

from __future__ import annotations

import datetime
from statistics import median
from typing import Any

from comps_analysis import MIN_COMPS_FOR_SUMMARY, safe_float

UNDERRENTED_THRESHOLD_PCT = 8.0


def _pct_gap(subject: float, benchmark: float) -> float | None:
    if subject <= 0 or benchmark <= 0:
        return None
    return round((subject - benchmark) / benchmark * 100, 1)


def normalize_rent_comp_record(raw: Any) -> dict[str, Any] | None:
    """Normalize one comparable rental record from LLM JSON."""
    if not isinstance(raw, dict):
        return None

    monthly_rent = safe_float(raw.get("monthly_rent"))
    if monthly_rent <= 0:
        return None

    sqft = int(safe_float(raw.get("square_footage")))
    return {
        "address": str(raw.get("address") or "Unknown").strip() or "Unknown",
        "monthly_rent": monthly_rent,
        "lease_date": str(raw.get("lease_date") or raw.get("listed_date") or "").strip(),
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


def normalize_rent_comps_payload(data: Any) -> dict[str, Any]:
    """Normalize rent comps agent JSON into a stable structure."""
    if not isinstance(data, dict):
        return {
            "comparable_rentals": [],
            "market_summary": "",
        }

    rentals: list[dict[str, Any]] = []
    for item in data.get("comparable_rentals") or []:
        normalized = normalize_rent_comp_record(item)
        if normalized:
            rentals.append(normalized)

    return {
        "comparable_rentals": rentals,
        "market_summary": str(data.get("market_summary") or "").strip(),
    }


def _median_rent_per_sqft(rentals: list[dict[str, Any]]) -> float | None:
    rates: list[float] = []
    for rental in rentals:
        sqft = rental.get("square_footage")
        rent = safe_float(rental.get("monthly_rent"))
        if sqft and sqft > 0 and rent > 0:
            rates.append(rent / sqft)
    if not rates:
        return None
    return float(median(rates))


def evaluate_rent_comps_against_subject(
    rent_comps_payload: dict[str, Any],
    subject: dict[str, Any],
    *,
    underrented_threshold_pct: float = UNDERRENTED_THRESHOLD_PCT,
) -> dict[str, Any]:
    """
    Compare AI / listing rent against comp-implied market rent.

    Returns a summary dict suitable for storage on property_data["rent_comps_analysis"].
    """
    rentals = list(rent_comps_payload.get("comparable_rentals") or [])
    subject_rent = safe_float(subject.get("rent"))
    if subject_rent <= 0:
        subject_rent = safe_float(subject.get("original_ai_rent"))
    subject_sqft = int(safe_float(subject.get("square_footage")))

    monthly_rents = [
        safe_float(r.get("monthly_rent"))
        for r in rentals
        if safe_float(r.get("monthly_rent")) > 0
    ]
    median_rent = float(median(monthly_rents)) if monthly_rents else 0.0
    median_rpsf = _median_rent_per_sqft(rentals)

    comp_suggested_rent = 0.0
    if median_rpsf and subject_sqft > 0:
        comp_suggested_rent = round(median_rpsf * subject_sqft)
    elif median_rent > 0:
        comp_suggested_rent = round(median_rent)

    benchmark = comp_suggested_rent or median_rent
    rent_gap_pct = _pct_gap(subject_rent, benchmark) if benchmark > 0 else None

    is_underrented = False
    if benchmark > 0 and len(monthly_rents) >= MIN_COMPS_FOR_SUMMARY:
        if rent_gap_pct is not None and rent_gap_pct <= -underrented_threshold_pct:
            is_underrented = True

    summary_parts: list[str] = []
    if len(monthly_rents) < MIN_COMPS_FOR_SUMMARY:
        summary_parts.append(
            f"Only {len(monthly_rents)} valid rental comp(s) found — need at least "
            f"{MIN_COMPS_FOR_SUMMARY} for a reliable cross-check."
        )
    elif benchmark > 0:
        summary_parts.append(
            f"Median comp rent: ${median_rent:,.0f}/mo"
            + (f" (${median_rpsf:,.2f}/sqft)" if median_rpsf else "")
            + f". Comp-implied rent: ${comp_suggested_rent:,.0f}/mo."
        )
        if is_underrented:
            summary_parts.append(
                "Listing or AI rent appears below nearby comparable rentals — upside potential."
            )
        else:
            summary_parts.append("Rent appears broadly aligned with area rental comps.")

    market_summary = str(rent_comps_payload.get("market_summary") or "").strip()
    if market_summary:
        summary_parts.append(market_summary)

    return {
        "comparable_rentals": rentals,
        "comp_count": len(rentals),
        "median_monthly_rent": median_rent,
        "median_rent_per_sqft": median_rpsf,
        "comp_suggested_rent": comp_suggested_rent,
        "subject_rent": subject_rent,
        "rent_vs_comps_pct": rent_gap_pct,
        "is_underrented": is_underrented,
        "underrented_threshold_pct": underrented_threshold_pct,
        "market_summary": market_summary,
        "summary": " ".join(summary_parts).strip(),
        "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


def apply_rent_comps_adjustment(
    property_data: dict[str, Any],
    rent_comps_analysis: dict[str, Any],
) -> bool:
    """Raise rent baseline when comps show material upside vs listing/AI rent."""
    if not rent_comps_analysis.get("is_underrented"):
        return False

    suggested = safe_float(rent_comps_analysis.get("comp_suggested_rent"))
    if suggested <= 0:
        suggested = safe_float(rent_comps_analysis.get("median_monthly_rent"))
    if suggested <= 0:
        return False

    current = safe_float(property_data.get("rent"))
    if current <= 0:
        return False

    uplift_pct = (suggested - current) / current * 100
    if uplift_pct < 5.0:
        return False

    property_data["rent"] = round(suggested)
    if property_data.get("original_ai_rent") is None:
        property_data["original_ai_rent"] = current
    property_data["rent_comps_adjusted"] = True
    return True
