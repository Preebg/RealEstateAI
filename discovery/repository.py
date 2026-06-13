"""SQLite queue + property mirror for harvester discovery."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from discovery.models import ListingSeed, ScrapedListing

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "capigen.db"

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS discovery_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    address TEXT NOT NULL,
    city TEXT NOT NULL,
    list_price REAL NOT NULL DEFAULT 0,
    listing_url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    raw_json TEXT,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS property_mirror (
    address_key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    primary_image_url TEXT NOT NULL DEFAULT '',
    synced_supabase_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_discovery_queue_status ON discovery_queue(status);
CREATE INDEX IF NOT EXISTS idx_discovery_queue_city ON discovery_queue(city);
CREATE INDEX IF NOT EXISTS idx_property_mirror_address ON property_mirror(address_key);
"""


class SqliteDiscoveryRepository:
    """Local SQLite persistence for scraper discovery."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path or DEFAULT_DB_PATH)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA_SQL)
            conn.commit()

    def upsert_seed(self, seed: ListingSeed) -> int:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO discovery_queue (
                    address, city, list_price, listing_url, source, external_id,
                    status, discovered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    address = excluded.address,
                    city = excluded.city,
                    list_price = excluded.list_price,
                    listing_url = excluded.listing_url,
                    updated_at = excluded.updated_at
                """,
                (
                    seed.address,
                    seed.city,
                    seed.list_price,
                    seed.listing_url,
                    seed.source,
                    seed.external_id,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM discovery_queue WHERE source = ? AND external_id = ?",
                (seed.source, seed.external_id),
            ).fetchone()
            conn.commit()
        if row is None:
            raise RuntimeError("Failed to upsert discovery seed")
        return int(row["id"])

    def mark_enriched(self, row_id: int, scraped: ScrapedListing) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE discovery_queue
                SET status = 'enriched', raw_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(scraped.to_dict()), now, row_id),
            )
            conn.commit()

    def mark_status(self, row_id: int, status: str) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                "UPDATE discovery_queue SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, row_id),
            )
            conn.commit()

    def mark_completed(self, row_id: int) -> None:
        """Mark a queue row harvested after Supabase save."""
        self.mark_status(row_id, "completed")

    def get_pending_rows(self, *, limit: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM discovery_queue
                WHERE status = 'pending'
                ORDER BY discovered_at ASC
                LIMIT ?
                """,
                (max(limit, 1),),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_enriched_by_external_id(
        self,
        source: str,
        external_id: str,
    ) -> ScrapedListing | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT raw_json FROM discovery_queue
                WHERE source = ? AND external_id = ? AND raw_json IS NOT NULL
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (source, external_id),
            ).fetchone()
        if row is None or not row["raw_json"]:
            return None
        payload = json.loads(str(row["raw_json"]))
        return ScrapedListing.from_dict(payload)

    def mirror_property(self, address_key: str, payload: dict[str, Any]) -> None:
        primary_image = str(payload.get("primary_image_url", "")).strip()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO property_mirror (address_key, payload_json, primary_image_url)
                VALUES (?, ?, ?)
                ON CONFLICT(address_key) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    primary_image_url = excluded.primary_image_url
                """,
                (address_key, json.dumps(payload), primary_image),
            )
            conn.commit()

    def list_enriched_seeds(
        self,
        *,
        limit: int,
    ) -> list[tuple[int, ListingSeed, ScrapedListing]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM discovery_queue
                WHERE status = 'enriched' AND raw_json IS NOT NULL
                ORDER BY discovered_at ASC
                LIMIT ?
                """,
                (max(limit, 1),),
            ).fetchall()
        results: list[tuple[int, ListingSeed, ScrapedListing]] = []
        for row in rows:
            scraped = ScrapedListing.from_dict(json.loads(str(row["raw_json"])))
            seed = ListingSeed(
                address=str(row["address"]),
                city=str(row["city"]),
                list_price=float(row["list_price"]),
                listing_url=str(row["listing_url"]),
                source=str(row["source"]),
                external_id=str(row["external_id"]),
                thumbnail_url=scraped.primary_image_url,
            )
            results.append((int(row["id"]), seed, scraped))
        return results


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
