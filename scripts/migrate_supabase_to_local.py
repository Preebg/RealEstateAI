#!/usr/bin/env python3
"""Copy hosted Supabase catalog data into local Postgres on the harvest machine.

Auth stays on hosted Supabase. This copies public catalog tables only.

  python scripts/migrate_supabase_to_local.py --dry-run
  python scripts/migrate_supabase_to_local.py

Requires DATABASE_REST_URL (local) and the hosted service_role JWT
(SUPABASE_AUTH_SERVICE_ROLE_KEY, or SUPABASE_SERVICE_ROLE_KEY starting with eyJ).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from supabase import Client, create_client  # noqa: E402

from authenticate import (  # noqa: E402
    _drop_local_postgrest_bearer,
    get_auth_base_url,
    get_data_base_url,
    using_local_database,
)
from config_secrets import load_local_secrets_into_environ, normalize_secret_value  # noqa: E402
from services.supabase_local_migration import (  # noqa: E402
    CONFLICT_KEYS,
    DEFAULT_UPSERT_BATCH,
    MIGRATE_TABLES,
    PAGE_SIZE,
    PROPERTY_CHILD_TABLES,
    PROPERTY_PARENT_TABLES,
    PROPERTY_UPSERT_BATCH,
    CopyPlan,
    MigrationReport,
    allowed_property_ids,
    hosted_service_role_key,
    plan_child_copy,
    plan_parent_copy,
    plan_simple_copy,
)

GUEST_SQL = ROOT / "docker" / "postgres" / "init" / "04_guest_share_functions.sql"
PREVIEW_USERNAMES_SQL = ROOT / "docker" / "postgres" / "init" / "05_preview_usernames.sql"


def _env(name: str) -> str | None:
    return normalize_secret_value(os.getenv(name))


def _hosted_client() -> Client:
    url = get_auth_base_url()
    key = hosted_service_role_key(_env)
    if not key:
        raise SystemExit(
            "Hosted SUPABASE service_role JWT is required to read catalog data.\n"
            "Set SUPABASE_AUTH_SERVICE_ROLE_KEY to the JWT from Supabase Dashboard\n"
            "→ Project Settings → API → service_role (starts with eyJ).\n"
            "Keep SUPABASE_SERVICE_ROLE_KEY as the local PostgREST dummy if you use one."
        )
    if "supabase.co" not in url and "supabase.com" not in url:
        print(f"Warning: SUPABASE_URL does not look hosted: {url}", flush=True)
    return create_client(url, key)


def _local_client() -> Client:
    if not using_local_database():
        raise SystemExit(
            "DATABASE_REST_URL is not set. This script writes to local Postgres.\n"
            "Add DATABASE_REST_URL=http://127.0.0.1:3001 to .env on the harvest machine."
        )
    key = _env("SUPABASE_SERVICE_ROLE_KEY") or "local-service-key"
    client = create_client(get_data_base_url(), key)
    return _drop_local_postgrest_bearer(client)


def fetch_all(client: Client, table: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    offset = 0
    while True:
        response = (
            client.table(table)
            .select("*")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        batch = list(response.data or [])
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def upsert_rows(client: Client, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    conflict = CONFLICT_KEYS[table]
    batch_size = PROPERTY_UPSERT_BATCH if table in PROPERTY_PARENT_TABLES else DEFAULT_UPSERT_BATCH
    for start in range(0, len(rows), batch_size):
        chunk = rows[start : start + batch_size]
        client.table(table).upsert(chunk, on_conflict=conflict).execute()
        print(
            f"  upserted {table} {start + 1}-{start + len(chunk)} / {len(rows)}",
            flush=True,
        )


def apply_sql_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"Missing {path}")
    user = _env("POSTGRES_USER") or "capeigen"
    db = _env("POSTGRES_DB") or "capeigen"
    sql = path.read_text(encoding="utf-8")
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        user,
        "-d",
        db,
        "-v",
        "ON_ERROR_STOP=1",
    ]
    print(f"Applying {label} to local Postgres...", flush=True)
    result = subprocess.run(
        cmd,
        input=sql,
        text=True,
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise SystemExit(
            f"Failed to apply {label} via docker compose exec postgres.\n"
            f"{detail}\n"
            "Start the stack: docker compose up -d postgres postgrest rest-gateway"
        )
    print(f"{label} applied.", flush=True)


def apply_guest_functions() -> None:
    apply_sql_file(GUEST_SQL, "guest share SQL functions")
    apply_sql_file(PREVIEW_USERNAMES_SQL, "preview usernames table")


def build_plans(source: Client, dest: Client) -> tuple[list[CopyPlan], set[str]]:
    local_parents: list[dict[str, Any]] = []
    copied_parents: list[dict[str, Any]] = []
    plans: list[CopyPlan] = []

    for table in ("properties", "archived_properties"):
        source_rows = fetch_all(source, table)
        local_rows = fetch_all(dest, table)
        plan = plan_parent_copy(
            table=table,
            source_rows=source_rows,
            local_rows=local_rows,
        )
        plans.append(plan)
        local_parents.extend(local_rows)
        copied_parents.extend(plan.rows)
        print(
            f"{table}: hosted {len(source_rows)}, local {len(local_rows)}, "
            f"copy {len(plan.rows)}, skip-id {plan.skipped_existing}, "
            f"skip-address {plan.skipped_address}",
            flush=True,
        )

    allowed_ids = allowed_property_ids(local_parents, copied_parents)

    for table in MIGRATE_TABLES:
        if table in PROPERTY_PARENT_TABLES:
            continue
        source_rows = fetch_all(source, table)
        local_rows = fetch_all(dest, table)
        conflict = CONFLICT_KEYS[table]
        if table in PROPERTY_CHILD_TABLES:
            plan = plan_child_copy(
                table=table,
                source_rows=source_rows,
                local_rows=local_rows,
                allowed_property_ids=allowed_ids,
                conflict_key=conflict,
            )
        else:
            plan = plan_simple_copy(
                table=table,
                source_rows=source_rows,
                local_rows=local_rows,
                conflict_key=conflict,
            )
        plans.append(plan)
        print(
            f"{table}: hosted {len(source_rows)}, local {len(local_rows)}, "
            f"copy {len(plan.rows)}, skip-existing {plan.skipped_existing}, "
            f"skip-parent {plan.skipped_missing_parent}",
            flush=True,
        )
    return plans, allowed_ids


def migrate(*, dry_run: bool, apply_functions: bool) -> MigrationReport:
    load_local_secrets_into_environ()
    if apply_functions and not dry_run:
        apply_guest_functions()

    source = _hosted_client()
    dest = _local_client()
    print(f"Source (hosted): {get_auth_base_url()}", flush=True)
    print(f"Dest (local):    {get_data_base_url()}", flush=True)

    plans, _allowed_ids = build_plans(source, dest)
    report = MigrationReport(plans=plans, dry_run=dry_run)
    if dry_run:
        print("Dry run — no rows written.", flush=True)
        return report

    for plan in plans:
        upsert_rows(dest, plan.table, plan.rows)
    copied = sum(len(plan.rows) for plan in plans)
    print(f"Done. Copied {copied} rows into local Postgres.", flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy hosted Supabase catalog tables into local Postgres."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows and conflicts without writing.",
    )
    parser.add_argument(
        "--skip-guest-functions",
        action="store_true",
        help="Do not apply docker/postgres/init/04_guest_share_functions.sql",
    )
    args = parser.parse_args()
    migrate(
        dry_run=args.dry_run,
        apply_functions=not args.skip_guest_functions,
    )


if __name__ == "__main__":
    main()
