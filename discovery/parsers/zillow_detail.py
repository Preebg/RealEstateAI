"""Pure parsers for Zillow listing detail payloads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from discovery.models import ListingSeed, ScrapedListing
from discovery.parsers.html_utils import (
    coerce_float,
    coerce_int,
    extract_next_data_json,
    normalize_listing_status,
)
from discovery.parsers.redfin_detail import extract_rent_from_description
from discovery.parsers.zillow_search import _absolute_zillow_url


def parse_zillow_detail_payload(
    payload: Any,
    *,
    seed: ListingSeed,
    html: str = "",
) -> ScrapedListing:
    """Parse Zillow detail JSON or HTML into ScrapedListing."""
    if isinstance(payload, dict) and payload:
        scraped = _from_json_payload(payload, seed=seed)
        if scraped is not None:
            return scraped
    if html.strip():
        return _from_html(html, seed=seed)
    return _fallback_from_seed(seed)


def _from_json_payload(payload: dict[str, Any], *, seed: ListingSeed) -> ScrapedListing | None:
    property_data = _extract_property(payload)
    if property_data is None:
        return None

    description = str(
        property_data.get("description")
        or _dig(property_data, "resoFacts", "description")
        or ""
    ).strip()
    image_urls = _collect_image_urls(property_data)
    primary_image = image_urls[0] if image_urls else seed.thumbnail_url
    list_price = coerce_float(
        property_data.get("price")
        or property_data.get("unformattedPrice")
        or seed.list_price
    )
    taxes_annual = coerce_float(
        property_data.get("taxAnnualAmount")
        or _dig(property_data, "resoFacts", "taxAnnualAmount")
        or _dig(property_data, "taxHistory", 0, "taxPaid")
    )
    hoa_monthly = coerce_float(
        property_data.get("monthlyHoaFee")
        or _dig(property_data, "resoFacts", "hoaFee")
    )
    year_built = coerce_int(
        property_data.get("yearBuilt")
        or _dig(property_data, "resoFacts", "yearBuilt")
    )
    square_footage = coerce_int(
        property_data.get("livingArea")
        or property_data.get("livingAreaValue")
        or _dig(property_data, "resoFacts", "livingArea")
    ) or 0
    property_type = str(
        property_data.get("homeType")
        or _dig(property_data, "resoFacts", "homeType")
        or "Unknown"
    ).strip() or "Unknown"
    lat, lon = _extract_coordinates(property_data)
    monthly_rent, rent_notes = extract_rent_from_description(description)
    listing_url = _absolute_zillow_url(
        str(property_data.get("url") or property_data.get("detailUrl") or seed.listing_url)
    )

    return ScrapedListing(
        address=str(property_data.get("streetAddress") or seed.address).strip(),
        city=seed.city,
        list_price=list_price or seed.list_price,
        listing_url=listing_url or seed.listing_url,
        source=seed.source,
        external_id=str(property_data.get("zpid") or seed.external_id).strip(),
        listing_status=normalize_listing_status(
            str(
                property_data.get("homeStatus")
                or property_data.get("statusText")
                or property_data.get("listingStatus")
                or ""
            )
        ),
        days_on_market=coerce_int(
            property_data.get("daysOnZillow")
            or property_data.get("timeOnZillow")
        ),
        view_count=coerce_int(property_data.get("pageViewCount")),
        listing_description=description,
        primary_image_url=primary_image,
        image_urls=tuple(image_urls),
        taxes_annual=round(taxes_annual, 2),
        hoa_monthly=round(hoa_monthly, 2),
        year_built=year_built,
        square_footage=square_footage,
        property_type=property_type,
        latitude=lat,
        longitude=lon,
        stated_gross_monthly_rent=monthly_rent,
        listing_rent_notes=rent_notes,
        property_condition="Good",
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )


def _from_html(html: str, *, seed: ListingSeed) -> ScrapedListing:
    next_data = extract_next_data_json(html)
    if isinstance(next_data, dict):
        scraped = _from_json_payload(next_data, seed=seed)
        if scraped is not None:
            return scraped
    return _fallback_from_seed(seed)


def _extract_property(payload: dict[str, Any]) -> dict[str, Any] | None:
    props = payload.get("props")
    if isinstance(props, dict):
        page_props = props.get("pageProps")
        if isinstance(page_props, dict):
            component_props = page_props.get("componentProps")
            if isinstance(component_props, dict):
                gdp_cache = component_props.get("gdpClientCache")
                if isinstance(gdp_cache, str):
                    import json

                    try:
                        cache = json.loads(gdp_cache)
                    except json.JSONDecodeError:
                        cache = None
                    if isinstance(cache, dict):
                        for value in cache.values():
                            if isinstance(value, dict):
                                property_data = value.get("property")
                                if isinstance(property_data, dict):
                                    return property_data
            for key in ("property", "initialData", "gdpClientCache"):
                value = page_props.get(key)
                if isinstance(value, dict) and (
                    value.get("zpid") or value.get("price") or value.get("streetAddress")
                ):
                    return value

    if payload.get("zpid") or payload.get("streetAddress"):
        return payload
    return None


def _collect_image_urls(property_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    photos = property_data.get("photos")
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, dict):
                href = photo.get("url") or photo.get("mixedSources", {}).get("jpeg", [{}])[0].get("url")
                if isinstance(href, str) and href.startswith("http"):
                    urls.append(href)
    responsive = property_data.get("responsivePhotos")
    if isinstance(responsive, list):
        for photo in responsive:
            if isinstance(photo, dict):
                href = photo.get("url")
                if isinstance(href, str) and href.startswith("http"):
                    urls.append(href)
    return list(dict.fromkeys(urls))


def _extract_coordinates(property_data: dict[str, Any]) -> tuple[float | None, float | None]:
    lat_long = property_data.get("latLong") or property_data.get("geo")
    if isinstance(lat_long, dict):
        lat = lat_long.get("latitude") or lat_long.get("lat")
        lon = lat_long.get("longitude") or lat_long.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    lat = property_data.get("latitude")
    lon = property_data.get("longitude")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    return None, None


def _dig(payload: dict[str, Any], *keys: str | int) -> Any:
    current: Any = payload
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and isinstance(key, int) and 0 <= key < len(current):
            current = current[key]
        else:
            return None
    return current


def _fallback_from_seed(seed: ListingSeed) -> ScrapedListing:
    return ScrapedListing(
        address=seed.address,
        city=seed.city,
        list_price=seed.list_price,
        listing_url=seed.listing_url,
        source=seed.source,
        external_id=seed.external_id,
        listing_status="For Sale",
        days_on_market=None,
        view_count=None,
        listing_description="",
        primary_image_url=seed.thumbnail_url,
        image_urls=(seed.thumbnail_url,) if seed.thumbnail_url else (),
        taxes_annual=0.0,
        hoa_monthly=0.0,
        year_built=None,
        square_footage=0,
        property_type="Unknown",
        latitude=None,
        longitude=None,
        stated_gross_monthly_rent=0.0,
        listing_rent_notes="",
        property_condition="Good",
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )
