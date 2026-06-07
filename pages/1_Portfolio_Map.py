"""Global portfolio map — macro-market geospatial view of the shared knowledge base."""

from __future__ import annotations

import hashlib
import os
from typing import Any

import pandas as pd
import pydeck as pdk
import streamlit as st

from authenticate import render_auth_sidebar
from knowledge_base import (
    _fetch_canonical_properties,
    _normalize_record_numerics,
    get_ai_baseline_rent,
    parse_zipcode_from_address,
    render_auth_page,
)
from market_pulse import render_market_pulse

# ---------------------------------------------------------------------------
# Market fallbacks — city centers with deterministic per-address jitter
# ---------------------------------------------------------------------------
MARKET_CITY_CENTERS: dict[str, tuple[float, float]] = {
    "Rochester, NY": (43.1566, -77.6088),
    "Syracuse, NY": (43.0481, -76.1474),
}

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
}

SORT_OPTIONS: dict[str, str] = {
    "Highest Profitability (Cap Rate / Cash-on-Cash)": "profitability_index",
    "Lowest Quantum Risk": "quantum_success",
    "Highest Total Value": "price",
}

JITTER_SCALE_DEGREES = 0.025


def _configure_mapbox_token() -> None:
    """Apply Mapbox credentials when available (required for dark-v9 basemap)."""
    token = os.getenv("MAPBOX_API_KEY", "").strip()
    if not token and hasattr(st, "secrets") and "MAPBOX_API_KEY" in st.secrets:
        token = str(st.secrets["MAPBOX_API_KEY"]).strip()
    if token:
        pdk.settings.mapbox_api_key = token


def _infer_market_city(address: str) -> str | None:
    """Return a known market key when the address belongs to Rochester or Syracuse."""
    lowered = address.lower()
    if "rochester" in lowered:
        return "Rochester, NY"
    if "syracuse" in lowered:
        return "Syracuse, NY"
    return None


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


def _resolve_profitability(prop: dict[str, Any], price: float, rent: float) -> tuple[float, str]:
    """
    Return (profitability_index, source_label).

    Prefers stored cash-on-cash or cap rate; otherwise applies the 50% OpEx
    baseline cap-rate fallback: (annual_rent * 0.5) / price.
    """
    if prop.get("cash_on_cash") is not None:
        return _safe_float(prop["cash_on_cash"]), "cash_on_cash"

    if prop.get("cap_rate") is not None:
        return _safe_float(prop["cap_rate"]), "cap_rate"

    if price > 0 and rent > 0:
        annual_rent = rent * 12.0
        baseline = (annual_rent * 0.5) / price * 100.0
        return baseline, "baseline_cap_rate"

    return 0.0, "unavailable"


