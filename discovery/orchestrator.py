"""Coordinate market search + detail enrichment for the harvester."""

from __future__ import annotations

import asyncio
from typing import Any

from app_logging import configure_logging
from discovery.merge import merge_scraped_listings, merge_seeds_by_address
from discovery.models import ListingSeed, ScrapedListing
from discovery.normalize import enriched_to_discovery_listing, seed_to_discovery_listing
from discovery.repository import DEFAULT_DB_PATH, SqliteDiscoveryRepository, discovery_repository
from discovery.sources.registry import build_default_sources
from discovery.transport.http_client import ScraperHttpClient
from knowledge_base import get_harvest_complete_addresses, normalize_address_key

_log = configure_logging("discovery.orchestrator")

GLOBAL_CONCURRENCY = 4
PER_SOURCE_CONCURRENCY = 2


class DiscoveryOrchestrator:
    """Search HOT_MARKETS across portals, queue seeds, and enrich detail rows."""

    def __init__(
        self,
        *,
        repository: Any | None = None,
        http_client: ScraperHttpClient | None = None,
        sources: list[Any] | None = None,
    ) -> None:
        self._repo = repository or discovery_repository(persist=True)
        self._http = http_client or ScraperHttpClient()
        self._owns_http = http_client is None
        self._sources = sources or build_default_sources(self._http)
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
            for primary, alternates in task.result():
                key = normalize_address_key(primary.address)
                if key in excluded or key in seen_keys:
                    continue
                seen_keys.add(key)
                row_id = self._repo.upsert_seed(primary)
                listing = seed_to_discovery_listing(primary)
                listing["_queue_id"] = row_id
                if alternates:
                    listing["_alternate_seeds"] = alternates
                listings.append(listing)
                if len(listings) >= MAX_DISCOVERY_LISTINGS:
                    break
            if len(listings) >= MAX_DISCOVERY_LISTINGS:
                break

        if enrich and listings:
            await self._enrich_listings(listings)

        for listing in listings:
            listing.pop("_queue_id", None)
            listing.pop("_alternate_seeds", None)
        return listings[:MAX_DISCOVERY_LISTINGS]

    async def _search_one_market(
        self,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[tuple[ListingSeed, list[ListingSeed]]]:
        seeds: list[ListingSeed] = []
        async with asyncio.TaskGroup() as tg:
            tasks = [
                tg.create_task(
                    self._search_market_source(
                        source,
                        market_city,
                        max_price=max_price,
                        limit=limit,
                    )
                )
                for source in self._sources
            ]
        for task in tasks:
            seeds.extend(task.result())

        merged = merge_seeds_by_address(seeds)
        if merged:
            sources_hit = sorted({seed.source for seed in seeds})
            _log.info(
                "discovery_market_search",
                market_city=market_city,
                sources=sources_hit,
                raw_count=len(seeds),
                merged_count=len(merged),
            )
        return merged[:limit]

    async def _search_market_source(
        self,
        source: Any,
        market_city: str,
        *,
        max_price: float,
        limit: int,
    ) -> list[ListingSeed]:
        source_sem = self._source_sems[source.source_name]
        async with self._global_sem:
            async with source_sem:
                try:
                    return await source.search_market(
                        market_city,
                        max_price=max_price,
                        limit=limit,
                    )
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
        alternate_seeds = _coerce_alternate_seeds(listing.get("_alternate_seeds"))

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

            supplemental: list[ScrapedListing] = []
            for alt_seed in alternate_seeds:
                alt_source = self._resolve_source(alt_seed.source)
                if alt_source is None:
                    continue
                alt_sem = self._source_sems[alt_source.source_name]
                async with alt_sem:
                    try:
                        supplemental.append(await alt_source.fetch_detail(alt_seed))
                    except Exception as exc:
                        _log.warning(
                            "discovery_cross_source_enrich_failed",
                            address=alt_seed.address,
                            source=alt_seed.source,
                            error=str(exc),
                        )

        if supplemental:
            scraped = merge_scraped_listings(scraped, *supplemental)

        if row_id:
            self._repo.mark_enriched(row_id, scraped)
        listing.update(enriched_to_discovery_listing(row_id, seed, scraped))
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


def _coerce_alternate_seeds(raw: Any) -> list[ListingSeed]:
    if not isinstance(raw, list):
        return []
    seeds: list[ListingSeed] = []
    for item in raw:
        if isinstance(item, ListingSeed):
            seeds.append(item)
        elif isinstance(item, dict):
            seeds.append(
                ListingSeed(
                    address=str(item.get("address", "")),
                    city=str(item.get("city", "")),
                    list_price=float(item.get("list_price", 0.0) or 0.0),
                    listing_url=str(item.get("listing_url", "")),
                    source=str(item.get("source", "")),
                    external_id=str(item.get("external_id", "")),
                    thumbnail_url=str(item.get("thumbnail_url", "")),
                )
            )
    return seeds


async def dequeue_enriched_listings_async(
    *,
    admin_user_id: str | None = None,
    exclude_addresses: list[str] | None = None,
    db_path: str | None = None,
) -> list[dict[str, Any]]:
    """Phase 2 Stage 1 — load enriched SQLite rows (no live scrape or Gemini)."""
    from engine import MAX_DISCOVERY_LISTINGS

    exclude_keys: set[str] = set()
    if admin_user_id:
        exclude_keys.update(get_harvest_complete_addresses(admin_user_id))
    for address in exclude_addresses or []:
        if str(address).strip():
            exclude_keys.add(normalize_address_key(str(address)))

    repo = SqliteDiscoveryRepository(db_path or DEFAULT_DB_PATH)
    rows = repo.list_enriched_seeds(limit=MAX_DISCOVERY_LISTINGS * 3)
    listings: list[dict[str, Any]] = []
    for row_id, seed, scraped in rows:
        key = normalize_address_key(seed.address)
        if key in exclude_keys:
            continue
        listings.append(enriched_to_discovery_listing(row_id, seed, scraped))
        if len(listings) >= MAX_DISCOVERY_LISTINGS:
            break
    return listings


async def run_enrich_only_async(
    *,
    db_path: str | None = None,
    limit: int = 500,
) -> int:
    """Fetch portal details for pending queue rows and mark them enriched."""
    repo = SqliteDiscoveryRepository(db_path or DEFAULT_DB_PATH)
    orchestrator = DiscoveryOrchestrator(repository=repo)
    try:
        pending = repo.get_pending_rows(limit=limit)
        if not pending:
            return 0
        listings: list[dict[str, Any]] = []
        for row in pending:
            seed = ListingSeed(
                address=str(row["address"]),
                city=str(row["city"]),
                list_price=float(row["list_price"]),
                listing_url=str(row["listing_url"]),
                source=str(row["source"]),
                external_id=str(row["external_id"]),
            )
            listing = seed_to_discovery_listing(seed)
            listing["_queue_id"] = int(row["id"])
            listings.append(listing)
        await orchestrator._enrich_listings(listings)
        return sum(1 for listing in listings if listing.get("_scraped") is not None)
    finally:
        await orchestrator.close()


async def run_scraper_discovery_async(
    *,
    admin_user_id: str | None = None,
    exclude_addresses: list[str] | None = None,
    max_price: float | None = None,
    db_path: str | None = None,
    per_market_limit: int = 25,
    enrich: bool = True,
    persist: bool = True,
) -> list[dict[str, Any]]:
    """Search HOT_MARKETS and optionally enrich; used by discovery_scraper.py."""
    from engine import MAX_DISCOVERY_PRICE

    exclude_keys: set[str] = set()
    if admin_user_id:
        exclude_keys.update(get_harvest_complete_addresses(admin_user_id))
    for address in exclude_addresses or []:
        if str(address).strip():
            exclude_keys.add(normalize_address_key(str(address)))

    repo = discovery_repository(persist=persist, db_path=db_path or DEFAULT_DB_PATH)
    orchestrator = DiscoveryOrchestrator(repository=repo)
    try:
        return await orchestrator.run(
            exclude_keys=exclude_keys,
            max_price=max_price or MAX_DISCOVERY_PRICE,
            per_market_limit=per_market_limit,
            enrich=enrich,
        )
    finally:
        await orchestrator.close()
