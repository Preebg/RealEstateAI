"""Global portfolio map — macro-market geospatial view of the shared knowledge base."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from authenticate import render_auth_sidebar
from finance import analyze_investment, calculate_10yr_appreciation, calculate_one_year_roi
from knowledge_base import (
    _fetch_canonical_properties,
    _normalize_record_numerics,
    get_ai_baseline_maint,
    get_ai_baseline_rent,
    normalize_address_key,
    parse_state_code_from_address,
    parse_zipcode_from_address,
)
from market_pulse import render_market_pulse
from app_nav import navigate_to_individual_search
from ui_theme import render_page_hero

# ---------------------------------------------------------------------------
# Market fallbacks — city centers with deterministic per-address jitter
# Keys match engine.DISCOVERY_MARKET_KEYS (Rochester, Charlotte, DFW, …).
# ---------------------------------------------------------------------------
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
    "Highest One-Year ROI": "one_year_roi",
    "Highest Quantum Alignment": "quantum_success",
    "Highest Total Value": "price",
}

JITTER_SCALE_DEGREES = 0.025

# Labeled basemap — no API key required (unlike Mapbox dark-v9 in pydeck).
FOLIUM_TILES = "CartoDB voyager"
NY_STATE_OVERVIEW = (42.75, -76.0, 7)
MAP_VIEW_WIDTH_PX = 960
MAP_VIEW_HEIGHT_PX = 520
VIEWPORT_FILTER_MIN_ZOOM = 9


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


@st.cache_data(ttl=300, show_spinner=False)
def load_global_portfolio_properties() -> list[dict[str, Any]]:
    """
    Load every canonical property row from the shared global KB.

    Uses the same Supabase ``properties`` table as ``get_kb_raw_data`` / harvester
    saves — one row per address across all users and harvest loops.
    """
    rows = _fetch_canonical_properties()
    return [_normalize_record_numerics(row) for row in rows if row.get("address")]


def invalidate_portfolio_cache() -> None:
    """Clear portfolio map caches without st.cache_data.clear() (avoids stale module KeyErrors)."""
    for cached in (
        load_global_portfolio_properties,
        load_geocoded_portfolio_dataframe,
    ):
        try:
            cached.clear()
        except Exception:
            pass
    try:
        from knowledge_base import invalidate_kb_cache

        invalidate_kb_cache()
    except Exception:
        pass


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


def _resolve_one_year_roi(prop: dict[str, Any], price: float, rent: float) -> float:
    """
    One-year ROI: (projected 1yr value gain + annual cash flow) / (down payment + closing).
    """
    if price <= 0:
        return 0.0

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
        lat_val = float(stored_lat) if stored_lat not in (None, "") else None
        lon_val = float(stored_lon) if stored_lon not in (None, "") else None

        records.append(
            {
                "address": address,
                "address_key": normalize_address_key(address),
                "zip_code": zip_code,
                "category": str(category),
                "price": price,
                "rent": rent,
                "monthly_cash_flow": monthly_cash_flow,
                "one_year_roi": one_year_roi,
                "quantum_success": quantum_success,
                "market_city": str(market_city),
                "state_code": str(state_code),
                "year_built": year_built,
                "location_score": location_score,
                "lat": lat_val,
                "lon": lon_val,
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
    return math.isfinite(lat_f) and math.isfinite(lon_f)


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


@st.cache_data(ttl=300, show_spinner=False)
def load_geocoded_portfolio_dataframe() -> pd.DataFrame:
    """Load, analyze, and geocode the full portfolio once per cache window."""
    properties = load_global_portfolio_properties()
    return attach_coordinates(build_portfolio_dataframe(properties))


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


def _match_click_to_address(
    click: dict[str, Any] | None,
    df: pd.DataFrame,
) -> str | None:
    """Resolve a folium map click to the nearest portfolio address."""
    if not click or click.get("lat") is None or click.get("lng") is None:
        return None

    click_lat = float(click["lat"])
    click_lng = float(click["lng"])
    mappable = df.dropna(subset=["lat", "lon"])
    if mappable.empty:
        return None

    distances = (mappable["lat"] - click_lat) ** 2 + (mappable["lon"] - click_lng) ** 2
    nearest_idx = distances.idxmin()
    if float(distances.loc[nearest_idx]) > 0.0004:
        return None
    return str(mappable.loc[nearest_idx, "address"])


def _parse_map_bounds(bounds: Any) -> tuple[float, float, float, float] | None:
    """Return (south, west, north, east) from an st_folium bounds payload."""
    if not bounds:
        return None

    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        try:
            sw, ne = bounds
            if isinstance(sw, dict):
                south = float(sw["lat"])
                west = float(sw.get("lng", sw.get("lon")))
                north = float(ne["lat"])
                east = float(ne.get("lng", ne.get("lon")))
            else:
                south = float(sw[0])
                west = float(sw[1])
                north = float(ne[0])
                east = float(ne[1])
            return south, west, north, east
        except (KeyError, IndexError, TypeError, ValueError):
            pass

    if not isinstance(bounds, dict):
        return None

    sw = bounds.get("_southWest") or bounds.get("southWest")
    ne = bounds.get("_northEast") or bounds.get("northEast")
    if not sw or not ne:
        return None
    try:
        return (
            float(sw["lat"]),
            float(sw.get("lng", sw.get("lon"))),
            float(ne["lat"]),
            float(ne.get("lng", ne.get("lon"))),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _safe_map_zoom(zoom: Any) -> int | None:
    try:
        if zoom is None or isinstance(zoom, dict):
            return None
        return int(zoom)
    except (TypeError, ValueError):
        return None


def _parse_map_center(center: Any) -> tuple[float, float] | None:
    if not center or not isinstance(center, dict):
        return None
    try:
        lat = center.get("lat")
        lng = center.get("lng", center.get("lon"))
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def _approximate_viewport_bounds(
    center: Any,
    zoom: Any,
    *,
    width_px: int = MAP_VIEW_WIDTH_PX,
    height_px: int = MAP_VIEW_HEIGHT_PX,
) -> dict[str, dict[str, float]] | None:
    """Estimate visible bounds from map center and zoom (Leaflet tile math)."""
    parsed_center = _parse_map_center(center)
    parsed_zoom = _safe_map_zoom(zoom)
    if parsed_center is None or parsed_zoom is None:
        return None

    lat, lng = parsed_center
    world_px = 256 * (2**parsed_zoom)
    lon_span = 360.0 * width_px / world_px
    cos_lat = max(math.cos(math.radians(lat)), 0.05)
    lat_span = 360.0 * height_px / world_px / cos_lat

    return {
        "_southWest": {"lat": lat - lat_span / 2, "lng": lng - lon_span / 2},
        "_northEast": {"lat": lat + lat_span / 2, "lng": lng + lon_span / 2},
    }


def _should_filter_viewport(
    bounds: dict[str, Any] | None,
    center: Any,
    zoom: Any,
) -> bool:
    """Only filter the ledger once the user has zoomed into a metro-sized view."""
    parsed_zoom = _safe_map_zoom(zoom)
    if parsed_zoom is not None and parsed_zoom >= VIEWPORT_FILTER_MIN_ZOOM:
        return True

    parsed = _parse_map_bounds(bounds)
    if parsed is None:
        return False

    south, west, north, east = parsed
    return (north - south) < 5.0 and (east - west) < 7.0


def _effective_viewport_bounds(viewport: dict[str, Any]) -> dict[str, Any] | None:
    center = viewport.get("center")
    zoom = viewport.get("zoom")
    bounds = viewport.get("bounds")
    parsed_zoom = _safe_map_zoom(zoom)

    if parsed_zoom is not None and parsed_zoom >= VIEWPORT_FILTER_MIN_ZOOM:
        approx = _approximate_viewport_bounds(center, zoom)
        if approx:
            return approx

    parsed = _parse_map_bounds(bounds)
    if parsed is not None:
        south, west, north, east = parsed
        if (north - south) < 5.0 and (east - west) < 7.0:
            return bounds

    approx = _approximate_viewport_bounds(center, zoom)
    return approx or bounds


def filter_df_by_map_bounds(df: pd.DataFrame, bounds: dict[str, Any] | None) -> pd.DataFrame:
    """Keep geocoded rows whose coordinates fall inside the given bounds."""
    parsed = _parse_map_bounds(bounds)
    if parsed is None or df.empty:
        return df

    south, west, north, east = parsed
    has_coords = df["lat"].notna() & df["lon"].notna()
    in_view = has_coords & (
        (df["lat"] >= south)
        & (df["lat"] <= north)
        & (df["lon"] >= west)
        & (df["lon"] <= east)
    )
    return df[in_view].copy()


def filter_df_by_map_viewport(df: pd.DataFrame, viewport: dict[str, Any] | None) -> pd.DataFrame:
    """Filter the ledger to properties visible in the current map viewport."""
    if df.empty or not viewport:
        return df

    bounds = viewport.get("bounds")
    center = viewport.get("center")
    zoom = viewport.get("zoom")
    if not _should_filter_viewport(bounds, center, zoom):
        return df

    effective_bounds = _effective_viewport_bounds(viewport)
    return filter_df_by_map_bounds(df, effective_bounds)


def _update_map_viewport(map_state: dict[str, Any]) -> None:
    """Persist pan/zoom state so the map does not reset on Streamlit reruns."""
    center = map_state.get("center")
    zoom = map_state.get("zoom")
    bounds = map_state.get("bounds")
    if center is None and zoom is None and bounds is None:
        return

    viewport = dict(st.session_state.get("map_viewport") or {})
    if center:
        viewport["center"] = center
    parsed_zoom = _safe_map_zoom(zoom)
    if parsed_zoom is not None:
        viewport["zoom"] = parsed_zoom
    if bounds:
        viewport["bounds"] = bounds
    st.session_state["map_viewport"] = viewport


def _sync_map_viewport_from_widget() -> None:
    """Callback for st_folium pan/zoom — copy widget state into map_viewport."""
    widget_state = st.session_state.get("portfolio_map")
    if isinstance(widget_state, dict):
        _update_map_viewport(widget_state)


def _resolve_map_view(
    df: pd.DataFrame,
    focus_address: str | None,
) -> tuple[tuple[float, float] | None, int | None, bool]:
    """Return st_folium center, zoom, and whether to skip fit_bounds."""
    focus_row = _resolve_focus_row(df, focus_address)
    if focus_row is not None:
        return (float(focus_row["lat"]), float(focus_row["lon"])), 15, True

    stored = st.session_state.get("map_viewport") or {}
    center_payload = stored.get("center")
    if center_payload:
        try:
            center = (float(center_payload["lat"]), float(center_payload["lng"]))
            zoom = int(stored.get("zoom") or 8)
            return center, zoom, True
        except (KeyError, TypeError, ValueError):
            pass

    return None, None, False


def _resolve_focus_row(
    df: pd.DataFrame,
    focus_address: str | None,
) -> pd.Series | None:
    """Return the mappable row for focus_address, if it exists."""
    if not focus_address:
        return None

    matches = df[df["address"] == focus_address].dropna(subset=["lat", "lon"])
    if matches.empty:
        return None
    return matches.iloc[0]


def _build_folium_map(
    df: pd.DataFrame,
    focus_address: str | None = None,
    *,
    skip_fit_bounds: bool = False,
) -> folium.Map:
    """Interactive labeled map with profitability-colored property markers."""
    mappable = df.dropna(subset=["lat", "lon"])
    if mappable.empty:
        lat, lon, zoom = NY_STATE_OVERVIEW
        return folium.Map(location=[lat, lon], zoom_start=zoom, tiles=FOLIUM_TILES)

    focus_row = _resolve_focus_row(df, focus_address)
    if focus_row is not None:
        center_lat = float(focus_row["lat"])
        center_lon = float(focus_row["lon"])
        zoom_start = 15
    else:
        center_lat = float(mappable["lat"].mean())
        center_lon = float(mappable["lon"].mean())
        zoom_start = 8

    fmap = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles=FOLIUM_TILES,
        control_scale=True,
    )

    if focus_row is None and not skip_fit_bounds:
        bounds = [
            [float(mappable["lat"].min()), float(mappable["lon"].min())],
            [float(mappable["lat"].max()), float(mappable["lon"].max())],
        ]
        fmap.fit_bounds(bounds, padding=(60, 60))

    if len(mappable) >= MAP_MARKER_CLUSTER_THRESHOLD:
        from folium.plugins import MarkerCluster

        marker_parent = MarkerCluster(name="Properties").add_to(fmap)
    else:
        marker_parent = fmap

    for row in mappable.itertuples(index=False):
        is_focus = focus_address is not None and row.address == focus_address
        tooltip = (
            f"<b>{row.address}</b><br/>"
            f"Price: ${row.price:,.0f}<br/>"
            f"Rent: ${row.rent:,.0f}/mo<br/>"
            f"Cash Flow: ${row.monthly_cash_flow:,.0f}/mo<br/>"
            f"1-Yr ROI: {row.one_year_roi:.2f}%<br/>"
            f"Alignment: {row.quantum_success:.1f}%<br/>"
            f"<i>Click to select</i>"
        )
        env = getattr(row, "environmental_risk", None)
        env_line = ""
        if isinstance(env, dict) and env.get("level"):
            env_score = env.get("score")
            env_line = (
                f"Environmental risk: {env.get('level')}"
                f"{f' ({env_score:.1f}/10)' if env_score is not None else ''}<br/>"
            )
        popup = (
            f"<div style='min-width:220px'>"
            f"<b>{row.address}</b><br/>"
            f"{row.category}<br/>"
            f"Price: ${row.price:,.0f}<br/>"
            f"Rent: ${row.rent:,.0f}/mo<br/>"
            f"Cash Flow: ${row.monthly_cash_flow:,.0f}/mo<br/>"
            f"1-Yr ROI: {row.one_year_roi:.2f}%<br/>"
            f"Quantum Alignment Score: {row.quantum_success:.1f}%<br/>"
            f"{env_line}"
            f"</div>"
        )
        folium.CircleMarker(
            location=[float(row.lat), float(row.lon)],
            radius=10 if is_focus else 6,
            popup=folium.Popup(popup, max_width=320),
            tooltip=tooltip,
            color="#2563eb" if is_focus else "#1a1a2e",
            weight=2 if is_focus else 1,
            fill=True,
            fill_color=getattr(row, "marker_color", "#78dc8c"),
            fill_opacity=0.95 if is_focus else 0.88,
        ).add_to(marker_parent)

    return fmap


def _numeric_column_bounds(
    series: pd.Series,
    *,
    default_min: float = 0.0,
    default_max: float = 100.0,
    as_int: bool = False,
) -> tuple[float, float]:
    """Return slider bounds from a numeric column, with sane fallbacks."""
    values = series.dropna()
    if values.empty:
        lo, hi = default_min, default_max
    else:
        lo, hi = float(values.min()), float(values.max())
    if hi <= lo:
        hi = lo + 1
    if as_int:
        return int(lo), int(hi)
    return lo, hi


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


def build_portfolio_filter_signature(
    *,
    states: list[str],
    cities: list[str],
    price_range: tuple[float, float],
    year_range: tuple[int, int],
    cashflow_range: tuple[float, float],
    roi_range: tuple[float, float],
    location_range: tuple[float, float],
    risk_range: tuple[float, float],
    sort_key: str,
    result_count: int,
) -> str:
    """Stable signature for resetting map viewport when filters change."""
    return "|".join(
        [
            ",".join(sorted(states)),
            ",".join(sorted(cities)),
            f"{price_range[0]}-{price_range[1]}",
            f"{year_range[0]}-{year_range[1]}",
            f"{cashflow_range[0]}-{cashflow_range[1]}",
            f"{roi_range[0]}-{roi_range[1]}",
            f"{location_range[0]}-{location_range[1]}",
            f"{risk_range[0]}-{risk_range[1]}",
            sort_key,
            str(result_count),
        ]
    )


def sort_portfolio(df: pd.DataFrame, sort_key: str) -> pd.DataFrame:
    """Sort the portfolio frame according to the selected analytical vector."""
    if df.empty:
        return df

    if sort_key == "quantum_success":
        # Highest quantum alignment first (descending score)
        return df.sort_values("quantum_success", ascending=False, kind="mergesort")
    if sort_key == "one_year_roi":
        return df.sort_values("one_year_roi", ascending=False, kind="mergesort")
    return df.sort_values("price", ascending=False, kind="mergesort")


def render_portfolio_map(
    df: pd.DataFrame,
    focus_address: str | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    """
    Labeled folium map with hover tooltips and click-to-select.

    Returns (selected address, persisted viewport state) for ledger filtering.
    """
    mappable = df.dropna(subset=["lat", "lon"])
    if mappable.empty:
        st.info("No geocoded properties to display on the map yet.")
        return None, None

    map_center, map_zoom, skip_fit_bounds = _resolve_map_view(df, focus_address)
    fmap = _build_folium_map(
        df,
        focus_address=focus_address,
        skip_fit_bounds=skip_fit_bounds,
    )
    map_state = st_folium(
        fmap,
        width=None,
        height=MAP_VIEW_HEIGHT_PX,
        center=map_center,
        zoom=map_zoom,
        returned_objects=["last_object_clicked", "bounds", "center", "zoom"],
        use_container_width=True,
        key="portfolio_map",
        on_change=_sync_map_viewport_from_widget,
    )
    if isinstance(map_state, dict):
        _update_map_viewport(map_state)
    clicked = _match_click_to_address(
        (map_state or {}).get("last_object_clicked"),
        df,
    )
    return clicked, st.session_state.get("map_viewport")


def compute_top_market(df: pd.DataFrame) -> str:
    """Return the market city with the highest average one-year ROI."""
    if df.empty or "market_city" not in df.columns:
        return "—"

    market_stats = (
        df[df["market_city"] != "—"]
        .groupby("market_city")["one_year_roi"]
        .mean()
    )
    if market_stats.empty:
        return "—"
    return str(market_stats.idxmax())


def _dataframe_selected_rows(state: Any) -> list[int]:
    """Read selected row indices from a Streamlit dataframe widget state."""
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


def _focus_map_on_address(address: str, map_df: pd.DataFrame) -> None:
    """Center the folium map on a ledger-selected property."""
    cleaned = str(address or "").strip()
    if not cleaned:
        return

    st.session_state["map_selected_address"] = cleaned
    matches = map_df[map_df["address"] == cleaned].dropna(subset=["lat", "lon"])
    if matches.empty:
        return

    lat = float(matches.iloc[0]["lat"])
    lon = float(matches.iloc[0]["lon"])
    st.session_state["map_viewport"] = {
        "center": {"lat": lat, "lng": lon},
        "zoom": 15,
    }


def _apply_ledger_selection_to_map(
    ledger_state: Any,
    map_df: pd.DataFrame,
) -> None:
    """Focus the map when the user selects a property ledger row."""
    rows = _dataframe_selected_rows(ledger_state)
    if not rows:
        return

    addresses = st.session_state.get("_property_ledger_addresses") or []
    row_idx = rows[0]
    if 0 <= row_idx < len(addresses):
        _focus_map_on_address(addresses[row_idx], map_df)


def _render_ledger_click_helper(addresses: list[str]) -> None:
    """Click any ledger row to select it and focus the map."""
    if not addresses:
        return

    addresses_json = json.dumps(addresses)
    components.html(
        f"""
        <script>
        (function() {{
            const ADDRESSES = {addresses_json};
            const doc = window.parent.document;

            function findLedgerGrid() {{
                const headings = doc.querySelectorAll("h5, h6, p, span");
                for (const heading of headings) {{
                    if (heading.textContent.trim() !== "Property ledger") {{
                        continue;
                    }}
                    const block = heading.closest('[data-testid="stVerticalBlock"]');
                    if (!block) {{
                        continue;
                    }}
                    const grid = block.querySelector('[data-testid="stDataFrameGlideDataEditor"]');
                    if (grid) {{
                        return grid;
                    }}
                }}
                return null;
            }}

            function rowFromCell(cell) {{
                return (
                    cell.closest('[class*="gdg-row"]')
                    || cell.closest('[role="row"]')
                    || cell.closest("tr")
                );
            }}

            function selectRow(row) {{
                if (!row) {{
                    return;
                }}
                const checkbox = row.querySelector('input[type="checkbox"]');
                if (checkbox) {{
                    checkbox.click();
                }}
            }}

            function bindGrid(grid) {{
                if (!grid || grid.dataset.ledgerDblBound === "1") {{
                    return;
                }}
                grid.dataset.ledgerDblBound = "1";
                grid.addEventListener(
                    "click",
                    (event) => {{
                        const cell = event.target.closest(
                            '[class*="gdg-cell"], [role="gridcell"], td'
                        );
                        if (!cell) {{
                            return;
                        }}
                        const row = rowFromCell(cell);
                        if (!row) {{
                            return;
                        }}
                        const text = row.textContent.trim();
                        const matched = ADDRESSES.find((address) => text.includes(address));
                        if (matched) {{
                            selectRow(row);
                        }}
                    }},
                    true
                );
            }}

            function scan() {{
                bindGrid(findLedgerGrid());
            }}

            const observer = new MutationObserver(scan);
            observer.observe(doc.body, {{ childList: true, subtree: true }});
            scan();
        }})();
        </script>
        """,
        height=0,
    )


# ---------------------------------------------------------------------------
# Page render
# ---------------------------------------------------------------------------
def render_portfolio_map_page() -> None:
    """Portfolio map home view."""
    from share_access import is_guest_viewer, render_guest_sidebar

    render_page_hero(
        "🗺️ Portfolio Map",
        "Explore harvested properties by one-year ROI, cash flow, and quantum alignment score.",
    )

    with st.sidebar:
        if is_guest_viewer():
            render_guest_sidebar()
        else:
            render_auth_sidebar()
        st.divider()
        render_market_pulse()

    portfolio_df = load_geocoded_portfolio_dataframe()

    if portfolio_df.empty:
        st.info("No properties in the knowledge base yet. Run the harvester to populate the map.")
        return

    price_min, price_max = _numeric_column_bounds(
        portfolio_df["price"], default_min=0, default_max=1_000_000, as_int=True
    )
    year_min, year_max = _numeric_column_bounds(
        portfolio_df["year_built"], default_min=1900, default_max=2025, as_int=True
    )
    cashflow_min, cashflow_max = _numeric_column_bounds(
        portfolio_df["monthly_cash_flow"], default_min=-5_000, default_max=5_000, as_int=True
    )
    roi_min, roi_max = _numeric_column_bounds(
        portfolio_df["one_year_roi"], default_min=-50.0, default_max=100.0
    )
    location_min, location_max = _numeric_column_bounds(
        portfolio_df["location_score"], default_min=0.0, default_max=10.0
    )
    risk_min, risk_max = _numeric_column_bounds(
        portfolio_df["quantum_success"], default_min=0.0, default_max=100.0
    )

    state_options = sorted(
        portfolio_df.loc[portfolio_df["state_code"] != "—", "state_code"].dropna().unique()
    )
    city_options = sorted(
        portfolio_df.loc[portfolio_df["market_city"] != "—", "market_city"].dropna().unique()
    )

    with st.container(border=True):
        st.markdown("##### Filters & sorting")
        cat_col1, cat_col2, sort_col = st.columns([1, 1, 1])

        with cat_col1:
            selected_states = st.multiselect(
                "State",
                options=state_options,
                placeholder="All states",
            )
        with cat_col2:
            selected_cities = st.multiselect(
                "City",
                options=city_options,
                placeholder="All cities",
            )
        with sort_col:
            sort_label = st.selectbox(
                "Sort by",
                options=list(SORT_OPTIONS.keys()),
                index=0,
            )

        range_col1, range_col2, range_col3 = st.columns(3)
        with range_col1:
            price_range = st.slider(
                "Price range",
                min_value=price_min,
                max_value=price_max,
                value=(price_min, price_max),
                step=max(1_000, (price_max - price_min) // 100 or 1_000),
                format="$%d",
            )
        with range_col2:
            year_range = st.slider(
                "Year built",
                min_value=year_min,
                max_value=year_max,
                value=(year_min, year_max),
                step=1,
            )
        with range_col3:
            cashflow_range = st.slider(
                "Monthly cash flow",
                min_value=cashflow_min,
                max_value=cashflow_max,
                value=(cashflow_min, cashflow_max),
                step=max(50, (cashflow_max - cashflow_min) // 100 or 50),
                format="$%d",
            )

        range_col4, range_col5, range_col6 = st.columns(3)
        with range_col4:
            roi_range = st.slider(
                "1-yr ROI (%)",
                min_value=roi_min,
                max_value=roi_max,
                value=(roi_min, roi_max),
                step=max(0.1, round((roi_max - roi_min) / 100, 1) or 0.1),
            )
        with range_col5:
            location_range = st.slider(
                "Location score",
                min_value=location_min,
                max_value=location_max,
                value=(location_min, location_max),
                step=max(0.1, round((location_max - location_min) / 20, 1) or 0.1),
            )
        with range_col6:
            risk_range = st.slider(
                "Risk score (alignment %)",
                min_value=risk_min,
                max_value=risk_max,
                value=(risk_min, risk_max),
                step=max(0.1, round((risk_max - risk_min) / 20, 1) or 0.1),
            )

    sort_key = SORT_OPTIONS[sort_label]

    filtered_df = filter_portfolio_dataframe(
        portfolio_df,
        states=selected_states or None,
        cities=selected_cities or None,
        price_range=price_range,
        price_bounds=(price_min, price_max),
        year_range=year_range,
        year_bounds=(year_min, year_max),
        cashflow_range=cashflow_range,
        cashflow_bounds=(cashflow_min, cashflow_max),
        roi_range=roi_range,
        roi_bounds=(roi_min, roi_max),
        location_range=location_range,
        location_bounds=(location_min, location_max),
        risk_range=risk_range,
        risk_bounds=(risk_min, risk_max),
    )
    if filtered_df.empty:
        st.info("No properties match the current filters. Widen a range or clear state/city selections.")
        return

    sorted_df = sort_portfolio(filtered_df, sort_key)
    map_df = apply_map_colors(sorted_df)

    filter_sig = build_portfolio_filter_signature(
        states=selected_states,
        cities=selected_cities,
        price_range=price_range,
        year_range=year_range,
        cashflow_range=cashflow_range,
        roi_range=roi_range,
        location_range=location_range,
        risk_range=risk_range,
        sort_key=sort_key,
        result_count=len(map_df),
    )
    if st.session_state.get("_map_filter_sig") != filter_sig:
        st.session_state["_map_filter_sig"] = filter_sig
        st.session_state.pop("map_viewport", None)

    if len(filtered_df) < len(portfolio_df):
        st.caption(
            f"Showing **{len(filtered_df):,}** of **{len(portfolio_df):,}** properties "
            "matching the filters above."
        )

    st.markdown("##### Map")
    st.caption(
        "Hover for quick stats · click a marker to select · "
        "zoom or pan to filter the ledger below · "
        "click a ledger row to focus the map · green = higher 1-yr ROI"
    )

    if "map_selected_address" not in st.session_state:
        st.session_state["map_selected_address"] = None

    _apply_ledger_selection_to_map(st.session_state.get("property_ledger"), map_df)

    selected_address = st.session_state.get("map_selected_address")
    clicked_address, map_viewport = render_portfolio_map(map_df, focus_address=selected_address)
    if clicked_address:
        st.session_state["map_selected_address"] = clicked_address

    ledger_df = filter_df_by_map_viewport(map_df, map_viewport)
    viewport_filter_active = (
        map_viewport is not None
        and _should_filter_viewport(
            map_viewport.get("bounds"),
            map_viewport.get("center"),
            map_viewport.get("zoom"),
        )
    )

    selected_address = st.session_state.get("map_selected_address")
    if selected_address:
        selected_row = map_df[map_df["address"] == selected_address]
        if not selected_row.empty:
            row = selected_row.iloc[0]
            with st.container(border=True):
                st.markdown("##### Selected property")
                sel_col1, sel_col2, sel_col3, sel_col4, sel_col5 = st.columns(5)
                sel_col1.metric("List price", f"${row['price']:,.0f}")
                sel_col2.metric("Rent", f"${row['rent']:,.0f}/mo")
                sel_col3.metric("Cash flow", f"${row['monthly_cash_flow']:,.0f}/mo")
                sel_col4.metric("1-yr ROI", f"{row['one_year_roi']:.2f}%")
                sel_col5.metric("Alignment Score", f"{row['quantum_success']:.1f}%")
                st.caption(f"{row['address']} · {row['category']} · {row['market_city']}")

                open_col, clear_col = st.columns([2, 1])
                with open_col:
                    if st.button(
                        "Open in Individual Search →",
                        type="primary",
                        use_container_width=True,
                        key="map_open_search",
                    ):
                        navigate_to_individual_search(selected_address)
                with clear_col:
                    if st.button("Clear", use_container_width=True, key="map_clear_selection"):
                        st.session_state["map_selected_address"] = None
                        st.rerun()

    ledger_col1, ledger_col2, ledger_col3 = st.columns(3)
    avg_roi = ledger_df["one_year_roi"].mean() if not ledger_df.empty else 0.0
    top_market = compute_top_market(ledger_df)

    ledger_col1.metric("Properties in view", f"{len(ledger_df):,}")
    ledger_col2.metric("Avg 1-yr ROI", f"{avg_roi:.2f}%")
    ledger_col3.metric("Top market", top_market)

    st.markdown("##### Property ledger")
    if viewport_filter_active and len(ledger_df) < len(map_df):
        st.caption(
            f"Showing {len(ledger_df):,} of {len(map_df):,} properties in the current map view. "
            "Zoom out to see more."
        )
    elif viewport_filter_active:
        st.caption(
            f"Map view filter active — {len(ledger_df):,} properties in the current viewport."
        )
    else:
        st.caption(
            "Zoom in on a metro area to filter this ledger to properties on screen. "
            "Click a row to focus it on the map."
        )
    display_df = ledger_df[
        [
            "address",
            "category",
            "price",
            "rent",
            "monthly_cash_flow",
            "one_year_roi",
            "quantum_success",
        ]
    ].rename(
        columns={
            "address": "Address",
            "category": "Category",
            "price": "Price",
            "rent": "Monthly rent",
            "monthly_cash_flow": "Cash flow",
            "one_year_roi": "1-yr ROI",
            "quantum_success": "Alignment Score",
        }
    )

    st.session_state["_property_ledger_addresses"] = ledger_df["address"].tolist()

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        key="property_ledger",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Address": st.column_config.TextColumn(
                help="Click the row to show this property on the map.",
            ),
            "Price": st.column_config.NumberColumn(format="$%d"),
            "Monthly rent": st.column_config.NumberColumn(format="$%d"),
            "Cash flow": st.column_config.NumberColumn(format="$%d"),
            "1-yr ROI": st.column_config.NumberColumn(format="%.2f%%"),
            "Alignment Score": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    _render_ledger_click_helper(st.session_state["_property_ledger_addresses"])

    geocoded_count = int(map_df["lat"].notna().sum())
    if geocoded_count < len(map_df):
        st.caption(
            f"{geocoded_count:,} of {len(map_df):,} properties placed on the map "
            "(unmapped addresses are omitted when the ledger is filtered by map view)."
        )
