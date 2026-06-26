"""Realtor.com listing source — GraphQL search + detail fetch."""

from __future__ import annotations

from discovery.market_defaults import get_market_location
from discovery.models import ListingSeed, ScrapedListing
from discovery.parsers.realtor_detail import parse_realtor_detail_payload
from discovery.parsers.realtor_search import REALTOR_BASE_URL, parse_realtor_search_payload
from discovery.sources.base import AbstractListingSource
from discovery.transport.http_client import ScraperHttpClient

REALTOR_SEARCH_URL = f"{REALTOR_BASE_URL}/api/v1/hulk_main_srp"
REALTOR_SEARCH_PARAMS = {"client_id": "rdc-x", "schema": "vesta"}
REALTOR_HEADERS = {
    "rdc-client-name": "RDC_WEB_DETAILS_PAGE",
    "rdc-client-version": "3.0.0",
    "Origin": REALTOR_BASE_URL,
    "Referer": f"{REALTOR_BASE_URL}/",
}

_HOME_SEARCH_QUERY = """
query ConsumerSearchMainQuery(
  $query: HomeSearchCriteria!
  $limit: Int
  $offset: Int
  $sort_type: SearchSortType
) {
  home_search(
    query: $query
    limit: $limit
    offset: $offset
    sort_type: $sort_type
  ) {
    total
    results {
      property_id
      listing_id
      list_price
      status
      permalink
      primary_photo {
        href
      }
      location {
        address {
          line
          city
          state_code
          postal_code
        }
      }
    }
  }
}
""".strip()


class RealtorListingSource(AbstractListingSource):
    """Realtor.com GraphQL search + HTML/JSON detail."""

    source_name = "realtor"

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
            "query": _HOME_SEARCH_QUERY,
            "variables": {
                "query": {
                    "status": ["for_sale"],
                    "primary": True,
                    "search_location": {"location": location.search_label},
                    "list_price": {"max": int(max_price)},
                },
                "limit": min(max(limit, 1), 42),
                "offset": 0,
                "sort_type": "relevant",
            },
            "callfrom": "SRP",
            "nrQueryType": "MAIN_SRP",
            "isClient": True,
        }
        payload = await self._http.post_json(
            REALTOR_SEARCH_URL,
            body,
            headers=REALTOR_HEADERS,
            params=REALTOR_SEARCH_PARAMS,
        )
        return parse_realtor_search_payload(
            payload,
            market_city=market_city,
            max_price=max_price,
        )[:limit]

    async def fetch_detail(self, seed: ListingSeed) -> ScrapedListing:
        if seed.listing_url:
            try:
                html = await self._http.get_text(seed.listing_url)
                return parse_realtor_detail_payload({}, seed=seed, html=html)
            except Exception:
                pass
        return parse_realtor_detail_payload({}, seed=seed)
