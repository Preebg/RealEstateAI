#!/usr/bin/env python3
"""Backfill zip_code on all properties from parsed address strings."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harvester import _load_local_secrets
from knowledge_base import get_client, parse_zipcode_from_address


def backfill_zip_codes() -> dict[str, int]:
    _load_local_secrets()
    if not os.getenv("SUPABASE_URL") or not os.getenv("SUPABASE_KEY"):
        raise SystemExit("SUPABASE_URL and SUPABASE_KEY must be set.")

    client = get_client()
    response = client.table("properties").select("address, zip_code").execute()
    rows = response.data or []

    updated = 0
    skipped_no_zip = 0
    skipped_unchanged = 0

    for row in rows:
        address = str(row.get("address") or "").strip()
        if not address:
            skipped_no_zip += 1
            continue

        parsed = parse_zipcode_from_address(address)
        if not parsed:
            skipped_no_zip += 1
            continue

        current = str(row.get("zip_code") or "").strip()
        if current == parsed:
            skipped_unchanged += 1
            continue

        client.table("properties").update({"zip_code": parsed}).eq(
            "address", address
        ).execute()
        updated += 1
        print(f"  {address} -> {parsed}")

    return {
        "total": len(rows),
        "updated": updated,
        "skipped_no_zip": skipped_no_zip,
        "skipped_unchanged": skipped_unchanged,
    }


def main() -> None:
    print("Backfilling zip_code from addresses...")
    report = backfill_zip_codes()
    print(
        f"Done: {report['updated']} updated, "
        f"{report['skipped_unchanged']} already correct, "
        f"{report['skipped_no_zip']} without parseable ZIP, "
        f"{report['total']} total rows"
    )


if __name__ == "__main__":
    main()
