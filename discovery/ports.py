"""Protocols for discovery sources and persistence."""

from __future__ import annotations

from typing import Any, Protocol

from discovery.models import ListingSeed, ScrapedListing


class ListingSource(Protocol):
    """Strategy interface for a portal scraper."""

    source_name: str

    async def search_market(
        self,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[ListingSeed]:
        """Return search seeds for one HOT_MARKET key."""

    async def fetch_detail(self, seed: ListingSeed) -> ScrapedListing:
        """Fetch and parse a single listing detail page."""


class DiscoveryRepository(Protocol):
    """SQLite queue + property mirror."""

    def upsert_seed(self, seed: ListingSeed) -> int:
        """Insert or refresh a pending queue row; return row id."""

    def mark_enriched(self, row_id: int, scraped: ScrapedListing) -> None:
        """Persist enriched scraper payload."""

    def mark_status(self, row_id: int, status: str) -> None:
        """Update queue row status."""

    def get_pending_rows(self, *, limit: int) -> list[dict[str, Any]]:
        """Return pending queue rows oldest-first."""

    def get_enriched_by_external_id(
        self,
        source: str,
        external_id: str,
    ) -> ScrapedListing | None:
        """Load enriched scraper payload when present."""

    def mirror_property(self, address_key: str, payload: dict[str, Any]) -> None:
        """Upsert local property mirror row."""
