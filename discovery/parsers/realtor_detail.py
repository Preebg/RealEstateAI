"""Pure parsers for Realtor.com listing detail payloads."""

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
from discovery.parsers.realtor_search import _absolute_realtor_url


def parse_realtor_detail_payload(
    payload: Any,
    *,
    seed: ListingSeed,
    html: str = "",
) -> ScrapedListing:
    """Parse Realtor detail JSON or HTML into ScrapedListing."""
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

    description = _collect_description(property_data)
    image_urls = _collect_image_urls(property_data)
    primary_image = image_urls[0] if image_urls else seed.thumbnail_url
    list_price = coerce_float(
        property_data.get("list_price")
        or property_data.get("price")
        or seed.list_price
    )
    taxes_annual = coerce_float(
        _dig(property_data, "tax_history", 0, "tax")
        or property_data.get("tax_amount")
        or property_data.get("tax_annual_amount")
    )
    hoa_monthly = coerce_float(
        property_data.get("hoa_fee")
        or _dig(property_data, "hoa", "fee")
    )
    year_built = coerce_int(property_data.get("year_built"))
    square_footage = coerce_int(
        property_data.get("sqft")
        or property_data.get("building_size")
        or property_data.get("description", {}).get("sqft")
        if isinstance(property_data.get("description"), dict)
        else property_data.get("sqft")
    ) or 0
    property_type = str(
        property_data.get("prop_type")
        or property_data.get("type")
        or "Unknown"
    ).strip() or "Unknown"
    lat, lon = _extract_coordinates(property_data)
    monthly_rent, rent_notes = extract_rent_from_description(description)
    listing_url = _absolute_realtor_url(
        str(property_data.get("permalink") or property_data.get("href") or seed.listing_url)
    )

    return ScrapedListing(
        address=str(
            _dig(property_data, "location", "address", "line")
            or seed.address
        ).strip(),
        city=seed.city,
        list_price=list_price or seed.list_price,
        listing_url=listing_url or seed.listing_url,
        source=seed.source,
        external_id=str(
            property_data.get("property_id")
            or property_data.get("listing_id")
            or seed.external_id
        ).strip(),
        listing_status=normalize_listing_status(
            str(property_data.get("status") or property_data.get("listing_status") or "")
        ),
        days_on_market=coerce_int(
            property_data.get("days_on_market")
            or _dig(property_data, "list_date", "days_on_market")
        ),
        view_count=coerce_int(
            property_data.get("view_count")
            or _dig(property_data, "popularity", "periods", 0, "views_total")
        ),
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
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("home", "property", "listing"):
            value = data.get(key)
            if isinstance(value, dict):
                return value

    props = payload.get("props")
    if isinstance(props, dict):
        page_props = props.get("pageProps")
        if isinstance(page_props, dict):
            for key in ("property", "listing", "initialReduxState"):
                value = page_props.get(key)
                if isinstance(value, dict):
                    if key == "initialReduxState":
                        property_info = value.get("propertyDetails", {}).get("propertyInfo")
                        if isinstance(property_info, dict):
                            return property_info
                    else:
                        return value

    if payload.get("property_id") or payload.get("listing_id"):
        return payload
    return None


def _collect_description(property_data: dict[str, Any]) -> str:
    description = property_data.get("description")
    if isinstance(description, dict):
        text = description.get("text") or description.get("value")
        if text:
            return str(text).strip()
    for key in ("remarks", "public_remarks", "listing_remarks"):
        value = property_data.get(key)
        if value:
            return str(value).strip()
    return ""


def _collect_image_urls(property_data: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    photos = property_data.get("photos")
    if isinstance(photos, list):
        for photo in photos:
            if isinstance(photo, dict):
                href = photo.get("href") or photo.get("url")
                if isinstance(href, str) and href.startswith("http"):
                    urls.append(href)
    primary = property_data.get("primary_photo")
    if isinstance(primary, dict):
        href = primary.get("href") or primary.get("url")
        if isinstance(href, str) and href.startswith("http"):
            urls.append(href)
    return list(dict.fromkeys(urls))


def _extract_coordinates(property_data: dict[str, Any]) -> tuple[float | None, float | None]:
    location = property_data.get("location")
    if isinstance(location, dict):
        address = location.get("address")
        if isinstance(address, dict):
            lat = address.get("coordinate", {}).get("lat") if isinstance(address.get("coordinate"), dict) else None
            lon = address.get("coordinate", {}).get("lon") if isinstance(address.get("coordinate"), dict) else None
            if lat is not None and lon is not None:
                return float(lat), float(lon)
        lat = location.get("latitude") or location.get("lat")
        lon = location.get("longitude") or location.get("lon")
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
