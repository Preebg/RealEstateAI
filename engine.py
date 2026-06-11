from __future__ import annotations

import asyncio
import contextvars
import json
import os
import random
import re
import threading
import time
from collections.abc import Callable
from functools import lru_cache
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from google import genai
from google.genai import errors, types
from app_logging import get_logger
from finance import (
    calculate_10yr_appreciation,
    normalize_monthly_insurance,
    normalize_percent_rate,
    normalize_tax_rate_percent,
)
from comps_analysis import (
    apply_comp_implied_market_value,
    ensure_comps_analysis_field,
    evaluate_comps_against_subject,
    normalize_comps_payload,
)
from rent_comps_analysis import (
    apply_rent_comps_adjustment,
    evaluate_rent_comps_against_subject,
    normalize_rent_comps_payload,
)
from data_provenance import attach_data_provenance
from knowledge_base import get_kb_context, lookup_property
from quantum_portfolio import (
    ALIGNMENT_SCORE_KEYS,
    PortfolioInputs,
    score_portfolio,
)

_log = get_logger("engine")

# --- Model routing (harvester + underwriter) ---
DISCOVERY_MODEL = "gemini-2.5-flash"
DISCOVERY_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash-lite",
    "gemma-4-26b-a4b-it",
)
DISCOVERY_MODEL_CHAIN: tuple[str, ...] = (
    DISCOVERY_MODEL,
    *DISCOVERY_FALLBACK_MODELS,
)
# Legacy label → hosted API slug.
_MODEL_API_SLUGS: dict[str, str] = {
    "gemma-4-21b-it": "gemma-4-26b-a4b-it",
    "gemma-4-a4b-26b": "gemma-4-26b-a4b-it",
}
# Backward-compatible alias for tests and harvester UI.
DISCOVERY_FALLBACK_MODEL = DISCOVERY_FALLBACK_MODELS[-1]
RESEARCH_MODEL = "gemma-4-31b-it"
SYNTHESIS_MODEL = "gemini-3.1-flash-lite-preview"
SYNTHESIS_FALLBACK_MODELS: tuple[str, ...] = (
    "gemini-3.5-flash",
    "gemma-4-26b-a4b-it",
)
SYNTHESIS_MODEL_CHAIN: tuple[str, ...] = (
    SYNTHESIS_MODEL,
    *SYNTHESIS_FALLBACK_MODELS,
)
# Backward-compatible alias for harvester RPD fallback.
SYNTHESIS_FALLBACK_MODEL = SYNTHESIS_FALLBACK_MODELS[-1]

# Accuracy workflow: discovery Maps tiers, property value, coordinate catch.
MAPS_GROUNDED_DISCOVERY_MODELS: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
PROPERTY_VALUE_MODEL = "gemma-4-26b-a4b-it"
PROPERTY_VALUE_TRIGGERED_MODEL = "gemma-4-31b-it"
COORDINATE_CATCH_MODEL = SYNTHESIS_MODEL
ACCURACY_WORKFLOW_MODEL_CHAIN: tuple[str, ...] = (
    *DISCOVERY_MODEL_CHAIN,
    RESEARCH_MODEL,
    PROPERTY_VALUE_MODEL,
    PROPERTY_VALUE_TRIGGERED_MODEL,
    *SYNTHESIS_MODEL_CHAIN,
)

# Geospatial agent chain — same Gemini tiers as discovery (Maps grounding).
GEOCODING_MODEL_CHAIN: tuple[str, ...] = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
)
GEOCODING_FALLBACK_MODEL = GEOCODING_MODEL_CHAIN[-1]
# Per-model generate_content RPM caps (shared harvester + outreach + UI).
DEFAULT_MODEL_RPM = 13
MODEL_RPM_LIMITS: dict[str, int] = {
    "gemini-2.5-flash": 5,
    "gemini-2.5-flash-lite": 10,
    "gemma-4-26b-a4b-it": 13,
    "gemma-4-31b-it": 13,
}
MODEL_RPM_STATE_PATH = Path(__file__).resolve().parent / ".gemini_model_rpm.json"
# Daily grounding budgets — favor search scouts over map lookups.
MAP_GROUNDING_DAILY_BUDGET = 500
SEARCH_GROUNDING_DAILY_BUDGET = 1500
GEOCODE_SEARCH_MAX_REMOTE_CALLS = 6
GEOCODE_MAP_MAX_REMOTE_CALLS = 4

# Underwriter search failover (UI path)
PRIMARY_SEARCH_MODEL = "gemma-4-31b-it"
SECONDARY_SEARCH_MODEL = "gemini-2.5-flash"

# (market_key, search scope for prompt, per-market base target before regional scale)
# Scaled targets sum to MAX_DISCOVERY_LISTINGS (base × DISCOVERY_TARGET_SCALE).
HOT_MARKETS: list[tuple[str, str, int]] = [
    (
        "Rochester",
        "Rochester NY metro (city + suburbs: Henrietta, Penfield, Fairport, Pittsford, "
        "Webster, Greece, Irondequoit, Brighton, Victor, Canandaigua)",
        5,
    ),
    (
        "Syracuse",
        "northern Syracuse suburbs — prioritize Cicero, Clay, Liverpool, and North Syracuse "
        "(secondary: Camillus, Baldwinsville; de-emphasize downtown Syracuse proper)",
        4,
    ),
    (
        "Buffalo",
        "Buffalo NY metro (city + suburbs: Amherst, Cheektowaga, Tonawanda, Williamsville, "
        "West Seneca, Hamburg, Orchard Park, Kenmore)",
        3,
    ),
    (
        "Albany",
        "Albany NY metro (city + suburbs: Colonie, Guilderland, Latham, Troy, Schenectady, "
        "Clifton Park, Bethlehem)",
        2,
    ),
    (
        "Philadelphia",
        "Philadelphia PA metro (city + suburbs: Ardmore, Media, Norristown, King of Prussia, "
        "Levittown, Bensalem, Cherry Hill NJ fringe)",
        2,
    ),
    (
        "Pittsburgh",
        "Pittsburgh PA metro (city + suburbs: Cranberry, Monroeville, Bethel Park, Ross "
        "Township, Mt. Lebanon, McCandless, Robinson Township)",
        1,
    ),
    (
        "Orlando",
        "Orlando FL metro (city + suburbs: Kissimmee, Winter Park, Sanford, Apopka, Ocoee, "
        "Altamonte Springs, Lake Mary)",
        2,
    ),
    (
        "Tampa",
        "Tampa FL metro (city + suburbs: St. Petersburg, Clearwater, Brandon, Wesley Chapel, "
        "Riverview, Largo, Palm Harbor)",
        2,
    ),
    (
        "Miami",
        "Miami–Fort Lauderdale metro (Miami-Dade + Broward: Miami, Fort Lauderdale, Hialeah, "
        "Pembroke Pines, Hollywood, Coral Springs, Miramar, Pompano Beach)",
        1,
    ),
    (
        "Charlotte",
        "Charlotte NC metro (city + suburbs: Concord, Matthews, Huntersville, Mint Hill, "
        "Indian Trail, Pineville, Mooresville)",
        1,
    ),
    (
        "Raleigh",
        "Raleigh NC metro (city + suburbs: Cary, Apex, Morrisville, Wake Forest, "
        "Holly Springs, Garner, Fuquay-Varina)",
        1,
    ),
    (
        "Charleston",
        "Charleston SC metro (city + suburbs: Mount Pleasant, Summerville, North Charleston, "
        "Goose Creek, James Island, Johns Island)",
        1,
    ),
]
# Regional groupings (planning / legacy top-up helpers only — harvest uses one combined call).
DISCOVERY_REGIONS: list[tuple[str, tuple[str, ...]]] = [
    ("Upstate NY", ("Rochester", "Syracuse", "Buffalo", "Albany")),
    ("Mid-Atlantic", ("Philadelphia", "Pittsburgh")),
    ("Florida", ("Orlando", "Tampa", "Miami")),
    ("Carolinas", ("Charlotte", "Raleigh", "Charleston")),
]
_MARKET_TO_DISCOVERY_REGION: dict[str, str] = {
    market: region
    for region, markets in DISCOVERY_REGIONS
    for market in markets
}
# One combined call covers all markets (base targets only — no regional multiplier).
DISCOVERY_TARGET_SCALE = 1
DISCOVERY_MARKET_KEYS = frozenset(name for name, _, _ in HOT_MARKETS)
MAX_DISCOVERY_LISTINGS = sum(
    base_target * DISCOVERY_TARGET_SCALE
    for _, _, base_target in HOT_MARKETS
)
# Hard floor for combined all-market discovery (model often stops at 6–13 without this).
MIN_DISCOVERY_LISTINGS = 18
DISCOVERY_PROMPT_TARGET = 20


def _scaled_market_target(market_name: str) -> int:
    """Per-market listing goal for this harvest (base HOT_MARKETS target × region scale)."""
    base = next(
        target for name, _, target in HOT_MARKETS if name == market_name
    )
    return base * DISCOVERY_TARGET_SCALE


def _region_scaled_target(region_key: str) -> int:
    """Sum of scaled per-market targets for all metros in a discovery region."""
    return sum(
        _scaled_market_target(market)
        for market in next(
            markets for region, markets in DISCOVERY_REGIONS if region == region_key
        )
    )
MIN_PREFERRED_YEAR_BUILT = 1985
MAX_DISCOVERY_PRICE = 250_000
_TRUSTED_LISTING_DOMAINS = ("zillow.com", "redfin.com", "realtor.com")
_LISTING_DETAIL_URL_MARKERS = (
    "homedetails",
    "/home/",
    "realestateandhomes-detail",
    "/property/",
)
_DISCOVERY_STATE_CODES = frozenset({"NY", "PA", "FL", "NC", "SC", "OH", "TX", "NJ"})
_US_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_STREET_NUMBER_RE = re.compile(r"(?:^|\s)(\d{1,6}[A-Za-z]?)\s+\S+")
# Grounded discovery needs more search calls than the SDK default (10 AFC).
DISCOVERY_MAX_REMOTE_CALLS = 25
DISCOVERY_FALLBACK_MAX_REMOTE_CALLS = 8
DISCOVERY_SPLIT_MAX_REMOTE_CALLS = 12
DISCOVERY_REGION_MAX_REMOTE_CALLS = 20
DISCOVERY_MAP_MAX_REMOTE_CALLS = 6
DISCOVERY_TOPUP_MAX_ROUNDS = 3
MAX_SYNTHESIS_PRICE = 400_000
MAX_API_RETRIES = 5
BACKOFF_BASE_SEC = 4.0
BACKOFF_MAX_SEC = 60.0
BACKOFF_MULTIPLIER = 2.0
# Upper bound for fixed sleeps; prefer retry_delay_seconds() for retries.
RATE_LIMIT_BACKOFF_SEC = BACKOFF_MAX_SEC
# Account-wide RPM reference; per-model caps live in MODEL_RPM_LIMITS.
HARVESTER_RPM_CAP = 13
HARVESTER_RPM_PER_MODEL = DEFAULT_MODEL_RPM
DISCOVERY_RPM_PER_MODEL = DEFAULT_MODEL_RPM
HARVESTER_RPM_WINDOW_SEC = 60.0


@dataclass(frozen=True, slots=True)
class GenaiSession:
    """Gemini API client scoped to a unit of work (request, job, or test)."""

    client: genai.Client


_current_session: contextvars.ContextVar[GenaiSession | None] = contextvars.ContextVar(
    "genai_session", default=None
)


def _get_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY")
    if key:
        return key
    try:
        import streamlit as st

        return str(st.secrets["GEMINI_API_KEY"])
    except Exception as exc:
        raise EnvironmentError(
            "GEMINI_API_KEY not set. Export it or add to Streamlit secrets."
        ) from exc


def create_genai_session(api_key: str | None = None) -> GenaiSession:
    """Build a new Gemini client session (factory entry point)."""
    key = api_key if api_key is not None else _get_api_key()
    return GenaiSession(client=genai.Client(api_key=key))


def get_session() -> GenaiSession:
    """Return the context-scoped session, creating one via the factory if needed."""
    session = _current_session.get()
    if session is None:
        session = create_genai_session()
        _current_session.set(session)
    return session


def set_session(session: GenaiSession | None) -> contextvars.Token[GenaiSession | None]:
    """Bind a session for the current context (e.g. tests or explicit DI)."""
    return _current_session.set(session)


def get_client() -> genai.Client:
    """Backward-compatible accessor for the active session client."""
    return get_session().client


def retry_delay_seconds(
    attempt: int,
    *,
    base_sec: float = BACKOFF_BASE_SEC,
    max_sec: float = BACKOFF_MAX_SEC,
    multiplier: float = BACKOFF_MULTIPLIER,
) -> float:
    """Full-jitter exponential backoff for retry attempt index (0-based)."""
    exp_cap = min(base_sec * (multiplier**attempt), max_sec)
    return random.uniform(0.0, exp_cap)


def model_rpm_limit(model: str) -> int:
    """Hosted Gemini requests-per-minute cap for this model slug."""
    slug = _MODEL_API_SLUGS.get(model, model)
    return MODEL_RPM_LIMITS.get(slug, DEFAULT_MODEL_RPM)


def _rpm_enforcement_enabled() -> bool:
    if os.getenv("GEMINI_RPM_DISABLE", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    return True


class SharedModelRateLimiter:
    """Cross-process sliding-window RPM limiter with per-model caps."""

    def __init__(
        self,
        state_path: Path = MODEL_RPM_STATE_PATH,
        window_sec: float = HARVESTER_RPM_WINDOW_SEC,
    ) -> None:
        self._state_path = state_path
        self._lock_path = state_path.with_suffix(".lock")
        self._window_sec = window_sec

    def _with_cross_process_lock(self, fn: Callable[[], Any]) -> Any:
        for _ in range(100):
            try:
                fd = os.open(self._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                try:
                    return fn()
                finally:
                    self._lock_path.unlink(missing_ok=True)
            except FileExistsError:
                time.sleep(0.05)
        raise TimeoutError(f"Could not acquire model RPM lock: {self._lock_path}")

    def _read_state(self) -> dict[str, list[float]]:
        if not self._state_path.is_file():
            return {}
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            str(key): [float(value) for value in values]
            for key, values in payload.items()
            if isinstance(values, list)
        }

    def _write_state(self, payload: dict[str, list[float]]) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self._state_path)

    def _prune(self, timestamps: list[float], now: float) -> list[float]:
        return [stamp for stamp in timestamps if now - stamp < self._window_sec]

    def try_acquire(self, model: str) -> float | None:
        """Return seconds to wait, or None when a slot was acquired."""
        if not _rpm_enforcement_enabled():
            return None
        slug = _MODEL_API_SLUGS.get(model, model)
        rpm = model_rpm_limit(slug)

        def _inner() -> float | None:
            now = time.time()
            state = self._read_state()
            window = self._prune(
                [float(value) for value in state.get(slug, [])],
                now,
            )
            if len(window) < rpm:
                window.append(now)
                state[slug] = window
                self._write_state(state)
                return None
            return max(0.0, self._window_sec - (now - window[0]))

        return cast(float | None, self._with_cross_process_lock(_inner))

    def acquire(self, model: str) -> None:
        while True:
            wait_sec = self.try_acquire(model)
            if wait_sec is None:
                return
            time.sleep(max(wait_sec, 0.05))


_shared_model_rate_limiter: SharedModelRateLimiter | None = None
_shared_model_rate_limiter_lock = threading.Lock()


def get_shared_model_rate_limiter() -> SharedModelRateLimiter:
    global _shared_model_rate_limiter
    with _shared_model_rate_limiter_lock:
        if _shared_model_rate_limiter is None:
            custom = os.getenv("GEMINI_RPM_STATE_PATH", "").strip()
            path = Path(custom) if custom else MODEL_RPM_STATE_PATH
            _shared_model_rate_limiter = SharedModelRateLimiter(path)
        return _shared_model_rate_limiter


def acquire_model_rpm(model: str) -> None:
    """Block until a per-model RPM slot is available (shared across CLI jobs)."""
    get_shared_model_rate_limiter().acquire(model)


async def acquire_model_rpm_async(model: str) -> None:
    """Async wrapper around the shared per-model RPM limiter."""
    limiter = get_shared_model_rate_limiter()
    while True:
        wait_sec = await asyncio.to_thread(limiter.try_acquire, model)
        if wait_sec is None:
            return
        await asyncio.sleep(max(wait_sec, 0.05))


class ModelRateLimiter:
    """Async limiter — delegates to shared per-model RPM budget."""

    def __init__(
        self,
        requests_per_minute: int = HARVESTER_RPM_PER_MODEL,
        window_sec: float = HARVESTER_RPM_WINDOW_SEC,
    ) -> None:
        _ = (requests_per_minute, window_sec)

    async def acquire(self, model: str) -> None:
        await acquire_model_rpm_async(model)


class SyncModelRateLimiter:
    """Sync limiter — delegates to shared per-model RPM budget."""

    def __init__(
        self,
        requests_per_minute: int = DISCOVERY_RPM_PER_MODEL,
        window_sec: float = HARVESTER_RPM_WINDOW_SEC,
    ) -> None:
        _ = (requests_per_minute, window_sec)

    def acquire(self, model: str) -> None:
        acquire_model_rpm(model)


def _log_retry(
    *,
    model: str,
    attempt: int,
    max_retries: int,
    error: Exception,
    delay_sec: float,
    total_wait_sec: float,
    retriable: bool,
) -> None:
    code = getattr(error, "code", None)
    print(
        f"[gemini-retry] model={model} attempt={attempt + 1}/{max_retries} "
        f"error={type(error).__name__} code={code} "
        f"delay_sec={delay_sec:.2f} total_wait_sec={total_wait_sec:.2f} "
        f"retriable={retriable}"
    )


def _is_retriable(error: Exception) -> bool:
    if isinstance(error, errors.ClientError):
        return error.code == 429
    return isinstance(error, (errors.ServerError, errors.APIError))


