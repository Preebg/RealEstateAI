"""Headless portfolio geocoding and dataframe helpers."""

from __future__ import annotations

import hashlib
import math
import time
from typing import Any

import pandas as pd

from finance import analyze_investment, calculate_10yr_appreciation, calculate_one_year_roi
from knowledge_base import (
    _fetch_canonical_properties,
    _normalize_record_numerics,
    get_ai_baseline_maint,
    get_ai_baseline_rent,
    invalidate_kb_cache,
    normalize_address_key,
    parse_state_code_from_address,
    parse_zipcode_from_address,
)
from viewer_timezone import parse_property_timestamp

_PORTFOLIO_CACHE: dict[str, Any] = {}
_PORTFOLIO_CACHE_TTL_SECONDS = 300


def load_global_portfolio_properties() -> list[dict[str, Any]]:
    """Load every canonical property row from the shared global KB."""
    now = time.time()
    cached = _PORTFOLIO_CACHE.get("properties")
    if cached and now - cached[0] < _PORTFOLIO_CACHE_TTL_SECONDS:
        return cached[1]
    rows = _fetch_canonical_properties()
    result = [_normalize_record_numerics(row) for row in rows if row.get("address")]
    _PORTFOLIO_CACHE["properties"] = (now, result)
    return result


def invalidate_portfolio_cache() -> None:
    """Clear portfolio caches and knowledge-base read caches."""
    _PORTFOLIO_CACHE.clear()
    try:
        invalidate_kb_cache()
    except Exception:
        pass

MARKET_CITY_CENTERS: dict[str, tuple[float, float]] = {
    "Rochester": (43.1566, -77.6088),
    "Syracuse": (43.0481, -76.1474),
    "Buffalo": (42.8864, -78.8784),
    "Albany": (42.6526, -73.7562),
    "Philadelphia": (39.9526, -75.1652),
    "Pittsburgh": (40.4406, -79.9959),
    "Orlando": (28.5383, -81.3792),
    "Tampa": (27.9506, -82.4572),
    "Miami": (25.7617, -80.1918),
    "Charlotte": (35.2271, -80.8431),
    "Raleigh": (35.7796, -78.6382),
    "Charleston": (32.7765, -79.9311),
    "Ohio": (40.0634, -82.9001),
    "DFW": (32.7767, -96.7970),
    "Austin": (30.2672, -97.7431),
}

