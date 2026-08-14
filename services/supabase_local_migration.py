"""Copy hosted Supabase catalog tables into local Postgres (harvest machine)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledge_base import normalize_address_key

# Parent first, then FK children. Auth stays on hosted Supabase (no auth.users copy).
# oauth_* tables are ephemeral tokens and are not copied.
MIGRATE_TABLES: tuple[str, ...] = (
    "properties",
    "archived_properties",
    "property_comparables",
    "property_shares",
    "property_share_comps",
    "user_property_overrides",
    "user_saved_properties",
    "user_notification_preferences",
    "recommendation_feedback",
    "digest_recommendation_log",
    "preview_events",
)

PROPERTY_PARENT_TABLES = frozenset({"properties", "archived_properties"})
PROPERTY_CHILD_TABLES = frozenset(
    {
        "property_comparables",
        "property_shares",
        "property_share_comps",
        "user_property_overrides",
        "user_saved_properties",
        "recommendation_feedback",
        "digest_recommendation_log",
    }
)

CONFLICT_KEYS: dict[str, str] = {
    "properties": "id",
    "archived_properties": "id",
    "property_comparables": "id",
    "property_shares": "id",
    "property_share_comps": "share_token",
    "user_property_overrides": "id",
    "user_saved_properties": "id",
    "user_notification_preferences": "user_id",
    "recommendation_feedback": "id",
    "digest_recommendation_log": "id",
    "preview_events": "id",
}

PAGE_SIZE = 500
PROPERTY_UPSERT_BATCH = 25
DEFAULT_UPSERT_BATCH = 100


@dataclass
class CopyPlan:
    table: str
    rows: list[dict[str, Any]]
    skipped_existing: int = 0
    skipped_address: int = 0
    skipped_missing_parent: int = 0


@dataclass
class MigrationReport:
    plans: list[CopyPlan] = field(default_factory=list)
    dry_run: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "tables": [
                {
                    "table": plan.table,
                    "copy": len(plan.rows),
                    "skipped_existing": plan.skipped_existing,
                    "skipped_address": plan.skipped_address,
                    "skipped_missing_parent": plan.skipped_missing_parent,
                }
                for plan in self.plans
            ],
        }


def _row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "").strip()


def _address_key(row: dict[str, Any]) -> str:
    return normalize_address_key(str(row.get("address") or ""))


def plan_parent_copy(
    *,
    table: str,
    source_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
) -> CopyPlan:
    """Keep local harvest rows; copy hosted rows that are new by id and address."""
    local_ids = {_row_id(row) for row in local_rows if _row_id(row)}
    local_addresses = {_address_key(row) for row in local_rows if _address_key(row)}
    to_copy: list[dict[str, Any]] = []
    skipped_existing = 0
    skipped_address = 0
    for row in source_rows:
        rid = _row_id(row)
        if rid and rid in local_ids:
            skipped_existing += 1
            continue
        addr = _address_key(row)
        if addr and addr in local_addresses:
            skipped_address += 1
            continue
        to_copy.append(row)
    return CopyPlan(
        table=table,
        rows=to_copy,
        skipped_existing=skipped_existing,
        skipped_address=skipped_address,
    )


def plan_child_copy(
    *,
    table: str,
    source_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    allowed_property_ids: set[str],
    conflict_key: str,
) -> CopyPlan:
    local_keys = {
        str(row.get(conflict_key) or "").strip()
        for row in local_rows
        if str(row.get(conflict_key) or "").strip()
    }
    to_copy: list[dict[str, Any]] = []
    skipped_existing = 0
    skipped_missing_parent = 0
    for row in source_rows:
        key = str(row.get(conflict_key) or "").strip()
        if key and key in local_keys:
            skipped_existing += 1
            continue
        parent_id = str(row.get("property_id") or "").strip()
        if parent_id and parent_id not in allowed_property_ids:
            skipped_missing_parent += 1
            continue
        to_copy.append(row)
    return CopyPlan(
        table=table,
        rows=to_copy,
        skipped_existing=skipped_existing,
        skipped_missing_parent=skipped_missing_parent,
    )


def allowed_property_ids(
    local_parent_rows: list[dict[str, Any]],
    copied_parent_rows: list[dict[str, Any]],
) -> set[str]:
    ids = {_row_id(row) for row in local_parent_rows if _row_id(row)}
    ids.update(_row_id(row) for row in copied_parent_rows if _row_id(row))
    return ids


def plan_simple_copy(
    *,
    table: str,
    source_rows: list[dict[str, Any]],
    local_rows: list[dict[str, Any]],
    conflict_key: str,
) -> CopyPlan:
    local_keys = {
        str(row.get(conflict_key) or "").strip()
        for row in local_rows
        if str(row.get(conflict_key) or "").strip()
    }
    to_copy: list[dict[str, Any]] = []
    skipped_existing = 0
    for row in source_rows:
        key = str(row.get(conflict_key) or "").strip()
        if key and key in local_keys:
            skipped_existing += 1
            continue
        to_copy.append(row)
    return CopyPlan(table=table, rows=to_copy, skipped_existing=skipped_existing)


def hosted_service_role_key(env_get: Any) -> str | None:
    """Return the hosted JWT service role, ignoring local PostgREST dummy keys."""
    for name in ("SUPABASE_AUTH_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        raw = env_get(name)
        if raw is None:
            continue
        key = str(raw).strip()
        if key.startswith("eyJ"):
            return key
    return None
