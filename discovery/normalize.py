"""Normalize scraper payloads into harvester/engine shapes."""

from __future__ import annotations

from typing import Any

from discovery.market_defaults import get_market_defaults
from discovery.models import ListingSeed, ScrapedListing


def enriched_to_discovery_listing(
    row_id: int,
    seed: ListingSeed,
    scraped: ScrapedListing,
) -> dict[str, Any]:
    """Map a dequeued enriched queue row to the harvester listing shape."""
    listing = seed_to_discovery_listing(seed)
    listing["_queue_id"] = row_id
    listing["listing_status"] = scraped.listing_status
    listing["primary_image_url"] = scraped.primary_image_url
    listing["image_urls"] = list(scraped.image_urls)
    listing["listing_description"] = scraped.listing_description
    listing["days_on_market"] = scraped.days_on_market
    listing["view_count"] = scraped.view_count
    listing["latitude"] = scraped.latitude
    listing["longitude"] = scraped.longitude
    listing["_scraped"] = scraped
    return listing


def seed_to_discovery_listing(seed: ListingSeed) -> dict[str, Any]:
    """Map a search seed to engine._normalize_discovery_item shape."""
    listing: dict[str, Any] = {
        "address": seed.address,
        "city": seed.city,
        "list_price": round(float(seed.list_price), 2),
        "listing_url": seed.listing_url,
        "source": seed.source,
        "external_id": seed.external_id,
        "discovery_model": "scraper",
    }
    if seed.thumbnail_url:
        listing["primary_image_url"] = seed.thumbnail_url
    return listing


def scraped_to_research_dict(
    scraped: ScrapedListing,
    *,
    market_city: str,
) -> dict[str, Any]:
    """Map enriched scraper output to engine._normalize_research_payload keys."""
    defaults = get_market_defaults(market_city)
    research: dict[str, Any] = {
        "address": scraped.address,
        "listing_status": scraped.listing_status,
        "price": round(float(scraped.list_price), 2),
        "taxes": round(float(scraped.taxes_annual), 2),
        "hoa": round(float(scraped.hoa_monthly), 2),
        "year_built": scraped.year_built,
        "square_footage": int(scraped.square_footage),
        "property_condition": scraped.property_condition or "Good",
        "property_type": scraped.property_type or "Unknown",
        "stated_gross_monthly_rent": round(float(scraped.stated_gross_monthly_rent), 2),
        "listing_rent_notes": scraped.listing_rent_notes,
        "listing_description": scraped.listing_description,
        "days_on_market": scraped.days_on_market,
        "view_count": scraped.view_count,
        "primary_image_url": scraped.primary_image_url,
        "image_urls": list(scraped.image_urls),
        "listing_url": scraped.listing_url,
        "latitude": scraped.latitude,
        "longitude": scraped.longitude,
        "discovery_model": "scraper",
        "vacancy_rate": defaults.vacancy_rate,
        "management_fee": defaults.management_fee,
        "insurance_monthly_default": defaults.insurance_monthly_default,
        "source": scraped.source,
        "external_id": scraped.external_id,
    }
    return research


def listing_dict_to_scraped(listing: dict[str, Any]) -> ScrapedListing | None:
    """Rehydrate ScrapedListing when harvester passes embedded scraper payload."""
    raw = listing.get("_scraped")
    if isinstance(raw, ScrapedListing):
        return raw
    if isinstance(raw, dict):
        return ScrapedListing.from_dict(raw)
    if listing.get("discovery_model") == "scraper" and listing.get("external_id"):
        return ScrapedListing.from_dict(
            {
                "address": listing.get("address", ""),
                "city": listing.get("city", ""),
                "list_price": listing.get("list_price", 0.0),
                "listing_url": listing.get("listing_url", ""),
                "source": listing.get("source", "redfin"),
                "external_id": listing.get("external_id", ""),
                "listing_status": listing.get("listing_status", "For Sale"),
                "days_on_market": listing.get("days_on_market"),
                "view_count": listing.get("view_count"),
                "listing_description": listing.get("listing_description", ""),
                "primary_image_url": listing.get("primary_image_url", ""),
                "image_urls": listing.get("image_urls", []),
                "taxes_annual": listing.get("taxes", 0.0),
                "hoa_monthly": listing.get("hoa", 0.0),
                "year_built": listing.get("year_built"),
                "square_footage": listing.get("square_footage", 0),
                "property_type": listing.get("property_type", "Unknown"),
                "latitude": listing.get("latitude"),
                "longitude": listing.get("longitude"),
                "stated_gross_monthly_rent": listing.get("stated_gross_monthly_rent", 0.0),
                "listing_rent_notes": listing.get("listing_rent_notes", ""),
                "property_condition": listing.get("property_condition", "Good"),
                "scraped_at": listing.get("scraped_at", ""),
            }
        )
    return None
