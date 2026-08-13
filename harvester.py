# harvester.py — 3-Stage Hot Market Harvester (multi-market discovery)
from __future__ import annotations

import asyncio
import os
import sys
import time
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from google.genai import errors

import engine
from app_logging import configure_logging, report_error
from discovery.normalize import listing_dict_to_scraped, scraped_to_research_dict
from discovery.orchestrator import run_scraper_discovery_async
from config_secrets import (
    load_local_secrets_into_environ,
    normalize_secret_value,
    resolve_hostname,
)
from finance import analyze_investment
from knowledge_base import (
    delete_unreliable_property,
    get_admin_uid,
    get_harvest_complete_addresses,
    get_kb_raw_data,
    get_market_pulse,
    archive_stale_properties,
    is_property_harvest_complete,
    normalize_address_key,
    one_year_roi_unreliable_reason,
    purge_unreliable_one_year_roi_properties,
    save_harvest_property,
)

log = configure_logging("harvester")

INVESTMENT_PARAMS = {
    "down_payment": 25.0,
    "interest_rate": 6.0,
    "loan_term": 30,
    "closing_costs_pct": 3.0,
}

# Active models for this run (updated when RPD fallback triggers).
_active_discovery_model = engine.DISCOVERY_MODEL
_active_research_model = engine.RESEARCH_MODEL
_active_synthesis_model = engine.SYNTHESIS_MODEL

def resolve_discovery_backend() -> str:
    """Return ``gemini`` (default) or ``scraper`` from DISCOVERY_BACKEND."""
    raw = os.getenv("DISCOVERY_BACKEND")
    if raw is not None and raw.strip():
        backend = raw.strip().lower()
        if backend in ("gemini", "scraper"):
            return backend
    legacy = os.getenv("HARVESTER_USE_SCRAPER", "").strip().lower()
    if legacy in ("1", "true", "yes", "on"):
        return "scraper"
    if legacy in ("0", "false", "no", "off"):
        return "gemini"
    return "gemini"


@dataclass
class _SynthesisJob:
    address: str
    market_city: str
    research: dict[str, Any]
    geospatial: dict[str, Any] = field(default_factory=dict)


@dataclass
class _HarvesterModelState:
    research_model: str = field(default_factory=lambda: engine.RESEARCH_MODEL)
    synthesis_model: str = field(default_factory=lambda: engine.SYNTHESIS_MODEL)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_research_model(self) -> str:
        async with self._lock:
            return self.research_model

    async def get_synthesis_model(self) -> str:
        async with self._lock:
            return self.synthesis_model

    async def set_research_fallback(self, fallback_model: str) -> None:
        global _active_research_model
        async with self._lock:
            self.research_model = fallback_model
            _active_research_model = fallback_model

    async def set_synthesis_fallback(self, fallback_model: str) -> None:
        global _active_synthesis_model
        async with self._lock:
            self.synthesis_model = fallback_model
            _active_synthesis_model = fallback_model

_HARVESTER_API_ERRORS = (
    errors.ClientError,
    errors.ServerError,
    errors.APIError,
    RuntimeError,
    ValueError,
    KeyError,
)