_RPD_QUOTA_MARKERS = (
    "per_day",
    "per day",
    "requests_per_day",
    "generate_requests_per_model",
    "daily quota",
    "daily limit",
    "rpd",
    "quota exceeded",
    "resource_exhausted",
    "resource exhausted",
    "check quota",
    "exceeded your current quota",
)


def _collect_error_messages(error: BaseException) -> str:
    """Flatten an exception chain into one lowercase string for quota heuristics."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(str(current))
        response = getattr(current, "response", None)
        if response is not None:
            parts.append(str(response))
        current = current.__cause__
    return " ".join(parts).lower()


def _has_quota_client_error(error: BaseException) -> bool:
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, errors.ClientError) and current.code in (403, 429):
            return True
        current = current.__cause__
    return False


def is_daily_quota_exhausted(error: BaseException) -> bool:
    """True when a Gemini error indicates daily (RPD) quota is exhausted."""
    if not _has_quota_client_error(error):
        return False

    message = _collect_error_messages(error)
    if any(marker in message for marker in _RPD_QUOTA_MARKERS):
        return True

    # After engine/harvester retry backoff, a lingering 429 is usually daily quota.
    if isinstance(error, RuntimeError) and "max retries" in message.lower():
        return True

    return False


def _model_supports_grounding(model: str) -> bool:
    """Google Search grounding is available on Gemini and Gemma 4 models."""
    return model.startswith("gemini") or model.startswith("gemma-4")


def _model_supports_map_grounding(model: str) -> bool:
    """Google Maps grounding is available on Gemini flash-tier models."""
    if "gemma" in model.lower():
        return False
    return model.startswith("gemini")


def _grounded_search_config(
    *,
    max_remote_calls: int = DISCOVERY_MAX_REMOTE_CALLS,
) -> types.GenerateContentConfig:
    """Config for Google Search grounding with a higher AFC remote-call budget."""
    return types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=max_remote_calls,
        ),
    )


_DISCOVERY_REGION_HINTS: dict[str, tuple[float, float]] = {
    "Upstate NY": (43.1, -77.6),
    "Mid-Atlantic": (40.0, -75.5),
    "Florida": (28.5, -81.4),
    "Carolinas": (35.2, -80.8),
}


def _grounded_discovery_config(
    model: str,
    *,
    max_remote_calls: int = DISCOVERY_MAX_REMOTE_CALLS,
    hint_lat: float | None = None,
    hint_lon: float | None = None,
) -> types.GenerateContentConfig:
    """Search grounding for all discovery models; Maps only on Gemini tiers."""
    tools: list[types.Tool] = []
    if _model_supports_grounding(model):
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    if _model_supports_map_grounding(model):
        tools.append(types.Tool(google_maps=types.GoogleMaps()))

    tool_config = None
    if (
        hint_lat is not None
        and hint_lon is not None
        and _model_supports_map_grounding(model)
    ):
        tool_config = types.ToolConfig(
            retrieval_config=types.RetrievalConfig(
                lat_lng=types.LatLng(latitude=hint_lat, longitude=hint_lon),
                language_code="en_US",
            )
        )

    return types.GenerateContentConfig(
        tools=tools,
        tool_config=tool_config,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=max_remote_calls,
        ),
    )


def _discovery_log(message: str) -> None:
    """Discovery progress lines — flush so long API waits show liveness in the console."""
    print(message, flush=True)


def _resolve_model_slug(model: str) -> str:
    """Map user-facing model labels to hosted Gemini API slugs."""
    return _MODEL_API_SLUGS.get(model, model)


def _resolve_discovery_model(model: str) -> str:
    """Map user-facing discovery tier labels to hosted Gemini API slugs."""
    resolved = _resolve_model_slug(model)
    if resolved != model:
        _discovery_log(
            f"[discovery] Model alias: {model} -> {resolved} (hosted API slug)"
        )
    return resolved


def _is_gemma_discovery_model(model: str) -> bool:
    return model.startswith("gemma")


def _discovery_models_to_try(explicit_model: str | None = None) -> list[str]:
    if explicit_model:
        return [_resolve_discovery_model(explicit_model)]
    return [_resolve_discovery_model(model) for model in DISCOVERY_MODEL_CHAIN]


def _discovery_afc_budget(
    model: str,
    *,
    split_market: str | None = None,
    split_region: str | None = None,
    region_market_needs: list[tuple[str, int]] | None = None,
    needed_count: int | None = None,
) -> int:
    """Right-size AFC search calls: combined needs more; per-market/gemma need fewer."""
    if split_region and region_market_needs:
        target = needed_count or sum(need for _, need in region_market_needs)
        market_count = len(region_market_needs)
        cap = (
            DISCOVERY_REGION_MAX_REMOTE_CALLS
            if _is_gemma_discovery_model(model)
            else DISCOVERY_MAX_REMOTE_CALLS
        )
        return min(max(target, 1) + 4 + max(0, market_count - 1) * 3, cap)
    if split_market:
        target = needed_count or next(
            (count for name, _, count in HOT_MARKETS if name == split_market),
            3,
        )
        per_market_cap = (
            DISCOVERY_FALLBACK_MAX_REMOTE_CALLS
            if _is_gemma_discovery_model(model)
            else DISCOVERY_SPLIT_MAX_REMOTE_CALLS
        )
        return min(max(target, 1) + 4, per_market_cap)
    if _is_gemma_discovery_model(model):
        return DISCOVERY_FALLBACK_MAX_REMOTE_CALLS
    return DISCOVERY_MAX_REMOTE_CALLS


def generate_with_retry(
    model: str,
    contents: str,
    *,
    use_search: bool = False,
    max_retries: int = MAX_API_RETRIES,
    session: GenaiSession | None = None,
) -> str:
    """Call Gemini with exponential backoff and full jitter on retriable errors."""
    active = session or get_session()
    config = None
    if use_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

    last_error: BaseException | None = None
    total_wait_sec = 0.0

    for attempt in range(max_retries):
        try:
            acquire_model_rpm(model)
            response = active.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            text = _extract_response_text(response)
            if not text.strip() and attempt < max_retries - 1:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=RuntimeError("empty response text"),
                    delay_sec=delay_sec,
                    total_wait_sec=total_wait_sec,
                    retriable=True,
                )
                time.sleep(delay_sec)
                continue
            if attempt > 0:
                print(
                    f"[gemini-retry] model={model} succeeded "
                    f"after {attempt + 1} attempt(s), total_wait_sec={total_wait_sec:.2f}"
                )
            return text
        except (errors.ClientError, errors.ServerError, errors.APIError) as e:
            last_error = e
            if is_daily_quota_exhausted(e):
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=e,
                    delay_sec=0.0,
                    total_wait_sec=total_wait_sec,
                    retriable=False,
                )
                raise
            will_retry = _is_retriable(e) and attempt < max_retries - 1
            if will_retry:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=e,
                    delay_sec=delay_sec,
                    total_wait_sec=total_wait_sec,
                    retriable=True,
                )
                time.sleep(delay_sec)
                continue
            _log_retry(
                model=model,
                attempt=attempt,
                max_retries=max_retries,
                error=e,
                delay_sec=0.0,
                total_wait_sec=total_wait_sec,
                retriable=False,
            )
            raise

    raise RuntimeError(
        f"Max retries ({max_retries}) exceeded for model={model}, "
        f"total_wait_sec={total_wait_sec:.2f}"
    ) from last_error


def _generate_with_grounding_retry(
    model: str,
    contents: str,
    *,
    use_search: bool = False,
    use_maps: bool = False,
    hint_lat: float | None = None,
    hint_lon: float | None = None,
    max_retries: int = MAX_API_RETRIES,
    session: GenaiSession | None = None,
    max_remote_calls: int = DISCOVERY_MAX_REMOTE_CALLS,
    rate_limiter: SyncModelRateLimiter | None = None,
) -> tuple[str, list[str]]:
    """Like generate_with_retry but also returns grounded search URLs for discovery."""
    active = session or get_session()
    config = None
    if use_search or use_maps:
        if use_maps:
            config = _grounded_discovery_config(
                model,
                max_remote_calls=max_remote_calls,
                hint_lat=hint_lat,
                hint_lon=hint_lon,
            )
            _discovery_log(
                f"[discovery] Grounded search + Maps in progress on {model} "
                f"(up to {max_remote_calls} tool calls; often 30–90s)..."
            )
        else:
            config = _grounded_search_config(max_remote_calls=max_remote_calls)
            _discovery_log(
                f"[discovery] Grounded search in progress on {model} "
                f"(up to {max_remote_calls} search calls; often 30–90s)..."
            )

    last_error: BaseException | None = None
    total_wait_sec = 0.0

    for attempt in range(max_retries):
        try:
            if rate_limiter is not None:
                rate_limiter.acquire(model)
            else:
                acquire_model_rpm(model)
            response = active.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            text = _extract_response_text(response)
            if not text.strip() and attempt < max_retries - 1:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=RuntimeError("empty response text"),
                    delay_sec=delay_sec,
                    total_wait_sec=total_wait_sec,
                    retriable=True,
                )
                time.sleep(delay_sec)
                continue
            if attempt > 0:
                print(
                    f"[gemini-retry] model={model} succeeded "
                    f"after {attempt + 1} attempt(s), total_wait_sec={total_wait_sec:.2f}"
                )
            return text, _extract_grounding_web_urls(response)
        except (errors.ClientError, errors.ServerError, errors.APIError) as e:
            last_error = e
            if is_daily_quota_exhausted(e):
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=e,
                    delay_sec=0.0,
                    total_wait_sec=total_wait_sec,
                    retriable=False,
                )
                raise
            will_retry = _is_retriable(e) and attempt < max_retries - 1
            if will_retry:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=e,
                    delay_sec=delay_sec,
                    total_wait_sec=total_wait_sec,
                    retriable=True,
                )
                time.sleep(delay_sec)
                continue
            _log_retry(
                model=model,
                attempt=attempt,
                max_retries=max_retries,
                error=e,
                delay_sec=0.0,
                total_wait_sec=total_wait_sec,
                retriable=False,
            )
            raise

    raise RuntimeError(
        f"Max retries ({max_retries}) exceeded for model={model}, "
        f"total_wait_sec={total_wait_sec:.2f}"
    ) from last_error


async def generate_with_retry_async(
    model: str,
    contents: str,
    *,
    use_search: bool = False,
    max_retries: int = MAX_API_RETRIES,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> str:
    """Async Gemini call with optional per-model RPM limiting and backoff."""
    active = session or get_session()
    config = None
    if use_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

    last_error: BaseException | None = None
    total_wait_sec = 0.0

    for attempt in range(max_retries):
        try:
            if rate_limiter is not None:
                await rate_limiter.acquire(model)
            else:
                await acquire_model_rpm_async(model)
            response = await active.client.aio.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            text = _extract_response_text(response)
            if not text.strip() and attempt < max_retries - 1:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=RuntimeError("empty response text"),
                    delay_sec=delay_sec,
                    total_wait_sec=total_wait_sec,
                    retriable=True,
                )
                await asyncio.sleep(delay_sec)
                continue
            if attempt > 0:
                print(
                    f"[gemini-retry] model={model} succeeded "
                    f"after {attempt + 1} attempt(s), total_wait_sec={total_wait_sec:.2f}"
                )
            return text
        except (errors.ClientError, errors.ServerError, errors.APIError) as e:
            last_error = e
            if is_daily_quota_exhausted(e):
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=e,
                    delay_sec=0.0,
                    total_wait_sec=total_wait_sec,
                    retriable=False,
                )
                raise
            will_retry = _is_retriable(e) and attempt < max_retries - 1
            if will_retry:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                _log_retry(
                    model=model,
                    attempt=attempt,
                    max_retries=max_retries,
                    error=e,
                    delay_sec=delay_sec,
                    total_wait_sec=total_wait_sec,
                    retriable=True,
                )
                await asyncio.sleep(delay_sec)
                continue
            _log_retry(
                model=model,
                attempt=attempt,
                max_retries=max_retries,
                error=e,
                delay_sec=0.0,
                total_wait_sec=total_wait_sec,
                retriable=False,
            )
            raise

    raise RuntimeError(
        f"Max retries ({max_retries}) exceeded for model={model}, "
        f"total_wait_sec={total_wait_sec:.2f}"
    ) from last_error


def _extract_response_text(response: Any) -> str:
    """Read model text safely; grounded responses sometimes omit response.text."""
    if response is None:
        return ""
    try:
        text = response.text
        if text:
            return str(text)
    except (AttributeError, ValueError):
        pass

    chunks: list[str] = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", "")
            if part_text:
                chunks.append(part_text)
    return "".join(chunks)


def _json_candidates(text: str) -> list[str]:
    """Build ordered JSON parse candidates from free-form LLM output."""
    stripped = text.strip()
    if not stripped:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(candidate: str) -> None:
        candidate = candidate.strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)

    _add(stripped)
    if "```json" in stripped:
        _add(stripped.split("```json", 1)[1].split("```", 1)[0])
    elif "```" in stripped:
        _add(stripped.split("```", 1)[1].split("```", 1)[0])

    for match in sorted(re.findall(r"\[[\s\S]*\]", stripped), key=len, reverse=True):
        _add(match)
    for match in sorted(re.findall(r"\{[\s\S]*\}", stripped), key=len, reverse=True):
        _add(match)

    return candidates


def _extract_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Helper to extract JSON from LLM responses."""
    for candidate in _json_candidates(text):
        try:
            return cast(dict[str, Any] | list[Any], json.loads(candidate))
        except json.JSONDecodeError:
            continue
    return None


def _coerce_discovery_list(parsed: Any) -> list[Any]:
    """Accept bare arrays or common wrapper objects from discovery models."""
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("listings", "properties", "results", "homes", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
        if parsed.get("address"):
            return [parsed]
    return []


# Suburb / alias keywords (lowercase) → canonical discovery market key.
_ADDRESS_MARKET_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("rochester", "Rochester"),
    ("henrietta", "Rochester"),
    ("penfield", "Rochester"),
    ("fairport", "Rochester"),
    ("pittsford", "Rochester"),
    ("webster", "Rochester"),
    ("greece", "Rochester"),
    ("irondequoit", "Rochester"),
    ("brighton", "Rochester"),
    ("victor", "Rochester"),
    ("canandaigua", "Rochester"),
    ("north syracuse", "Syracuse"),
    ("cicero", "Syracuse"),
    ("clay", "Syracuse"),
    ("liverpool", "Syracuse"),
    ("syracuse", "Syracuse"),
    ("camillus", "Syracuse"),
    ("dewitt", "Syracuse"),
    ("fayetteville", "Syracuse"),
    ("baldwinsville", "Syracuse"),
    ("manlius", "Syracuse"),
    ("buffalo", "Buffalo"),
    ("amherst", "Buffalo"),
    ("cheektowaga", "Buffalo"),
    ("tonawanda", "Buffalo"),
    ("williamsville", "Buffalo"),
    ("west seneca", "Buffalo"),
    ("hamburg", "Buffalo"),
    ("orchard park", "Buffalo"),
    ("kenmore", "Buffalo"),
    ("albany", "Albany"),
    ("colonie", "Albany"),
    ("guilderland", "Albany"),
    ("latham", "Albany"),
    ("schenectady", "Albany"),
    ("clifton park", "Albany"),
    ("troy", "Albany"),
    ("philadelphia", "Philadelphia"),
    ("ardmore", "Philadelphia"),
    ("norristown", "Philadelphia"),
    ("king of prussia", "Philadelphia"),
    ("levittown", "Philadelphia"),
    ("bensalem", "Philadelphia"),
    ("pittsburgh", "Pittsburgh"),
    ("cranberry", "Pittsburgh"),
    ("monroeville", "Pittsburgh"),
    ("bethel park", "Pittsburgh"),
    ("mt. lebanon", "Pittsburgh"),
    ("mccandless", "Pittsburgh"),
    ("orlando", "Orlando"),
    ("kissimmee", "Orlando"),
    ("winter park", "Orlando"),
    ("sanford", "Orlando"),
    ("apopka", "Orlando"),
    ("ocoee", "Orlando"),
    ("altamonte springs", "Orlando"),
    ("lake mary", "Orlando"),
    ("tampa", "Tampa"),
    ("st. petersburg", "Tampa"),
    ("clearwater", "Tampa"),
    ("brandon", "Tampa"),
    ("wesley chapel", "Tampa"),
    ("riverview", "Tampa"),
    ("largo", "Tampa"),
    ("palm harbor", "Tampa"),
    ("miami", "Miami"),
    ("fort lauderdale", "Miami"),
    ("hialeah", "Miami"),
    ("pembroke pines", "Miami"),
    ("hollywood", "Miami"),
    ("coral springs", "Miami"),
    ("miramar", "Miami"),
    ("pompano beach", "Miami"),
    ("charlotte", "Charlotte"),
    ("concord", "Charlotte"),
    ("matthews", "Charlotte"),
    ("huntersville", "Charlotte"),
    ("mint hill", "Charlotte"),
    ("indian trail", "Charlotte"),
    ("pineville", "Charlotte"),
    ("mooresville", "Charlotte"),
    ("raleigh", "Raleigh"),
    ("cary", "Raleigh"),
    ("apex", "Raleigh"),
    ("morrisville", "Raleigh"),
    ("wake forest", "Raleigh"),
    ("holly springs", "Raleigh"),
    ("garner", "Raleigh"),
    ("fuquay-varina", "Raleigh"),
    ("charleston", "Charleston"),
    ("mount pleasant", "Charleston"),
    ("summerville", "Charleston"),
    ("north charleston", "Charleston"),
    ("goose creek", "Charleston"),
    ("james island", "Charleston"),
    ("johns island", "Charleston"),
    ("cleveland", "Ohio"),
    ("columbus", "Ohio"),
    ("cincinnati", "Ohio"),
    ("lakewood", "Ohio"),
    ("parma", "Ohio"),
    ("dublin", "Ohio"),
    ("westerville", "Ohio"),
    ("mason", "Ohio"),
    ("fairfield", "Ohio"),
    ("hamilton", "Ohio"),
    ("dallas", "DFW"),
    ("fort worth", "DFW"),
    ("arlington", "DFW"),
    ("plano", "DFW"),
    ("frisco", "DFW"),
    ("irving", "DFW"),
    ("garland", "DFW"),
    ("mckinney", "DFW"),
    ("denton", "DFW"),
    ("austin", "Austin"),
    ("round rock", "Austin"),
    ("cedar park", "Austin"),
    ("pflugerville", "Austin"),
    ("georgetown", "Austin"),
    ("leander", "Austin"),
    ("kyle", "Austin"),
    ("buda", "Austin"),
)
_DISCOVERY_MARKET_LOOKUP = {name.lower(): name for name in DISCOVERY_MARKET_KEYS}