# Suburb/city keywords → local map center (same pattern as legacy Ohio handling).
METRO_SUBURB_CENTERS: dict[str, tuple[tuple[str, tuple[float, float]], ...]] = {
    "Buffalo": (
        ("amherst", (42.9784, -78.7997)),
        ("cheektowaga", (42.9034, -78.7548)),
        ("tonawanda", (43.0203, -78.8803)),
        ("williamsville", (42.9639, -78.7378)),
        ("west seneca", (42.8501, -78.7998)),
        ("hamburg", (42.7159, -78.8295)),
        ("orchard park", (42.7676, -78.7439)),
        ("kenmore", (42.9659, -78.8700)),
    ),
    "Albany": (
        ("colonie", (42.7170, -73.7818)),
        ("guilderland", (42.7048, -73.9110)),
        ("latham", (42.7470, -73.7590)),
        ("schenectady", (42.8142, -73.9396)),
        ("clifton park", (42.8656, -73.7701)),
        ("troy", (42.7284, -73.6918)),
    ),
    "Philadelphia": (
        ("ardmore", (40.0068, -75.2855)),
        ("media", (39.9168, -75.3877)),
        ("norristown", (40.1215, -75.3399)),
        ("king of prussia", (40.0893, -75.3960)),
        ("levittown", (40.1551, -74.8288)),
        ("bensalem", (40.1046, -74.9513)),
    ),
    "Pittsburgh": (
        ("cranberry", (40.6849, -80.1062)),
        ("monroeville", (40.4212, -79.7881)),
        ("bethel park", (40.3276, -80.0395)),
        ("mt. lebanon", (40.3554, -80.0495)),
        ("mccandless", (40.5870, -80.0289)),
        ("robinson township", (40.4587, -80.1289)),
    ),
    "Orlando": (
        ("kissimmee", (28.2920, -81.4076)),
        ("winter park", (28.5997, -81.3392)),
        ("sanford", (28.8006, -81.2731)),
        ("apopka", (28.6934, -81.5322)),
        ("ocoee", (28.5692, -81.5440)),
        ("altamonte springs", (28.6611, -81.3656)),
        ("lake mary", (28.7589, -81.3178)),
    ),
    "Tampa": (
        ("st. petersburg", (27.7676, -82.6403)),
        ("clearwater", (27.9659, -82.8001)),
        ("brandon", (27.9378, -82.2859)),
        ("wesley chapel", (28.2397, -82.3279)),
        ("riverview", (27.8661, -82.3265)),
        ("largo", (27.9095, -82.7873)),
        ("palm harbor", (28.0781, -82.7637)),
    ),
    "Miami": (
        ("fort lauderdale", (26.1224, -80.1373)),
        ("hialeah", (25.8576, -80.2781)),
        ("pembroke pines", (26.0031, -80.2239)),
        ("hollywood", (26.0112, -80.1495)),
        ("coral springs", (26.2712, -80.2706)),
        ("miramar", (25.9861, -80.3036)),
        ("pompano beach", (26.2379, -80.1248)),
    ),
    "Ohio": (
        ("cleveland", (41.4993, -81.6944)),
        ("lakewood", (41.4810, -81.7980)),
        ("parma", (41.4048, -81.7229)),
        ("columbus", (39.9612, -82.9988)),
        ("dublin", (40.0992, -83.1141)),
        ("westerville", (40.1262, -82.9291)),
        ("cincinnati", (39.1031, -84.5120)),
        ("mason", (39.3601, -84.3099)),
        ("fairfield", (39.3459, -84.5603)),
        ("hamilton", (39.3995, -84.5613)),
    ),
}

# ZIP-prefix → discovery market when no centroid is in ZIP_CENTROIDS.
_ZIP_PREFIX_MARKETS: tuple[tuple[str, str], ...] = (
    ("146", "Rochester"),
    ("145", "Rochester"),
    ("132", "Syracuse"),
    ("130", "Syracuse"),
    ("131", "Syracuse"),
    ("142", "Buffalo"),
    ("140", "Buffalo"),
    ("141", "Buffalo"),
    ("122", "Albany"),
    ("123", "Albany"),
    ("120", "Albany"),
    ("121", "Albany"),
    ("191", "Philadelphia"),
    ("190", "Philadelphia"),
    ("152", "Pittsburgh"),
    ("151", "Pittsburgh"),
    ("150", "Pittsburgh"),
    ("328", "Orlando"),
    ("327", "Orlando"),
    ("347", "Orlando"),
    ("336", "Tampa"),
    ("337", "Tampa"),
    ("335", "Tampa"),
    ("346", "Tampa"),
    ("331", "Miami"),
    ("330", "Miami"),
    ("333", "Miami"),
    ("334", "Miami"),
    ("282", "Charlotte"),
    ("280", "Charlotte"),
    ("276", "Raleigh"),
    ("275", "Raleigh"),
    ("294", "Charleston"),
    ("441", "Ohio"),
    ("440", "Ohio"),
    ("432", "Ohio"),
    ("430", "Ohio"),
    ("452", "Ohio"),
    ("451", "Ohio"),
    ("752", "DFW"),
    ("761", "DFW"),
    ("750", "DFW"),
    ("787", "Austin"),
    ("786", "Austin"),
)

