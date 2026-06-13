"""Redfin listing source — GIS search + detail fetch."""

from __future__ import annotations

from urllib.parse import quote

from discovery.market_defaults import REDFIN_REGION_IDS
from discovery.models import ListingSeed, ScrapedListing
from discovery.parsers.redfin_detail import parse_redfin_detail_payload
from discovery.parsers.redfin_gis import REDFIN_BASE_URL, parse_redfin_gis_payload
from discovery.sources.base import AbstractListingSource
from discovery.transport.http_client import ScraperHttpClient

GIS_URL = f"{REDFIN_BASE_URL}/stingray/api/gis"


class RedfinListingSource(AbstractListingSource):
    """Redfin Stingray GIS + detail endpoints."""

    source_name = "redfin"

    def __init__(self, http_client: ScraperHttpClient) -> None:
        self._http = http_client

    async def search_market(
        self,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[ListingSeed]:
        region_id = REDFIN_REGION_IDS.get(market_city)
        if region_id is None:
            return []

        params = (
            f"region_id={region_id}"
            f"&region_type=6"
            f"&status=1"
            f"&num_homes={min(max(limit, 1), 350)}"
            f"&max_price={int(max_price)}"
            f"&v=8"
        )
        payload = await self._http.get_json(f"{GIS_URL}?{params}")
        return parse_redfin_gis_payload(
            payload,
            market_city=market_city,
            max_price=max_price,
        )[:limit]

    async def fetch_detail(self, seed: ListingSeed) -> ScrapedListing:
        path = _listing_path(seed.listing_url)
        if path:
            detail_url = (
                f"{REDFIN_BASE_URL}/stingray/api/home/details/initialInfo"
                f"?path={quote(path, safe='')}"
            )
            try:
                payload = await self._http.get_json(detail_url)
                return parse_redfin_detail_payload(payload, seed=seed)
            except Exception:
                pass

        if seed.listing_url:
            try:
                html = await self._http.get_text(seed.listing_url)
                return parse_redfin_detail_payload({}, seed=seed, html=html)
            except Exception:
                pass

        return parse_redfin_detail_payload({}, seed=seed)


def _listing_path(listing_url: str) -> str:
    url = str(listing_url or "").strip()
    if not url:
        return ""
    if url.startswith(REDFIN_BASE_URL):
        return url[len(REDFIN_BASE_URL) :]
    if url.startswith("/"):
        return url
    return ""