def _match_market_from_text(text: str) -> str:
    """Map free-text city or address to a canonical discovery market key."""
    lowered = text.lower()
    for keyword, market in _ADDRESS_MARKET_KEYWORDS:
        if keyword in lowered:
            return market
    return ""


def _infer_discovery_city(address: str, city: str) -> str:
    """Normalize suburb/city text to a canonical discovery market key."""
    normalized = city.strip()
    if normalized:
        canonical = _DISCOVERY_MARKET_LOOKUP.get(normalized.lower())
        if canonical:
            return canonical
        matched = _match_market_from_text(normalized)
        if matched:
            return matched
    return _match_market_from_text(address)


def _is_trusted_listing_url(url: str) -> bool:
    """True when URL points at a major listing site."""
    if not url or not url.strip():
        return False
    host = urlparse(url.strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == domain or host.endswith(f".{domain}") for domain in _TRUSTED_LISTING_DOMAINS)


def is_plausible_discovery_address(address: str) -> bool:
    """Reject hallucinated or incomplete discovery addresses."""
    normalized = address.strip()
    if len(normalized) < 12 or "," not in normalized:
        return False
    if not _US_ZIP_RE.search(normalized):
        return False
    if not _STREET_NUMBER_RE.search(normalized):
        return False
    upper = normalized.upper()
    if not any(f", {state}" in upper or f" {state} " in upper for state in _DISCOVERY_STATE_CODES):
        return False
    return True


def _extract_grounding_web_urls(response: Any) -> list[str]:
    """Collect grounded search result URLs from a Gemini response."""
    urls: list[str] = []
    seen: set[str] = set()
    for candidate in getattr(response, "candidates", None) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        if metadata is None:
            continue
        for chunk in getattr(metadata, "grounding_chunks", None) or []:
            web = getattr(chunk, "web", None)
            uri = getattr(web, "uri", None) if web is not None else None
            if uri and uri not in seen:
                seen.add(uri)
                urls.append(str(uri))
    return urls


def _extract_grounding_maps_places(response: Any) -> list[dict[str, str]]:
    """Collect grounded Google Maps place references from a Gemini response."""
    places: list[dict[str, str]] = []
    seen: set[str] = set()
    for candidate in getattr(response, "candidates", None) or []:
        metadata = getattr(candidate, "grounding_metadata", None)
        if metadata is None:
            continue
        for chunk in getattr(metadata, "grounding_chunks", None) or []:
            maps_chunk = getattr(chunk, "maps", None)
            if maps_chunk is None:
                continue
            place_id = str(getattr(maps_chunk, "place_id", "") or "").strip()
            uri = str(getattr(maps_chunk, "uri", "") or "").strip()
            title = str(getattr(maps_chunk, "title", "") or "").strip()
            key = place_id or uri or title
            if not key or key in seen:
                continue
            seen.add(key)
            places.append(
                {
                    "place_id": place_id,
                    "uri": uri,
                    "title": title,
                }
            )
    return places


@dataclass
class GroundingRpdBudget:
    """Track remaining daily map/search grounding calls for a harvest or session."""

    map_remaining: int = MAP_GROUNDING_DAILY_BUDGET
    search_remaining: int = SEARCH_GROUNDING_DAILY_BUDGET

    def consume_map(self, count: int = 1) -> bool:
        if self.map_remaining < count:
            return False
        self.map_remaining -= count
        return True

    def consume_search(self, count: int = 1) -> bool:
        if self.search_remaining < count:
            return False
        self.search_remaining -= count
        return True


_MARKET_GEO_HINTS: dict[str, tuple[float, float]] = {
    "Rochester": (43.1566, -77.6088),
    "Syracuse": (43.0481, -76.1474),
    "Buffalo": (42.8864, -78.8784),
    "Albany": (42.6526, -73.7562),
    "Philadelphia": (39.9526, -75.1652),
    "Pittsburgh": (40.4406, -79.9959),
    "Orlando": (28.5383, -81.3792),
    "Tampa": (27.9506, -82.4572),
    "Miami": (25.7617, -80.1918),
    "Charlotte": (35.2271, -80.8431),
    "Raleigh": (35.7796, -78.6382),
    "Charleston": (32.7765, -79.9311),
}


def _geocode_hint_lat_lng(
    address: str,
    *,
    market_city: str | None = None,
) -> tuple[float | None, float | None]:
    """Approximate lat/lon to seed Maps grounding (ZIP centroid or market center)."""
    from knowledge_base import parse_zipcode_from_address

    zip_code = parse_zipcode_from_address(address)
    if zip_code:
        try:
            from portfolio_map_page import ZIP_CENTROIDS

            centroid = ZIP_CENTROIDS.get(zip_code)
            if centroid:
                return centroid
        except ImportError:
            pass

    market_key = str(market_city or "").strip()
    if market_key in _MARKET_GEO_HINTS:
        return _MARKET_GEO_HINTS[market_key]

    matched = _match_market_from_text(address)
    if matched and matched in _MARKET_GEO_HINTS:
        return _MARKET_GEO_HINTS[matched]
    return None, None


def _grounded_maps_config(
    *,
    hint_lat: float | None = None,
    hint_lon: float | None = None,
    max_remote_calls: int = GEOCODE_MAP_MAX_REMOTE_CALLS,
) -> types.GenerateContentConfig:
    """Config for Google Maps grounding with optional regional hint."""
    tool_config = None
    if hint_lat is not None and hint_lon is not None:
        tool_config = types.ToolConfig(
            retrieval_config=types.RetrievalConfig(
                lat_lng=types.LatLng(latitude=hint_lat, longitude=hint_lon),
                language_code="en_US",
            )
        )
    return types.GenerateContentConfig(
        tools=[types.Tool(google_maps=types.GoogleMaps())],
        tool_config=tool_config,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(
            maximum_remote_calls=max_remote_calls,
        ),
    )


def _generate_with_map_grounding_retry(
    model: str,
    contents: str,
    *,
    hint_lat: float | None = None,
    hint_lon: float | None = None,
    max_retries: int = MAX_API_RETRIES,
    session: GenaiSession | None = None,
    max_remote_calls: int = GEOCODE_MAP_MAX_REMOTE_CALLS,
    rate_limiter: SyncModelRateLimiter | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Gemini call with Google Maps grounding; returns text and Maps place refs."""
    active = session or get_session()
    config = _grounded_maps_config(
        hint_lat=hint_lat,
        hint_lon=hint_lon,
        max_remote_calls=max_remote_calls,
    )

    last_error: BaseException | None = None
    total_wait_sec = 0.0

    for attempt in range(max_retries):
        try:
            if rate_limiter is not None:
                rate_limiter.acquire(model)
            else:
                acquire_model_rpm(model)
            response = active.client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            text = _extract_response_text(response)
            if not text.strip() and attempt < max_retries - 1:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                time.sleep(delay_sec)
                continue
            return text, _extract_grounding_maps_places(response)
        except (errors.ClientError, errors.ServerError, errors.APIError) as e:
            last_error = e
            if is_daily_quota_exhausted(e):
                raise
            will_retry = _is_retriable(e) and attempt < max_retries - 1
            if will_retry:
                delay_sec = retry_delay_seconds(attempt)
                total_wait_sec += delay_sec
                time.sleep(delay_sec)
                continue
            raise

    raise RuntimeError(
        f"Max retries ({max_retries}) exceeded for model={model}, "
        f"total_wait_sec={total_wait_sec:.2f}"
    ) from last_error


def _geocoding_models_to_try(explicit_model: str | None = None) -> list[str]:
    if explicit_model:
        return [_resolve_model_slug(explicit_model)]
    return [_resolve_model_slug(model) for model in GEOCODING_MODEL_CHAIN]


def _search_geocode_scout_prompt(address: str) -> str:
    return f"""You are a geocoding scout for US residential properties.

Property address: {address}

Use Google Search to locate this exact property on Zillow, Redfin, Realtor.com, or county records.
Return ONLY JSON:
{{
  "latitude": number,
  "longitude": number,
  "confidence": "high" | "medium" | "low",
  "matched_address": "normalized address string from listing",
  "source_url": "best listing or map URL"
}}

Rules:
- latitude/longitude must be decimal degrees for the property parcel or building centroid.
- If you cannot resolve coordinates, omit latitude and longitude entirely (do not return 0).
- Do not guess city-center coordinates."""


def _map_geocode_environment_prompt(address: str) -> str:
    return f"""You are a geospatial analyst for US investment properties.

Property address: {address}

Use Google Maps to resolve the EXACT latitude and longitude of this residential property.
Then assess environmental and location risks within ~1 mile:
- FEMA / flood exposure or nearby waterways
- Industrial sites, landfills, superfund or brownfield proximity
- Major highway / rail / airport noise corridors
- Wildfire or hurricane exposure when relevant to the region
- Crime or safety hotspots only when Maps reviews/data support it

Return ONLY JSON:
{{
  "latitude": number,
  "longitude": number,
  "confidence": "high" | "medium" | "low",
  "matched_address": "Maps-normalized address",
  "maps_place_id": "places/... if available",
  "environmental_risk": {{
    "score": number,
    "level": "Low" | "Moderate" | "High",
    "factors": ["short bullet strings"],
    "summary": "2-3 sentence investor-focused summary"
  }}
}}

Rules:
- score is 0 (lowest risk) to 10 (highest risk).
- latitude/longitude must be the property location, not a city center.
- If Maps cannot resolve the parcel, omit latitude and longitude entirely (do not return 0)."""


def _normalize_geospatial_payload(
    address: str,
    data: Any,
    *,
    model: str,
    source: str,
    maps_places: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "address": address,
        "latitude": None,
        "longitude": None,
        "geocode_confidence": "low",
        "geocode_source": source,
        "geocode_model": model,
        "maps_place_id": "",
        "maps_uri": "",
        "environmental_risk": None,
    }
    if not isinstance(data, dict):
        return payload

    lat = safe_float(data.get("latitude"))
    lon = safe_float(data.get("longitude"))
    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
        payload["latitude"] = lat
        payload["longitude"] = lon

    confidence = str(data.get("confidence", "")).strip().lower()
    if confidence in {"high", "medium", "low"}:
        payload["geocode_confidence"] = confidence

    env = data.get("environmental_risk")
    if isinstance(env, dict):
        score = safe_float(env.get("score"))
        level = str(env.get("level", "")).strip()
        factors = env.get("factors")
        summary = str(env.get("summary", "")).strip()
        payload["environmental_risk"] = {
            "score": max(0.0, min(10.0, score)),
            "level": level or "Unknown",
            "factors": [str(item).strip() for item in factors or [] if str(item).strip()],
            "summary": summary,
        }

    place_id = str(data.get("maps_place_id", "")).strip()
    if place_id:
        payload["maps_place_id"] = place_id
    if maps_places:
        top = maps_places[0]
        if not payload["maps_place_id"]:
            payload["maps_place_id"] = top.get("place_id", "")
        payload["maps_uri"] = top.get("uri", "")
    return payload


def _merge_geospatial_results(
    address: str,
    scout: dict[str, Any] | None,
    maps_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Prefer Maps-grounded coordinates; fall back to search scout."""
    merged: dict[str, Any] = {
        "address": address,
        "latitude": None,
        "longitude": None,
        "geocode_confidence": "low",
        "geocode_source": "unresolved",
        "geocode_model": "",
        "maps_place_id": "",
        "maps_uri": "",
        "environmental_risk": None,
    }
    for candidate in (maps_result, scout):
        if not candidate:
            continue
        lat = candidate.get("latitude")
        lon = candidate.get("longitude")
        if lat is None or lon is None:
            continue
        if merged["latitude"] is None:
            merged["latitude"] = lat
            merged["longitude"] = lon
            merged["geocode_confidence"] = candidate.get("geocode_confidence", "low")
            merged["geocode_source"] = candidate.get("geocode_source", "unknown")
            merged["geocode_model"] = candidate.get("geocode_model", "")
        for key in ("maps_place_id", "maps_uri"):
            if not merged.get(key) and candidate.get(key):
                merged[key] = candidate[key]
    if maps_result and maps_result.get("environmental_risk"):
        merged["environmental_risk"] = maps_result["environmental_risk"]
    return merged


def attach_geospatial_to_property(
    property_data: dict[str, Any],
    geospatial: dict[str, Any],
) -> dict[str, Any]:
    """Merge geocode + environmental fields onto a property record."""
    updated = dict(property_data)
    lat = geospatial.get("latitude")
    lon = geospatial.get("longitude")
    if _has_precise_coordinates(lat, lon):
        updated["latitude"] = safe_float(lat)
        updated["longitude"] = safe_float(lon)

    for meta_key in (
        "geocode_confidence",
        "geocode_source",
        "geocode_model",
        "maps_place_id",
        "maps_uri",
    ):
        if geospatial.get(meta_key):
            updated[meta_key] = geospatial[meta_key]

    env = geospatial.get("environmental_risk")
    if isinstance(env, dict) and env:
        updated["environmental_risk"] = env
        env_score = safe_float(env.get("score"))
        if env_score > 0 and safe_float(updated.get("location_score")) > 0:
            penalty = min(2.5, env_score * 0.2)
            updated["location_score"] = max(
                0.0,
                round(safe_float(updated.get("location_score")) - penalty, 2),
            )

    return updated


def geospatial_from_cached_coords(research: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build a geospatial payload when discovery/research already resolved coordinates.

    Avoids redundant gemini-2.5-flash geocode calls (major RPD drain during harvest).
    """
    lat = research.get("latitude")
    lon = research.get("longitude")
    if not _has_precise_coordinates(lat, lon):
        return None
    discovery_model = research.get("discovery_model")
    from_maps = _discovery_model_provides_map_coords(
        str(discovery_model) if discovery_model else None
    )
    return {
        "latitude": safe_float(lat),
        "longitude": safe_float(lon),
        "geocode_confidence": "high" if from_maps else "medium",
        "geocode_source": "discovery_maps" if from_maps else "cached_coords",
        "geocode_model": str(discovery_model) if discovery_model else None,
    }


def run_geospatial_enrichment(
    address: str,
    *,
    market_city: str | None = None,
    model: str | None = None,
    budget: GroundingRpdBudget | None = None,
    session: GenaiSession | None = None,
    rate_limiter: SyncModelRateLimiter | None = None,
) -> dict[str, Any]:
    """
    Agentic geocode pipeline:
    1) Search-grounded scout (higher RPD budget)
    2) Maps-grounded coordinate + environmental risk (lower RPD budget)
    Model order: gemini-2.5-flash -> gemini-2.5-flash-lite
    """
    active_budget = budget or GroundingRpdBudget()
    hint_lat, hint_lon = _geocode_hint_lat_lng(address, market_city=market_city)
    scout_result: dict[str, Any] | None = None
    maps_result: dict[str, Any] | None = None
    last_error: BaseException | None = None

    for geo_model in _geocoding_models_to_try(model):
        if not _model_supports_map_grounding(geo_model):
            continue

        if scout_result is None and active_budget.consume_search():
            try:
                scout_raw = _generate_with_grounding_retry(
                    geo_model,
                    _search_geocode_scout_prompt(address),
                    use_search=True,
                    session=session,
                    max_remote_calls=GEOCODE_SEARCH_MAX_REMOTE_CALLS,
                    rate_limiter=rate_limiter,
                )[0]
                scout_result = _normalize_geospatial_payload(
                    address,
                    _extract_json(scout_raw),
                    model=geo_model,
                    source="search_grounding",
                )
            except errors.ClientError as exc:
                last_error = exc
                if is_daily_quota_exhausted(exc):
                    continue
                raise
            except (errors.ServerError, errors.APIError, RuntimeError) as exc:
                last_error = exc
                _log.warning("geocode_scout_failed", address=address, error=str(exc))

        scout_lat = safe_float((scout_result or {}).get("latitude"))
        scout_lon = safe_float((scout_result or {}).get("longitude"))
        seed_lat = scout_lat if scout_lat else hint_lat
        seed_lon = scout_lon if scout_lon else hint_lon

        if maps_result is None and active_budget.consume_map():
            try:
                maps_raw, maps_places = _generate_with_map_grounding_retry(
                    geo_model,
                    _map_geocode_environment_prompt(address),
                    hint_lat=seed_lat,
                    hint_lon=seed_lon,
                    session=session,
                    rate_limiter=rate_limiter,
                )
                maps_result = _normalize_geospatial_payload(
                    address,
                    _extract_json(maps_raw),
                    model=geo_model,
                    source="maps_grounding",
                    maps_places=maps_places,
                )
                break
            except errors.ClientError as exc:
                last_error = exc
                if is_daily_quota_exhausted(exc):
                    continue
                raise
            except (errors.ServerError, errors.APIError, RuntimeError) as exc:
                last_error = exc
                _log.warning("geocode_maps_failed", address=address, error=str(exc))
                continue

        if scout_result and maps_result:
            break

    merged = _merge_geospatial_results(address, scout_result, maps_result)
    if not _has_precise_coordinates(merged.get("latitude"), merged.get("longitude")):
        catch_lat, catch_lon = _resolve_missing_coordinates_with_grounding_sync(
            address,
            session=session,
        )
        if catch_lat is not None and catch_lon is not None:
            merged["latitude"] = catch_lat
            merged["longitude"] = catch_lon
            merged["geocode_confidence"] = "medium"
            merged["geocode_source"] = "geocode_grounding_catch"
            merged["geocode_model"] = COORDINATE_CATCH_MODEL
        elif not _has_precise_coordinates(merged.get("latitude"), merged.get("longitude")):
            local_lat, local_lon = _local_coordinate_fallback(
                address,
                market_city=market_city,
            )
            if local_lat is not None and local_lon is not None:
                merged["latitude"] = local_lat
                merged["longitude"] = local_lon
                merged["geocode_confidence"] = "low"
                merged["geocode_source"] = "local_fallback"
    if merged["latitude"] is None and last_error is not None:
        merged["geocode_error"] = str(last_error)
    return merged


async def run_geospatial_enrichment_async(
    address: str,
    *,
    market_city: str | None = None,
    model: str | None = None,
    budget: GroundingRpdBudget | None = None,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> dict[str, Any]:
    """Async wrapper — geospatial agents run in a worker thread."""
    if rate_limiter is not None:
        active_model = _resolve_model_slug(model or GEOCODING_MODEL_CHAIN[0])
        await rate_limiter.acquire(active_model)
    return await asyncio.to_thread(
        run_geospatial_enrichment,
        address,
        market_city=market_city,
        model=model,
        budget=budget,
        session=session,
    )


def _is_listing_detail_url(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in _LISTING_DETAIL_URL_MARKERS)


def _infer_listing_url_from_grounding(
    address: str,
    grounding_urls: list[str],
) -> str:
    """Best-effort match of a listing row to a grounded search result URL."""
    trusted = [url for url in grounding_urls if _is_trusted_listing_url(url)]
    if not trusted:
        return ""

    zip_match = _US_ZIP_RE.search(address)
    zip_code = zip_match.group(0)[:5] if zip_match else ""
    street_match = _STREET_NUMBER_RE.search(address)
    street_number = street_match.group(1) if street_match else ""

    best_url = ""
    best_score = -1
    for url in trusted:
        lowered = url.lower()
        score = 0
        if _is_listing_detail_url(url):
            score += 2
        if zip_code and zip_code in url:
            score += 3
        if street_number and street_number in lowered:
            score += 2
        if score > best_score:
            best_score = score
            best_url = url
    if best_score >= 3:
        return best_url
    return ""


def _filter_verified_discovery_listings(
    listings: list[dict[str, Any]],
    *,
    max_price: float,
    grounding_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Drop discovery rows that look invented or lack verifiable listing evidence."""
    grounded_trusted = [
        url
        for url in grounding_urls or []
        if _is_trusted_listing_url(url)
    ]
    verified: list[dict[str, Any]] = []
    reject_counts = {
        "address": 0,
        "price": 0,
        "url": 0,
    }
    for item in listings:
        address = str(item.get("address", "")).strip()
        list_price = safe_float(item.get("list_price"))
        listing_url = str(
            item.get("listing_url")
            or item.get("source_url")
            or item.get("url")
            or ""
        ).strip()

        if not is_plausible_discovery_address(address):
            reject_counts["address"] += 1
            _log.info("discovery_rejected_address", address=address[:80], reason="implausible")
            continue
        if list_price <= 0 or list_price > max_price:
            reject_counts["price"] += 1
            _log.info(
                "discovery_rejected_price",
                address=address[:80],
                list_price=list_price,
            )
            continue
        if not listing_url or not _is_trusted_listing_url(listing_url):
            listing_url = _infer_listing_url_from_grounding(
                address, grounding_urls or []
            )
        if not listing_url or not _is_trusted_listing_url(listing_url):
            if grounded_trusted:
                # Search grounding hit listing sites; allow address+price through.
                listing_url = ""
            else:
                reject_counts["url"] += 1
                _log.info(
                    "discovery_rejected_url",
                    address=address[:80],
                    listing_url=listing_url[:120],
                )
                continue

        verified.append(
            {**item, "address": address, "list_price": list_price, "listing_url": listing_url}
        )
    if listings and not verified:
        _log.warning(
            "discovery_all_rejected",
            parsed=len(listings),
            grounded_trusted=len(grounded_trusted),
            reject_counts=reject_counts,
        )
        print(
            "[discovery] All parsed listings failed verification "
            f"(parsed={len(listings)}, rejections={reject_counts}, "
            f"grounded_listing_sites={len(grounded_trusted)}). "
            "Need ZIP + street number + valid price + listing URL or grounded search."
        )
    elif listings and len(verified) < len(listings):
        rejected = len(listings) - len(verified)
        print(
            f"[discovery] Rejected {rejected} unverified listing(s) after parsing "
            f"({reject_counts})."
        )
    return verified


