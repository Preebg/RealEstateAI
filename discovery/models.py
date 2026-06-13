"""Discovery dataclasses shared across scraper sources."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ListingSeed:
    """Minimal listing row from a portal search response."""

    address: str
    city: str
    list_price: float
    listing_url: str
    source: str
    external_id: str
    thumbnail_url: str = ""


@dataclass(frozen=True, slots=True)
class ScrapedListing:
    """Fully enriched listing from a portal detail response."""

    address: str
    city: str
    list_price: float
    listing_url: str
    source: str
    external_id: str
    listing_status: str
    days_on_market: int | None
    view_count: int | None
    listing_description: str
    primary_image_url: str
    image_urls: tuple[str, ...]
    taxes_annual: float
    hoa_monthly: float
    year_built: int | None
    square_footage: int
    property_type: str
    latitude: float | None
    longitude: float | None
    stated_gross_monthly_rent: float
    listing_rent_notes: str
    property_condition: str
    scraped_at: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["image_urls"] = list(self.image_urls)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ScrapedListing:
        image_urls = payload.get("image_urls") or ()
        if isinstance(image_urls, list):
            images = tuple(str(url) for url in image_urls if url)
        else:
            images = tuple(str(url) for url in image_urls if url)
        days_raw = payload.get("days_on_market")
        views_raw = payload.get("view_count")
        year_raw = payload.get("year_built")
        return cls(
            address=str(payload.get("address", "")).strip(),
            city=str(payload.get("city", "")).strip(),
            list_price=float(payload.get("list_price", 0.0) or 0.0),
            listing_url=str(payload.get("listing_url", "")).strip(),
            source=str(payload.get("source", "")).strip(),
            external_id=str(payload.get("external_id", "")).strip(),
            listing_status=str(payload.get("listing_status", "")).strip(),
            days_on_market=int(days_raw) if days_raw is not None else None,
            view_count=int(views_raw) if views_raw is not None else None,
            listing_description=str(payload.get("listing_description", "")).strip(),
            primary_image_url=str(payload.get("primary_image_url", "")).strip(),
            image_urls=images,
            taxes_annual=float(payload.get("taxes_annual", 0.0) or 0.0),
            hoa_monthly=float(payload.get("hoa_monthly", 0.0) or 0.0),
            year_built=int(year_raw) if year_raw is not None else None,
            square_footage=int(payload.get("square_footage", 0) or 0),
            property_type=str(payload.get("property_type", "Unknown")).strip() or "Unknown",
            latitude=(
                float(payload["latitude"])
                if payload.get("latitude") is not None
                else None
            ),
            longitude=(
                float(payload["longitude"])
                if payload.get("longitude") is not None
                else None
            ),
            stated_gross_monthly_rent=float(
                payload.get("stated_gross_monthly_rent", 0.0) or 0.0
            ),
            listing_rent_notes=str(payload.get("listing_rent_notes", "")).strip(),
            property_condition=str(payload.get("property_condition", "Good")).strip()
            or "Good",
            scraped_at=str(payload.get("scraped_at", "")).strip(),
        )
