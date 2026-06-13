"""Pure parsers for Redfin listing detail JSON/HTML."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from discovery.models import ListingSeed, ScrapedListing
from discovery.parsers.redfin_gis import _absolute_redfin_url, _unwrap_number, _unwrap_text

_STATUS_MAP = {
    "active": "For Sale",
    "for sale": "For Sale",
    "pending": "Pending",
    "contingent": "Contingent",
    "sold": "Sold",
    "off market": "Off Market",
    "coming soon": "Coming Soon",
}

_RENT_MONTHLY_RE = re.compile(
    r"(?:rent(?:s|al)?|leased?)\s*(?:for|at)?\s*\$?\s*([\d,]+(?:\.\d{2})?)\s*(?:/|per\s*)?mo(?:nth)?",
    re.IGNORECASE,
)
_RENT_ANNUAL_RE = re.compile(
    r"(?:annual|yearly)\s+(?:rent|income|gross)\s*(?:of|is|:)?\s*\$?\s*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)
_GROSS_INCOME_RE = re.compile(
    r"gross\s+(?:monthly\s+)?(?:rent|income)\s*(?:of|is|:)?\s*\$?\s*([\d,]+(?:\.\d{2})?)",
    re.IGNORECASE,
)


def parse_redfin_detail_payload(
    payload: Any,
    *,
    seed: ListingSeed,
    html: str = "",
) -> ScrapedListing:
    """Parse Redfin detail JSON (initialInfo / aboveTheFold / belowTheFold) into ScrapedListing."""
    if isinstance(payload, dict) and payload:
        return _from_json_payload(payload, seed=seed)
    if html.strip():
        return _from_html(html, seed=seed)
    return _fallback_from_seed(seed)


def _from_json_payload(payload: dict[str, Any], *, seed: ListingSeed) -> ScrapedListing:
    payload_body = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    above = _first_dict(payload_body, "aboveTheFold", "aboveTheFoldData")
    below = _first_dict(payload_body, "belowTheFold", "belowTheFoldData")
    initial = _first_dict(payload_body, "initialInfo", "initialInfoData")

    address_info = _first_dict(initial, "addressSectionInfo", "addressInfo") or initial
    listing_info = _first_dict(above, "addressSectionInfo", "listingInfo") or above

    street = _unwrap_text(address_info.get("streetAddress")) or seed.address
    city = seed.city
    list_price = _unwrap_number(
        listing_info.get("price")
        or address_info.get("price")
        or initial.get("price")
        or seed.list_price
    )
    listing_url = _absolute_redfin_url(
        str(
            address_info.get("url")
            or listing_info.get("url")
            or seed.listing_url
            or ""
        ).strip()
    )

    status_raw = _unwrap_text(
        listing_info.get("status")
        or address_info.get("status")
        or listing_info.get("listingStatus")
    )
    listing_status = _normalize_status(status_raw)

    days_on_market = _coerce_int(
        listing_info.get("timeOnRedfin")
        or listing_info.get("daysOnMarket")
        or below.get("timeOnRedfin")
    )
    view_count = _coerce_int(
        listing_info.get("listingViewCount")
        or listing_info.get("viewCount")
        or below.get("listingViewCount")
    )

    description = _collect_description(below, listing_info, initial)
    image_urls = _collect_image_urls(above, below, initial, listing_info)
    primary_image = image_urls[0] if image_urls else seed.thumbnail_url

    taxes_annual = _unwrap_number(
        below.get("publicRecordsInfo", {}).get("taxInfo", {}).get("taxAmount")
        if isinstance(below.get("publicRecordsInfo"), dict)
        else below.get("taxAnnualAmount")
    )
    if taxes_annual <= 0:
        taxes_annual = _unwrap_number(listing_info.get("taxAnnualAmount"))

    hoa_monthly = _unwrap_number(listing_info.get("hoaDues") or listing_info.get("hoa"))
    year_built = _coerce_int(
        listing_info.get("yearBuilt")
        or below.get("yearBuilt")
        or initial.get("yearBuilt")
    )
    square_footage = _coerce_int(
        listing_info.get("sqFt")
        or listing_info.get("squareFeet")
        or below.get("sqFt")
    ) or 0
    property_type = (
        _unwrap_text(listing_info.get("propertyType"))
        or _unwrap_text(initial.get("propertyType"))
        or "Unknown"
    )

    lat, lon = _extract_coordinates(listing_info, address_info, initial)
    monthly_rent, rent_notes = extract_rent_from_description(description)

    return ScrapedListing(
        address=street if "," in street else seed.address,
        city=city,
        list_price=list_price,
        listing_url=listing_url or seed.listing_url,
        source=seed.source,
        external_id=seed.external_id,
        listing_status=listing_status,
        days_on_market=days_on_market,
        view_count=view_count,
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
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    description = ""
    for selector in (
        ".remarks .remarksText",
        "[data-rf-test-id='listing-remarks']",
        ".listingRemarks",
    ):
        node = tree.css_first(selector)
        if node is not None:
            description = node.text(separator=" ", strip=True)
            break

    image_urls: list[str] = []
    for node in tree.css("img"):
        src = str(node.attributes.get("src", "")).strip()
        if "ssl.cdn-redfin.com" in src or "redfin.com/photo" in src:
            image_urls.append(src)
    image_urls = list(dict.fromkeys(image_urls))

    status_node = tree.css_first("[data-rf-test-id='listing-status']")
    listing_status = _normalize_status(status_node.text(strip=True) if status_node else "")

    monthly_rent, rent_notes = extract_rent_from_description(description)
    return ScrapedListing(
        address=seed.address,
        city=seed.city,
        list_price=seed.list_price,
        listing_url=seed.listing_url,
        source=seed.source,
        external_id=seed.external_id,
        listing_status=listing_status or "For Sale",
        days_on_market=None,
        view_count=None,
        listing_description=description,
        primary_image_url=image_urls[0] if image_urls else seed.thumbnail_url,
        image_urls=tuple(image_urls),
        taxes_annual=0.0,
        hoa_monthly=0.0,
        year_built=None,
        square_footage=0,
        property_type="Unknown",
        latitude=None,
        longitude=None,
        stated_gross_monthly_rent=monthly_rent,
        listing_rent_notes=rent_notes,
        property_condition="Good",
        scraped_at=datetime.now(timezone.utc).isoformat(),
    )


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


def extract_rent_from_description(description: str) -> tuple[float, str]:
    """Heuristic rent extraction from agent remarks."""
    text = str(description or "").strip()
    if not text:
        return 0.0, ""

    for pattern in (_RENT_MONTHLY_RE, _GROSS_INCOME_RE):
        match = pattern.search(text)
        if match:
            amount = _parse_money(match.group(1))
            if amount > 0:
                return round(amount, 2), f"Monthly rent mentioned in listing: ${amount:,.0f}/mo"

    annual_match = _RENT_ANNUAL_RE.search(text)
    if annual_match:
        annual = _parse_money(annual_match.group(1))
        if annual > 0:
            monthly = round(annual / 12.0, 2)
            return monthly, f"Annual income mentioned in listing: ${annual:,.0f}/yr"

    return 0.0, ""


def _parse_money(raw: str) -> float:
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _normalize_status(raw: str) -> str:
    cleaned = str(raw or "").strip()
    if not cleaned:
        return "For Sale"
    mapped = _STATUS_MAP.get(cleaned.lower())
    return mapped or cleaned


def _collect_description(*sections: dict[str, Any]) -> str:
    parts: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for key in (
            "marketingRemarks",
            "publicRemarks",
            "agentRemarks",
            "listingRemarks",
            "remarks",
        ):
            value = section.get(key)
            if isinstance(value, list):
                for item in value:
                    text = _unwrap_text(item)
                    if text:
                        parts.append(text)
            else:
                text = _unwrap_text(value)
                if text:
                    parts.append(text)
    return "\n\n".join(dict.fromkeys(parts))


def _collect_image_urls(*sections: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        media = section.get("mediaBrowserInfo") or section.get("photos")
        if isinstance(media, dict):
            photos = media.get("photos") or media.get("items")
            if isinstance(photos, list):
                for photo in photos:
                    if isinstance(photo, dict):
                        url = photo.get("photoUrl") or photo.get("url")
                        if isinstance(url, str) and url.startswith("http"):
                            urls.append(url)
        primary = section.get("primaryPhoto")
        if isinstance(primary, str) and primary.startswith("http"):
            urls.append(primary)
    return list(dict.fromkeys(url for url in urls if url))


def _extract_coordinates(*sections: dict[str, Any]) -> tuple[float | None, float | None]:
    for section in sections:
        if not isinstance(section, dict):
            continue
        lat_long = section.get("latLong") or section.get("coordinates")
        if isinstance(lat_long, dict):
            lat = lat_long.get("latitude") or lat_long.get("lat")
            lon = lat_long.get("longitude") or lat_long.get("lng") or lat_long.get("lon")
            if lat is not None and lon is not None:
                return float(lat), float(lon)
        lat = section.get("latitude") or section.get("lat")
        lon = section.get("longitude") or section.get("lng") or section.get("lon")
        if lat is not None and lon is not None:
            return float(lat), float(lon)
    return None, None


def _first_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("value")
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
