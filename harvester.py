# harvester.py — 3-Stage Hot Market Harvester (Rochester + Syracuse)
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from google.genai import errors

import engine
from finance import analyze_investment
from knowledge_base import get_admin_uid, get_market_pulse, save_harvest_property

LOG_FILE = "failed_addresses.log"
INVESTMENT_PARAMS = {
    "down_payment": 25.0,
    "interest_rate": 6.0,
    "loan_term": 30,
    "closing_costs_pct": 3.0,
}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def execute_with_backoff(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Delegates to engine retry; 60s backoff on 429."""
    retries = 0
    while retries < engine.MAX_API_RETRIES:
        try:
            return func(*args, **kwargs)
        except errors.ClientError as e:
            if e.code == 429:
                print(
                    f"429 rate limit. Backing off {engine.RATE_LIMIT_BACKOFF_SEC}s..."
                )
                time.sleep(engine.RATE_LIMIT_BACKOFF_SEC)
                retries += 1
            else:
                raise
    raise RuntimeError("Max retries exceeded for API rate limits.")


def headless_cash_flow(property_data: dict[str, Any]) -> float:
    """Monthly net cash flow using centralized finance module."""
    analysis = analyze_investment(
        price=float(property_data.get("price", 0)),
        down_payment_pct=INVESTMENT_PARAMS["down_payment"],
        interest_rate=INVESTMENT_PARAMS["interest_rate"],
        loan_term=int(INVESTMENT_PARAMS["loan_term"]),
        closing_costs_pct=INVESTMENT_PARAMS["closing_costs_pct"],
        tax_rate=float(property_data.get("tax_rate", 0)),
        monthly_insurance=float(property_data.get("insurance", 0)),
        monthly_hoa=float(property_data.get("hoa", 0)),
        maint_percent=float(property_data.get("maint_percent", 4)),
        monthly_rent=float(property_data.get("rent", 0)),
        vacancy_reserve_pct=float(property_data.get("ai_vacancy_rate", 5)),
        management_fee_pct=float(property_data.get("ai_management_fee", 10)),
    )
    return analysis["monthly_net_cash_flow"]


def _load_local_secrets() -> None:
    """Load .streamlit/secrets.toml into os.environ for headless CLI runs."""
    secrets_path = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        return
    try:
        import tomllib

        with secrets_path.open("rb") as f:
            for key, value in tomllib.load(f).items():
                if isinstance(value, str) and not os.getenv(key):
                    os.environ[key] = value
    except Exception as exc:
        print(f"Note: Could not load secrets.toml ({exc}). Use environment variables.")


def require_harvest_config() -> str:
    """Validate API keys and return admin user_id for attributed saves."""
    _load_local_secrets()

    missing = [
        name
        for name in ("GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_KEY", "ADMIN_USER_ID")
        if not os.getenv(name) and not _secret_fallback(name)
    ]
    if missing:
        print(
            "Missing required configuration: "
            + ", ".join(missing)
            + "\nAdd them to .streamlit/secrets.toml or set as environment variables."
        )
        sys.exit(1)

    admin_uid = get_admin_uid()
    if not admin_uid:
        print(
            "ADMIN_USER_ID is not set.\n"
            "1. Supabase Dashboard → Authentication → Users → copy your User UID\n"
            "2. Add to .streamlit/secrets.toml: ADMIN_USER_ID = \"your-uuid-here\""
        )
        sys.exit(1)

    print(f"Harvest saves will use admin user_id: {admin_uid}")
    return admin_uid


def _secret_fallback(name: str) -> str | None:
    """Read a secret from Streamlit when running under streamlit run harvester.py."""
    try:
        import streamlit as st

        return st.secrets.get(name)
    except Exception:
        return None


def run_harvester_pipeline(admin_user_id: str) -> dict[str, Any]:
    """
    Execute the full 3-stage harvester once per run.

    Stage 1: Single grounded discovery (gemini-2.5-flash) — 20 RPD max.
    Stage 2: Per-address research (gemma-4-31b-it).
    Stage 3: Synthesis + quantum + KB save (gemini-3.1-flash-lite-preview).
    """
    report: dict[str, Any] = {
        "discovered": 0,
        "researched": 0,
        "synthesized": 0,
        "skipped": [],
        "failed": [],
        "saved": [],
        "rochester": [],
        "syracuse": [],
    }

    print("=" * 60)
    print("STAGE 1 — Discovery (single Search Grounding call)")
    print("=" * 60)
    listings = execute_with_backoff(engine.discover_hot_market_listings)
    report["discovered"] = len(listings)
    print(f"Found {len(listings)} listings under ${engine.MAX_DISCOVERY_PRICE:,}")

    if not listings:
        print("No listings discovered. Exiting.")
        return report

    for idx, listing in enumerate(listings):
        address = listing["address"]
        market_city = listing["city"]
        print(f"\n[{idx + 1}/{len(listings)}] {address} ({market_city})")

        try:
            print("  STAGE 2 — Research (gemma)")
            research = execute_with_backoff(engine.research_property, address)
            report["researched"] += 1

            if engine.should_skip_synthesis(research):
                reason = (
                    "Poor condition"
                    if str(research.get("property_condition", "")).lower() == "poor"
                    else f"Price > ${engine.MAX_SYNTHESIS_PRICE:,}"
                )
                print(f"  SKIP Stage 3 — {reason}")
                report["skipped"].append({"address": address, "reason": reason})
                continue

            print("  STAGE 3 — Synthesis + Quantum")
            final_data = execute_with_backoff(
                engine.synthesize_harvest_property, address, research, market_city
            )
            report["synthesized"] += 1

            cash_flow = headless_cash_flow(final_data)
            quantum = engine.run_harvest_quantum(final_data, cash_flow)
            final_data["monthly_net_cash_flow"] = cash_flow

            save_harvest_property(final_data, user_id=admin_user_id)
            report["saved"].append(address)
            bucket = market_city.lower()
            if bucket in report:
                report[bucket].append(
                    {"address": address, "quantum": quantum, "cash_flow": cash_flow}
                )

            print(f"  Saved — Quantum: {quantum:.1f}% | Cash Flow: ${cash_flow:,.2f}")

        except Exception as e:
            print(f"  FAILED — {e}")
            report["failed"].append({"address": address, "error": str(e)})
            logging.error("Address: %s | Error: %s", address, e)

    print("\n" + "=" * 60)
    print("HARVEST COMPLETE")
    print(
        f"Discovered: {report['discovered']} | "
        f"Researched: {report['researched']} | "
        f"Synthesized: {report['synthesized']} | "
        f"Skipped: {len(report['skipped'])} | "
        f"Failed: {len(report['failed'])}"
    )
    return report


def main() -> None:
    admin_user_id = require_harvest_config()
    run_harvester_pipeline(admin_user_id)


# ---------------------------------------------------------------------------
# Streamlit control panel (streamlit run harvester.py)
# ---------------------------------------------------------------------------

def _render_streamlit_app() -> None:
    import streamlit as st
    from market_pulse import render_market_pulse

    st.set_page_config(page_title="Hot Market Harvester", page_icon="🌾")
    st.title("🌾 Upstate NY Hot Market Harvester")
    st.caption(
        "Rochester & Syracuse • Stage 1: 1× grounded discovery • "
        "Stage 2: Gemma research • Stage 3: Synthesis + Quantum"
    )

    render_market_pulse()
    st.divider()

    try:
        admin_user_id = require_harvest_config()
        st.caption(f"Saving as admin: `{admin_user_id[:8]}...`")
    except SystemExit:
        st.error(
            "Set GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY, and ADMIN_USER_ID in "
            ".streamlit/secrets.toml or environment variables."
        )
        st.stop()

    col1, col2, col3 = st.columns(3)
    col1.metric("Discovery Model", engine.DISCOVERY_MODEL)
    col2.metric("Research Model", engine.RESEARCH_MODEL)
    col3.metric("Synthesis Model", engine.SYNTHESIS_MODEL)

    st.info(
        f"Stage 1 uses **one** Search Grounding call (≤20 listings under "
        f"${engine.MAX_DISCOVERY_PRICE:,}). Stage 3 skips Poor condition or "
        f"price > ${engine.MAX_SYNTHESIS_PRICE:,}."
    )

    if st.button("🚀 Run Full Harvest", type="primary"):
        with st.status("Running 3-stage harvest...", expanded=True) as status:
            report = run_harvester_pipeline(admin_user_id)
            status.update(label="Harvest complete", state="complete")

        st.success(
            f"Saved {len(report['saved'])} properties "
            f"({len(report['rochester'])} Rochester, {len(report['syracuse'])} Syracuse)"
        )

        if report["skipped"]:
            with st.expander(f"Skipped ({len(report['skipped'])})"):
                st.dataframe(report["skipped"], use_container_width=True)
        if report["failed"]:
            with st.expander(f"Failed ({len(report['failed'])})"):
                st.dataframe(report["failed"], use_container_width=True)

        st.rerun()

    with st.expander("Raw Market Pulse Data"):
        st.json(get_market_pulse())


def _running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


if __name__ == "__main__":
    if _running_under_streamlit():
        _render_streamlit_app()
    else:
        main()
