"""Zillow listing source — async search + detail fetch."""

from __future__ import annotations

from discovery.market_defaults import get_market_location
from discovery.models import ListingSeed, ScrapedListing
from discovery.parsers.zillow_detail import parse_zillow_detail_payload
from discovery.parsers.zillow_search import ZILLOW_BASE_URL, parse_zillow_search_payload
from discovery.sources.base import AbstractListingSource
from discovery.transport.http_client import ScraperHttpClient

ZILLOW_SEARCH_URL = f"{ZILLOW_BASE_URL}/async-create-search-page-state"


class ZillowListingSource(AbstractListingSource):
    """Zillow async search API + HTML detail."""

    source_name = "zillow"

    def __init__(self, http_client: ScraperHttpClient) -> None:
        self._http = http_client

    async def search_market(
        self,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[ListingSeed]:
        location = get_market_location(market_city)
        if location is None:
            return []

        body = {
            "searchQueryState": {
                "pagination": {},
                "usersSearchTerm": location.search_label,
                "mapBounds": location.zillow_bbox,
                "filterState": {
                    "isForSaleByAgent": {"value": True},
                    "isForSaleByOwner": {"value": True},
                    "isNewConstruction": {"value": True},
                    "isComingSoon": {"value": True},
                    "isAuction": {"value": True},
                    "isForSaleForeclosure": {"value": True},
                    "price": {"max": int(max_price)},
                },
                "isListVisible": True,
            },
            "wants": {"cat1": ["listResults", "mapResults"]},
            "requestId": 2,
        }
        payload = await self._http.post_json(
            ZILLOW_SEARCH_URL,
            body,
            headers={"Referer": f"{ZILLOW_BASE_URL}/"},
        )
        return parse_zillow_search_payload(
            payload,
            market_city=market_city,
            max_price=max_price,
        )[:limit]

    async def fetch_detail(self, seed: ListingSeed) -> ScrapedListing:
        if seed.listing_url:
            try:
                html = await self._http.get_text(seed.listing_url)
                return parse_zillow_detail_payload({}, seed=seed, html=html)
            except Exception:
                pass
        return parse_zillow_detail_payload({}, seed=seed)
