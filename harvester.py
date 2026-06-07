# harvester.py — 3-Stage Hot Market Harvester (multi-market discovery)
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from google.genai import errors

import engine
from app_logging import configure_logging, report_error
from finance import analyze_investment
from knowledge_base import (
    get_admin_uid,
    get_market_pulse,
    get_scanned_addresses,
    is_property_already_scanned,
    normalize_address_key,
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
_active_synthesis_model = engine.SYNTHESIS_MODEL

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


def _parse_secrets_toml(path: Path) -> dict[str, Any]:
    """Parse secrets.toml on Python 3.11+ (tomllib) or older (tomli)."""
    with path.open("rb") as secrets_file:
        try:
            import tomllib

            return tomllib.load(secrets_file)
        except ImportError:
            import tomli

            return tomli.load(secrets_file)


def _load_local_secrets() -> None:
    """Load .streamlit/secrets.toml into os.environ for headless CLI runs."""
    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        log.info("secrets_toml_missing", path=str(secrets_path))
        return

    try:
        secrets = _parse_secrets_toml(secrets_path)
    except Exception as exc:
        log.error("secrets_toml_parse_failed", path=str(secrets_path), error=str(exc))
        print(f"Warning: could not parse {secrets_path}: {exc}")
        return

    for key, value in secrets.items():
        if os.getenv(key):
            continue
        if isinstance(value, str):
            os.environ[key] = value
        elif isinstance(value, (int, float, bool)):
            os.environ[key] = str(value)


def _secret_from_env_or_streamlit(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    if os.environ.get("STREAMLIT_RUNTIME_ENV"):
        import streamlit as st

        secret = st.secrets.get(name)
        return str(secret) if secret is not None else None
    return None


def validate_harvest_config() -> str | None:
    """Validate API keys and return admin user_id, or None if configuration is incomplete."""
    _load_local_secrets()

    missing = [
        name
        for name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "ADMIN_USER_ID")
        if not _secret_from_env_or_streamlit(name)
    ]
    if missing:
        log.error("harvest_config_missing", missing=missing)
        print(
            "Missing required configuration: "
            + ", ".join(missing)
            + "\nAdd them to .streamlit/secrets.toml or set as environment variables."
        )
        return None

    admin_uid = get_admin_uid()
    if not admin_uid:
        raw_admin = _secret_from_env_or_streamlit("ADMIN_USER_ID") or ""
        log.error("harvest_admin_uid_invalid", admin_user_id=raw_admin)
        print(
            "ADMIN_USER_ID is missing or not a valid UUID.\n"
            "1. Supabase Dashboard -> Authentication -> Users -> copy your User UID\n"
            "2. Add to .streamlit/secrets.toml: ADMIN_USER_ID = \"your-uuid-here\"\n"
            "   Watch for typos: letter 'l' vs digit '1', letter 'O' vs zero '0'.\n"
            f"   Current value: {raw_admin!r}"
        )
        return None

    from authenticate import get_service_client

    if get_service_client() is None:
        log.error("harvest_service_role_missing")
        print(
            "SUPABASE_SERVICE_ROLE_KEY is required for headless harvest.\n"
            "RLS blocks the anon key when no user session is present.\n"
            "Supabase Dashboard -> Project Settings -> API -> service_role (secret)\n"
            "Add to .streamlit/secrets.toml:\n"
            "  SUPABASE_SERVICE_ROLE_KEY = \"your-service-role-key\"\n"
            "Keep SUPABASE_KEY as the anon/public key for the Streamlit app."
        )
        return None

    log.info("harvest_config_ready", admin_user_id=admin_uid[:8] + "...")
    print(f"Harvest saves will use admin user_id: {admin_uid}")
    return admin_uid


def require_harvest_config() -> str:
    """CLI entry: exit process when harvest configuration is invalid."""
    admin_uid = validate_harvest_config()
    if not admin_uid:
        sys.exit(1)
    return admin_uid


def _process_listing(
    listing: dict[str, Any],
    admin_user_id: str,
    report: dict[str, Any],
) -> None:
    """Run stages 2-3 for one listing; record outcome in report."""
    address = str(listing.get("address", "")).strip()
    market_city = str(listing.get("city", "")).strip()
    if not address:
        raise ValueError("Listing is missing a valid address")
    if market_city not in engine.DISCOVERY_MARKET_KEYS:
        raise ValueError(f"Listing has unsupported market city: {market_city!r}")

    if is_property_already_scanned(address, user_id=admin_user_id):
        print("  SKIP - Already scanned (in knowledge base)")
        report["already_scanned"].append({"address": address, "reason": "Already in KB"})
        log.info("listing_already_scanned", address=address)
        return

    log.info("listing_start", address=address, market_city=market_city)
    print("  STAGE 2 - Research (gemma)")
    research = execute_with_backoff(engine.research_property, address)
    report["researched"] += 1

    skip_reason = engine.synthesis_skip_reason(research)
    if skip_reason:
        print(f"  SKIP Stage 3 - {skip_reason}")
        report["skipped"].append({"address": address, "reason": skip_reason})
        log.info("listing_skipped", address=address, reason=skip_reason)
        return

    print("  STAGE 3 - Synthesis + Quantum")
    final_data = execute_with_rpd_fallback(
        engine.synthesize_harvest_property,
        address,
        research,
        market_city,
        stage="synthesis",
        fallback_model=engine.SYNTHESIS_FALLBACK_MODEL,
        model=_active_synthesis_model,
        user_id=admin_user_id,
    )
    report["synthesized"] += 1

    cash_flow = headless_cash_flow(final_data)
    quantum = engine.run_harvest_quantum(final_data, cash_flow)
    final_data["monthly_net_cash_flow"] = cash_flow

    save_result = save_harvest_property(final_data, user_id=admin_user_id)
    if save_result is None:
        raise RuntimeError("Failed to save property to Supabase")
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
    print(f"  Saved - Quantum: {quantum:.1f}% | Cash Flow: ${cash_flow:,.2f}")


def run_harvester_pipeline(admin_user_id: str) -> dict[str, Any]:
    """
    Execute the full 3-stage harvester once per run.

    Stage 1: Single grounded discovery (gemini-2.5-flash) — up to 25 listings per run.
    Stage 2: Per-address research (gemma-4-31b-it).
    Stage 3: Synthesis + quantum + KB save (gemini-3.1-flash-lite-preview).

    On daily quota exhaustion, discovery and synthesis switch to their
    configured fallback models for the remainder of the run.
    """
    global _active_discovery_model, _active_synthesis_model
    _active_discovery_model = engine.DISCOVERY_MODEL
    _active_synthesis_model = engine.SYNTHESIS_MODEL

    report: dict[str, Any] = {
        "discovered": 0,
        "researched": 0,
        "synthesized": 0,
        "skipped": [],
        "already_scanned": [],
        "failed": [],
        "saved": [],
        **{name.lower(): [] for name, _, _ in engine.HOT_MARKETS},
    }

    scanned_addresses = sorted(get_scanned_addresses(admin_user_id))
    if scanned_addresses:
        print(f"Skipping {len(scanned_addresses)} addresses already in the knowledge base.")

    print("=" * 60)
    print("STAGE 1 - Discovery (single Search Grounding call)")
    print("=" * 60)
    listings = execute_with_rpd_fallback(
        engine.discover_hot_market_listings,
        stage="discovery",
        fallback_model=engine.DISCOVERY_FALLBACK_MODEL,
        exclude_addresses=scanned_addresses,
    )
    if scanned_addresses:
        scanned_keys = {normalize_address_key(addr) for addr in scanned_addresses}
        listings = [
            listing
            for listing in listings
            if normalize_address_key(str(listing.get("address", ""))) not in scanned_keys
        ]
    report["discovered"] = len(listings)
    print(f"Found {len(listings)} listings under ${engine.MAX_DISCOVERY_PRICE:,}")

    if not listings:
        print("No listings discovered. Exiting.")
        print(
            "Tip: 503/empty grounded responses are usually transient. "
            "Pull latest code and rerun; discovery now retries per market "
            "and falls back to the Gemma discovery model automatically."
        )
        return report

    for idx, listing in enumerate(listings):
        address = str(listing.get("address", "")).strip()
        market_city = str(listing.get("city", "")).strip()
        print(f"\n[{idx + 1}/{len(listings)}] {address or '(missing address)'} ({market_city})")

        try:
            _process_listing(listing, admin_user_id, report)
        except Exception as exc:
            if isinstance(exc, KeyboardInterrupt):
                raise
            report_error(log, "listing_failed", exc, address=address)
            print(f"  FAILED - {exc}")
            report["failed"].append({"address": address, "error": str(exc)})

    print("\n" + "=" * 60)
    print("HARVEST COMPLETE")
    print(
        f"Discovered: {report['discovered']} | "
        f"Researched: {report['researched']} | "
        f"Synthesized: {report['synthesized']} | "
        f"Skipped: {len(report['skipped'])} | "
        f"Already scanned: {len(report['already_scanned'])} | "
        f"Failed: {len(report['failed'])}"
    )
    log.info(
        "harvest_complete",
        discovered=report["discovered"],
        researched=report["researched"],
        synthesized=report["synthesized"],
        skipped=len(report["skipped"]),
        already_scanned=len(report["already_scanned"]),
        failed=len(report["failed"]),
        saved=len(report["saved"]),
    )
    return report


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


def main() -> None:
    _configure_stdio()
    admin_user_id = require_harvest_config()
    run_harvester_pipeline(admin_user_id)


# ---------------------------------------------------------------------------
# Streamlit control panel (streamlit run harvester.py)
# ---------------------------------------------------------------------------

def _render_streamlit_app() -> None:
    import streamlit as st
    from market_pulse import render_market_pulse

    st.set_page_config(page_title="Hot Market Harvester", page_icon="🌾")
    st.title("🌾 Hot Market Harvester")
    st.caption(
        "Upstate NY (priority) → Charlotte, Raleigh, Charleston, Ohio, DFW, Austin • "
        "Stage 1: grounded discovery • Stage 2: Gemma research • Stage 3: Synthesis + Quantum"
    )

    render_market_pulse()
    st.divider()

    admin_user_id = validate_harvest_config()
    if not admin_user_id:
        st.error(
            "Set GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, and ADMIN_USER_ID in "
            ".streamlit/secrets.toml or environment variables."
        )
        st.stop()

    st.caption(f"Saving as admin: `{admin_user_id[:8]}...`")

    col1, col2, col3 = st.columns(3)
    col1.metric("Discovery Model", _active_discovery_model)
    col2.metric("Research Model", engine.RESEARCH_MODEL)
    col3.metric("Synthesis Model", _active_synthesis_model)

    st.info(
        f"Stage 1 uses Search Grounding (≤{engine.MAX_DISCOVERY_LISTINGS} listings under "
        f"${engine.MAX_DISCOVERY_PRICE:,}, suburbs included). Stage 3 skips Poor condition or "
        f"price > ${engine.MAX_SYNTHESIS_PRICE:,}."
    )

    if st.button("🚀 Run Full Harvest", type="primary"):
        with st.status("Running 3-stage harvest...", expanded=True) as status:
            report = run_harvester_pipeline(admin_user_id)
            status.update(label="Harvest complete", state="complete")

        market_summary = ", ".join(
            f"{len(report[name.lower()])} {name}"
            for name, _, _ in engine.HOT_MARKETS
            if report.get(name.lower())
        )
        st.success(
            f"Saved {len(report['saved'])} properties"
            + (f" ({market_summary})" if market_summary else "")
        )

        if report["skipped"]:
            with st.expander(f"Skipped ({len(report['skipped'])})"):
                st.dataframe(report["skipped"], use_container_width=True)
        if report["already_scanned"]:
            with st.expander(f"Already scanned ({len(report['already_scanned'])})"):
                st.dataframe(report["already_scanned"], use_container_width=True)
        if report["failed"]:
            with st.expander(f"Failed ({len(report['failed'])})"):
                st.dataframe(report["failed"], use_container_width=True)

        st.rerun()

    with st.expander("Raw Market Pulse Data"):
        st.json(get_market_pulse())


def _running_under_streamlit() -> bool:
    return bool(os.environ.get("STREAMLIT_RUNTIME_ENV"))


if __name__ == "__main__":
    if _running_under_streamlit():
        _render_streamlit_app()
    else:
        main()
