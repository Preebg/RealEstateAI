"""Abstract listing source base class."""

from __future__ import annotations

from abc import ABC, abstractmethod

from discovery.models import ListingSeed, ScrapedListing


class AbstractListingSource(ABC):
    """Strategy base for portal scrapers."""

    source_name: str

    @abstractmethod
    async def search_market(
        self,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[ListingSeed]:
        """Return search seeds for one HOT_MARKET key."""

    @abstractmethod
    async def fetch_detail(self, seed: ListingSeed) -> ScrapedListing:
        """Fetch and parse a single listing detail page."""