# High-volume ZIP centroids — instant lookup, no network calls.
ZIP_CENTROIDS: dict[str, tuple[float, float]] = {
    "14604": (43.1547, -77.6120),
    "14605": (43.1680, -77.5930),
    "14606": (43.1700, -77.6600),
    "14607": (43.1547, -77.5772),
    "14608": (43.1480, -77.5980),
    "14609": (43.1759, -77.5495),
    "14610": (43.1420, -77.5500),
    "14611": (43.1389, -77.6278),
    "14612": (43.2600, -77.6900),
    "14613": (43.1650, -77.6350),
    "14614": (43.1540, -77.6050),
    "14615": (43.2100, -77.6400),
    "14616": (43.2300, -77.6700),
    "14617": (43.2200, -77.5900),
    "14618": (43.1200, -77.5400),
    "14619": (43.1300, -77.6200),
    "14620": (43.1287, -77.6134),
    "14621": (43.1750, -77.6100),
    "14622": (43.1540, -77.6200),
    "14623": (43.0840, -77.6700),
    "14624": (43.1200, -77.7200),
    "14625": (43.1300, -77.5600),
    "14626": (43.2000, -77.7000),
    "13202": (43.0362, -76.1398),
    "13203": (43.0580, -76.1200),
    "13204": (43.0471, -76.1534),
    "13205": (43.0700, -76.1000),
    "13206": (43.0667, -76.1067),
    "13207": (43.0400, -76.1700),
    "13208": (43.0800, -76.1300),
    "13209": (43.0900, -76.1800),
    "13210": (43.0280, -76.1165),
    "13211": (43.1000, -76.1100),
    "13212": (43.1200, -76.1400),
    "13214": (43.0400, -76.0800),
    "13215": (43.0100, -76.1600),
    # Syracuse area suburbs
    "13039": (43.1890, -76.1190),
    "13041": (43.1850, -76.1720),
    "13088": (43.1060, -76.2090),
    "13090": (43.1650, -76.2200),
    # Buffalo
    "14221": (42.9860, -78.7270),
    "14226": (42.9610, -78.7820),
    "14228": (43.0180, -78.7520),
    "14217": (42.9630, -78.8640),
    "14043": (42.9860, -78.6970),
    # Albany
    "12203": (42.6520, -73.7860),
    "12208": (42.6540, -73.8060),
    "12211": (42.7070, -73.7620),
    "12303": (42.7980, -73.9390),
    "12110": (42.8140, -73.9390),
    # Philadelphia
    "19103": (39.9520, -75.1740),
    "19104": (39.9590, -75.1960),
    "19107": (39.9520, -75.1620),
    "19123": (39.9650, -75.1410),
    "19087": (40.0890, -75.3960),
    "19073": (39.9170, -75.3880),
    # Pittsburgh
    "15213": (40.4440, -79.9530),
    "15217": (40.4350, -79.9200),
    "15237": (40.5470, -80.0180),
    "15146": (40.4690, -79.7620),
    "16066": (40.6850, -80.1060),
    # Orlando
    "32801": (28.5380, -81.3790),
    "32803": (28.5560, -81.3510),
    "32825": (28.5230, -81.2470),
    "34741": (28.2920, -81.4080),
    # Tampa
    "33602": (27.9500, -82.4570),
    "33607": (27.9600, -82.5070),
    "33615": (28.0130, -82.5720),
    "33701": (27.7710, -82.6400),
    "33511": (27.9380, -82.2860),
    # Miami / South Florida
    "33101": (25.7750, -80.1930),
    "33125": (25.7750, -80.2370),
    "33139": (25.7820, -80.1340),
    "33301": (26.1220, -80.1370),
    "33024": (26.0180, -80.2690),
}

# Default underwriting assumptions when recomputing cash flow for ROI.
DEFAULT_DOWN_PAYMENT_PCT = 25.0
DEFAULT_INTEREST_RATE = 6.0
DEFAULT_LOAN_TERM = 30
DEFAULT_CLOSING_COSTS_PCT = 3.0