def _normalize_discovery_item(item: Any) -> dict[str, Any] | None:
    """Map alternate discovery field names into the harvester listing shape."""
    if not isinstance(item, dict):
        return None

    address = str(
        item.get("address")
        or item.get("street_address")
        or item.get("full_address")
        or item.get("location")
        or ""
    ).strip()
    if not address:
        return None

    city = _infer_discovery_city(
        address,
        str(item.get("city") or item.get("market") or item.get("market_city") or ""),
    )
    if not city:
        return None

    list_price = safe_float(
        item.get("list_price", item.get("price", item.get("asking_price", 0)))
    )
    listing_url = str(
        item.get("listing_url")
        or item.get("source_url")
        or item.get("url")
        or ""
    ).strip()
    listing: dict[str, Any] = {
        "address": address,
        "city": city,
        "list_price": list_price,
        "listing_url": listing_url,
    }
    lat = safe_float(item.get("latitude", item.get("lat")))
    lon = safe_float(item.get("longitude", item.get("lon", item.get("lng"))))
    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
        listing["latitude"] = lat
        listing["longitude"] = lon
    year_built = parse_year_built(item)
    if year_built is not None and not _is_suspicious_default_year_built(year_built):
        listing["year_built"] = year_built
    return listing


def _parse_discovery_fallback(text: str) -> list[dict[str, Any]]:
    """Parse plain-text address lines when JSON discovery fails."""
    results: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip().lstrip("-•*0123456789.) ")
        if len(line) < 10 or "," not in line:
            continue
        city = _infer_discovery_city(line, "")
        if city:
            results.append({"address": line, "city": city, "list_price": 0.0, "listing_url": ""})
    return results