def build_portfolio_dataframe(properties: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize raw KB rows into an analytics-ready DataFrame."""
    records: list[dict[str, Any]] = []
    for prop in properties:
        address = str(prop.get("address") or "").strip()
        if not address:
            continue

        price = _safe_float(prop.get("price"))
        rent = get_ai_baseline_rent(prop)
        profitability, profit_source = _resolve_profitability(prop, price, rent)
        quantum_success = _safe_float(prop.get("quantum_risk_score"))
        category = (
            prop.get("property_category")
            or prop.get("property_label")
            or "—"
        )
        market_city = prop.get("market_city") or _infer_market_city(address) or "—"
        zip_code = _normalize_zip_code(prop.get("zip_code"), address)

        records.append(
            {
                "address": address,
                "zip_code": zip_code,
                "category": str(category),
                "price": price,
                "rent": rent,
                "profitability_index": profitability,
                "profitability_source": profit_source,
                "quantum_success": quantum_success,
                "market_city": str(market_city),
            }
        )

    if not records:
        return pd.DataFrame(
            columns=[
                "address",
                "category",
                "price",
                "rent",
                "profitability_index",
                "profitability_source",
                "quantum_success",
                "market_city",
                "lat",
                "lon",
                "color",
            ]
        )

    return pd.DataFrame(records)


def _market_key_from_city(market_city: str) -> str | None:
    """Normalize stored market_city values to MARKET_CITY_CENTERS keys."""
    if not market_city or market_city == "—":
        return None
    lowered = market_city.lower()
    if "rochester" in lowered:
        return "Rochester, NY"
    if "syracuse" in lowered:
        return "Syracuse, NY"
    return None


def _coords_from_market_center(address: str, market_key: str) -> tuple[float, float]:
    base_lat, base_lon = MARKET_CITY_CENTERS[market_key]
    lat_off, lon_off = _deterministic_jitter(address)
    return base_lat + lat_off, base_lon + lon_off


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

    if zip_val.startswith("146"):
        return _coords_from_market_center(normalized, "Rochester, NY")
    if zip_val.startswith("132"):
        return _coords_from_market_center(normalized, "Syracuse, NY")

    market_key = _market_key_from_city(market_city_text) or _infer_market_city(normalized)
    if market_key:
        return _coords_from_market_center(normalized, market_key)

    return None, None


@st.cache_data(ttl=300, show_spinner=False)
def attach_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Resolve lat/lon instantly from ZIP centroids and market fallbacks (no network)."""
    if df.empty:
        return df

    enriched = df.copy()

    def _resolve_row(row: pd.Series) -> pd.Series:
        lat, lon = resolve_coordinates_local(
            str(row["address"]),
            row.get("zip_code"),
            str(row["market_city"]),
        )
        return pd.Series({"lat": lat, "lon": lon})

    coords = enriched.apply(_resolve_row, axis=1)
    enriched["lat"] = coords["lat"]
    enriched["lon"] = coords["lon"]
    return enriched


def _profitability_to_color(
    value: float,
    min_val: float,
    max_val: float,
) -> list[int]:
    """Map profitability to a green (high) → amber → red (low) RGBA tuple."""
    if max_val <= min_val:
        return [120, 220, 140, 210]

    ratio = (value - min_val) / (max_val - min_val)
    ratio = max(0.0, min(1.0, ratio))

    # Low ratio → amber/red; high ratio → bright green glow
    red = int(255 * (1.0 - ratio) + 40 * ratio)
    green = int(90 + 165 * ratio)
    blue = int(60 * (1.0 - ratio) + 100 * ratio)
    alpha = 200
    return [red, green, blue, alpha]


def apply_map_colors(df: pd.DataFrame) -> pd.DataFrame:
    """Attach per-row RGBA color arrays for pydeck rendering."""
    if df.empty:
        return df

    colored = df.copy()
    profitability = colored["profitability_index"].fillna(0.0)
    min_p = float(profitability.min())
    max_p = float(profitability.max())
    colored["color"] = profitability.apply(
        lambda v: _profitability_to_color(float(v), min_p, max_p)
    )
    return colored


def sort_portfolio(df: pd.DataFrame, sort_key: str) -> pd.DataFrame:
    """Sort the portfolio frame according to the selected analytical vector."""
    if df.empty:
        return df

    if sort_key == "quantum_success":
        # Lowest quantum risk → highest success probability first
        return df.sort_values("quantum_success", ascending=False, kind="mergesort")
    if sort_key == "profitability_index":
        return df.sort_values("profitability_index", ascending=False, kind="mergesort")
    return df.sort_values("price", ascending=False, kind="mergesort")


def render_portfolio_map(df: pd.DataFrame) -> None:
    """Dark-themed pydeck map with profitability-colored 3D pillars."""
    mappable = df.dropna(subset=["lat", "lon"])
    if mappable.empty:
        st.info("No geocoded properties to display on the map yet.")
        return

    _configure_mapbox_token()

    center_lat = float(mappable["lat"].mean())
    center_lon = float(mappable["lon"].mean())

    tooltip = {
        "html": (
            "<b>{address}</b><br/>"
            "Price: ${price:,.0f}<br/>"
            "Rent: ${rent:,.0f}/mo<br/>"
            "Profitability: {profitability_index:.2f}%<br/>"
            "Quantum Success: {quantum_success:.1f}%"
        ),
        "style": {"backgroundColor": "#1a1a2e", "color": "#e8e8f0"},
    }

    max_price = max(float(mappable["price"].max()), 1.0)
    elevation_scale = 50.0 / max_price

    column_layer = pdk.Layer(
        "ColumnLayer",
        data=mappable,
        get_position="[lon, lat]",
        get_elevation="price",
        elevation_scale=elevation_scale,
        radius=250,
        get_fill_color="color",
        pickable=True,
        auto_highlight=True,
    )

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=mappable,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=180,
        radius_min_pixels=4,
        radius_max_pixels=14,
        pickable=True,
    )

    view_state = pdk.ViewState(
        latitude=center_lat,
        longitude=center_lon,
        zoom=9,
        pitch=45,
        bearing=0,
    )

    deck = pdk.Deck(
        map_style="mapbox://styles/mapbox/dark-v9",
        initial_view_state=view_state,
        layers=[column_layer, scatter_layer],
        tooltip=tooltip,
    )
    st.pydeck_chart(deck, use_container_width=True)