SORT_OPTIONS: dict[str, str] = {
    "Newest added": "added_at",
    "Highest One-Year ROI": "one_year_roi",
    "Highest Quantum Alignment": "quantum_success",
    "Highest Total Value": "price",
}

JITTER_SCALE_DEGREES = 0.025

# Labeled basemap — no API key required (unlike Mapbox dark-v9 in pydeck).
def _infer_market_city(address: str) -> str | None:
    """Return a discovery market key inferred from address text."""
    from engine import _match_market_from_text

    matched = _match_market_from_text(address)
    return matched or None


def _deterministic_jitter(address: str, scale: float = JITTER_SCALE_DEGREES) -> tuple[float, float]:
    """Stable lat/lon offsets so fallback markers do not stack on the city center."""
    digest = hashlib.md5(address.encode("utf-8")).hexdigest()
    seed = int(digest[:8], 16)
    lat_offset = ((seed % 1000) / 1000.0 - 0.5) * scale
    lon_offset = (((seed // 1000) % 1000) / 1000.0 - 0.5) * scale
    return lat_offset, lon_offset


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_zip_code(zip_code: Any, address: str | None = None) -> str:
    """Coerce zip_code from DB/DataFrame (float, NaN, int, str) to a 5-digit string."""
    if zip_code is not None:
        try:
            if pd.isna(zip_code):
                zip_code = None
        except (TypeError, ValueError):
            pass

    if zip_code not in (None, ""):
        text = str(zip_code).strip()
        if text:
            try:
                return f"{int(float(text)):05d}"
            except (TypeError, ValueError):
                if len(text) >= 5 and text[:5].isdigit():
                    return text[:5]

    if address:
        parsed = parse_zipcode_from_address(str(address).strip())
        if parsed:
            return parsed
    return ""


def _resolve_monthly_cash_flow(prop: dict[str, Any], price: float, rent: float) -> float:
    """Return stored monthly net cash flow or recompute with default loan assumptions."""
    if prop.get("monthly_net_cash_flow") is not None:
        return _safe_float(prop["monthly_net_cash_flow"])

    if price <= 0 or rent <= 0:
        return 0.0

    analysis = analyze_investment(
        price=price,
        down_payment_pct=DEFAULT_DOWN_PAYMENT_PCT,
        interest_rate=DEFAULT_INTEREST_RATE,
        loan_term=DEFAULT_LOAN_TERM,
        closing_costs_pct=DEFAULT_CLOSING_COSTS_PCT,
        tax_rate=_safe_float(prop.get("tax_rate")),
        monthly_insurance=_safe_float(prop.get("insurance")),
        monthly_hoa=_safe_float(prop.get("hoa")),
        maint_percent=get_ai_baseline_maint(prop),
        monthly_rent=rent,
        vacancy_reserve_pct=_safe_float(prop.get("ai_vacancy_rate"), 5.0),
        management_fee_pct=_safe_float(prop.get("ai_management_fee"), 10.0),
    )
    return analysis["monthly_net_cash_flow"]


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _resolve_one_year_roi(prop: dict[str, Any], price: float, rent: float) -> float:
    """
    One-year ROI: (projected 1yr value gain + annual cash flow) / (down payment + closing).
    """
    if price <= 0:
        return 0.0

    stored_roi = prop.get("one_year_roi")
    if stored_roi is not None and _safe_float(stored_roi) != 0.0:
        return _safe_float(stored_roi)

    predicted_value = _safe_float(prop.get("predicted_value"))
    forecast_rate = _safe_float(prop.get("forecast_rate"))
    if forecast_rate <= 0:
        location_score = _safe_float(prop.get("location_score"), 5.0)
        forecast_rate = calculate_10yr_appreciation(
            price,
            location_score,
            prop.get("market_city"),
        )["annual_rate"]

    monthly_cash_flow = _resolve_monthly_cash_flow(prop, price, rent)
    return calculate_one_year_roi(
        current_price=price,
        predicted_value=predicted_value,
        forecast_rate_pct=forecast_rate,
        monthly_net_cash_flow=monthly_cash_flow,
        down_payment_pct=DEFAULT_DOWN_PAYMENT_PCT,
        closing_costs_pct=DEFAULT_CLOSING_COSTS_PCT,
    )


def build_portfolio_dataframe(properties: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize raw KB rows into an analytics-ready DataFrame."""
    records: list[dict[str, Any]] = []
    for prop in properties:
        address = str(prop.get("address") or "").strip()
        if not address:
            continue

        price = _safe_float(prop.get("price"))
        rent = get_ai_baseline_rent(prop)
        monthly_cash_flow = _resolve_monthly_cash_flow(prop, price, rent)
        one_year_roi = _resolve_one_year_roi(prop, price, rent)
        quantum_success = _safe_float(prop.get("quantum_risk_score"))
        category = (
            prop.get("property_category")
            or prop.get("property_label")
            or "—"
        )
        market_city = prop.get("market_city") or _infer_market_city(address) or "—"
        zip_code = _normalize_zip_code(prop.get("zip_code"), address)
        state_code = prop.get("state_code") or parse_state_code_from_address(address) or "—"
        year_raw = prop.get("year_built")
        year_built = int(_safe_float(year_raw)) if year_raw not in (None, "", 0) else pd.NA
        location_score = _safe_float(prop.get("location_score"))

        stored_lat = prop.get("latitude")
        stored_lon = prop.get("longitude")
        if _has_stored_coordinates(stored_lat, stored_lon):
            lat_val = float(stored_lat)
            lon_val = float(stored_lon)
        else:
            lat_val = None
            lon_val = None

        added_at = parse_property_timestamp(prop.get("timestamp"))

        records.append(
            {
                "address": address,
                "address_key": normalize_address_key(address),
                "zip_code": zip_code,
                "category": str(category),
                "price": price,
                "rent": rent,
                "monthly_cash_flow": monthly_cash_flow,
                "primary_image_url": str(prop.get("primary_image_url") or "").strip(),
                "listing_status": str(prop.get("listing_status") or "").strip(),
                "days_on_market": _coerce_optional_int(prop.get("days_on_market")),
                "view_count": _coerce_optional_int(prop.get("view_count")),
                "one_year_roi": one_year_roi,
                "quantum_success": quantum_success,
                "market_city": str(market_city),
                "state_code": str(state_code),
                "year_built": year_built,
                "location_score": location_score,
                "lat": lat_val,
                "lon": lon_val,
                "added_at": added_at,
                "environmental_risk": prop.get("environmental_risk"),
                "geocode_confidence": prop.get("geocode_confidence"),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=[
                "address",
                "category",
                "price",
                "rent",
                "monthly_cash_flow",
                "one_year_roi",
                "quantum_success",
                "market_city",
                "state_code",
                "year_built",
                "location_score",
                "lat",
                "lon",
                "added_at",
                "color",
            ]
        )

    return pd.DataFrame(records)


def _market_key_from_city(market_city: str) -> str | None:
    """Normalize stored market_city values to MARKET_CITY_CENTERS keys."""
    from engine import DISCOVERY_MARKET_KEYS, _match_market_from_text

    if not market_city or market_city == "—":
        return None
    text = str(market_city).strip()
    if text in DISCOVERY_MARKET_KEYS:
        return text
    matched = _match_market_from_text(text)
    return matched or None


def _coords_from_market_center(address: str, market_key: str) -> tuple[float, float]:
    base_lat, base_lon = MARKET_CITY_CENTERS[market_key]
    lat_off, lon_off = _deterministic_jitter(address)
    return base_lat + lat_off, base_lon + lon_off


def _coords_for_market(address: str, market_key: str) -> tuple[float, float]:
    """Market-center fallback with suburb-level centers when the address matches."""
    suburb_centers = METRO_SUBURB_CENTERS.get(market_key)
    if suburb_centers:
        lowered = address.lower()
        for keyword, center in suburb_centers:
            if keyword in lowered:
                base_lat, base_lon = center
                lat_off, lon_off = _deterministic_jitter(address)
                return base_lat + lat_off, base_lon + lon_off
    return _coords_from_market_center(address, market_key)


def resolve_coordinates_local(
    address: Any,
    zip_code: Any,
    market_city: Any,
) -> tuple[float | None, float | None]:
    """
    Instant coordinate resolution — no network I/O.

    Priority: known ZIP centroid → ZIP prefix market → address/market text.
    """
    normalized = str(address or "").strip()
    if not normalized:
        return None, None

    zip_val = _normalize_zip_code(zip_code, normalized)
    market_city_text = str(market_city or "").strip()

    if zip_val in ZIP_CENTROIDS:
        base_lat, base_lon = ZIP_CENTROIDS[zip_val]
        lat_off, lon_off = _deterministic_jitter(normalized, scale=0.006)
        return base_lat + lat_off, base_lon + lon_off

    for prefix, market_key in _ZIP_PREFIX_MARKETS:
        if zip_val.startswith(prefix):
            return _coords_for_market(normalized, market_key)

    market_key = _market_key_from_city(market_city_text) or _infer_market_city(normalized)
    if market_key and market_key in MARKET_CITY_CENTERS:
        return _coords_for_market(normalized, market_key)

    return None, None


MAP_MARKER_CLUSTER_THRESHOLD = 75


def _has_stored_coordinates(lat: Any, lon: Any) -> bool:
    """True only for finite DB-grounded coordinates (pandas NaN counts as missing)."""
    if lat is None or lon is None:
        return False
    try:
        if pd.isna(lat) or pd.isna(lon):
            return False
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    # Gemini returns (0, 0) when geocoding fails — not a real parcel location.
    if lat_f == 0.0 and lon_f == 0.0:
        return False
    return (
        math.isfinite(lat_f)
        and math.isfinite(lon_f)
        and -90.0 <= lat_f <= 90.0
        and -180.0 <= lon_f <= 180.0
    )


def attach_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Prefer Maps-grounded lat/lon; fall back to ZIP centroids and market centers."""
    if df.empty:
        return df

    enriched = df.copy()
    latitudes: list[float | None] = []
    longitudes: list[float | None] = []
    for row in enriched.itertuples(index=False):
        stored_lat = getattr(row, "lat", None)
        stored_lon = getattr(row, "lon", None)
        if _has_stored_coordinates(stored_lat, stored_lon):
            latitudes.append(float(stored_lat))
            longitudes.append(float(stored_lon))
            continue
        lat, lon = resolve_coordinates_local(
            str(row.address),
            getattr(row, "zip_code", None),
            str(row.market_city),
        )
        latitudes.append(lat)
        longitudes.append(lon)
    enriched["lat"] = latitudes
    enriched["lon"] = longitudes
    return enriched


def _profitability_to_hex(
    value: float,
    min_val: float,
    max_val: float,
) -> str:
    """Map profitability to a green (high) → amber → red (low) hex color."""
    if max_val <= min_val:
        return "#78dc8c"

    ratio = (value - min_val) / (max_val - min_val)
    ratio = max(0.0, min(1.0, ratio))

    red = int(255 * (1.0 - ratio) + 40 * ratio)
    green = int(90 + 165 * ratio)
    blue = int(60 * (1.0 - ratio) + 100 * ratio)
    return f"#{red:02x}{green:02x}{blue:02x}"


def apply_map_colors(df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-row marker colors for folium rendering."""
    if df.empty:
        return df

    colored = df.copy()
    roi_values = colored["one_year_roi"].fillna(0.0)
    min_p = float(roi_values.min())
    max_p = float(roi_values.max())
    colored["marker_color"] = roi_values.apply(
        lambda v: _profitability_to_hex(float(v), min_p, max_p)
    )
    return colored


def _range_filter_active(
    selected: tuple[float, float],
    bounds: tuple[float, float],
) -> bool:
    """True when the user narrowed a range slider below the full data extent."""
    return selected[0] > bounds[0] or selected[1] < bounds[1]


def filter_portfolio_dataframe(
    df: pd.DataFrame,
    *,
    states: list[str] | None = None,
    cities: list[str] | None = None,
    price_range: tuple[float, float] | None = None,
    price_bounds: tuple[float, float] | None = None,
    year_range: tuple[int, int] | None = None,
    year_bounds: tuple[int, int] | None = None,
    cashflow_range: tuple[float, float] | None = None,
    cashflow_bounds: tuple[float, float] | None = None,
    roi_range: tuple[float, float] | None = None,
    roi_bounds: tuple[float, float] | None = None,
    location_range: tuple[float, float] | None = None,
    location_bounds: tuple[float, float] | None = None,
    risk_range: tuple[float, float] | None = None,
    risk_bounds: tuple[float, float] | None = None,
) -> pd.DataFrame:
    """Apply portfolio map filters; empty categorical selections mean no filter."""
    if df.empty:
        return df

    result = df.copy()
    if states:
        result = result[result["state_code"].isin(states)]
    if cities:
        result = result[result["market_city"].isin(cities)]

    if price_range and price_bounds and _range_filter_active(price_range, price_bounds):
        result = result[
            (result["price"] >= price_range[0]) & (result["price"] <= price_range[1])
        ]

    if year_range and year_bounds and _range_filter_active(
        (float(year_range[0]), float(year_range[1])),
        (float(year_bounds[0]), float(year_bounds[1])),
    ):
        year_mask = result["year_built"].isna() | (
            (result["year_built"] >= year_range[0])
            & (result["year_built"] <= year_range[1])
        )
        result = result[year_mask]

    if cashflow_range and cashflow_bounds and _range_filter_active(
        cashflow_range, cashflow_bounds
    ):
        result = result[
            (result["monthly_cash_flow"] >= cashflow_range[0])
            & (result["monthly_cash_flow"] <= cashflow_range[1])
        ]

    if roi_range and roi_bounds and _range_filter_active(roi_range, roi_bounds):
        result = result[
            (result["one_year_roi"] >= roi_range[0])
            & (result["one_year_roi"] <= roi_range[1])
        ]

    if location_range and location_bounds and _range_filter_active(
        location_range, location_bounds
    ):
        result = result[
            (result["location_score"] >= location_range[0])
            & (result["location_score"] <= location_range[1])
        ]

    if risk_range and risk_bounds and _range_filter_active(risk_range, risk_bounds):
        result = result[
            (result["quantum_success"] >= risk_range[0])
            & (result["quantum_success"] <= risk_range[1])
        ]

    return result


def sort_portfolio(df: pd.DataFrame, sort_key: str) -> pd.DataFrame:
    """Sort the portfolio frame according to the selected analytical vector."""
    if df.empty:
        return df

    if sort_key == "added_at":
        return df.sort_values("added_at", ascending=False, kind="mergesort", na_position="last")
    if sort_key == "quantum_success":
        # Highest quantum alignment first (descending score)
        return df.sort_values("quantum_success", ascending=False, kind="mergesort")
    if sort_key == "one_year_roi":
        return df.sort_values("one_year_roi", ascending=False, kind="mergesort")
    return df.sort_values("price", ascending=False, kind="mergesort")


def _dataframe_selected_rows(state: Any) -> list[int]:
    if state is None:
        return []

    if isinstance(state, dict):
        selection = state.get("selection") or {}
        rows = selection.get("rows") if isinstance(selection, dict) else []
    else:
        selection = getattr(state, "selection", None)
        if selection is None:
            return []
        rows = (
            selection.get("rows")
            if isinstance(selection, dict)
            else getattr(selection, "rows", None)
        )
    return list(rows or [])