def _dedupe_discovery_listings(
    listings: list[dict[str, Any]],
    *,
    max_price: float,
    limit: int = MAX_DISCOVERY_LISTINGS,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in listings:
        key = item["address"].lower()
        if key in seen:
            continue
        seen.add(key)
        if 0 < item["list_price"] <= max_price:
            unique.append(item)
    return unique[:limit]


def _extend_discovery_listings(
    existing: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    *,
    max_price: float,
    on_listing_found: Callable[[dict[str, Any]], None] | None = None,
    discovery_model: str | None = None,
) -> list[dict[str, Any]]:
    """Merge new discovery rows, dedupe, and optionally notify per new listing."""
    before_keys = {item["address"].lower() for item in existing}
    merged = list(existing) + list(new_items)
    deduped = _dedupe_discovery_listings(merged, max_price=max_price)
    if on_listing_found:
        for item in deduped:
            key = item["address"].lower()
            if key not in before_keys:
                if discovery_model:
                    item["discovery_model"] = discovery_model
                on_listing_found(item)
                before_keys.add(key)
    return deduped


def _build_listings_from_raw(
    raw: str,
    max_price: float,
    *,
    grounding_urls: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Parse and normalize discovery model output into listing dicts."""
    parsed = _extract_json(raw)
    listings: list[dict[str, Any]] = []
    for item in _coerce_discovery_list(parsed):
        normalized = _normalize_discovery_item(item)
        if normalized:
            listings.append(normalized)

    if not listings:
        listings = _parse_discovery_fallback(raw)

    parsed_count = len(listings)
    listings = _filter_verified_discovery_listings(
        listings,
        max_price=max_price,
        grounding_urls=grounding_urls,
    )
    if parsed_count and not listings:
        preview = raw.strip().replace("\n", " ")[:240]
        print(f"[discovery] Parsed {parsed_count} row(s) from model but none passed verification.")
        if preview:
            print(f"[discovery] Model response preview: {preview}...")
    return _dedupe_discovery_listings(listings, max_price=max_price)


def _count_listings_by_market(listings: list[dict[str, Any]]) -> dict[str, int]:
    """Count verified discovery rows per canonical market key."""
    counts = {name: 0 for name, _, _ in HOT_MARKETS}
    for item in listings:
        city = str(item.get("city", "")).strip()
        if city in counts:
            counts[city] += 1
    return counts


def _plan_market_discovery_pass(
    listings: list[dict[str, Any]],
    exhausted_markets: set[str],
) -> list[tuple[str, int]]:
    """
    Build per-market discovery requests for the next pass.

    Markets that still need inventory are filled to their base target first.
    Unfilled slots from exhausted markets (e.g. Rochester found 3/5) are
    redistributed in HOT_MARKETS priority order to other cities until the
    global cap of MAX_DISCOVERY_LISTINGS is reached.
    """
    by_market = _count_listings_by_market(listings)
    global_remaining = MAX_DISCOVERY_LISTINGS - len(listings)
    if global_remaining <= 0:
        return []

    plan_counts: dict[str, int] = {}

    for market_name, _, _ in HOT_MARKETS:
        if market_name in exhausted_markets:
            continue
        scaled_target = _scaled_market_target(market_name)
        base_deficit = max(0, scaled_target - by_market.get(market_name, 0))
        if base_deficit > 0:
            plan_counts[market_name] = plan_counts.get(market_name, 0) + base_deficit

    still_need = global_remaining - sum(plan_counts.values())

    while still_need > 0:
        added_any = False
        for market_name, _, _ in HOT_MARKETS:
            if still_need <= 0:
                break
            if market_name in exhausted_markets:
                continue
            plan_counts[market_name] = plan_counts.get(market_name, 0) + 1
            still_need -= 1
            added_any = True
        if not added_any:
            break

    return [
        (name, plan_counts[name])
        for name, _, _ in HOT_MARKETS
        if plan_counts.get(name, 0) > 0
    ]


def _plan_region_discovery_pass(
    listings: list[dict[str, Any]],
    exhausted_markets: set[str],
) -> list[tuple[str, list[tuple[str, int]]]]:
    """
    Collapse per-market deficits into regional discovery tasks.

    e.g. Charlotte (1) + Raleigh (1) + Charleston (1) -> one Carolinas agent
    asking for 3 listings across NC/SC metros in a single grounded search.
    """
    market_plan = _plan_market_discovery_pass(listings, exhausted_markets)
    if not market_plan:
        return []

    region_needs: dict[str, list[tuple[str, int]]] = {}
    for market_name, needed_count in market_plan:
        region_key = _MARKET_TO_DISCOVERY_REGION.get(market_name)
        if not region_key:
            continue
        region_needs.setdefault(region_key, []).append((market_name, needed_count))

    return [
        (region_key, region_needs[region_key])
        for region_key, _ in DISCOVERY_REGIONS
        if region_key in region_needs
    ]


def _discovery_prompt(
    max_price: float,
    *,
    split_market: str | None = None,
    split_region: str | None = None,
    region_market_needs: list[tuple[str, int]] | None = None,
    exclude_addresses: list[str] | None = None,
    needed_count: int | None = None,
    total_needed: int | None = None,
    use_maps: bool = False,
) -> str:
    """Build a grounded-search discovery prompt."""
    ask_total = needed_count if needed_count and needed_count > 0 else MAX_DISCOVERY_LISTINGS
    if split_region and region_market_needs:
        parts: list[str] = []
        for market_name, need in region_market_needs:
            location = next(
                loc for name, loc, _ in HOT_MARKETS if name == market_name
            )
            parts.append(f"{need} in {location}")
        ask_total = sum(need for _, need in region_market_needs)
        scope = (
            f"{ask_total} NEW residential properties CURRENTLY FOR SALE across "
            f"{split_region} ({'; '.join(parts)}) — return different addresses only"
        )
    elif split_market:
        city, location, count = next(
            (name, loc, target)
            for name, loc, target in HOT_MARKETS
            if name == split_market
        )
        ask_count = needed_count if needed_count and needed_count > 0 else count
        ask_total = ask_count
        scope = (
            f"{ask_count} NEW residential properties CURRENTLY FOR SALE in {location} "
            f"(we already have listings for this market — return different addresses only)"
        )
    else:
        if total_needed and total_needed > 0:
            scope = (
                f"{total_needed} additional distinct residential properties CURRENTLY FOR SALE "
                f"across these hot markets (do not repeat addresses we already have)"
            )
        else:
            markets_desc = ", ".join(
                f"{count} in {location}" for _, location, count in HOT_MARKETS
            )
            scope = (
                f"at least {MIN_DISCOVERY_LISTINGS} distinct residential properties "
                f"(target {DISCOVERY_PROMPT_TARGET}–{MAX_DISCOVERY_LISTINGS}) CURRENTLY FOR SALE "
                f"across these hot markets: {markets_desc}"
            )

    exclude_block = ""
    if exclude_addresses:
        sample = exclude_addresses[:40]
        exclude_block = (
            "\n- Do NOT return any property whose address matches (or is substantially "
            "the same as) an address we have already analyzed:\n"
            + "\n".join(f"  - {addr}" for addr in sample)
        )
        if len(exclude_addresses) > len(sample):
            exclude_block += f"\n  - ... and {len(exclude_addresses) - len(sample)} more"

    market_keys = ", ".join(f'"{name}"' for name, _, _ in HOT_MARKETS)
    newer_inventory_note = (
        "Buyer preference: prioritize the newest available inventory in every search — "
        "buyers are far more likely to purchase move-in-ready, newer construction than "
        "dated stock. On Zillow/Redfin/Realtor, apply year-built filters and sort by "
        "newest listings when the site allows."
    )
    priority_note = (
        "Search priority: fill Upstate NY first (Rochester, Syracuse, Buffalo, Albany), "
        "then Philadelphia, Pittsburgh, Orlando, Tampa, and Miami–Fort Lauderdale, then "
        "Charlotte, Raleigh, and Charleston. "
        f"{newer_inventory_note} "
        "Strongly favor conventional site-built homes over manufactured/mobile housing."
    )
    if split_region and region_market_needs:
        region_markets = {name for name, _ in region_market_needs}
        priority_note = (
            f"Cover all metros in {split_region} listed in the scope — include city proper "
            "AND surrounding suburbs for each (do not limit to downtown/city limits). "
            "Distribute results across the requested metros; do not cluster in one city."
        )
        if "Syracuse" in region_markets:
            priority_note += (
                " For Syracuse, weight searches toward Cicero, Clay, Liverpool, and "
                "North Syracuse ZIPs (13039, 13041, 13088, 13212)."
            )
        if region_markets & {"Rochester", "Buffalo", "Albany"}:
            priority_note += (
                " Upstate NY metros should skew newest-available; exclude "
                "manufactured/mobile homes entirely."
            )
    elif split_market:
        priority_note = (
            f"Focus this search on {location} only — include city proper AND surrounding "
            "suburbs listed in the scope (do not limit to downtown/city limits)."
        )
        if split_market == "Syracuse":
            priority_note += (
                " Weight searches toward Cicero, Clay, Liverpool, and North Syracuse ZIPs "
                "(13039, 13041, 13088, 13212) before central Syracuse."
            )
        elif split_market in ("Rochester", "Buffalo", "Albany"):
            priority_note += (
                " Prioritize Upstate NY suburbs with newer single-family inventory; "
                "exclude manufactured/mobile homes entirely."
            )

    if split_region or split_market:
        return_count_rule = (
            f"You MUST return {ask_total} distinct listings — do not return fewer."
        )
    elif total_needed and total_needed > 0:
        return_count_rule = (
            f"You MUST return {total_needed} additional distinct listings in this response "
            f"— do not return fewer. Search new listing pages; do not repeat addresses "
            f"from the exclude list."
        )
    else:
        return_count_rule = (
            f"You MUST return a JSON array with AT LEAST {MIN_DISCOVERY_LISTINGS} objects "
            f"(aim for {DISCOVERY_PROMPT_TARGET}–{MAX_DISCOVERY_LISTINGS}). "
            f"Short arrays of 6, 10, or 13 listings are unacceptable — keep running "
            f"additional Zillow/Redfin/Realtor searches until you have verified "
            f"at least {MIN_DISCOVERY_LISTINGS} distinct active listings."
        )

    maps_coords_rule = ""
    maps_example_fields = ""
    if use_maps:
        maps_coords_rule = (
            "- Use Google Maps grounding to resolve exact latitude/longitude for each "
            "property parcel (decimal degrees). Do not return city-center coordinates.\n"
        )
        maps_example_fields = (
            '    "latitude": 43.12345,\n'
            '    "longitude": -77.54321,\n'
        )

    count_floor_rule = ""
    if not split_region and not split_market and not (total_needed and total_needed > 0):
        count_floor_rule = (
            f"- MINIMUM ARRAY LENGTH: {MIN_DISCOVERY_LISTINGS} verified listings in the JSON "
            f"array (target {DISCOVERY_PROMPT_TARGET}+). The example below shows only 2 rows "
            f"for format — your response must include many more.\n"
        )

    return f"""You are a real estate discovery agent for US hot rental markets.

Use Google Search to find {scope}.
Each listing price must be strictly under ${max_price:,.0f}.
{priority_note}

Return ONLY a JSON array (no markdown, no commentary). Example:
[
  {{
    "address": "123 Main St, Henrietta, NY 14623",
    "city": "Rochester",
    "list_price": 189000,
    "year_built": 2004,
{maps_example_fields}    "listing_url": "https://www.zillow.com/homedetails/123-Main-St-Henrietta-NY-14623/12345678_zpid/"
  }},
  {{
    "address": "456 Oak Ave, Penfield, NY 14526",
    "city": "Rochester",
    "list_price": 175000,
    "year_built": 1998,
{maps_example_fields}    "listing_url": "https://www.redfin.com/NY/Penfield/456-Oak-Ave-14526/home/12345678"
  }}
]

Rules:
- Search Zillow, Redfin, Realtor.com, or MLS listing pages for active for-sale homes.
- NEVER invent, guess, or fabricate addresses. Only return properties you found on an
  active listing page in this search session.
- listing_url is REQUIRED for every row — must be the exact Zillow, Redfin, or Realtor.com
  URL of the active listing you used (not a search-results page).
- Include suburbs and townships — not just the core city (e.g. Henrietta/Penfield/Fairport
  count as Rochester; Cicero/Clay/Liverpool/North Syracuse count as Syracuse; Amherst/Cheektowaga
  count as Buffalo; Colonie/Guilderland count as Albany).
- {return_count_rule} Do not stop early.
{count_floor_rule}- ONLY include: conventional site-built single-family detached homes, townhomes/townhouses,
  and small multifamily (duplex, triplex, or fourplex — at most 4 units total).
- NEVER include manufactured homes, mobile homes, modular homes, trailers, park-model homes,
  or HUD-code housing. Skip "Manufactured" / "Mobile" listing filters entirely; on Zillow/Redfin/
  Realtor use property-type filters for Single Family, Townhouse, and small Multi-Family only.
- EXCLUDE apartment buildings and any multifamily with 5+ units.
- INVENTORY AGE (buyer preference): return the newest homes you can verify. Prefer listings
  built in {MIN_PREFERRED_YEAR_BUILT} or later; when year built is visible, deprioritize
  pre-{MIN_PREFERRED_YEAR_BUILT} homes unless no newer inventory exists in that metro.
  Between two similar listings at similar price, always choose the newer build.
  Upstate NY (Rochester, Syracuse, Buffalo, Albany) should skew newest-available.
- Include year_built (4-digit) when shown on the listing page; omit the field if unknown.
- Use real street addresses with city/town, state, and ZIP (5-digit ZIP required).
- list_price must be the active asking price as a plain number (no $ or commas).
- city must be the parent metro key: one of {market_keys} (NOT the suburb name).
{maps_coords_rule}- If you cannot verify a listing with a real URL and asking price, omit it — do not pad
  the list with speculative addresses.{exclude_block}"""


def _run_discovery_attempt(
    *,
    model: str,
    max_price: float,
    split_market: str | None = None,
    split_region: str | None = None,
    region_market_needs: list[tuple[str, int]] | None = None,
    exclude_addresses: list[str] | None = None,
    needed_count: int | None = None,
    total_needed: int | None = None,
    rate_limiter: SyncModelRateLimiter | None = None,
) -> tuple[list[dict[str, Any]], str]:
    afc_budget = _discovery_afc_budget(
        model,
        split_market=split_market,
        split_region=split_region,
        region_market_needs=region_market_needs,
        needed_count=needed_count,
    )
    use_maps = _model_supports_map_grounding(model)
    hint_lat: float | None = None
    hint_lon: float | None = None
    if use_maps and split_region:
        hint = _DISCOVERY_REGION_HINTS.get(split_region)
        if hint:
            hint_lat, hint_lon = hint
    elif use_maps and split_market:
        hint = _MARKET_GEO_HINTS.get(split_market)
        if hint:
            hint_lat, hint_lon = hint

    prompt = _discovery_prompt(
        max_price,
        split_market=split_market,
        split_region=split_region,
        region_market_needs=region_market_needs,
        exclude_addresses=exclude_addresses,
        needed_count=needed_count,
        total_needed=total_needed,
        use_maps=use_maps,
    )
    raw, grounding_urls = _generate_with_grounding_retry(
        model,
        prompt,
        use_search=_model_supports_grounding(model),
        use_maps=use_maps,
        hint_lat=hint_lat,
        hint_lon=hint_lon,
        max_remote_calls=afc_budget,
        rate_limiter=rate_limiter,
    )
    listings = _build_listings_from_raw(raw, max_price, grounding_urls=grounding_urls)
    return listings, raw


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float, handling None, currency strings, and commas."""
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        return float(value)
    except (ValueError, TypeError):
        return default


_SUSPICIOUS_YEAR_BUILT_WINDOW = 3
_YEAR_BUILT_BACKFILL_CACHE: dict[str, int | None] = {}


def _is_suspicious_default_year_built(year: int | float | None) -> bool:
    """True when year_built looks like an LLM 'current year' placeholder."""
    if year is None:
        return False
    try:
        built = int(safe_float(year))
    except (TypeError, ValueError):
        return False
    current = date.today().year
    return current - _SUSPICIOUS_YEAR_BUILT_WINDOW <= built <= current


def parse_year_built(property_info: dict[str, Any]) -> int | None:
    """Extract 4-digit construction year from year_built or year fields."""
    for key in ("year_built", "year"):
        raw = property_info.get(key)
        if raw is None:
            continue
        year = safe_float(raw, default=0.0)
        if year >= 1800:
            return int(year)
    return None


def canonicalize_year_built_fields(data: dict[str, Any]) -> None:
    """Normalize year/year_built to a single trustworthy year_built value."""
    year = parse_year_built(data)
    if year is not None and not _is_suspicious_default_year_built(year):
        data["year_built"] = year
        data["year"] = year
        return
    data.pop("year_built", None)
    data.pop("year", None)


def backfill_year_built_if_needed(
    property_data: dict[str, Any],
    address: str,
) -> dict[str, Any]:
    """
    Re-research year_built when cached records contain a suspicious placeholder
    (e.g. harvester synthesis defaulting to the current year).
    """
    from knowledge_base import normalize_address_key

    existing = parse_year_built(property_data)
    if existing is not None and not _is_suspicious_default_year_built(existing):
        return property_data

    key = normalize_address_key(address)
    if not key:
        return property_data

    if key in _YEAR_BUILT_BACKFILL_CACHE:
        cached_year = _YEAR_BUILT_BACKFILL_CACHE[key]
        if cached_year is None:
            return property_data
        updated = dict(property_data)
        updated["year_built"] = cached_year
        updated["year"] = cached_year
        return updated

    research = research_property(address)
    year_built: int | None = None
    raw = research.get("year_built")
    if raw is not None:
        parsed = safe_float(raw)
        if parsed >= 1800 and not _is_suspicious_default_year_built(parsed):
            year_built = int(parsed)

    _YEAR_BUILT_BACKFILL_CACHE[key] = year_built
    if year_built is None:
        return property_data

    updated = dict(property_data)
    updated["year_built"] = year_built
    updated["year"] = year_built
    return updated


def calculate_property_age_years(property_info: dict[str, Any]) -> int | None:
    """Property age in whole years: current calendar year minus year built."""
    year_built = parse_year_built(property_info)
    if year_built is None or _is_suspicious_default_year_built(year_built):
        return None
    return max(date.today().year - year_built, 0)


_SYNTHESIS_NUMERIC_KEYS = (
    "price",
    "year",
    "rent",
    "tax_rate",
    "taxes",
    "hoa",
    "insurance",
    "maint_percent",
    "predicted_value",
    "location_score",
    "vacancy_rate",
    "management_fee",
    "square_footage",
)
_INTEGER_SYNTHESIS_KEYS = frozenset({"year", "square_footage"})


def _sanitize_synthesis_numerics(data: dict[str, Any]) -> None:
    """Normalize LLM numeric fields so finance/harvester never see formatted strings."""
    for key in _SYNTHESIS_NUMERIC_KEYS:
        if key not in data:
            continue
        parsed = safe_float(data[key])
        if key == "insurance":
            parsed = normalize_monthly_insurance(parsed)
        elif key == "tax_rate":
            parsed = normalize_tax_rate_percent(parsed)
        elif key in ("vacancy_rate", "management_fee", "maint_percent"):
            parsed = normalize_percent_rate(parsed)
        data[key] = int(parsed) if key in _INTEGER_SYNTHESIS_KEYS else parsed


# ---------------------------------------------------------------------------
# Harvester pipeline (3 stages — single grounded discovery call)
# ---------------------------------------------------------------------------

_DISCOVERY_API_ERRORS = (
    errors.ClientError,
    errors.ServerError,
    errors.APIError,
    RuntimeError,
)

_DiscoveryRegionResult = tuple[
    str,
    list[tuple[str, int]],
    list[dict[str, Any]],
    str,
    float,
]


def _run_single_region_discovery(
    *,
    region_key: str,
    market_needs: list[tuple[str, int]],
    model: str,
    max_price: float,
    exclude_addresses: list[str] | None,
    found_addrs: list[str],
    rate_limiter: SyncModelRateLimiter | None,
    round_idx: int | None = None,
    round_total: int | None = None,
    region_idx: int | None = None,
    region_total: int | None = None,
    split_listings: list[dict[str, Any]] | None = None,
    label: str = "region",
) -> _DiscoveryRegionResult:
    """Run one regional discovery agent covering multiple metros in one search."""
    total_needed = sum(need for _, need in market_needs)
    by_market = _count_listings_by_market(split_listings or [])
    breakdown = ", ".join(
        f"{name} {by_market.get(name, 0)}/{_scaled_market_target(name)} (+{need})"
        for name, need in market_needs
    )
    merged_exclude = list(exclude_addresses or []) + found_addrs
    round_note = (
        f"Round {round_idx}/{round_total} " if round_idx and round_total else ""
    )
    region_note = (
        f"{label} {region_idx}/{region_total}: " if region_idx and region_total else ""
    )
    total_count = len(split_listings or [])
    _discovery_log(
        f"[discovery] {round_note}{region_note}{region_key} "
        f"(need {total_needed} across {breakdown}, "
        f"total {total_count}/{MAX_DISCOVERY_LISTINGS})..."
    )
    started = time.monotonic()
    region_listings, region_raw = _run_discovery_attempt(
        model=model,
        max_price=max_price,
        split_region=region_key,
        region_market_needs=market_needs,
        exclude_addresses=merged_exclude,
        needed_count=total_needed,
        rate_limiter=rate_limiter,
    )
    elapsed = time.monotonic() - started
    return region_key, market_needs, region_listings, region_raw, elapsed


def _execute_region_discovery_plan(
    plan: list[tuple[str, list[tuple[str, int]]]],
    *,
    model: str,
    max_price: float,
    exclude_addresses: list[str] | None,
    split_listings: list[dict[str, Any]],
    rate_limiter: SyncModelRateLimiter | None,
    round_idx: int | None = None,
    round_total: int | None = None,
    label: str = "region",
) -> list[_DiscoveryRegionResult]:
    """Run regional discovery agents sequentially (one agent per geography)."""
    if not plan:
        return []

    found_addrs = [str(item.get("address", "")) for item in split_listings]
    region_total = len(plan)
    results: list[_DiscoveryRegionResult] = []
    for region_idx, (region_key, market_needs) in enumerate(plan, start=1):
        results.append(
            _run_single_region_discovery(
                region_key=region_key,
                market_needs=market_needs,
                model=model,
                max_price=max_price,
                exclude_addresses=exclude_addresses,
                found_addrs=found_addrs,
                rate_limiter=rate_limiter,
                round_idx=round_idx,
                round_total=round_total,
                region_idx=region_idx,
                region_total=region_total,
                split_listings=split_listings,
                label=label,
            )
        )
    return results


def _merge_discovery_region_results(
    split_listings: list[dict[str, Any]],
    results: list[_DiscoveryRegionResult],
    *,
    max_price: float,
    on_listing_found: Callable[[dict[str, Any]], None] | None,
    exhausted_markets: set[str],
    discovery_model: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Merge regional discovery results; mark per-metro exhaustion when a metro adds nothing."""
    round_added = 0
    for region_key, market_needs, region_listings, _region_raw, elapsed in results:
        before_by_market = _count_listings_by_market(split_listings)
        before = len(split_listings)
        split_listings = _extend_discovery_listings(
            split_listings,
            region_listings,
            max_price=max_price,
            on_listing_found=on_listing_found,
            discovery_model=discovery_model,
        )
        added = len(split_listings) - before
        round_added += added
        after_by_market = _count_listings_by_market(split_listings)
        for market_name, needed_count in market_needs:
            added_for_market = (
                after_by_market.get(market_name, 0)
                - before_by_market.get(market_name, 0)
            )
            if needed_count > 0 and added_for_market == 0:
                exhausted_markets.add(market_name)
        _discovery_log(
            f"[discovery] {region_key}: +{added} new verified in "
            f"{elapsed:.0f}s (total {len(split_listings)}/{MAX_DISCOVERY_LISTINGS})"
        )
    return split_listings, round_added


def _discover_listings_per_market(
    *,
    model: str,
    max_price: float,
    exclude_addresses: list[str] | None,
    seed_listings: list[dict[str, Any]] | None = None,
    on_listing_found: Callable[[dict[str, Any]], None] | None = None,
    rate_limiter: SyncModelRateLimiter | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Regional discovery: sequential agents per geography (legacy top-up path)."""
    split_listings = list(seed_listings or [])
    last_raw = ""
    exhausted_markets: set[str] = set()

    for round_idx in range(1, DISCOVERY_TOPUP_MAX_ROUNDS + 1):
        if len(split_listings) >= MAX_DISCOVERY_LISTINGS:
            break

        plan = _plan_region_discovery_pass(split_listings, exhausted_markets)
        if not plan:
            break

        exhausted_before = set(exhausted_markets)
        if exhausted_markets:
            _discovery_log(
                f"[discovery] Round {round_idx}/{DISCOVERY_TOPUP_MAX_ROUNDS}: "
                f"redistributing unfilled slots from "
                f"{', '.join(sorted(exhausted_markets))} to other markets"
            )
        region_summary = ", ".join(
            f"{region} ({sum(need for _, need in needs)})"
            for region, needs in plan
        )
        _discovery_log(
            f"[discovery] Round {round_idx}/{DISCOVERY_TOPUP_MAX_ROUNDS}: "
            f"running {len(plan)} regional discovery agent(s) sequentially: {region_summary} "
            f"(≤{DISCOVERY_RPM_PER_MODEL} RPM)..."
        )

        results = _execute_region_discovery_plan(
            plan,
            model=model,
            max_price=max_price,
            exclude_addresses=exclude_addresses,
            split_listings=split_listings,
            rate_limiter=rate_limiter,
            round_idx=round_idx,
            round_total=DISCOVERY_TOPUP_MAX_ROUNDS,
        )
        for _region_key, _market_needs, _region_listings, region_raw, _elapsed in results:
            last_raw = region_raw or last_raw

        split_listings, round_added = _merge_discovery_region_results(
            split_listings,
            results,
            max_price=max_price,
            on_listing_found=on_listing_found,
            exhausted_markets=exhausted_markets,
            discovery_model=model,
        )

        if round_added == 0:
            can_redistribute = (
                bool(exhausted_markets - exhausted_before)
                and len(split_listings) < MAX_DISCOVERY_LISTINGS
                and bool(_plan_region_discovery_pass(split_listings, exhausted_markets))
            )
            if not can_redistribute:
                break

    if len(split_listings) < MAX_DISCOVERY_LISTINGS:
        plan = _plan_region_discovery_pass(split_listings, exhausted_markets)
        if plan:
            _discovery_log(
                f"[discovery] Final regional top-up toward "
                f"{MAX_DISCOVERY_LISTINGS} listings "
                f"(have {len(split_listings)}, plan={plan})..."
            )
            results = _execute_region_discovery_plan(
                plan,
                model=model,
                max_price=max_price,
                exclude_addresses=exclude_addresses,
                split_listings=split_listings,
                rate_limiter=rate_limiter,
                label="top-up",
            )
            for _region_key, _market_needs, _region_listings, region_raw, _elapsed in results:
                last_raw = region_raw or last_raw
            split_listings, _round_added = _merge_discovery_region_results(
                split_listings,
                results,
                max_price=max_price,
                on_listing_found=on_listing_found,
                exhausted_markets=exhausted_markets,
                discovery_model=model,
            )

    if len(split_listings) < MAX_DISCOVERY_LISTINGS:
        remaining = MAX_DISCOVERY_LISTINGS - len(split_listings)
        found_addrs = [str(item.get("address", "")) for item in split_listings]
        merged_exclude = list(exclude_addresses or []) + found_addrs
        _discovery_log(
            f"[discovery] Global top-up: need {remaining} more listing(s) "
            f"(have {len(split_listings)}/{MAX_DISCOVERY_LISTINGS})..."
        )
        topup_listings, topup_raw = _run_discovery_attempt(
            model=model,
            max_price=max_price,
            exclude_addresses=merged_exclude,
            total_needed=remaining,
            rate_limiter=rate_limiter,
        )
        last_raw = topup_raw or last_raw
        before = len(split_listings)
        split_listings = _extend_discovery_listings(
            split_listings,
            topup_listings,
            max_price=max_price,
            on_listing_found=on_listing_found,
            discovery_model=model,
        )
        _discovery_log(
            f"[discovery] Global top-up: +{len(split_listings) - before} new "
            f"(total {len(split_listings)}/{MAX_DISCOVERY_LISTINGS})"
        )

    return split_listings, last_raw


def _discover_listings_for_model(
    *,
    model: str,
    max_price: float,
    exclude_addresses: list[str] | None,
    on_listing_found: Callable[[dict[str, Any]], None] | None = None,
    rate_limiter: SyncModelRateLimiter | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """One combined all-market discovery call; optional single global top-up."""
    model = _resolve_discovery_model(model)
    use_maps = _model_supports_map_grounding(model)
    maps_note = "Search + Maps grounding" if use_maps else "Search grounding"
    _discovery_log(
        f"[discovery] Combined all-market search on {model} "
        f"({maps_note}, target {MAX_DISCOVERY_LISTINGS} listings, "
        f"≤{DISCOVERY_MAX_REMOTE_CALLS} AFC calls)..."
    )

    listings, last_raw = _run_discovery_attempt(
        model=model,
        max_price=max_price,
        exclude_addresses=exclude_addresses,
        rate_limiter=rate_limiter,
    )
    deduped = _extend_discovery_listings(
        [],
        listings,
        max_price=max_price,
        on_listing_found=on_listing_found,
        discovery_model=model,
    )
    if len(deduped) >= MAX_DISCOVERY_LISTINGS:
        return deduped, last_raw

    if deduped:
        _log.info(
            "discovery_partial_combined",
            model=model,
            count=len(deduped),
            target=MAX_DISCOVERY_LISTINGS,
            minimum=MIN_DISCOVERY_LISTINGS,
        )
        _discovery_log(
            f"[discovery] Combined search returned {len(deduped)}/{MAX_DISCOVERY_LISTINGS} "
            f"(minimum {MIN_DISCOVERY_LISTINGS}) on {model}; running global top-up(s)..."
        )
    else:
        _log.warning(
            "discovery_empty_combined",
            model=model,
            raw_preview=last_raw[:400],
        )
        _discovery_log(
            f"[discovery] Combined search returned 0 listings on {model}; "
            f"retrying for at least {MIN_DISCOVERY_LISTINGS}..."
        )

    for topup_round in range(1, DISCOVERY_TOPUP_MAX_ROUNDS + 1):
        if len(deduped) >= MAX_DISCOVERY_LISTINGS:
            break
        if len(deduped) >= MIN_DISCOVERY_LISTINGS and len(deduped) >= DISCOVERY_PROMPT_TARGET:
            break

        remaining = max(
            MAX_DISCOVERY_LISTINGS - len(deduped),
            MIN_DISCOVERY_LISTINGS - len(deduped),
        )
        found_addrs = [str(item.get("address", "")) for item in deduped]
        merged_exclude = list(exclude_addresses or []) + found_addrs
        _discovery_log(
            f"[discovery] Global top-up {topup_round}/{DISCOVERY_TOPUP_MAX_ROUNDS}: "
            f"need {remaining} more (have {len(deduped)}, "
            f"minimum {MIN_DISCOVERY_LISTINGS})..."
        )
        topup_listings, topup_raw = _run_discovery_attempt(
            model=model,
            max_price=max_price,
            exclude_addresses=merged_exclude,
            total_needed=remaining,
            rate_limiter=rate_limiter,
        )
        last_raw = topup_raw or last_raw
        before = len(deduped)
        deduped = _extend_discovery_listings(
            deduped,
            topup_listings,
            max_price=max_price,
            on_listing_found=on_listing_found,
            discovery_model=model,
        )
        added = len(deduped) - before
        _discovery_log(
            f"[discovery] Global top-up {topup_round}: +{added} new "
            f"(total {len(deduped)}/{MAX_DISCOVERY_LISTINGS})"
        )
        if added == 0:
            break

    if len(deduped) < MIN_DISCOVERY_LISTINGS:
        _discovery_log(
            f"[discovery] Still below minimum ({len(deduped)}/{MIN_DISCOVERY_LISTINGS}); "
            f"running regional discovery pass..."
        )
        regional, regional_raw = _discover_listings_per_market(
            model=model,
            max_price=max_price,
            exclude_addresses=exclude_addresses,
            seed_listings=deduped,
            on_listing_found=on_listing_found,
            rate_limiter=rate_limiter,
        )
        last_raw = regional_raw or last_raw
        if len(regional) > len(deduped):
            deduped = regional

    return deduped, last_raw


def discover_hot_market_listings(
    max_price: float = MAX_DISCOVERY_PRICE,
    *,
    model: str | None = None,
    exclude_addresses: list[str] | None = None,
    on_listing_found: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """
    Stage 1 (Discovery): Search Grounding across prioritized hot markets.
    Returns up to MAX_DISCOVERY_LISTINGS listings (< max_price).

    Model order: gemini-2.5-flash -> gemini-2.5-flash-lite -> gemma-4-26b-a4b-it
    Gemini tiers also enable Maps grounding; Gemma is search-only.
    (tier 3 resolves to gemma-4-26b-a4b-it on the hosted API).

    One combined all-market call per model tier (≤2 calls/tier: initial + optional
    top-up). Gemini tiers enable Maps grounding on the same prompt.
    """
    models_to_try = _discovery_models_to_try(model)
    discovery_rate_limiter = SyncModelRateLimiter(requests_per_minute=DISCOVERY_RPM_PER_MODEL)
    chain_label = " -> ".join(models_to_try)
    _discovery_log(
        f"[discovery] Model chain: {chain_label} "
        f"(target {MAX_DISCOVERY_LISTINGS} listings, exclude {len(exclude_addresses or [])} KB rows)"
    )
    last_raw = ""
    for tier_idx, active_model in enumerate(models_to_try):
        try:
            listings, last_raw = _discover_listings_for_model(
                model=active_model,
                max_price=max_price,
                exclude_addresses=exclude_addresses,
                on_listing_found=on_listing_found,
                rate_limiter=discovery_rate_limiter,
            )
        except _DISCOVERY_API_ERRORS as exc:
            if (
                is_daily_quota_exhausted(exc)
                and tier_idx < len(models_to_try) - 1
            ):
                next_model = models_to_try[tier_idx + 1]
                _log.warning(
                    "discovery_quota_fallback",
                    from_model=active_model,
                    to_model=next_model,
                    error=str(exc),
                )
                _discovery_log(
                    f"[discovery] {active_model} daily quota exhausted; "
                    f"switching to {next_model}..."
                )
                _discovery_log(
                    "[discovery] Note: 'AFC is enabled with max remote calls' is normal SDK "
                    "output for Google Search (per-call budget is shown before each search)."
                )
                continue
            raise

        if listings:
            for item in listings:
                item.setdefault("discovery_model", active_model)
            _log.info(
                "discovery_success",
                model=active_model,
                count=len(listings),
            )
            return listings

        _log.warning(
            "discovery_empty_all_strategies",
            model=active_model,
            raw_preview=last_raw[:400],
        )
        if tier_idx < len(models_to_try) - 1:
            next_model = models_to_try[tier_idx + 1]
            _discovery_log(
                f"[discovery] No listings from {active_model}; "
                f"trying {next_model}..."
            )

    if last_raw.strip():
        print("[discovery] Last model response preview:")
        print(last_raw[:500])
    else:
        print(
            "[discovery] Models returned empty text after search grounding. "
            "This is a known intermittent Gemini issue; rerun the harvester."
        )

    return []


def _discovery_hint_block(discovery: dict[str, Any] | None) -> str:
    if not discovery:
        return ""
    list_price = safe_float(discovery.get("list_price"))
    listing_url = str(discovery.get("listing_url", "")).strip()
    if list_price <= 0 and not listing_url:
        return ""
    lines = [
        "",
        "DISCOVERY HINT (verify on the live listing page — do not invent data):",
    ]
    if listing_url:
        lines.append(f"- Listing URL from discovery: {listing_url}")
    if list_price > 0:
        lines.append(f"- Discovery reported asking price: ${list_price:,.0f}")
    lines.append(
        "- Open that listing page first. If the address or URL is wrong, return price 0."
    )
    return "\n".join(lines) + "\n"


def _research_prompt(address: str, discovery: dict[str, Any] | None = None) -> str:
    return f"""Research the residential property at: {address}
{_discovery_hint_block(discovery)}
Use live listing search results (Zillow, Redfin, Realtor.com, MLS, county records).
Read the FULL listing description and agent remarks — not just headline stats or Rent Zestimate.

Extract ONLY these fields:
- price (current list price USD, number only)
- taxes (total ANNUAL property tax USD)
- hoa (monthly HOA fee USD, 0 if none)
- year_built (4-digit construction year from listing facts — NOT property age in years; 0 if unknown)
- square_footage (integer)
- property_condition: exactly one of "Excellent", "Good", "Fair", "Poor"
- property_type: e.g. "Single Family", "Townhome", "Duplex", "Triplex", "Fourplex",
  "Multi-Family (3 units)". Do NOT label manufactured/mobile/modular homes as allowed types.
- stated_gross_monthly_rent: TOTAL monthly gross rent for the entire property if explicitly
  stated in the listing description (sum all units). Use 0 if not stated. If the listing gives
  ANNUAL rent/income, divide by 12. If it gives per-unit rent, multiply by unit count.
- listing_rent_notes: quote or paraphrase any rent/income/tenant language from the listing
  (empty string if none). Include whether amounts were monthly or annual.

Return ONLY JSON:
{{
  "address": "{address}",
  "price": number,
  "taxes": number,
  "hoa": number,
  "year_built": 1968,
  "square_footage": number,
  "property_condition": "Good",
  "property_type": "Single Family",
  "stated_gross_monthly_rent": 0,
  "listing_rent_notes": ""
}}"""


def _normalize_research_payload(address: str, data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "address": address,
            "price": 0.0,
            "taxes": 0.0,
            "hoa": 0.0,
            "year_built": 0,
            "square_footage": 0,
            "property_condition": "Unknown",
            "property_type": "Unknown",
            "stated_gross_monthly_rent": 0.0,
            "listing_rent_notes": "",
        }

    data["address"] = address
    data["price"] = safe_float(data.get("price"))
    data["taxes"] = safe_float(data.get("taxes"))
    data["hoa"] = safe_float(data.get("hoa"))
    year_built = int(safe_float(data.get("year_built")))
    if year_built >= 1800 and not _is_suspicious_default_year_built(year_built):
        data["year_built"] = year_built
    else:
        data["year_built"] = None
    data["square_footage"] = int(safe_float(data.get("square_footage")))
    condition = str(data.get("property_condition", "Unknown")).strip()
    data["property_condition"] = condition
    data["property_type"] = str(data.get("property_type", "Unknown")).strip() or "Unknown"
    data["stated_gross_monthly_rent"] = safe_float(data.get("stated_gross_monthly_rent"))
    data["listing_rent_notes"] = str(data.get("listing_rent_notes", "")).strip()
    return data


def _discovery_model_provides_map_coords(model: str | None) -> bool:
    """True when discovery used a Gemini tier with Maps grounding."""
    if not model:
        return False
    return _resolve_discovery_model(model) in MAPS_GROUNDED_DISCOVERY_MODELS


def _has_precise_coordinates(lat: Any, lon: Any) -> bool:
    if lat is None or lon is None:
        return False
    lat_f = safe_float(lat)
    lon_f = safe_float(lon)
    if lat_f == 0.0 and lon_f == 0.0:
        return False
    return -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0


def _needs_coordinate_catch(
    discovery_model: str | None,
    lat: Any,
    lon: Any,
) -> bool:
    """
    Run synthesis coordinate catch when coordinates are missing or null-island.

    Maps-grounded discovery often omits lat/lon in JSON even when Maps tools ran,
    so missing coords always warrant a catch pass — not only for Gemma discovery.
    """
    _ = discovery_model
    return not _has_precise_coordinates(lat, lon)


def _local_coordinate_fallback(
    address: str,
    *,
    market_city: str | None = None,
    zip_code: str | None = None,
) -> tuple[float | None, float | None]:
    """ZIP centroid / market-center fallback when grounding agents fail."""
    from knowledge_base import parse_zipcode_from_address
    from portfolio_map_page import resolve_coordinates_local

    normalized = str(address or "").strip()
    if not normalized:
        return None, None
    zip_val = str(zip_code or parse_zipcode_from_address(normalized) or "").strip()
    return resolve_coordinates_local(normalized, zip_val, str(market_city or ""))


def sanitize_property_coordinates(payload: dict[str, Any]) -> None:
    """Strip null-island sentinels and apply local fallback before DB writes."""
    lat = payload.get("latitude")
    lon = payload.get("longitude")
    if _has_precise_coordinates(lat, lon):
        payload["latitude"] = safe_float(lat)
        payload["longitude"] = safe_float(lon)
        return

    payload.pop("latitude", None)
    payload.pop("longitude", None)
    if payload.get("geocode_source") in {None, "", "unresolved"}:
        address = str(payload.get("address") or "").strip()
        if not address:
            return
        local_lat, local_lon = _local_coordinate_fallback(
            address,
            market_city=str(payload.get("market_city") or ""),
            zip_code=str(payload.get("zip_code") or "") or None,
        )
        if local_lat is not None and local_lon is not None:
            payload["latitude"] = local_lat
            payload["longitude"] = local_lon
            payload.setdefault("geocode_confidence", "low")
            payload.setdefault("geocode_source", "local_fallback")


def _normalize_strategy_label(label: str) -> str:
    return re.sub(r"[\s_-]+", " ", str(label).strip().lower())


_PROPERTY_VALUE_TRIGGER_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bturnkey\b.*\brental\b", re.IGNORECASE),
    re.compile(r"\brental\b.*\bturnkey\b", re.IGNORECASE),
    re.compile(r"\bcash\s*flow(?:er|ing)?\b", re.IGNORECASE),
    re.compile(r"\bsuburban\b.*\brental\b", re.IGNORECASE),
    re.compile(r"\bsuburban\s+core\b", re.IGNORECASE),
    re.compile(r"\bbuy[\s-]+and[\s-]+hold\b", re.IGNORECASE),
    re.compile(r"\bincome\s+property\b", re.IGNORECASE),
    re.compile(r"\bcash[\s-]+flowing\b", re.IGNORECASE),
)


def matches_property_value_trigger(label: str) -> bool:
    """True when a strategy label should trigger the property value comps agent."""
    normalized = _normalize_strategy_label(label)
    if not normalized:
        return False
    exact_labels = {
        "turnkey rental",
        "cash flower",
        "cash flow",
        "cash flowing",
        "suburban core rental",
        "buy and hold",
        "income property",
    }
    if normalized in exact_labels:
        return True
    return any(pattern.search(normalized) for pattern in _PROPERTY_VALUE_TRIGGER_PATTERNS)


def _apply_discovery_research_fallback(
    research: dict[str, Any],
    discovery: dict[str, Any] | None,
) -> dict[str, Any]:
    """Use verified discovery price when research could not resolve the listing."""
    if discovery:
        discovery_model = discovery.get("discovery_model")
        if discovery_model:
            research["discovery_model"] = discovery_model
        for coord_key in ("latitude", "longitude"):
            if discovery.get(coord_key) is not None:
                research[coord_key] = discovery[coord_key]
    if safe_float(research.get("price")) > 0 or not discovery:
        return research
    hint_price = safe_float(discovery.get("list_price"))
    listing_url = str(discovery.get("listing_url", "")).strip()
    if hint_price > 0 and _is_trusted_listing_url(listing_url):
        research["price"] = hint_price
        note = (
            "Research could not confirm price; using discovery listing URL price."
        )
        existing = str(research.get("listing_rent_notes", "")).strip()
        research["listing_rent_notes"] = f"{existing} {note}".strip()
    return research


def _resolve_research_model(model: str | None = None) -> str:
    active = model or RESEARCH_MODEL
    return _resolve_model_slug(active)


def research_property(
    address: str,
    *,
    discovery: dict[str, Any] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Stage 2 (Research): Gemma extraction with Search Grounding.
    """
    active_model = _resolve_research_model(model)
    raw = generate_with_retry(
        active_model,
        _research_prompt(address, discovery),
        use_search=_model_supports_grounding(active_model),
    )
    research = _normalize_research_payload(address, _extract_json(raw))
    return _apply_discovery_research_fallback(research, discovery)


async def research_property_async(
    address: str,
    *,
    discovery: dict[str, Any] | None = None,
    model: str | None = None,
    rate_limiter: ModelRateLimiter | None = None,
    session: GenaiSession | None = None,
) -> dict[str, Any]:
    """Async Stage 2 research for parallel harvester workers."""
    active_model = _resolve_research_model(model)
    raw = await generate_with_retry_async(
        active_model,
        _research_prompt(address, discovery),
        use_search=_model_supports_grounding(active_model),
        rate_limiter=rate_limiter,
        session=session,
    )
    research = _normalize_research_payload(address, _extract_json(raw))
    return _apply_discovery_research_fallback(research, discovery)


def _classify_strategy_prompt(research: dict[str, Any], market_city: str) -> str:
    return f"""Classify this {market_city} investment property into ONE strategy label.

RESEARCH:
{json.dumps(research, indent=2)}

Choose the best label from:
- Turnkey Rental (move-in ready with tenant or rent-ready)
- Cash Flower (strong monthly cash flow relative to price)
- Suburban Core Rental (suburban single-family or small multi rental)
- Buy and Hold (stable long-term hold, moderate cash flow)
- Value-Add Play
- Appreciation Machine
- High-Risk Speculation
- Needs Review

Return ONLY JSON: {{"property_label": "exact label from list above"}}"""


def classify_investment_strategy(
    research: dict[str, Any],
    market_city: str,
    *,
    model: str | None = None,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> str:
    """Lightweight strategy classification using the property value model (Gemma 26B)."""
    active_model = _resolve_model_slug(model or PROPERTY_VALUE_MODEL)
    raw = generate_with_retry(
        active_model,
        _classify_strategy_prompt(research, market_city),
        use_search=_model_supports_grounding(active_model),
        session=session,
    )
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        label = str(parsed.get("property_label", "")).strip()
        if label:
            return label
    return "Needs Review"


async def classify_investment_strategy_async(
    research: dict[str, Any],
    market_city: str,
    *,
    model: str | None = None,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> str:
    """Async strategy classification for harvester property value stage."""
    active_model = _resolve_model_slug(model or PROPERTY_VALUE_MODEL)
    raw = await generate_with_retry_async(
        active_model,
        _classify_strategy_prompt(research, market_city),
        use_search=_model_supports_grounding(active_model),
        session=session,
        rate_limiter=rate_limiter,
    )
    parsed = _extract_json(raw)
    if isinstance(parsed, dict):
        label = str(parsed.get("property_label", "")).strip()
        if label:
            return label
    return "Needs Review"


def _research_to_property_value_context(
    research: dict[str, Any],
    market_city: str,
) -> dict[str, Any]:
    """Build minimal property context for comps from research-stage fields."""
    price = safe_float(research.get("price"))
    return {
        "price": price,
        "predicted_value": price,
        "square_footage": research.get("square_footage", 0),
        "property_type": research.get("property_type", "Unknown"),
        "property_condition": research.get("property_condition", "Unknown"),
        "market_city": market_city,
        "rent": safe_float(research.get("stated_gross_monthly_rent")),
        "summary": research.get("listing_rent_notes", ""),
    }


def run_property_value_agent(
    address: str,
    research: dict[str, Any],
    market_city: str,
    *,
    session: GenaiSession | None = None,
) -> dict[str, Any]:
    """
    Stage 2.5 (Property Value): Classify strategy with Gemma 26B; when the label
    matches income-hold keywords, fetch 4-6 recent comps with Gemma 31B + search.
    """
    enriched = dict(research)
    strategy_label = classify_investment_strategy(
        research,
        market_city,
        session=session,
    )
    enriched["predicted_strategy_label"] = strategy_label
    if not matches_property_value_trigger(strategy_label):
        return enriched

    from comps_analysis import property_has_existing_comps

    if property_has_existing_comps(enriched):
        return enriched

    _log.info(
        "triggering_property_value_agent",
        address=address,
        label=_normalize_strategy_label(strategy_label),
    )
    property_context = _research_to_property_value_context(research, market_city)
    try:
        comp_result = fetch_comparable_properties(
            address,
            property_context,
            model=PROPERTY_VALUE_TRIGGERED_MODEL,
            num_comps="4 to 6",
        )
        comps_analysis = comp_result.get("comps_analysis")
        if comps_analysis:
            enriched["comps_analysis"] = comps_analysis
        if comp_result.get("predicted_value"):
            enriched["comps_implied_value"] = comp_result["predicted_value"]
        if comp_result.get("prediction_reasoning"):
            enriched["comps_value_reasoning"] = comp_result["prediction_reasoning"]
    except Exception as exc:
        _log.warning("property_value_agent_failed", address=address, error=str(exc))
    return enriched


async def run_property_value_agent_async(
    address: str,
    research: dict[str, Any],
    market_city: str,
    *,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> dict[str, Any]:
    """Async property value stage for parallel harvester workers."""
    enriched = dict(research)
    strategy_label = await classify_investment_strategy_async(
        research,
        market_city,
        session=session,
        rate_limiter=rate_limiter,
    )
    enriched["predicted_strategy_label"] = strategy_label
    if not matches_property_value_trigger(strategy_label):
        return enriched

    from comps_analysis import property_has_existing_comps

    if property_has_existing_comps(enriched):
        return enriched

    _log.info(
        "triggering_property_value_agent_async",
        address=address,
        label=_normalize_strategy_label(strategy_label),
    )
    property_context = _research_to_property_value_context(research, market_city)
    try:
        comp_result = await asyncio.to_thread(
            fetch_comparable_properties,
            address,
            property_context,
            model=PROPERTY_VALUE_TRIGGERED_MODEL,
            num_comps="4 to 6",
        )
        comps_analysis = comp_result.get("comps_analysis")
        if comps_analysis:
            enriched["comps_analysis"] = comps_analysis
        if comp_result.get("predicted_value"):
            enriched["comps_implied_value"] = comp_result["predicted_value"]
        if comp_result.get("prediction_reasoning"):
            enriched["comps_value_reasoning"] = comp_result["prediction_reasoning"]
    except Exception as exc:
        _log.warning(
            "property_value_agent_failed_async",
            address=address,
            error=str(exc),
        )
    return enriched


_DISALLOWED_PROPERTY_TYPE_RE = re.compile(
    r"\b(?:"
    r"manufactured(?:\s+home)?|mobile\s+home|modular\s+home|trailer(?:\s+home)?|"
    r"park[\s-]?model|prefab(?:ricated)?|manufactured\s+housing"
    r")\b",
    re.IGNORECASE,
)
_LARGE_MULTIFAMILY_RE = re.compile(
    r"\b(?:apartment(?:\s+building|\s+complex)?|"
    r"(?:multi[\s-]?family|multifamily).*(?:5|6|7|8|9|\d{2,})\s*units?|"
    r"(?:5|6|7|8|9|\d{2,})\s*units?.*(?:multi[\s-]?family|multifamily)|"
    r"(?:5|6|7|8|9|\d{2,})[\s-]?unit)\b",
    re.IGNORECASE,
)


def is_disallowed_property_type(property_type: str) -> bool:
    """True for manufactured homes and multifamily with 5+ units."""
    normalized = property_type.strip()
    if not normalized or normalized.lower() == "unknown":
        return False
    if _DISALLOWED_PROPERTY_TYPE_RE.search(normalized):
        return True
    if _LARGE_MULTIFAMILY_RE.search(normalized):
        return True
    for match in re.finditer(r"\b(\d+)\s*units?\b", normalized, flags=re.IGNORECASE):
        if int(match.group(1)) >= 5:
            return True
    return False


def synthesis_skip_reason(research: dict[str, Any]) -> str | None:
    """Human-readable reason to skip Stage 3, or None if synthesis should run."""
    condition = str(research.get("property_condition", "")).strip().lower()
    if condition == "poor":
        return "Poor condition"
    price = safe_float(research.get("price"))
    if price <= 0:
        return "Missing or zero price"
    if price > MAX_SYNTHESIS_PRICE:
        return f"Price > ${MAX_SYNTHESIS_PRICE:,}"
    property_type = str(research.get("property_type", "")).strip()
    if is_disallowed_property_type(property_type):
        return f"Excluded property type: {property_type}"
    return None


def should_skip_synthesis(research: dict[str, Any]) -> bool:
    """Skip Stage 3 if condition, price, or property type fails investment filters."""
    return synthesis_skip_reason(research) is not None


def _synthesis_prompt(
    research: dict[str, Any],
    market_city: str,
    *,
    user_id: str | None = None,
) -> str:
    kb_context = get_kb_context(user_id)
    return f"""You are an expert real estate underwriter for {market_city} hot market investments.

CONTEXT FROM DATABASE:
{kb_context}

RESEARCH DATA (verified extraction):
{json.dumps(research, indent=2)}

PROPERTY VALUE / COMPS (when present — from property value agent):
{json.dumps(research.get("comps_analysis") or {}, indent=2)}

PREDICTED STRATEGY (from property value classifier):
{research.get("predicted_strategy_label") or "unknown"}

GEOSPATIAL / ENVIRONMENTAL (when present — from Maps grounding):
{json.dumps(research.get("environmental_risk") or {}, indent=2)}

Produce a complete investment underwriting. Use research price/taxes/hoa/sqft/year_built as anchors.
When comps_analysis is present, anchor predicted_value to recent comparable sales and cite comps
in prediction_reasoning.
If environmental_risk is present, reflect flood/industrial/noise factors in summary and location_score.

YEAR BUILT (critical):
- "year" must be the 4-digit construction year (e.g. 1968), NOT property age in years.
- If research includes year_built >= 1800, use that exact value. Do not substitute the current year.

RENT (critical):
- If research includes stated_gross_monthly_rent > 0 or listing_rent_notes, use that as rent
  (total building gross monthly rent). Do NOT substitute a single-family Rent Zestimate.
- For duplex/triplex/multifamily, rent must reflect ALL units combined.
- If listing_rent_notes mention annual income, divide by 12 for monthly rent.

Return ONLY JSON with these keys:
{{
  "price": number,
  "year": number,
  "rent": number,
  "tax_rate": number, (effective annual tax rate as PERCENT — e.g. 3.4 for 3.4%, NOT 0.034; use annual_taxes / price * 100),
  "hoa": number,
  "insurance": number, (MONTHLY cost — if research implies an annual premium above $400, divide by 12),
  "summary": "3-4 sentence investment summary",
  "maint_percent": number,
  "predicted_value": number,
  "prediction_reasoning": "1-2 sentences",
  "location_score": number,
  "vacancy_rate": number, (vacancy reserve as PERCENT of rent — e.g. 6 for 6%, NOT 0.06; typical range 3-10, never below 1),
  "management_fee": number, (management fee as PERCENT of rent — e.g. 10 for 10%, NOT 0.10; typical range 8-12, never below 1),
  "property_label": "strategy label",
  "square_footage": number,
  "property_condition": "string",
  "sources": ["url strings"]
}}

No currency symbols or commas outside JSON."""


def _research_year_built(research: dict[str, Any]) -> int | None:
    raw = research.get("year_built")
    if raw is None:
        return None
    parsed = safe_float(raw)
    if parsed >= 1800 and not _is_suspicious_default_year_built(parsed):
        return int(parsed)
    return None


def _apply_research_year_built(data: dict[str, Any], research: dict[str, Any]) -> None:
    """Prefer grounded research year_built over synthesis guesses."""
    research_year = _research_year_built(research)
    if research_year is not None:
        data["year"] = research_year
        data["year_built"] = research_year
        return

    synth_year = None
    for key in ("year_built", "year"):
        raw = data.get(key)
        if raw is None:
            continue
        parsed = safe_float(raw)
        if parsed >= 1800:
            synth_year = int(parsed)
            break

    if synth_year is not None and _is_suspicious_default_year_built(synth_year):
        data.pop("year", None)
        data.pop("year_built", None)


def _synthesis_fallback_payload(research: dict[str, Any]) -> dict[str, Any]:
    price = safe_float(research.get("price"))
    taxes = safe_float(research.get("taxes"))
    fallback_year = _research_year_built(research)
    payload: dict[str, Any] = {
        "price": price,
        "rent": 0.0,
        "tax_rate": (taxes / price * 100) if price > 0 else 0.0,
        "hoa": safe_float(research.get("hoa")),
        "insurance": 100.0,
        "summary": "Synthesis failed; partial record from research.",
        "maint_percent": 4.0,
        "predicted_value": price,
        "prediction_reasoning": "Research-only fallback.",
        "location_score": 5.0,
        "vacancy_rate": 5.0,
        "management_fee": 10.0,
        "property_label": "Needs Review",
        "square_footage": research.get("square_footage", 0),
        "property_condition": research.get("property_condition", "Unknown"),
        "sources": [],
    }
    if fallback_year is not None:
        payload["year"] = fallback_year
        payload["year_built"] = fallback_year
    return payload


def _finalize_synthesis_payload(
    address: str,
    research: dict[str, Any],
    market_city: str,
    data: Any,
    *,
    geospatial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(data, dict):
        data = _synthesis_fallback_payload(research)

    data["address"] = address
    data["market_city"] = market_city
    data["square_footage"] = data.get("square_footage", research.get("square_footage"))
    data["property_condition"] = data.get(
        "property_condition", research.get("property_condition")
    )
    _apply_research_year_built(data, research)
    _sanitize_synthesis_numerics(data)
    canonicalize_year_built_fields(data)
    enriched = enrich_with_forecast(data)
    if geospatial:
        enriched = attach_geospatial_to_property(enriched, geospatial)
    elif research.get("environmental_risk"):
        enriched = attach_geospatial_to_property(
            enriched,
            {
                "latitude": research.get("latitude"),
                "longitude": research.get("longitude"),
                "environmental_risk": research.get("environmental_risk"),
            },
        )
    return _merge_property_value_into_synthesis(
        attach_data_provenance(enriched, research, pipeline="harvester"),
        research,
    )


def _merge_property_value_into_synthesis(
    enriched: dict[str, Any],
    research: dict[str, Any],
) -> dict[str, Any]:
    """Attach harvest comps/value signals from the property value agent stage."""
    comps = research.get("comps_analysis")
    if isinstance(comps, dict) and comps.get("comparable_properties"):
        enriched["comps_analysis"] = comps
        if apply_comp_implied_market_value(enriched, comps):
            enriched = enrich_with_forecast(enriched)
        reasoning = str(research.get("comps_value_reasoning") or "").strip()
        if reasoning and not str(enriched.get("prediction_reasoning") or "").strip():
            enriched["prediction_reasoning"] = reasoning
    strategy = str(research.get("predicted_strategy_label") or "").strip()
    if strategy and strategy.lower() != "needs review":
        enriched.setdefault("property_label", strategy)
    return enriched


def _synthesis_models_to_try(explicit_model: str | None = None) -> list[str]:
    if explicit_model:
        return [_resolve_model_slug(explicit_model)]
    return [_resolve_model_slug(model) for model in SYNTHESIS_MODEL_CHAIN]


def _generate_synthesis_with_model_chain(
    research: dict[str, Any],
    market_city: str,
    *,
    model: str | None = None,
    user_id: str | None = None,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> tuple[str, str]:
    """Try synthesis models in order; return (raw_json_text, model_used)."""
    prompt = _synthesis_prompt(research, market_city, user_id=user_id)
    last_error: BaseException | None = None
    for active_model in _synthesis_models_to_try(model):
        try:
            raw = generate_with_retry(
                active_model,
                prompt,
                use_search=False,
                session=session,
            )
            return raw, active_model
        except errors.ClientError as exc:
            last_error = exc
            if is_daily_quota_exhausted(exc):
                _log.warning(
                    "synthesis_model_fallback",
                    from_model=active_model,
                    error=str(exc),
                )
                continue
            raise
    raise RuntimeError(
        f"Synthesis failed for all models in {SYNTHESIS_MODEL_CHAIN}"
    ) from last_error


def _resolve_missing_coordinates_with_grounding_sync(
    address: str,
    session: GenaiSession | None = None,
) -> tuple[float | None, float | None]:
    """Runs a dedicated search-grounding coordinate catch using COORDINATE_CATCH_MODEL."""
    prompt = f"""Search for the exact geographic coordinates (latitude and longitude) of the property at: {address}.
    Return the coordinates in this exact format:
    COORDINATES: LAT: <latitude>, LON: <longitude>
    Do not return any other text."""
    try:
        raw = generate_with_retry(
            COORDINATE_CATCH_MODEL,
            prompt,
            use_search=True,
            session=session,
        )
        lat_match = re.search(r"(?:lat|latitude)[:\s=-]*([-\d.]+)", raw, re.IGNORECASE)
        lon_match = re.search(r"(?:lon|lng|longitude)[:\s=-]*([-\d.]+)", raw, re.IGNORECASE)
        if lat_match and lon_match:
            lat = safe_float(lat_match.group(1))
            lon = safe_float(lon_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                return lat, lon
    except Exception as exc:
        _log.warning("grounding_string_catch_failed_sync", address=address, error=str(exc))
    return None, None


async def _resolve_missing_coordinates_with_grounding_async(
    address: str,
    session: GenaiSession | None = None,
    rate_limiter: ModelRateLimiter | None = None,
) -> tuple[float | None, float | None]:
    """Runs a dedicated search-grounding coordinate catch asynchronously."""
    prompt = f"""Search for the exact geographic coordinates (latitude and longitude) of the property at: {address}.
    Return the coordinates in this exact format:
    COORDINATES: LAT: <latitude>, LON: <longitude>
    Do not return any other text."""
    try:
        raw = await generate_with_retry_async(
            COORDINATE_CATCH_MODEL,
            prompt,
            use_search=True,
            session=session,
            rate_limiter=rate_limiter,
        )
        lat_match = re.search(r"(?:lat|latitude)[:\s=-]*([-\d.]+)", raw, re.IGNORECASE)
        lon_match = re.search(r"(?:lon|lng|longitude)[:\s=-]*([-\d.]+)", raw, re.IGNORECASE)
        if lat_match and lon_match:
            lat = safe_float(lat_match.group(1))
            lon = safe_float(lon_match.group(2))
            if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0 and (lat != 0.0 or lon != 0.0):
                return lat, lon
    except Exception as exc:
        _log.warning("grounding_string_catch_failed_async", address=address, error=str(exc))
    return None, None


def synthesize_harvest_property(
    address: str,
    research: dict[str, Any],
    market_city: str,
    *,
    model: str | None = None,
    user_id: str | None = None,
    geospatial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Stage 4 (Synthesis): Investment summary from research + property value data.
    Model chain: gemini-3.1-flash-lite-preview -> gemini-3.5-flash -> gemma-4-26b-a4b-it.
    """
    raw, _active_model = _generate_synthesis_with_model_chain(
        research,
        market_city,
        model=model,
        user_id=user_id,
    )

    lat = geospatial.get("latitude") if geospatial else research.get("latitude")
    lon = geospatial.get("longitude") if geospatial else research.get("longitude")
    discovery_model = research.get("discovery_model")
    if _needs_coordinate_catch(discovery_model, lat, lon):
        catch_lat, catch_lon = _resolve_missing_coordinates_with_grounding_sync(address)
        if catch_lat is not None and catch_lon is not None:
            if not geospatial:
                geospatial = {}
            geospatial["latitude"] = catch_lat
            geospatial["longitude"] = catch_lon
            geospatial["geocode_confidence"] = "medium"
            geospatial["geocode_source"] = "synthesis_grounding_catch"
            geospatial["geocode_model"] = COORDINATE_CATCH_MODEL

    return _finalize_synthesis_payload(
        address,
        research,
        market_city,
        _extract_json(raw),
        geospatial=geospatial,
    )


async def synthesize_harvest_property_async(
    address: str,
    research: dict[str, Any],
    market_city: str,
    *,
    model: str | None = None,
    user_id: str | None = None,
    rate_limiter: ModelRateLimiter | None = None,
    session: GenaiSession | None = None,
    geospatial: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Async Stage 3 synthesis for parallel harvester workers."""
    prompt = _synthesis_prompt(research, market_city, user_id=user_id)
    last_error: BaseException | None = None
    raw = ""
    for active_model in _synthesis_models_to_try(model):
        try:
            raw = await generate_with_retry_async(
                active_model,
                prompt,
                use_search=False,
                rate_limiter=rate_limiter,
                session=session,
            )
            break
        except errors.ClientError as exc:
            last_error = exc
            if is_daily_quota_exhausted(exc):
                _log.warning(
                    "synthesis_model_fallback",
                    from_model=active_model,
                    error=str(exc),
                )
                continue
            raise
    else:
        raise RuntimeError(
            f"Synthesis failed for all models in {SYNTHESIS_MODEL_CHAIN}"
        ) from last_error

    lat = geospatial.get("latitude") if geospatial else research.get("latitude")
    lon = geospatial.get("longitude") if geospatial else research.get("longitude")
    discovery_model = research.get("discovery_model")
    if _needs_coordinate_catch(discovery_model, lat, lon):
        catch_lat, catch_lon = await _resolve_missing_coordinates_with_grounding_async(
            address, session=session, rate_limiter=rate_limiter
        )
        if catch_lat is not None and catch_lon is not None:
            if not geospatial:
                geospatial = {}
            geospatial["latitude"] = catch_lat
            geospatial["longitude"] = catch_lon
            geospatial["geocode_confidence"] = "medium"
            geospatial["geocode_source"] = "synthesis_grounding_catch"
            geospatial["geocode_model"] = COORDINATE_CATCH_MODEL

    return _finalize_synthesis_payload(
        address,
        research,
        market_city,
        _extract_json(raw),
        geospatial=geospatial,
    )


def enrich_with_forecast(property_data: dict[str, Any]) -> dict[str, Any]:
    """Attach appreciation forecast and AI fee defaults."""
    if property_data.get("vacancy_rate") is not None:
        vacancy = normalize_percent_rate(safe_float(property_data["vacancy_rate"]))
    else:
        vacancy = normalize_percent_rate(
            safe_float(property_data.get("ai_vacancy_rate", 5.0))
        )
    if property_data.get("management_fee") is not None:
        mgmt = normalize_percent_rate(safe_float(property_data["management_fee"]))
    else:
        mgmt = normalize_percent_rate(
            safe_float(property_data.get("ai_management_fee", 10.0))
        )

    property_data["ai_vacancy_rate"] = vacancy
    property_data["ai_management_fee"] = mgmt

    forecast = calculate_10yr_appreciation(
        safe_float(property_data.get("predicted_value")),
        safe_float(property_data.get("location_score")),
        property_data.get("market_city"),
    )
    property_data["appreciation_forecast"] = forecast["future_value"]
    property_data["forecast_rate"] = forecast["annual_rate"]
    property_data["forecast_growth"] = forecast["total_growth"]
    property_data["forecast_value_p10"] = forecast["future_value_p10"]
    property_data["forecast_value_p90"] = forecast["future_value_p90"]
    property_data["forecast_rate_p10"] = forecast["annual_rate_p10"]
    property_data["forecast_rate_p90"] = forecast["annual_rate_p90"]
    return property_data


def run_harvest_quantum(
    property_data: dict[str, Any],
    monthly_net_cash_flow: float,
) -> float:
    """Run quantum probability and attach score to property_data."""
    result = score_portfolio(
        PortfolioInputs(
            monthly_cash_flow=monthly_net_cash_flow,
            forecast_rate=safe_float(property_data.get("forecast_rate")),
            location_score=safe_float(property_data.get("location_score")),
        )
    )
    property_data["quantum_risk_score"] = result.overall_success_pct
    return result.overall_success_pct


# ---------------------------------------------------------------------------
# Underwriter pipeline (UI — unchanged behavior, env-based client)
# ---------------------------------------------------------------------------


def _comps_context_block(property_data: dict[str, Any]) -> str:
    lines = [
        f"- List price: ${safe_float(property_data.get('price')):,.0f}",
        f"- AI predicted value: ${safe_float(property_data.get('predicted_value')):,.0f}",
    ]
    sqft = int(safe_float(property_data.get("square_footage")))
    if sqft > 0:
        lines.append(f"- Square footage: {sqft:,}")
    year_built = parse_year_built(property_data)
    if year_built:
        lines.append(f"- Year built: {year_built}")
    summary = str(property_data.get("summary") or "").strip()
    if summary:
        lines.append(f"- Listing summary: {summary[:400]}")
    return "\n".join(lines)


def comps_agent(address: str, property_data: dict[str, Any], model: str, num_comps: str = "3 to 5") -> str:
    """Grounded search for structured comparable sales near the subject property."""
    context = _comps_context_block(property_data)
    prompt = f"""Find recent comparable SALES (closed transactions, not active listings) near:
{address}

SUBJECT PROPERTY CONTEXT:
{context}

Requirements:
- Return {num_comps} comps sold within the last 18 months when possible.
- Match property type, beds/baths, square footage (+/- 20%), and neighborhood.
- Prefer sales within 1 mile of the subject.
- Use Zillow sold history, Redfin sold data, Realtor.com, county recorder, or MLS.
- Each comp must have a verified sale price.

Return ONLY JSON:
{{
  "comparable_properties": [
    {{
      "address": "full street address",
      "sale_price": number,
      "sale_date": "YYYY-MM or YYYY-MM-DD",
      "square_footage": number,
      "bedrooms": number,
      "bathrooms": number,
      "property_type": "Single Family | Duplex | Townhome | etc",
      "distance_miles": number,
      "comparison_notes": "how this comp compares to the subject",
      "source_url": "url"
    }}
  ],
  "market_summary": "1-2 sentences on what comps imply for subject value"
}}

No currency symbols or commas outside JSON numbers."""
    return generate_with_retry(model, prompt, use_search=True)


def fetch_comparable_properties(
    address: str,
    property_data: dict[str, Any],
    *,
    model: str | None = None,
    num_comps: str = "3 to 5",
) -> dict[str, Any]:
    """
    Research area comps and attach comps_analysis to a copy of property_data.

    May adjust predicted_value upward when comps show material undervaluation.
    """
    from comps_analysis import property_has_existing_comps

    if property_has_existing_comps(property_data):
        return dict(property_data)

    active_model = model or PRIMARY_SEARCH_MODEL
    raw = comps_agent(address, property_data, active_model, num_comps=num_comps)
    extracted = _extract_json(raw)
    comps_payload = normalize_comps_payload(extracted if isinstance(extracted, dict) else {})
    comps_analysis = evaluate_comps_against_subject(comps_payload, property_data)

    updated = dict(property_data)
    updated["comps_analysis"] = comps_analysis
    if apply_comp_implied_market_value(updated, comps_analysis):
        enriched = enrich_with_forecast(updated)
        updated.update(
            {
                "predicted_value": enriched.get("predicted_value", updated.get("predicted_value")),
                "prediction_reasoning": enriched.get(
                    "prediction_reasoning", updated.get("prediction_reasoning")
                ),
                "appreciation_forecast": enriched.get("appreciation_forecast"),
                "forecast_rate": enriched.get("forecast_rate"),
                "forecast_growth": enriched.get("forecast_growth"),
            }
        )
    return updated


def rent_comps_agent(address: str, property_data: dict[str, Any], model: str) -> str:
    """Grounded search for structured comparable rentals near the subject property."""
    context = _comps_context_block(property_data)
    rent = safe_float(property_data.get("rent"))
    if rent > 0:
        context += f"\n- AI / listing rent: ${rent:,.0f}/mo"
    prompt = f"""Find recent comparable RENTALS (active listings or signed leases) near:
{address}

SUBJECT PROPERTY CONTEXT:
{context}

Requirements:
- Return 3 to 5 comps listed or leased within the last 12 months when possible.
- Match property type, beds/baths, square footage (+/- 20%), and neighborhood.
- Prefer rentals within 1 mile of the subject.
- Use Zillow rentals, Apartments.com, Realtor.com rentals, Craigslist, or MLS lease data.
- Each comp must have a verified monthly rent amount.

Return ONLY JSON:
{{
  "comparable_rentals": [
    {{
      "address": "full street address or building name",
      "monthly_rent": number,
      "lease_date": "YYYY-MM or YYYY-MM-DD",
      "square_footage": number,
      "bedrooms": number,
      "bathrooms": number,
      "property_type": "Single Family | Duplex | Townhome | etc",
      "distance_miles": number,
      "comparison_notes": "how this rental compares to the subject",
      "source_url": "url"
    }}
  ],
  "market_summary": "1-2 sentences on what rental comps imply for subject rent"
}}

No currency symbols or commas outside JSON numbers."""
    return generate_with_retry(model, prompt, use_search=True)


def fetch_rental_comparables(
    address: str,
    property_data: dict[str, Any],
    *,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Research area rental comps and attach rent_comps_analysis to a copy of property_data.

    May adjust rent upward when comps show material upside vs listing/AI rent.
    """
    active_model = model or PRIMARY_SEARCH_MODEL
    raw = rent_comps_agent(address, property_data, active_model)
    extracted = _extract_json(raw)
    rent_payload = normalize_rent_comps_payload(extracted if isinstance(extracted, dict) else {})
    rent_comps_analysis = evaluate_rent_comps_against_subject(rent_payload, property_data)

    updated = dict(property_data)
    updated["rent_comps_analysis"] = rent_comps_analysis
    apply_rent_comps_adjustment(updated, rent_comps_analysis)
    return updated


def researcher_agent(address: str, model: str) -> str:
    prompt = f"""Research the property at {address}.
          CRITICAL: You must cross-reference at least 3 different real estate sources (e.g., Zillow, Redfin, Realtor.com, local MLS) to find the currrent
      listed price of the home. If the property is not currently listed, insert 9999999 as the price of the home.

          Find the following details:
          1. PROPERTY BASICS: Current listing price (or estimated market value), year built, HOA fees, and property type (single-family, duplex, triplex, multifamily, etc.). Read the FULL Zillow/Redfin listing description and agent remarks — not just the summary card.
          2. TAXES: Total Annual Property Tax (including school and local taxes).
          3. RENT (read listing description carefully):
             - First, extract any rent or income explicitly stated in the listing description (e.g. "currently rents for $X", "gross annual rent $X", "tenant paying $X/month", "each unit rents for $X"). Note whether amounts are monthly or annual; if annual, also state the monthly equivalent.
             - For multifamily/duplex/triplex, report TOTAL gross monthly rent for the entire building (sum all units). Do not report rent for only one unit unless the property is single-family.
             - Only if the listing does NOT state rent/income, fall back to Rent Zestimate or comparable rental listings — and note that the estimate assumes single-family unless comps match the property type.
          4. INSURANCE: Monthly insurance costs or local zip code averages.
          5. VALUATION: Recent comparable sales (comps) in the immediate area; preferably 3 properties. Comps must be properties with similar characteristics (size, age, location). Provide the names of the properties you used to determine the comps, their
      sale prices, and how they compare to the target property.
          6. MARKET METRICS: Average vacancy rate and standard property management fees for this neighborhood.
          7. Local news or factors that could impact the property's value (e.g., new developments, school ratings, crime rates).

          Return the raw findings and explicitly list every URL you visited for verification."""

    return generate_with_retry(model, prompt, use_search=True)


def analyzer_agent(
    address: str, research_data: str, model: str, kb_context: str
) -> str:
    prompt = f"""You are an expert real estate analyst. Your goal is to provide a comprehensive underwrite for the property at {address}.
    
    CONTEXT FROM DATABASE:
    {kb_context}
    (Only use properties analyzed within the past 6 months for comparison).

    RESEARCH DATA:
    {research_data}
    If the price given is 9999999, it means the property is not currently listed and you must use the comps and market data to estimate a realistic listing price. Do not leave the price as 9999999 in your final JSON output.

    RENT (critical):
    - If the research cites rent or income from the listing description, use that as "rent" (monthly gross for the whole property). Convert annual amounts to monthly (/12). Sum per-unit rents for multifamily/duplex/triplex.
    - Do NOT use a single-family Rent Zestimate when the property is multifamily or when the listing already states rent/income.
    - Only estimate from comps/zestimates when the listing provides no rent/income data.

    OUTPUT FORMAT:
    Return ONLY a JSON object with these keys:
    {{
        "price": number,
        "year": number, (4-digit year BUILT — e.g. 1968 — NOT property age in years),
        "rent": number,
        "tax_rate": number, (Annual Tax / Price * 100 as a PERCENT value — e.g. 3.4 for 3.4%, NOT 0.034),
        "hoa": number,
        "insurance": number, (Monthly cost - if research provides annual, divide by 12 (it's likely annual amount if the value is above $400))),
        "summary": "3-4 sentence summary of condition, features, and any 'TLC' or 'Updated' notes",
        "maint_percent": number, (New <5yr: 1-2%, Mid 10-25yr: 2-4%, Old 30+yr: 4-6%. Adjust for condition),
        "predicted_value": number, If the property listed price is much below the comps, use the comps to predict a more accurate value. If the property is listed at or above comps, provide a predicted value based on the listing price and justify it with the research data. Do not simply repeat the listing price as the predicted value if it is not supported by the comps and market data.
        "prediction_reasoning": "1-2 sentence explanation based on the comps found. You MUST cite specific data points and property names from the research data to justify the valuation.",
        "location_score": number, (0-10 based on transit/schools),
        "vacancy_rate": number, (vacancy reserve as PERCENT of rent — e.g. 6 for 6%, NOT 0.06; typical 3-10, minimum 1),
        "management_fee": number, (management fee as PERCENT of rent — e.g. 10 for 10%, NOT 0.10; typical 8-12, minimum 1),
        "property_label": "A dynamic label describing the property (e.g., 'Cash-flower' - if cashflow above 8%, 'Appreciation Machine' if greater than 4%, 'Value-Add Play' if description says TLC or somethng like that, 'High-Risk Speculation' if cashflow below 4% and appreciation is below 2%) based on the financial metrics",
        "sources": ["list of URLs used"]
    }}
    IMPORTANT: No currency symbols, no commas, no markdown prose outside the JSON. The 'price' should be the active listing price; if unavailable, use the most recent sale price or a reliable market estimate found in the research."""

    return generate_with_retry(model, prompt, use_search=False)


def get_initial_analysis(address: str) -> tuple[dict[str, Any], bool, str | None]:
    """Stage 1: Fast research and basic analysis for immediate display."""
    cached = lookup_property(address)
    if cached:
        return cached, True, None

    research_results = researcher_agent(address, PRIMARY_SEARCH_MODEL)
    kb_context = get_kb_context()
    analysis_results = analyzer_agent(
        address, research_results, SYNTHESIS_MODEL, kb_context
    )

    extracted = _extract_json(analysis_results)
    if extracted is None or not isinstance(extracted, dict):
        return (
            {
                "price": 0,
                "summary": "AI failed to generate a valid analysis. Please try again.",
                "location_score": 0,
                "predicted_value": 0,
            },
            False,
            research_results,
        )

    _sanitize_synthesis_numerics(extracted)
    canonicalize_year_built_fields(extracted)
    return extracted, False, research_results


def get_final_analysis(
    initial_data: dict[str, Any],
    address: str,
    research_results: str | None = None,
    *,
    skip_comps: bool = False,
) -> dict[str, Any]:
    """Stage 2: Verification, comps cross-check, detailed mapping, and forecasting."""
    property_data = backfill_year_built_if_needed(dict(initial_data), address)
    canonicalize_year_built_fields(property_data)
    if not property_data.get("sources"):
        property_data["sources"] = [
            f"https://www.google.com/search?q={address.replace(' ', '+')}"
        ]

    from comps_analysis import property_has_existing_comps

    if not skip_comps and not property_has_existing_comps(property_data):
        try:
            property_data = fetch_comparable_properties(address, property_data)
        except Exception as exc:
            _log.warning("comps_fetch_failed", address=address, error=str(exc))

    if not _has_precise_coordinates(
        property_data.get("latitude"),
        property_data.get("longitude"),
    ):
        try:
            geospatial = run_geospatial_enrichment(
                address,
                market_city=str(property_data.get("market_city") or ""),
            )
            property_data = attach_geospatial_to_property(property_data, geospatial)
        except Exception as exc:
            _log.warning("geospatial_enrichment_failed", address=address, error=str(exc))
        if not _has_precise_coordinates(
            property_data.get("latitude"),
            property_data.get("longitude"),
        ):
            local_lat, local_lon = _local_coordinate_fallback(
                address,
                market_city=str(property_data.get("market_city") or ""),
                zip_code=str(property_data.get("zip_code") or "") or None,
            )
            if local_lat is not None and local_lon is not None:
                property_data = attach_geospatial_to_property(
                    property_data,
                    {
                        "latitude": local_lat,
                        "longitude": local_lon,
                        "geocode_confidence": "low",
                        "geocode_source": "local_fallback",
                    },
                )

    enriched = enrich_with_forecast(property_data)
    return attach_data_provenance(
        ensure_comps_analysis_field(enriched),
        pipeline="underwriter_ui",
    )


def _portfolio_inputs_from_legacy(
    *args: float, **kwargs: float
) -> PortfolioInputs:
    """Parse cash_flow, forecast_rate, location_score from positional/kw args."""
    cash_flow = 0.0
    forecast_rate = 0.0
    location_score = 0.0

    if len(args) == 1:
        location_score = float(args[0])
    elif len(args) == 2:
        cash_flow = float(args[0])
        forecast_rate = float(args[1])
    elif len(args) >= 3:
        cash_flow = float(args[0])
        forecast_rate = float(args[1])
        location_score = float(args[2])

    if "cash_flow" in kwargs:
        cash_flow = float(kwargs["cash_flow"])
    if "forecast_rate" in kwargs:
        forecast_rate = float(kwargs["forecast_rate"])
    if "location_score" in kwargs:
        location_score = float(kwargs["location_score"])

    return PortfolioInputs(
        monthly_cash_flow=cash_flow,
        forecast_rate=forecast_rate,
        location_score=location_score,
    )


def _quantum_risk_cache_key(
    cash_flow: float, forecast_rate: float, location_score: float
) -> tuple[float, float, float]:
    """Stable cache key aligned with ``finance_task_signature`` rounding."""
    return (round(cash_flow, 2), round(forecast_rate, 4), round(location_score, 2))


def calculate_quantum_risk(*args: float, **kwargs: float) -> dict[str, float]:
    """Backward-compatible wrapper around :func:`quantum_portfolio.score_portfolio`."""
    inputs = _portfolio_inputs_from_legacy(*args, **kwargs)
    cash_flow, forecast_rate, location_score = _quantum_risk_cache_key(
        inputs.monthly_cash_flow,
        inputs.forecast_rate,
        inputs.location_score,
    )
    return dict(_cached_quantum_risk(cash_flow, forecast_rate, location_score))


@lru_cache(maxsize=256)
def _cached_quantum_risk(
    cash_flow: float, forecast_rate: float, location_score: float
) -> dict[str, float]:
    return score_portfolio(
        PortfolioInputs(
            monthly_cash_flow=cash_flow,
            forecast_rate=forecast_rate,
            location_score=location_score,
        )
    ).to_dict()


def clear_quantum_risk_cache() -> None:
    """Reset memoized QAOA scores (e.g. before tests that patch the optimizer)."""
    _cached_quantum_risk.cache_clear()


def calculate_quantum_probability(*args: float, **kwargs: float) -> float:
    """
    Simulates investment success via QAOA. Returns the weighted overall success score.
    Use calculate_quantum_risk() for cash-flow and appreciation breakdowns.
    """
    return score_portfolio(
        _portfolio_inputs_from_legacy(*args, **kwargs)
    ).overall_success_pct