def compute_top_market(df: pd.DataFrame) -> str:
    """Return the market city with the highest average profitability index."""
    if df.empty or "market_city" not in df.columns:
        return "—"

    market_stats = (
        df[df["market_city"] != "—"]
        .groupby("market_city")["profitability_index"]
        .mean()
    )
    if market_stats.empty:
        return "—"
    return str(market_stats.idxmax())


# ---------------------------------------------------------------------------
# Page entry
# ---------------------------------------------------------------------------
if not render_auth_page():
    st.stop()

st.title("🗺️ Global Portfolio Map")
st.caption(
    "Macro-market view of every property in the shared knowledge base — "
    "sorted, filtered, and plotted by profitability and quantum success."
)

with st.sidebar:
    render_auth_sidebar()
    st.divider()
    render_market_pulse()

properties = load_global_portfolio_properties()
portfolio_df = build_portfolio_dataframe(properties)

if portfolio_df.empty:
    st.warning("No properties found in the global knowledge base yet.")
    st.stop()

# --- Filters & sorting ---
st.subheader("🔎 Portfolio Controls")
filter_col1, filter_col2 = st.columns([2, 1])

price_values = portfolio_df["price"].dropna()
price_min = int(price_values.min()) if not price_values.empty else 0
price_max = int(price_values.max()) if not price_values.empty else 1_000_000
if price_max <= price_min:
    price_max = price_min + 1

with filter_col1:
    min_price = st.slider(
        "Minimum Acquisition Price ($)",
        min_value=price_min,
        max_value=price_max,
        value=price_min,
        step=max(1_000, (price_max - price_min) // 100 or 1_000),
        format="$%d",
    )

with filter_col2:
    sort_label = st.selectbox(
        "Primary Sort Vector",
        options=list(SORT_OPTIONS.keys()),
        index=0,
    )
sort_key = SORT_OPTIONS[sort_label]

filtered_df = portfolio_df[portfolio_df["price"] >= min_price].copy()
sorted_df = sort_portfolio(filtered_df, sort_key)

geo_df = attach_coordinates(sorted_df)
map_df = apply_map_colors(geo_df)

# --- Map ---
st.subheader("🌐 Geospatial Portfolio View")
render_portfolio_map(map_df)

# --- Aggregates ---
st.subheader("📊 Market Ledger")
metric_col1, metric_col2, metric_col3 = st.columns(3)

avg_cap = map_df["profitability_index"].mean() if not map_df.empty else 0.0
top_market = compute_top_market(map_df)

metric_col1.metric("Total Assets Evaluated", f"{len(map_df):,}")
metric_col2.metric("Market-Wide Average Cap Rate", f"{avg_cap:.2f}%")
metric_col3.metric("Top Performing Market", top_market)

# --- Detail table ---
st.subheader("📋 Sorted Property Ledger")
display_df = map_df[
    [
        "address",
        "category",
        "price",
        "rent",
        "profitability_index",
        "quantum_success",
    ]
].rename(
    columns={
        "address": "Address",
        "category": "Category",
        "price": "Price",
        "rent": "Monthly Rent",
        "profitability_index": "Profitability Index",
        "quantum_success": "Quantum Success Metric",
    }
)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Price": st.column_config.NumberColumn(format="$%d"),
        "Monthly Rent": st.column_config.NumberColumn(format="$%d"),
        "Profitability Index": st.column_config.NumberColumn(format="%.2f%%"),
        "Quantum Success Metric": st.column_config.NumberColumn(format="%.1f%%"),
    },
)

geocoded_count = int(map_df["lat"].notna().sum())
if geocoded_count < len(map_df):
    st.caption(
        f"{geocoded_count:,} of {len(map_df):,} properties mapped. "
        "Unplaced addresses are outside Rochester/Syracuse ZIP markets."
    )
else:
    st.caption(
        "Coordinates resolved instantly from ZIP centroids and market fallbacks."
    )
