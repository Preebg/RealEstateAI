#!/usr/bin/env python3
"""CLI to search portal listings and enrich the local SQLite discovery queue."""

from __future__ import annotations

import argparse
import asyncio
import sys

from discovery.orchestrator import run_enrich_only_async, run_scraper_discovery_async


def _configure_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


async def _run_async(args: argparse.Namespace) -> int:
    if args.enrich_only:
        enriched = await run_enrich_only_async(limit=args.limit)
        print(f"Enriched {enriched} pending listing(s).")
        return 0

    listings = await run_scraper_discovery_async(
        max_price=args.max_price,
        per_market_limit=args.per_market_limit,
        enrich=False,
    )
    print(
        f"Queued {len(listings)} listing seed(s). "
        "Run with --enrich-only to fetch portal details."
    )
    return 0


def main() -> None:
    _configure_stdio()
    parser = argparse.ArgumentParser(
        description="Search Redfin markets and enrich the local discovery queue.",
    )
    parser.add_argument(
        "--enrich-only",
        action="store_true",
        help="Fetch portal details for pending queue rows (no new search).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max pending rows to enrich when --enrich-only is set (default: 500).",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        default=None,
        help="List-price ceiling for market search (default: engine.MAX_DISCOVERY_PRICE).",
    )
    parser.add_argument(
        "--per-market-limit",
        type=int,
        default=25,
        help="Max seeds per HOT_MARKET during search (default: 25).",
    )
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(_run_async(args)))
    except KeyboardInterrupt:
        print("\nInterrupted.", flush=True)
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