def execute_with_backoff(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Wrap harvester stages with the same jittered exponential backoff as engine."""
    total_wait_sec = 0.0
    last_error: BaseException | None = None
    for attempt in range(engine.MAX_API_RETRIES):
        try:
            return func(*args, **kwargs)
        except errors.ClientError as e:
            last_error = e
            if e.code == 429 and attempt < engine.MAX_API_RETRIES - 1:
                delay_sec = engine.retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                log.warning(
                    "rate_limit_backoff",
                    attempt=attempt + 1,
                    max_attempts=engine.MAX_API_RETRIES,
                    delay_sec=round(delay_sec, 2),
                    total_wait_sec=round(total_wait_sec, 2),
                )
                time.sleep(delay_sec)
                continue
            raise
    raise RuntimeError(
        f"Max retries ({engine.MAX_API_RETRIES}) exceeded for API rate limits, "
        f"total_wait_sec={total_wait_sec:.2f}"
    ) from last_error


def execute_with_rpd_fallback(
    func: Callable[..., Any],
    *args: Any,
    stage: str,
    fallback_model: str,
    model_kw: str = "model",
    **kwargs: Any,
) -> Any:
    """Retry a stage on fallback model when daily (RPD) quota is exhausted."""
    global _active_discovery_model, _active_synthesis_model

    current_model = kwargs.get(model_kw)
    try:
        # generate_with_retry already backs off on transient 429s; avoid nesting
        # another retry loop here (that blocked RPD fallback for 15+ attempts).
        return func(*args, **kwargs)
    except _HARVESTER_API_ERRORS as exc:
        if not engine.is_daily_quota_exhausted(exc):
            raise
        if current_model == fallback_model:
            raise

        log.warning(
            "rpd_model_fallback",
            stage=stage,
            from_model=current_model or "default",
            to_model=fallback_model,
            error=str(exc),
        )
        print(
            f"  {stage} daily quota exhausted - switching to {fallback_model}"
        )

        if stage == "discovery":
            _active_discovery_model = fallback_model
        elif stage == "synthesis":
            _active_synthesis_model = fallback_model

        retry_kwargs = {**kwargs, model_kw: fallback_model}
        return func(*args, **retry_kwargs)


def headless_cash_flow(property_data: dict[str, Any]) -> float:
    """Monthly net cash flow using centralized finance module."""
    analysis = analyze_investment(
        price=engine.safe_float(property_data.get("price", 0)),
        down_payment_pct=INVESTMENT_PARAMS["down_payment"],
        interest_rate=INVESTMENT_PARAMS["interest_rate"],
        loan_term=int(INVESTMENT_PARAMS["loan_term"]),
        closing_costs_pct=INVESTMENT_PARAMS["closing_costs_pct"],
        tax_rate=engine.safe_float(property_data.get("tax_rate", 0)),
        monthly_insurance=engine.safe_float(property_data.get("insurance", 0)),
        monthly_hoa=engine.safe_float(property_data.get("hoa", 0)),
        maint_percent=engine.safe_float(property_data.get("maint_percent", 4)),
        monthly_rent=engine.safe_float(property_data.get("rent", 0)),
        vacancy_reserve_pct=engine.safe_float(property_data.get("ai_vacancy_rate", 5)),
        management_fee_pct=engine.safe_float(property_data.get("ai_management_fee", 10)),
    )
    return analysis["monthly_net_cash_flow"]


def _load_local_secrets() -> None:
    """Optionally load root ``secrets.toml`` into os.environ (tests / optional local file)."""
    secrets_path = Path(__file__).resolve().parent / "secrets.toml"
    if not secrets_path.exists():
        return

    if not load_local_secrets_into_environ(secrets_path=secrets_path):
        log.error("secrets_toml_parse_failed", path=str(secrets_path))
        print(f"Warning: could not parse {secrets_path}")


def _secret_from_env(name: str) -> str | None:
    return normalize_secret_value(os.getenv(name))


def _validate_harvest_network() -> bool:
    """Confirm data API (and scraper hosts) resolve on this machine."""
    from authenticate import get_data_base_url, using_local_database

    try:
        data_url = get_data_base_url()
        host = urlparse(data_url).hostname or ""
        label = "DATABASE_REST_URL" if using_local_database() else "SUPABASE_URL"
        if host not in {"localhost", "127.0.0.1", "0.0.0.0", "::1", "rest-gateway"}:
            resolve_hostname(host, label=label)
        if using_local_database():
            os.environ["DATABASE_REST_URL"] = data_url
        else:
            os.environ["SUPABASE_URL"] = data_url
    except (OSError, ValueError, EnvironmentError) as exc:
        log.error("harvest_dns_failed", error=str(exc))
        print(f"Network configuration error: {exc}")
        return False

    if resolve_discovery_backend() == "scraper":
        for host, label in (
            ("www.redfin.com", "Redfin scraper"),
            ("www.realtor.com", "Realtor scraper"),
            ("www.zillow.com", "Zillow scraper"),
        ):
            try:
                resolve_hostname(host, label=label)
            except OSError as exc:
                log.error("harvest_dns_failed", error=str(exc), host=host)
                print(f"Network configuration error: {exc}")
                return False

    return True


def validate_harvest_config() -> str | None:
    """Validate API keys and return admin user_id, or None if configuration is incomplete."""
    _load_local_secrets()

    has_data = bool(
        _secret_from_env("DATABASE_REST_URL") or _secret_from_env("SUPABASE_URL")
    )
    missing = [
        name
        for name in ("GEMINI_API_KEY", "SUPABASE_KEY", "ADMIN_USER_ID")
        if not _secret_from_env(name)
    ]
    if not has_data:
        missing.append("DATABASE_REST_URL or SUPABASE_URL")
    if missing:
        log.error("harvest_config_missing", missing=missing)
        print(
            "Missing required configuration: "
            + ", ".join(missing)
            + "\nAdd them to environment variables or a local .env / optional legacy secrets TOML."
        )
        return None

    admin_uid = get_admin_uid()
    if not admin_uid:
        raw_admin = _secret_from_env("ADMIN_USER_ID") or ""
        log.error("harvest_admin_uid_invalid", admin_user_id=raw_admin)
        print(
            "ADMIN_USER_ID is missing or not a valid UUID.\n"
            "1. Supabase Dashboard -> Authentication -> Users -> copy your User UID\n"
            "2. Set ADMIN_USER_ID in the environment (or optional legacy secrets TOML)\n"
            "   Watch for typos: letter 'l' vs digit '1', letter 'O' vs zero '0'.\n"
            f"   Current value: {raw_admin!r}"
        )
        return None

    if not _validate_harvest_network():
        return None

    from authenticate import ensure_catalog_admin_config, get_service_client, using_local_database

    if get_service_client() is None:
        log.error("harvest_service_role_missing")
        print(
            "SUPABASE_SERVICE_ROLE_KEY is required for headless harvest.\n"
            "On hosted Supabase: Project Settings -> API -> service_role (secret).\n"
            "On local Postgres/PostgREST: any non-empty key works (e.g. local-service-key).\n"
            "Keep SUPABASE_KEY as the anon/public key for the React web app / Auth."
        )
        return None

    ensure_catalog_admin_config(admin_uid)

    backend = "local-postgres" if using_local_database() else "supabase"
    log.info("harvest_config_ready", admin_user_id=admin_uid[:8] + "...", backend=backend)
    print(f"Harvest data backend: {backend}")
    print(f"Harvest saves will use admin user_id: {admin_uid}")
    return admin_uid


def require_harvest_config() -> str:
    """CLI entry: exit process when harvest configuration is invalid."""
    admin_uid = validate_harvest_config()
    if not admin_uid:
        sys.exit(1)
    return admin_uid


def _validate_listing(listing: dict[str, Any]) -> tuple[str, str]:
    address = str(listing.get("address", "")).strip()
    market_city = str(listing.get("city", "")).strip()
    if not address:
        raise ValueError("Listing is missing a valid address")
    if market_city not in engine.DISCOVERY_MARKET_KEYS:
        raise ValueError(f"Listing has unsupported market city: {market_city!r}")
    return address, market_city


async def _research_listing_with_fallback(
    address: str,
    listing: dict[str, Any],
    market_city: str,
    model_state: _HarvesterModelState,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
) -> dict[str, Any]:
    """Stage 2 research — local scraper payload or gemma research fallback."""
    _ = model_state  # research model is fixed; state kept for pipeline symmetry
    if listing.get("discovery_model") == "scraper":
        scraped = listing_dict_to_scraped(listing)
        if scraped is None:
            raise RuntimeError(f"Missing scraper payload for {address}")
        research = scraped_to_research_dict(scraped, market_city=market_city)
        research = engine._normalize_research_payload(address, research)
        print(f"  [research] SCRAPER {address} — skipped Gemini research")
    else:
        research = await engine.research_property_async(
            address,
            discovery=listing,
            model=engine.RESEARCH_MODEL,
            rate_limiter=rate_limiter,
            session=session,
        )
    return await _run_property_value_stage(
        address,
        research,
        market_city,
        rate_limiter=rate_limiter,
        session=session,
    )


async def _run_property_value_stage(
    address: str,
    research: dict[str, Any],
    market_city: str,
    *,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
) -> dict[str, Any]:
    """Stage 2.5 — classify strategy and fetch comps when income-hold keywords match."""
    print(f"  [property_value] START {address} ({engine.PROPERTY_VALUE_MODEL})")
    enriched = await engine.run_property_value_agent_async(
        address,
        research,
        market_city,
        session=session,
        rate_limiter=rate_limiter,
    )
    comps = enriched.get("comps_analysis")
    comp_count = 0
    if isinstance(comps, dict):
        comp_count = int(comps.get("comp_count") or len(comps.get("comparable_properties") or []))
    if comp_count > 0:
        print(
            f"  [property_value] DONE {address} — "
            f"{comp_count} comps via {engine.PROPERTY_VALUE_TRIGGERED_MODEL}"
        )
    else:
        strategy = enriched.get("predicted_strategy_label") or "unknown"
        print(f"  [property_value] SKIP {address} — no comps ({strategy})")
    return enriched


async def _geocode_listing_parallel(
    address: str,
    market_city: str,
    *,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
    geospatial_budget: engine.GroundingRpdBudget | None = None,
) -> dict[str, Any]:
    """Dedicated coordinate agent — runs alongside research / property value."""
    print(f"  [geocode] START {address} — {engine.COORDINATE_MODEL} (parallel)")
    geospatial = await engine.run_geospatial_enrichment_async(
        address,
        market_city=market_city,
        model=engine.COORDINATE_MODEL,
        budget=geospatial_budget,
        rate_limiter=rate_limiter,
        session=session,
    )
    if engine._has_precise_coordinates(
        geospatial.get("latitude"),
        geospatial.get("longitude"),
    ):
        print(
            f"  [geocode] DONE {address} — "
            f"{geospatial['latitude']:.5f}, {geospatial['longitude']:.5f} "
            f"({geospatial.get('geocode_confidence', 'low')}; "
            f"{geospatial.get('geocode_source', 'unknown')})"
        )
    else:
        print(f"  [geocode] SKIP {address} — coordinates unresolved")
    return geospatial


async def _research_listing(
    listing: dict[str, Any],
    admin_user_id: str,
    report: dict[str, Any],
    report_lock: asyncio.Lock,
    model_state: _HarvesterModelState,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
    *,
    geospatial_budget: engine.GroundingRpdBudget | None = None,
) -> _SynthesisJob | None:
    """Stage 2 for one listing; returns a synthesis job or None when skipped."""
    address, market_city = _validate_listing(listing)

    already_complete = await asyncio.to_thread(
        is_property_harvest_complete, address, user_id=admin_user_id
    )
    if already_complete:
        print(f"  [research] SKIP {address} — already in knowledge base")
        async with report_lock:
            report["already_scanned"].append(
                {"address": address, "reason": "Already in KB"}
            )
        log.info("listing_already_scanned", address=address)
        return None

    log.info("listing_research_start", address=address, market_city=market_city)
    print(f"  [research] START {address} ({market_city})")

    research_task = asyncio.create_task(
        _research_listing_with_fallback(
            address,
            listing,
            market_city,
            model_state,
            rate_limiter,
            session,
        ),
        name=f"research:{address}",
    )
    geocode_task = asyncio.create_task(
        _geocode_listing_parallel(
            address,
            market_city,
            rate_limiter=rate_limiter,
            session=session,
            geospatial_budget=geospatial_budget,
        ),
        name=f"geocode:{address}",
    )
    research_outcome, geocode_outcome = await asyncio.gather(
        research_task,
        geocode_task,
        return_exceptions=True,
    )

    if isinstance(research_outcome, BaseException):
        if isinstance(research_outcome, KeyboardInterrupt):
            raise research_outcome
        if isinstance(geocode_outcome, BaseException) and not isinstance(
            geocode_outcome, KeyboardInterrupt
        ):
            report_error(
                log,
                "listing_geocode_failed",
                geocode_outcome,
                address=address,
            )
        raise research_outcome

    research = research_outcome
    if isinstance(geocode_outcome, BaseException):
        if isinstance(geocode_outcome, KeyboardInterrupt):
            raise geocode_outcome
        report_error(log, "listing_geocode_failed", geocode_outcome, address=address)
        print(f"  [geocode] FAILED {address} — {geocode_outcome}")
        geospatial = engine.geospatial_from_cached_coords(research) or {}
    else:
        geospatial = geocode_outcome

    async with report_lock:
        report["researched"] += 1
        if isinstance(research.get("comps_analysis"), dict) and research["comps_analysis"].get(
            "comparable_properties"
        ):
            report["property_valued"] = int(report.get("property_valued", 0)) + 1

    skip_reason = engine.research_stage_skip_reason(research, listing)
    if skip_reason:
        print(f"  [research] SKIP {address} — {skip_reason}")
        async with report_lock:
            report["skipped"].append({"address": address, "reason": skip_reason})
        log.info("listing_skipped", address=address, reason=skip_reason)
        return None

    print(f"  [research] DONE {address}")
    return _SynthesisJob(
        address=address,
        market_city=market_city,
        research=research,
        geospatial=geospatial,
    )


async def _synthesize_harvest_property_with_fallback(
    address: str,
    research: dict[str, Any],
    market_city: str,
    admin_user_id: str,
    model_state: _HarvesterModelState,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
    *,
    geospatial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Stage 3 synthesis — model chain handled in engine (no grounding)."""
    model = await model_state.get_synthesis_model()
    return await engine.synthesize_harvest_property_async(
        address,
        research,
        market_city,
        model=model,
        user_id=admin_user_id,
        rate_limiter=rate_limiter,
        session=session,
        geospatial=geospatial,
    )


async def _synthesize_listing(
    job: _SynthesisJob,
    admin_user_id: str,
    report: dict[str, Any],
    report_lock: asyncio.Lock,
    model_state: _HarvesterModelState,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
    *,
    geospatial_budget: engine.GroundingRpdBudget | None = None,
) -> None:
    """Stage 3 + finance + quantum + KB save for one property."""
    address = job.address
    market_city = job.market_city
    print(f"  [synthesis] START {address} ({market_city})")

    geospatial = dict(job.geospatial or {})
    if not engine._has_precise_coordinates(
        geospatial.get("latitude"),
        geospatial.get("longitude"),
    ):
        cached = engine.geospatial_from_cached_coords(job.research)
        if cached is not None:
            geospatial = cached
            print(
                f"  [geocode] REUSE {address} — research/discovery coordinates "
                f"({geospatial['latitude']:.5f}, {geospatial['longitude']:.5f})"
            )
        else:
            print(
                f"  [geocode] RETRY {address} — {engine.COORDINATE_MODEL} "
                "(parallel agent missed coords)"
            )
            geospatial = await engine.run_geospatial_enrichment_async(
                address,
                market_city=market_city,
                model=engine.COORDINATE_MODEL,
                budget=geospatial_budget,
                rate_limiter=rate_limiter,
                session=session,
            )
    enriched_research = dict(job.research)
    if geospatial.get("environmental_risk"):
        enriched_research["environmental_risk"] = geospatial["environmental_risk"]
    if engine._has_precise_coordinates(
        geospatial.get("latitude"),
        geospatial.get("longitude"),
    ):
        enriched_research["latitude"] = geospatial["latitude"]
        enriched_research["longitude"] = geospatial["longitude"]
        print(
            f"  [synthesis] coords {address} — "
            f"{geospatial['latitude']:.5f}, {geospatial['longitude']:.5f} "
            f"({geospatial.get('geocode_source', 'unknown')})"
        )
    else:
        print(f"  [synthesis] coords {address} — unresolved")

    final_data = await _synthesize_harvest_property_with_fallback(
        address,
        enriched_research,
        market_city,
        admin_user_id,
        model_state,
        rate_limiter,
        session,
        geospatial=geospatial,
    )
    async with report_lock:
        report["synthesized"] += 1

    cash_flow = await asyncio.to_thread(headless_cash_flow, final_data)
    quantum = await asyncio.to_thread(
        engine.run_harvest_quantum, final_data, cash_flow
    )
    final_data["monthly_net_cash_flow"] = cash_flow

    unreliable_reason = one_year_roi_unreliable_reason(
        final_data,
        down_payment_pct=INVESTMENT_PARAMS["down_payment"],
        closing_costs_pct=INVESTMENT_PARAMS["closing_costs_pct"],
        interest_rate=INVESTMENT_PARAMS["interest_rate"],
        loan_term=int(INVESTMENT_PARAMS["loan_term"]),
    )
    if unreliable_reason:
        await asyncio.to_thread(delete_unreliable_property, final_data)
        async with report_lock:
            report.setdefault("unreliable_deleted", []).append(
                {"address": address, "reason": unreliable_reason}
            )
        log.warning(
            "listing_unreliable_foreclosure",
            address=address,
            reason=unreliable_reason,
        )
        print(f"  [synthesis] UNRELIABLE {address} — {unreliable_reason} (deleted)")
        return

    final_data = await asyncio.to_thread(
        engine.backfill_year_built_if_needed, final_data, address
    )

    save_result = await asyncio.to_thread(
        save_harvest_property, final_data, user_id=admin_user_id
    )
    if save_result is None:
        raise RuntimeError("Failed to save property to Supabase")

    comps_saved = isinstance(final_data.get("comps_analysis"), dict) and bool(
        final_data["comps_analysis"].get("comparable_properties")
    )
    if comps_saved:
        print(f"  [property_value] SAVED comps for {address}")

    async with report_lock:
        report["saved"].append(address)
        bucket = market_city.lower()
        if bucket in report:
            report[bucket].append(
                {"address": address, "quantum": quantum, "cash_flow": cash_flow}
            )

    log.info(
        "listing_saved",
        address=address,
        quantum=round(quantum, 1),
        cash_flow=round(cash_flow, 2),
    )
    print(
        f"  [synthesis] SAVED {address} — "
        f"Quantum: {quantum:.1f}% | Cash Flow: ${cash_flow:,.2f}"
    )


async def _run_synthesis_safe(
    job: _SynthesisJob,
    admin_user_id: str,
    report: dict[str, Any],
    report_lock: asyncio.Lock,
    model_state: _HarvesterModelState,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
    *,
    geospatial_budget: engine.GroundingRpdBudget | None = None,
) -> None:
    """Stage 3 wrapper that records synthesis failures in the harvest report."""
    try:
        await _synthesize_listing(
            job,
            admin_user_id,
            report,
            report_lock,
            model_state,
            rate_limiter,
            session,
            geospatial_budget=geospatial_budget,
        )
    except Exception as exc:
        if isinstance(exc, KeyboardInterrupt):
            raise
        report_error(log, "listing_synthesis_failed", exc, address=job.address)
        print(f"  [synthesis] FAILED {job.address} — {exc}")
        async with report_lock:
            report["failed"].append({"address": job.address, "error": str(exc)})


async def _research_and_schedule_synthesis(
    listing: dict[str, Any],
    admin_user_id: str,
    report: dict[str, Any],
    report_lock: asyncio.Lock,
    model_state: _HarvesterModelState,
    rate_limiter: engine.ModelRateLimiter,
    session: engine.GenaiSession,
    synthesis_tasks: list[asyncio.Task[None]],
    *,
    research_semaphore: asyncio.Semaphore,
    geospatial_budget: engine.GroundingRpdBudget | None = None,
) -> None:
    """Run research for one listing; start synthesis immediately when it passes filters."""
    address = str(listing.get("address", "")).strip() or "(missing address)"
    async with research_semaphore:
        try:
            job = await _research_listing(
                listing,
                admin_user_id,
                report,
                report_lock,
                model_state,
                rate_limiter,
                session,
                geospatial_budget=geospatial_budget,
            )
        except Exception as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            report_error(log, "listing_research_failed", exc, address=address)
            print(f"  [research] FAILED {address} — {exc}")
            async with report_lock:
                report["failed"].append({"address": address, "error": str(exc)})
            return

        if job is None:
            return

        synthesis_tasks.append(
            asyncio.create_task(
                _run_synthesis_safe(
                    job,
                    admin_user_id,
                    report,
                    report_lock,
                    model_state,
                    rate_limiter,
                    session,
                    geospatial_budget=geospatial_budget,
                ),
                name=f"synthesis:{job.address}",
            )
        )


async def run_harvester_pipeline_async(admin_user_id: str) -> dict[str, Any]:
    """
    Execute the full accuracy workflow harvester once per run.
    """
    global _active_discovery_model, _active_research_model, _active_synthesis_model
    discovery_backend = resolve_discovery_backend()
    _active_discovery_model = (
        "scraper" if discovery_backend == "scraper" else engine.DISCOVERY_MODEL
    )
    _active_research_model = engine.RESEARCH_MODEL
    _active_synthesis_model = engine.SYNTHESIS_MODEL

    report: dict[str, Any] = {
        "discovered": 0,
        "researched": 0,
        "property_valued": 0,
        "synthesized": 0,
        "skipped": [],
        "already_scanned": [],
        "failed": [],
        "saved": [],
        "unreliable_deleted": [],
        **{name.lower(): [] for name, _, _ in engine.HOT_MARKETS},
    }

    purged = await asyncio.to_thread(purge_unreliable_one_year_roi_properties)
    if purged:
        from portfolio_geo import invalidate_portfolio_cache

        invalidate_portfolio_cache()
        print(
            f"Purged {len(purged)} unreliable properties "
            f"(1-year ROI > 100%, likely foreclosures)."
        )
        for entry in purged[:5]:
            print(f"  - {entry['address']}")
        if len(purged) > 5:
            print(f"  - ... and {len(purged) - 5} more")
        log.info("harvest_unreliable_purge_complete", purged=len(purged))

    archived = await asyncio.to_thread(archive_stale_properties)
    if archived:
        from portfolio_geo import invalidate_portfolio_cache

        invalidate_portfolio_cache()
        print(
            f"Archived {archived} properties older than 30 days "
            "(moved to archived_properties)."
        )
        log.info("harvest_archive_stale_complete", archived=archived)
        report["archived"] = archived

    complete_keys = get_harvest_complete_addresses(admin_user_id)
    scanned_keys = set(complete_keys)
    kb_raw = get_kb_raw_data(admin_user_id)
    scanned_addresses = sorted(
        str(row.get("address", "")).strip()
        for key, row in kb_raw.items()
        if key in scanned_keys and str(row.get("address", "")).strip()
    )
    if complete_keys:
        print(
            f"Skipping {len(complete_keys)} addresses with complete harvest data "
            "(year_built present)."
        )

    session = engine.create_genai_session()
    rate_limiter = engine.ModelRateLimiter(requests_per_minute=engine.HARVESTER_RPM_PER_MODEL)
    geospatial_budget = engine.GroundingRpdBudget()
    report_lock = asyncio.Lock()
    model_state = _HarvesterModelState(synthesis_model=engine.SYNTHESIS_MODEL)
    synthesis_tasks: list[asyncio.Task[None]] = []
    research_tasks: list[asyncio.Task[None]] = []
    research_semaphore = asyncio.Semaphore(engine.MAX_CONCURRENT_RESEARCH_AGENTS)

    print("=" * 60)
    print("ACCURACY WORKFLOW - discovery -> research -> property value -> synthesis")
    print("=" * 60)

    print(
        f"[discovery] Stage 1 START — "
        f"{'live multi-portal search (Redfin, Realtor, Zillow)' if discovery_backend == 'scraper' else 'hot-market LLM search'} "
        f"(Supabase KB skip list; ≤{engine.MAX_DISCOVERY_LISTINGS} listings under "
        f"${engine.MAX_DISCOVERY_PRICE:,})...",
        flush=True,
    )

    if discovery_backend == "scraper":
        listings = await run_scraper_discovery_async(
            admin_user_id=admin_user_id,
            exclude_addresses=scanned_addresses,
            enrich=True,
            persist=False,
        )
        if not listings:
            print(
                "[discovery] Scraper returned 0 listings (portal 403/bot blocks are common). "
                "Falling back to Gemini hot-market search...",
                flush=True,
            )
            listings = await asyncio.to_thread(
                lambda: engine.discover_hot_market_listings(
                    exclude_addresses=scanned_addresses,
                )
            )
            if listings:
                used_model = str(listings[0].get("discovery_model", "")).strip()
                if used_model:
                    _active_discovery_model = used_model
    else:

        def _run_discovery() -> list[dict[str, Any]]:
            return engine.discover_hot_market_listings(
                exclude_addresses=scanned_addresses,
            )

        listings = await asyncio.to_thread(_run_discovery)
        if listings:
            used_model = str(listings[0].get("discovery_model", "")).strip()
            if used_model:
                _active_discovery_model = used_model
    if scanned_keys:
        listings = [
            listing
            for listing in listings
            if normalize_address_key(str(listing.get("address", ""))) not in scanned_keys
        ]
    report["discovered"] = len(listings)
    print(
        f"[discovery] Stage 1 DONE — {len(listings)} new listings under "
        f"${engine.MAX_DISCOVERY_PRICE:,} (model: {_active_discovery_model})",
        flush=True,
    )

    if not listings:
        if discovery_backend == "scraper":
            if complete_keys:
                print(
                    "No new listings to harvest — live search found only addresses "
                    f"already in Supabase ({len(complete_keys)} complete)."
                )
            else:
                print(
                    "Live scraper search returned no listings under the price cap. Exiting."
                )
        else:
            print("No listings discovered. Exiting.")
        return report

    print(
        f"[research] Stage 2 START — {len(listings)} listings via "
        f"{engine.RESEARCH_MODEL} "
        f"(max {engine.MAX_CONCURRENT_RESEARCH_AGENTS} concurrent workers)...",
        flush=True,
    )
    for listing in listings:
        address = str(listing.get("address", "")).strip() or "(missing address)"
        research_tasks.append(
            asyncio.create_task(
                _research_and_schedule_synthesis(
                    listing,
                    admin_user_id,
                    report,
                    report_lock,
                    model_state,
                    rate_limiter,
                    session,
                    synthesis_tasks,
                    research_semaphore=research_semaphore,
                    geospatial_budget=geospatial_budget,
                ),
                name=f"research:{address}",
            )
        )
    await asyncio.gather(*research_tasks)
    print(
        f"[research] Stage 2 DONE — researched {report['researched']}, "
        f"skipped {len(report['skipped'])}, "
        f"already scanned {len(report['already_scanned'])}",
        flush=True,
    )

    if synthesis_tasks:
        await asyncio.gather(*synthesis_tasks)

    print("\n" + "=" * 60)
    print("HARVEST COMPLETE")
    print(
        f"Discovered: {report['discovered']} | "
        f"Researched: {report['researched']} | "
        f"Property valued: {report.get('property_valued', 0)} | "
        f"Synthesized: {report['synthesized']} | "
        f"Skipped: {len(report['skipped'])} | "
        f"Already scanned: {len(report['already_scanned'])} | "
        f"Unreliable deleted: {len(report['unreliable_deleted'])} | "
        f"Failed: {len(report['failed'])}"
    )
    log.info(
        "harvest_complete",
        discovered=report["discovered"],
        researched=report["researched"],
        synthesized=report["synthesized"],
        skipped=len(report["skipped"]),
        already_scanned=len(report["already_scanned"]),
        unreliable_deleted=len(report["unreliable_deleted"]),
        failed=len(report["failed"]),
        saved=len(report["saved"]),
    )
    return report


def run_harvester_pipeline(admin_user_id: str) -> dict[str, Any]:
    """Sync entry point for the CLI harvester."""
    return asyncio.run(run_harvester_pipeline_async(admin_user_id))


def _configure_stdio() -> None:
    """Avoid Windows cp1252 crashes when logging non-ASCII text."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _print_harvest_exit_summary(report: dict[str, Any]) -> None:
    """CLI footer — distinguish zero-save runs from successful harvests."""
    saved_count = len(report.get("saved", []))
    if saved_count > 0:
        print(f"Harvester finished successfully. Saved {saved_count} properties.", flush=True)
        return

    skipped = len(report.get("skipped", []))
    already = len(report.get("already_scanned", []))
    failed = len(report.get("failed", []))
    unreliable = len(report.get("unreliable_deleted", []))
    discovered = int(report.get("discovered", 0))

    print("Harvester finished with 0 properties saved.", flush=True)
    if discovered == 0:
        print(
            "  Discovery found no new listings (all markets already in Supabase or search empty).",
            flush=True,
        )
    else:
        print(
            f"  Discovery: {discovered} | Skipped: {skipped} | "
            f"Already in KB: {already} | Unreliable: {unreliable} | Failed: {failed}",
            flush=True,
        )
        print(
            "  Tip: listings already in Supabase with year_built are skipped automatically.",
            flush=True,
        )


def main() -> None:
    _configure_stdio()
    print("Harvester starting (headless CLI)...", flush=True)
    try:
        admin_user_id = require_harvest_config()
        report = run_harvester_pipeline(admin_user_id)
        _print_harvest_exit_summary(report)
    except SystemExit:
        raise
    except Exception as exc:
        report_error(log, "harvest_fatal", exc)
        print(f"Harvester failed: {exc}", flush=True)
        raise


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        raise SystemExit(exc.code) from exc
