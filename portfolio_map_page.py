"""Global portfolio map — macro-market geospatial view of the shared knowledge base."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from authenticate import render_auth_sidebar
from share_access import is_guest_viewer, render_guest_sidebar
from finance import analyze_investment, calculate_10yr_appreciation, calculate_one_year_roi
from knowledge_base import (
    _fetch_canonical_properties,
    _normalize_record_numerics,
    get_ai_baseline_maint,
    get_ai_baseline_rent,
    normalize_address_key,
    parse_zipcode_from_address,
)
from market_pulse import render_market_pulse
from app_nav import navigate_to_individual_search
from ui_theme import render_page_hero

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
    # Syracuse area suburbs
    "13039": (43.1890, -76.1190),
    "13041": (43.1850, -76.1720),
    "13088": (43.1060, -76.2090),
    "13090": (43.1650, -76.2200),
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


def invalidate_portfolio_cache() -> None:
    """Clear portfolio map caches without st.cache_data.clear() (avoids stale module KeyErrors)."""
    for cached in (load_global_portfolio_properties, attach_coordinates):
        try:
            cached.clear()
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
    if zip_val.startswith(("132", "130")):
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

    if focus_row is None:
        bounds = [
            [float(mappable["lat"].min()), float(mappable["lon"].min())],
            [float(mappable["lat"].max()), float(mappable["lon"].max())],
        ]
        fmap.fit_bounds(bounds, padding=(60, 60))

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
        popup = (
            f"<div style='min-width:220px'>"
            f"<b>{row.address}</b><br/>"
            f"{row.category}<br/>"
            f"Price: ${row.price:,.0f}<br/>"
            f"Rent: ${row.rent:,.0f}/mo<br/>"
            f"Cash Flow: ${row.monthly_cash_flow:,.0f}/mo<br/>"
            f"1-Yr ROI: {row.one_year_roi:.2f}%<br/>"
            f"Quantum Alignment Score: {row.quantum_success:.1f}%"
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
        ).add_to(fmap)

    return fmap


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
) -> str | None:
    """
    Labeled folium map with hover tooltips and click-to-select.

    Returns the selected address when the user clicks a marker.
    """
    mappable = df.dropna(subset=["lat", "lon"])
    if mappable.empty:
        st.info("No geocoded properties to display on the map yet.")
        return None

    fmap = _build_folium_map(df, focus_address=focus_address)
    map_state = st_folium(
        fmap,
        width=None,
        height=520,
        returned_objects=["last_object_clicked"],
        use_container_width=True,
        key="portfolio_map",
    )
    return _match_click_to_address(map_state.get("last_object_clicked"), df)


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


def _sync_ledger_selection_to_map() -> None:
    """Focus the map when the user selects a property ledger row."""
    state = st.session_state.get("property_ledger")
    if state is None:
        return

    rows = getattr(getattr(state, "selection", None), "rows", None)
    if not rows:
        return

    addresses = st.session_state.get("_property_ledger_addresses") or []
    row_idx = rows[0]
    if 0 <= row_idx < len(addresses):
        st.session_state["map_selected_address"] = addresses[row_idx]


def _render_ledger_dblclick_helper(addresses: list[str]) -> None:
    """Double-click an address cell to select the ledger row and focus the map."""
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
                    "dblclick",
                    (event) => {{
                        const cell = event.target.closest(
                            '[class*="gdg-cell"], [role="gridcell"], td'
                        );
                        if (!cell) {{
                            return;
                        }}
                        const text = cell.textContent.trim();
                        if (!text) {{
                            return;
                        }}
                        const matched = ADDRESSES.find(
                            (address) => address === text || text.includes(address)
                        );
                        if (!matched) {{
                            return;
                        }}
                        selectRow(rowFromCell(cell));
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

    properties = load_global_portfolio_properties()
    portfolio_df = build_portfolio_dataframe(properties)

    if portfolio_df.empty:
        st.info("No properties in the knowledge base yet. Run the harvester to populate the map.")
        return

    with st.container(border=True):
        st.markdown("##### Filters & sorting")
        filter_col1, filter_col2 = st.columns([2, 1])

        price_values = portfolio_df["price"].dropna()
        price_min = int(price_values.min()) if not price_values.empty else 0
        price_max = int(price_values.max()) if not price_values.empty else 1_000_000
        if price_max <= price_min:
            price_max = price_min + 1

        with filter_col1:
            min_price = st.slider(
                "Minimum price",
                min_value=price_min,
                max_value=price_max,
                value=price_min,
                step=max(1_000, (price_max - price_min) // 100 or 1_000),
                format="$%d",
            )

        with filter_col2:
            sort_label = st.selectbox(
                "Sort by",
                options=list(SORT_OPTIONS.keys()),
                index=0,
            )
    sort_key = SORT_OPTIONS[sort_label]

    filtered_df = portfolio_df[portfolio_df["price"] >= min_price].copy()
    sorted_df = sort_portfolio(filtered_df, sort_key)

    geo_df = attach_coordinates(sorted_df)
    map_df = apply_map_colors(geo_df)

    st.markdown("##### Map")
    st.caption(
        "Hover for quick stats · click a marker to select · "
        "double-click an address in the ledger to focus the map · green = higher 1-yr ROI"
    )

    if "map_selected_address" not in st.session_state:
        st.session_state["map_selected_address"] = None

    selected_address = st.session_state.get("map_selected_address")
    clicked_address = render_portfolio_map(map_df, focus_address=selected_address)
    if clicked_address:
        st.session_state["map_selected_address"] = clicked_address

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
    avg_roi = map_df["one_year_roi"].mean() if not map_df.empty else 0.0
    top_market = compute_top_market(map_df)

    ledger_col1.metric("Properties shown", f"{len(map_df):,}")
    ledger_col2.metric("Avg 1-yr ROI", f"{avg_roi:.2f}%")
    ledger_col3.metric("Top market", top_market)

    st.markdown("##### Property ledger")
    st.caption("Double-click an address to focus it on the map above.")
    display_df = map_df[
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

    st.session_state["_property_ledger_addresses"] = map_df["address"].tolist()

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        key="property_ledger",
        on_select=_sync_ledger_selection_to_map,
        selection_mode="single-row",
        column_config={
            "Address": st.column_config.TextColumn(
                help="Double-click to show this property on the map.",
            ),
            "Price": st.column_config.NumberColumn(format="$%d"),
            "Monthly rent": st.column_config.NumberColumn(format="$%d"),
            "Cash flow": st.column_config.NumberColumn(format="$%d"),
            "1-yr ROI": st.column_config.NumberColumn(format="%.2f%%"),
            "Alignment Score": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    _render_ledger_dblclick_helper(st.session_state["_property_ledger_addresses"])

    geocoded_count = int(map_df["lat"].notna().sum())
    if geocoded_count < len(map_df):
        st.caption(f"{geocoded_count:,} of {len(map_df):,} properties placed on the map.")
