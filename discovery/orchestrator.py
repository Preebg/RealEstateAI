"""Coordinate market search + detail enrichment for the harvester."""

from __future__ import annotations

import asyncio
from typing import Any

from app_logging import configure_logging
from discovery.models import ListingSeed, ScrapedListing
from discovery.normalize import seed_to_discovery_listing
from discovery.repository import DEFAULT_DB_PATH, SqliteDiscoveryRepository
from discovery.sources.redfin import RedfinListingSource
from discovery.transport.http_client import ScraperHttpClient
from knowledge_base import get_harvest_complete_addresses, normalize_address_key

_log = configure_logging("discovery.orchestrator")

GLOBAL_CONCURRENCY = 4
PER_SOURCE_CONCURRENCY = 2


class DiscoveryOrchestrator:
    """Search HOT_MARKETS, queue seeds, and enrich pending detail rows."""

    def __init__(
        self,
        *,
        repository: SqliteDiscoveryRepository | None = None,
        http_client: ScraperHttpClient | None = None,
        sources: list[Any] | None = None,
    ) -> None:
        self._repo = repository or SqliteDiscoveryRepository()
        self._http = http_client or ScraperHttpClient()
        self._owns_http = http_client is None
        self._sources = sources or [RedfinListingSource(self._http)]
        self._global_sem = asyncio.Semaphore(GLOBAL_CONCURRENCY)
        self._source_sems = {
            source.source_name: asyncio.Semaphore(PER_SOURCE_CONCURRENCY)
            for source in self._sources
        }

    async def close(self) -> None:
        if self._owns_http:
            await self._http.close()

    async def run(
        self,
        *,
        exclude_keys: set[str] | None = None,
        max_price: float,
        per_market_limit: int,
        enrich: bool = True,
    ) -> list[dict[str, Any]]:
        """Search all configured markets and optionally enrich pending rows."""
        from engine import HOT_MARKETS, MAX_DISCOVERY_LISTINGS

        excluded = set(exclude_keys or set())
        listings: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self._search_one_market(
                        market_name,
                        max_price=max_price,
                        limit=per_market_limit,
                    )
                )
                for market_name, _, _ in HOT_MARKETS
            ]

        for task in tasks:
            for seed in task.result():
                key = normalize_address_key(seed.address)
                if key in excluded or key in seen_keys:
                    continue
                seen_keys.add(key)
                row_id = self._repo.upsert_seed(seed)
                listing = seed_to_discovery_listing(seed)
                listing["_queue_id"] = row_id
                listings.append(listing)
                if len(listings) >= MAX_DISCOVERY_LISTINGS:
                    break
            if len(listings) >= MAX_DISCOVERY_LISTINGS:
                break

        if enrich and listings:
            await self._enrich_listings(listings)

        for listing in listings:
            listing.pop("_queue_id", None)
        return listings[:MAX_DISCOVERY_LISTINGS]

    async def _search_one_market(
        self,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[ListingSeed]:
        async with self._global_sem:
            for source in self._sources:
                source_sem = self._source_sems[source.source_name]
                async with source_sem:
                    try:
                        seeds = await source.search_market(
                            market_city,
                            max_price=max_price,
                            limit=limit,
                        )
                        if seeds:
                            _log.info(
                                "discovery_market_search",
                                market_city=market_city,
                                source=source.source_name,
                                count=len(seeds),
                            )
                            return seeds
                    except Exception as exc:
                        _log.warning(
                            "discovery_market_search_failed",
                            market_city=market_city,
                            source=source.source_name,
                            error=str(exc),
                        )
        return []

    async def _enrich_listings(self, listings: list[dict[str, Any]]) -> None:
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(self._enrich_one_listing(listing))
                for listing in listings
            ]
        for task in tasks:
            enriched = task.result()
            if enriched is None:
                continue

    async def _enrich_one_listing(self, listing: dict[str, Any]) -> ScrapedListing | None:
        row_id = int(listing.get("_queue_id", 0) or 0)
        seed = ListingSeed(
            address=str(listing.get("address", "")),
            city=str(listing.get("city", "")),
            list_price=float(listing.get("list_price", 0.0) or 0.0),
            listing_url=str(listing.get("listing_url", "")),
            source=str(listing.get("source", "redfin")),
            external_id=str(listing.get("external_id", "")),
            thumbnail_url=str(listing.get("primary_image_url", "")),
        )
        source = self._resolve_source(seed.source)
        if source is None:
            return None

        async with self._global_sem:
            source_sem = self._source_sems[source.source_name]
            async with source_sem:
                try:
                    scraped = await source.fetch_detail(seed)
                except Exception as exc:
                    _log.warning(
                        "discovery_enrich_failed",
                        address=seed.address,
                        source=seed.source,
                        error=str(exc),
                    )
                    if row_id:
                        self._repo.mark_status(row_id, "failed")
                    return None

        if row_id:
            self._repo.mark_enriched(row_id, scraped)
        listing.update(seed_to_discovery_listing(seed))
        listing["listing_status"] = scraped.listing_status
        listing["primary_image_url"] = scraped.primary_image_url
        listing["image_urls"] = list(scraped.image_urls)
        listing["listing_description"] = scraped.listing_description
        listing["days_on_market"] = scraped.days_on_market
        listing["view_count"] = scraped.view_count
        listing["latitude"] = scraped.latitude
        listing["longitude"] = scraped.longitude
        listing["_scraped"] = scraped
        self._repo.mirror_property(
            normalize_address_key(scraped.address),
            scraped.to_dict(),
        )
        return scraped

    def _resolve_source(self, source_name: str) -> Any | None:
        for source in self._sources:
            if source.source_name == source_name:
                return source
        return None

    def get_scraped_for_listing(self, listing: dict[str, Any]) -> ScrapedListing | None:
        """Load enriched scraper payload for a discovery listing."""
        embedded = listing.get("_scraped")
        if isinstance(embedded, ScrapedListing):
            return embedded
        if isinstance(embedded, dict):
            return ScrapedListing.from_dict(embedded)

        source = str(listing.get("source", "")).strip()
        external_id = str(listing.get("external_id", "")).strip()
        if source and external_id:
            scraped = self._repo.get_enriched_by_external_id(source, external_id)
            if scraped is not None:
                return scraped
        return None


async def run_scraper_discovery_async(
    *,
    admin_user_id: str | None = None,
    exclude_addresses: list[str] | None = None,
    max_price: float | None = None,
    db_path: str | None = None,
    per_market_limit: int = 25,
) -> list[dict[str, Any]]:
    """Entry point used by harvester Stage 1 discovery."""
    from engine import MAX_DISCOVERY_PRICE

    exclude_keys: set[str] = set()
    if admin_user_id:
        exclude_keys.update(get_harvest_complete_addresses(admin_user_id))
    for address in exclude_addresses or []:
        if str(address).strip():
            exclude_keys.add(normalize_address_key(str(address)))

    repo = SqliteDiscoveryRepository(db_path or DEFAULT_DB_PATH)
    orchestrator = DiscoveryOrchestrator(repository=repo)
    try:
        return await orchestrator.run(
            exclude_keys=exclude_keys,
            max_price=max_price or MAX_DISCOVERY_PRICE,
            per_market_limit=per_market_limit,
            enrich=True,
        )
    finally:
        await orchestrator.close()
