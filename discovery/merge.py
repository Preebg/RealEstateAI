"""Cross-portal seed selection and scraped-field merging."""

from __future__ import annotations

from typing import TypeVar

from discovery.models import ListingSeed, ScrapedListing
from knowledge_base import normalize_address_key

SOURCE_PRIORITY: tuple[str, ...] = ("redfin", "realtor", "zillow")

_T = TypeVar("_T")


def source_rank(source: str) -> int:
    """Lower rank means higher priority when picking a primary portal."""
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def merge_seeds_by_address(
    seeds: list[ListingSeed],
) -> list[tuple[ListingSeed, list[ListingSeed]]]:
    """Group seeds by normalized address; pick primary by portal priority."""
    buckets: dict[str, list[ListingSeed]] = {}
    for seed in seeds:
        key = normalize_address_key(seed.address)
        if not key:
            continue
        buckets.setdefault(key, []).append(seed)

    merged: list[tuple[ListingSeed, list[ListingSeed]]] = []
    for group in buckets.values():
        ordered = sorted(group, key=lambda item: source_rank(item.source))
        primary = ordered[0]
        alternates = ordered[1:]
        merged.append((primary, alternates))
    return merged


def merge_scraped_listings(
    primary: ScrapedListing,
    *others: ScrapedListing,
) -> ScrapedListing:
    """Fill gaps in the primary scrape using supplemental portal payloads."""
    ordered = sorted(
        (primary, *others),
        key=lambda item: source_rank(item.source),
    )
    best = ordered[0]

    taxes = _first_positive(best.taxes_annual, *(item.taxes_annual for item in ordered))
    hoa = _first_positive(best.hoa_monthly, *(item.hoa_monthly for item in ordered))
    sqft = _first_positive(
        float(best.square_footage),
        *(float(item.square_footage) for item in ordered),
    )
    year_built = _first_optional(best.year_built, *(item.year_built for item in ordered))
    days_on_market = _first_optional(
        best.days_on_market,
        *(item.days_on_market for item in ordered),
    )
    view_count = _first_optional(best.view_count, *(item.view_count for item in ordered))
    latitude = _first_optional(best.latitude, *(item.latitude for item in ordered))
    longitude = _first_optional(best.longitude, *(item.longitude for item in ordered))
    monthly_rent = _first_positive(
        best.stated_gross_monthly_rent,
        *(item.stated_gross_monthly_rent for item in ordered),
    )
    description = _longest_text(*(item.listing_description for item in ordered))
    rent_notes = _longest_text(*(item.listing_rent_notes for item in ordered))
    property_type = _first_text(
        best.property_type,
        *(item.property_type for item in ordered),
        skip={"Unknown", ""},
    )
    listing_status = _first_text(
        best.listing_status,
        *(item.listing_status for item in ordered),
        skip={"", "Unknown"},
    )
    image_urls = _union_images(*(item.image_urls for item in ordered))
    primary_image = image_urls[0] if image_urls else best.primary_image_url

    return ScrapedListing(
        address=best.address,
        city=best.city,
        list_price=best.list_price,
        listing_url=best.listing_url,
        source=best.source,
        external_id=best.external_id,
        listing_status=listing_status or best.listing_status,
        days_on_market=days_on_market,
        view_count=view_count,
        listing_description=description,
        primary_image_url=primary_image,
        image_urls=image_urls,
        taxes_annual=round(taxes, 2),
        hoa_monthly=round(hoa, 2),
        year_built=year_built,
        square_footage=int(sqft),
        property_type=property_type or best.property_type,
        latitude=latitude,
        longitude=longitude,
        stated_gross_monthly_rent=round(monthly_rent, 2),
        listing_rent_notes=rent_notes,
        property_condition=best.property_condition or "Good",
        scraped_at=best.scraped_at,
    )


def _first_positive(primary: float, *values: float) -> float:
    if primary > 0:
        return primary
    for value in values:
        if value > 0:
            return value
    return primary


def _first_optional(primary: _T | None, *values: _T | None) -> _T | None:
    if primary is not None:
        return primary
    for value in values:
        if value is not None:
            return value
    return None


def _first_text(primary: str, *values: str, skip: set[str] | None = None) -> str:
    blocked = skip or set()
    if primary and primary not in blocked:
        return primary
    for value in values:
        if value and value not in blocked:
            return value
    return primary


def _longest_text(*values: str) -> str:
    return max((str(value or "").strip() for value in values), key=len, default="")


def _union_images(*groups: tuple[str, ...]) -> tuple[str, ...]:
    urls: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for url in group:
            cleaned = str(url or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                urls.append(cleaned)
    return tuple(urls)
