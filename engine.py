from __future__ import annotations

import contextvars
import json
import os
import random
import re
import time
from dataclasses import dataclass
from datetime import date
from typing import Any

from google import genai
from google.genai import errors, types
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from scipy.optimize import minimize

from app_logging import get_logger, report_error
from finance import (
    calculate_10yr_appreciation,
    normalize_monthly_insurance,
    normalize_percent_rate,
    normalize_tax_rate_percent,
)
from knowledge_base import get_kb_context, lookup_property

_log = get_logger("engine")

# --- Model routing (harvester + underwriter) ---
DISCOVERY_MODEL = "gemini-2.5-flash"
DISCOVERY_FALLBACK_MODEL = "gemma-4-26b-a4b-it"
RESEARCH_MODEL = "gemma-4-31b-it"
SYNTHESIS_MODEL = "gemini-3.1-flash-lite-preview"
SYNTHESIS_FALLBACK_MODEL = "gemma-4-26b-a4b-it"

# Underwriter search failover (UI path)
PRIMARY_SEARCH_MODEL = "gemma-4-31b-it"
SECONDARY_SEARCH_MODEL = "gemini-2.5-flash"

# (market_key, search scope for prompt, per-market target when topping up)
HOT_MARKETS: list[tuple[str, str, int]] = [
    (
        "Rochester",
        "Rochester NY metro (city + suburbs: Henrietta, Penfield, Fairport, Pittsford, "
        "Webster, Greece, Irondequoit, Brighton, Victor, Canandaigua)",
        6,
    ),
    (
        "Syracuse",
        "Syracuse NY metro (city + suburbs: Camillus, Liverpool, DeWitt, Fayetteville, "
        "Cicero, Clay, Baldwinsville, Manlius)",
        4,
    ),
    (
        "Charlotte",
        "Charlotte NC metro (city + suburbs: Concord, Matthews, Huntersville, Mint Hill, "
        "Indian Trail, Pineville, Mooresville)",
        3,
    ),
    (
        "Raleigh",
        "Raleigh NC metro (city + suburbs: Cary, Apex, Morrisville, Wake Forest, "
        "Holly Springs, Garner, Fuquay-Varina)",
        3,
    ),
    (
        "Charleston",
        "Charleston SC metro (city + suburbs: Mount Pleasant, Summerville, North Charleston, "
        "Goose Creek, James Island, Johns Island)",
        2,
    ),
    (
        "Ohio",
        "Ohio metros (Cleveland, Columbus, Cincinnati and suburbs: Lakewood, Parma, Dublin, "
        "Westerville, Mason, Fairfield, Hamilton)",
        3,
    ),
    (
        "DFW",
        "Dallas–Fort Worth TX metro (Dallas, Fort Worth, Arlington, Plano, Frisco, Irving, "
        "Garland, McKinney, Denton)",
        2,
    ),
    (
        "Austin",
        "Austin TX metro (city + suburbs: Round Rock, Cedar Park, Pflugerville, Georgetown, "
        "Leander, Kyle, Buda)",
        2,
    ),
]
DISCOVERY_MARKET_KEYS = frozenset(name for name, _, _ in HOT_MARKETS)
MAX_DISCOVERY_LISTINGS = 25
MAX_DISCOVERY_PRICE = 250_000
MAX_SYNTHESIS_PRICE = 400_000
MAX_API_RETRIES = 5
BACKOFF_BASE_SEC = 4.0
BACKOFF_MAX_SEC = 60.0
BACKOFF_MULTIPLIER = 2.0
# Upper bound for fixed sleeps; prefer retry_delay_seconds() for retries.
RATE_LIMIT_BACKOFF_SEC = BACKOFF_MAX_SEC


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

        return st.secrets["GEMINI_API_KEY"]
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


def _extract_response_text(response: Any) -> str:
    """Read model text safely; grounded responses sometimes omit response.text."""
    try:
        text = response.text
        if text:
            return text
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
            return json.loads(candidate)
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
    ("syracuse", "Syracuse"),
    ("camillus", "Syracuse"),
    ("liverpool", "Syracuse"),
    ("dewitt", "Syracuse"),
    ("fayetteville", "Syracuse"),
    ("cicero", "Syracuse"),
    ("clay", "Syracuse"),
    ("baldwinsville", "Syracuse"),
    ("manlius", "Syracuse"),
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
    return {"address": address, "city": city, "list_price": list_price}


def _parse_discovery_fallback(text: str) -> list[dict[str, Any]]:
    """Parse plain-text address lines when JSON discovery fails."""
    results: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip().lstrip("-•*0123456789.) ")
        if len(line) < 10 or "," not in line:
            continue
        city = _infer_discovery_city(line, "")
        if city:
            results.append({"address": line, "city": city, "list_price": 0.0})
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
        if item["list_price"] <= max_price or item["list_price"] == 0:
            unique.append(item)
    return unique[:limit]


def _build_listings_from_raw(raw: str, max_price: float) -> list[dict[str, Any]]:
    """Parse and normalize discovery model output into listing dicts."""
    parsed = _extract_json(raw)
    listings: list[dict[str, Any]] = []
    for item in _coerce_discovery_list(parsed):
        normalized = _normalize_discovery_item(item)
        if normalized:
            listings.append(normalized)

    if not listings:
        listings = _parse_discovery_fallback(raw)

    return _dedupe_discovery_listings(listings, max_price=max_price)


def _discovery_prompt(
    max_price: float,
    *,
    split_market: str | None = None,
    exclude_addresses: list[str] | None = None,
) -> str:
    """Build a grounded-search discovery prompt."""
    if split_market:
        city, location, count = next(
            (name, loc, target)
            for name, loc, target in HOT_MARKETS
            if name == split_market
        )
        scope = f"{count} residential properties CURRENTLY FOR SALE in {location}"
    else:
        markets_desc = ", ".join(
            f"{count} in {location}" for _, location, count in HOT_MARKETS
        )
        scope = f"residential properties CURRENTLY FOR SALE: {markets_desc}"

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
    priority_note = (
        "Search priority: fill Upstate NY (Rochester, Syracuse) first, then Charlotte, "
        "Raleigh, Charleston, Ohio, DFW, and Austin metros."
    )
    if split_market:
        priority_note = (
            f"Focus this search on {location} only — include city proper AND surrounding "
            "suburbs listed in the scope (do not limit to downtown/city limits)."
        )

    return f"""You are a real estate discovery agent for US hot rental markets.

Use Google Search to find {scope}.
Each listing price must be strictly under ${max_price:,.0f}.
{priority_note}

Return ONLY a JSON array (no markdown, no commentary). Example:
[
  {{"address": "123 Main St, Henrietta, NY 14623", "city": "Rochester", "list_price": 189000}},
  {{"address": "456 Oak Ave, Penfield, NY 14526", "city": "Rochester", "list_price": 175000}},
  {{"address": "789 Elm Dr, Cary, NC 27511", "city": "Raleigh", "list_price": 245000}}
]

Rules:
- Search Zillow, Redfin, Realtor.com, or MLS listing pages for active for-sale homes.
- Include suburbs and townships — not just the core city (e.g. Henrietta/Penfield/Fairport
  count as Rochester; Cary/Apex count as Raleigh).
- You MUST return {MAX_DISCOVERY_LISTINGS} distinct listings when possible. Do not stop at 7–13.
- Use real street addresses with city/town, state, and ZIP when available.
- list_price must be the active asking price as a plain number (no $ or commas).
- city must be the parent metro key: one of {market_keys} (NOT the suburb name).{exclude_block}"""


def _run_discovery_attempt(
    *,
    model: str,
    max_price: float,
    split_market: str | None = None,
    exclude_addresses: list[str] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    prompt = _discovery_prompt(
        max_price,
        split_market=split_market,
        exclude_addresses=exclude_addresses,
    )
    raw = generate_with_retry(
        model,
        prompt,
        use_search=_model_supports_grounding(model),
    )
    listings = _build_listings_from_raw(raw, max_price)
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


def parse_year_built(property_info: dict[str, Any]) -> int | None:
    """Extract construction year from year_built or year fields."""
    for key in ("year_built", "year"):
        raw = property_info.get(key)
        if raw is None:
            continue
        year = safe_float(raw, default=0.0)
        if year >= 1800:
            return int(year)
    return None


def calculate_property_age_years(property_info: dict[str, Any]) -> int | None:
    """Years since the property was built (today minus built date)."""
    year = parse_year_built(property_info)
    if year is None:
        return None
    built_date = date(year, 1, 1)
    today = date.today()
    age = today.year - built_date.year - (
        (today.month, today.day) < (built_date.month, built_date.day)
    )
    return max(age, 0)


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


def _discover_listings_for_model(
    *,
    model: str,
    max_price: float,
    exclude_addresses: list[str] | None,
) -> tuple[list[dict[str, Any]], str]:
    """Run combined discovery, then top up per market until MAX_DISCOVERY_LISTINGS."""
    listings, last_raw = _run_discovery_attempt(
        model=model,
        max_price=max_price,
        exclude_addresses=exclude_addresses,
    )
    deduped = _dedupe_discovery_listings(listings, max_price=max_price)
    if len(deduped) >= MAX_DISCOVERY_LISTINGS:
        return deduped, last_raw

    if deduped:
        _log.info(
            "discovery_partial_combined",
            model=model,
            count=len(deduped),
            target=MAX_DISCOVERY_LISTINGS,
        )
        print(
            f"[discovery] Combined search returned {len(deduped)}/{MAX_DISCOVERY_LISTINGS} "
            f"listings on {model}; topping up per market..."
        )
    else:
        _log.warning(
            "discovery_empty_combined",
            model=model,
            raw_preview=last_raw[:400],
        )
        print(
            f"[discovery] Combined search returned 0 listings on {model}; "
            "retrying per market..."
        )

    split_listings = list(deduped)
    for market_name, _, _ in HOT_MARKETS:
        if len(split_listings) >= MAX_DISCOVERY_LISTINGS:
            break
        found_addrs = [str(item.get("address", "")) for item in split_listings]
        merged_exclude = list(exclude_addresses or []) + found_addrs
        market_listings, market_raw = _run_discovery_attempt(
            model=model,
            max_price=max_price,
            split_market=market_name,
            exclude_addresses=merged_exclude,
        )
        last_raw = market_raw or last_raw
        split_listings.extend(market_listings)
        split_listings = _dedupe_discovery_listings(split_listings, max_price=max_price)

    return split_listings, last_raw


def discover_hot_market_listings(
    max_price: float = MAX_DISCOVERY_PRICE,
    *,
    model: str | None = None,
    exclude_addresses: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Stage 1 (Discovery): Search Grounding across prioritized hot markets.
    Returns up to MAX_DISCOVERY_LISTINGS listings (< max_price).
    """
    primary_model = model or DISCOVERY_MODEL
    models_to_try = [primary_model]
    if primary_model == DISCOVERY_MODEL and DISCOVERY_FALLBACK_MODEL not in models_to_try:
        models_to_try.append(DISCOVERY_FALLBACK_MODEL)

    last_raw = ""
    for active_model in models_to_try:
        try:
            listings, last_raw = _discover_listings_for_model(
                model=active_model,
                max_price=max_price,
                exclude_addresses=exclude_addresses,
            )
        except _DISCOVERY_API_ERRORS as exc:
            fallback = models_to_try[-1]
            if is_daily_quota_exhausted(exc) and active_model != fallback:
                _log.warning(
                    "discovery_quota_fallback",
                    from_model=active_model,
                    to_model=fallback,
                    error=str(exc),
                )
                print(
                    f"[discovery] {active_model} daily quota exhausted; "
                    f"switching to {fallback}..."
                )
                continue
            raise

        if listings:
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
        if active_model != models_to_try[-1]:
            print(
                f"[discovery] No listings from {active_model}; "
                f"trying fallback model {models_to_try[-1]}..."
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


def research_property(address: str) -> dict[str, Any]:
    """
    Stage 2 (Research): Gemma extraction with Search Grounding.
    """
    prompt = f"""Research the residential property at: {address}

Use live listing search results (Zillow, Redfin, Realtor.com, MLS, county records).
Read the FULL listing description and agent remarks — not just headline stats or Rent Zestimate.

Extract ONLY these fields:
- price (current list price USD, number only)
- taxes (total ANNUAL property tax USD)
- hoa (monthly HOA fee USD, 0 if none)
- square_footage (integer)
- property_condition: exactly one of "Excellent", "Good", "Fair", "Poor"
- property_type: e.g. "Single Family", "Duplex", "Triplex", "Multi-Family", "Mixed Use"
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
  "square_footage": number,
  "property_condition": "Good",
  "property_type": "Single Family",
  "stated_gross_monthly_rent": 0,
  "listing_rent_notes": ""
}}"""

    raw = generate_with_retry(
        RESEARCH_MODEL,
        prompt,
        use_search=_model_supports_grounding(RESEARCH_MODEL),
    )
    data = _extract_json(raw)
    if not isinstance(data, dict):
        return {
            "address": address,
            "price": 0.0,
            "taxes": 0.0,
            "hoa": 0.0,
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
    data["square_footage"] = int(safe_float(data.get("square_footage")))
    condition = str(data.get("property_condition", "Unknown")).strip()
    data["property_condition"] = condition
    data["property_type"] = str(data.get("property_type", "Unknown")).strip() or "Unknown"
    data["stated_gross_monthly_rent"] = safe_float(data.get("stated_gross_monthly_rent"))
    data["listing_rent_notes"] = str(data.get("listing_rent_notes", "")).strip()
    return data


def should_skip_synthesis(research: dict[str, Any]) -> bool:
    """Skip Stage 3 if condition is Poor, price is missing, or price exceeds cap."""
    condition = str(research.get("property_condition", "")).strip().lower()
    price = safe_float(research.get("price"))
    return condition == "poor" or price <= 0 or price > MAX_SYNTHESIS_PRICE


def synthesize_harvest_property(
    address: str,
    research: dict[str, Any],
    market_city: str,
    *,
    model: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Stage 3 (Synthesis): Investment summary from research data only.
    """
    kb_context = get_kb_context(user_id)
    prompt = f"""You are an expert real estate underwriter for {market_city} hot market investments.

CONTEXT FROM DATABASE:
{kb_context}

RESEARCH DATA (verified extraction):
{json.dumps(research, indent=2)}

Produce a complete investment underwriting. Use research price/taxes/hoa/sqft as anchors.

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

    raw = generate_with_retry(model or SYNTHESIS_MODEL, prompt, use_search=False)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        price = safe_float(research.get("price"))
        taxes = safe_float(research.get("taxes"))
        data = {
            "price": price,
            "year": 1980,
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

    data["address"] = address
    data["market_city"] = market_city
    data["square_footage"] = data.get("square_footage", research.get("square_footage"))
    data["property_condition"] = data.get(
        "property_condition", research.get("property_condition")
    )
    _sanitize_synthesis_numerics(data)
    return enrich_with_forecast(data)


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
    )
    property_data["appreciation_forecast"] = forecast["future_value"]
    property_data["forecast_rate"] = forecast["annual_rate"]
    property_data["forecast_growth"] = forecast["total_growth"]
    return property_data


def run_harvest_quantum(
    property_data: dict[str, Any],
    monthly_net_cash_flow: float,
) -> float:
    """Run quantum probability and attach score to property_data."""
    score = calculate_quantum_probability(
        monthly_net_cash_flow,
        safe_float(property_data.get("forecast_rate")),
        safe_float(property_data.get("location_score")),
    )
    property_data["quantum_risk_score"] = score
    return score


# ---------------------------------------------------------------------------
# Underwriter pipeline (UI — unchanged behavior, env-based client)
# ---------------------------------------------------------------------------


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
        "year": number,
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
    return extracted, False, research_results


def get_final_analysis(
    initial_data: dict[str, Any],
    address: str,
    research_results: str | None = None,
) -> dict[str, Any]:
    """Stage 2: Verification, detailed mapping, and forecasting."""
    property_data = dict(initial_data)
    property_data["sources"] = [
        f"https://www.google.com/search?q={address.replace(' ', '+')}"
    ]
    return enrich_with_forecast(property_data)


def _parse_quantum_inputs(
    *args: float, **kwargs: float
) -> tuple[float, float, float]:
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

    return cash_flow, forecast_rate, location_score


def _success_targets(
    cash_flow: float, forecast_rate: float, location_score: float
) -> tuple[float, float, float]:
    """
    Map investment inputs to [0, 1] success targets for each QAOA qubit.

    Negative or zero cash flow targets 0 (cash-flow qubit should stay |0⟩).
    """
    if cash_flow <= 0:
        cf_t = 0.0
    else:
        cf_t = min(cash_flow / 800.0, 1.0)

    rate_t = min(max(forecast_rate / 8.0, 0.0), 1.0)
    loc_t = min(max(location_score / 10.0, 0.0), 1.0)
    return cf_t, rate_t, loc_t


def _probabilities_from_measurement_counts(
    counts: dict[str, int],
    *,
    cf_t: float,
    rate_t: float,
    loc_t: float,
) -> dict[str, float]:
    """
    Derive interpretable success probabilities from QAOA bitstrings.

    Qubit 0 = cash flow, qubit 1 = appreciation, qubit 2 = location.
    Each score scales the measured |1⟩ probability by the input target so
    negative cash flow cannot produce a high cash-flow success rate.
    """
    total = sum(counts.values()) or 1
    exp_x0 = exp_x1 = exp_x2 = 0.0

    for state_str, count in counts.items():
        prob = count / total
        bits = state_str.zfill(3)
        exp_x0 += prob * (bits[2] == "1")
        exp_x1 += prob * (bits[1] == "1")
        exp_x2 += prob * (bits[0] == "1")

    cf_pct = 100.0 * cf_t * exp_x0
    app_pct = 100.0 * rate_t * exp_x1
    loc_pct = 100.0 * loc_t * exp_x2
    combined = 100.0 * cf_t * rate_t * exp_x0 * exp_x1
    overall = 0.45 * cf_pct + 0.35 * app_pct + 0.20 * loc_pct

    return {
        "cashflow_success_pct": min(max(cf_pct, 0.0), 100.0),
        "appreciation_success_pct": min(max(app_pct, 0.0), 100.0),
        "location_success_pct": min(max(loc_pct, 0.0), 100.0),
        "combined_wealth_success_pct": min(max(combined, 0.0), 100.0),
        "overall_success_pct": min(max(overall, 0.0), 100.0),
    }


def calculate_quantum_risk(*args, **kwargs) -> dict[str, float]:
    """
    QAOA simulation returning cash-flow, appreciation, and combined wealth success odds.

    Each qubit encodes whether a dimension (cash flow, appreciation, location) aligns
    with investment success. Input targets drive the cost Hamiltonian; negative cash
    flow forces the cash-flow qubit toward |0⟩ so success scores stay near 0%.
    """
    cash_flow, forecast_rate, location_score = _parse_quantum_inputs(*args, **kwargs)
    cf_t, rate_t, loc_t = _success_targets(cash_flow, forecast_rate, location_score)

    if cf_t == 0.0 and rate_t == 0.0 and loc_t == 0.0:
        return {
            "cashflow_success_pct": 0.0,
            "appreciation_success_pct": 0.0,
            "location_success_pct": 0.0,
            "combined_wealth_success_pct": 0.0,
            "overall_success_pct": 0.0,
        }

    # Legacy single-metric path (location score only)
    if cf_t == 0.0 and rate_t == 0.0 and location_score > 0:
        loc_pct = loc_t * 100.0
        return {
            "cashflow_success_pct": loc_pct,
            "appreciation_success_pct": loc_pct,
            "location_success_pct": loc_pct,
            "combined_wealth_success_pct": loc_pct,
            "overall_success_pct": loc_pct,
        }

    def compute_cost(x0: int, x1: int, x2: int) -> float:
        misalignment = (
            (cf_t - x0) ** 2 + (rate_t - x1) ** 2 + (loc_t - x2) ** 2
        )
        coupling = 0.15 * ((x0 - x1) ** 2 + (x1 - x2) ** 2)
        return misalignment + coupling

    def build_qaoa_circuit(gamma: float, beta: float) -> QuantumCircuit:
        qc = QuantumCircuit(3)
        qc.h([0, 1, 2])
        for i, target in enumerate([cf_t, rate_t, loc_t]):
            qc.rz(gamma * (2.0 * target - 1.0), i)
        qc.rzz(-0.15 * gamma, 0, 1)
        qc.rzz(-0.15 * gamma, 1, 2)
        for i in range(3):
            qc.rx(2 * beta, i)
        return qc

    gamma_bounds = (0.0, 3.14159)
    beta_bounds = (0.0, 1.57079)
    optimize_shots = 256
    final_shots = 1024
    simulator = AerSimulator()

    def clip_gamma_beta(params: list[float] | tuple[float, ...]) -> tuple[float, float]:
        gamma = min(max(float(params[0]), gamma_bounds[0]), gamma_bounds[1])
        beta = min(max(float(params[1]), beta_bounds[0]), beta_bounds[1])
        return gamma, beta

    def cost_function(params: list[float] | tuple[float, ...]) -> float:
        gamma, beta = clip_gamma_beta(params)
        qc_measure = build_qaoa_circuit(gamma, beta).copy()
        qc_measure.measure_all()
        compiled_circuit = transpile(qc_measure, simulator)
        job = simulator.run(
            compiled_circuit, shots=optimize_shots, seed_simulator=42
        )
        counts = job.result().get_counts()
        total = sum(counts.values()) or 1
        expected_cost = 0.0
        for state_str, count in counts.items():
            prob = count / total
            bits = state_str.zfill(3)
            x2 = int(bits[0])
            x1 = int(bits[1])
            x0 = int(bits[2])
            expected_cost += prob * compute_cost(x0, x1, x2)
        return expected_cost

    initial_params = [1.04719, 0.52359]
    final_gamma, final_beta = clip_gamma_beta(initial_params)

    try:
        opt_result = minimize(
            cost_function,
            x0=initial_params,
            method="COBYLA",
            options={"maxiter": 30, "rhobeg": 0.35},
        )
        final_gamma, final_beta = clip_gamma_beta(opt_result.x)
        if not opt_result.success:
            _log.warning(
                "qaoa_optimizer_did_not_converge",
                message=str(opt_result.message),
                nit=getattr(opt_result, "nit", None),
                final_cost=float(opt_result.fun),
                gamma=final_gamma,
                beta=final_beta,
            )
    except Exception as exc:
        report_error(
            _log,
            "qaoa_optimizer_failed",
            exc,
            gamma=final_gamma,
            beta=final_beta,
        )

    opt_qc = build_qaoa_circuit(final_gamma, final_beta)
    opt_qc.measure_all()
    compiled_circuit = transpile(opt_qc, simulator)
    job = simulator.run(compiled_circuit, shots=final_shots, seed_simulator=42)
    counts = job.result().get_counts()
    return _probabilities_from_measurement_counts(
        counts, cf_t=cf_t, rate_t=rate_t, loc_t=loc_t
    )


def calculate_quantum_probability(*args, **kwargs) -> float:
    """
    Simulates investment success via QAOA. Returns the weighted overall success score.
    Use calculate_quantum_risk() for cash-flow and appreciation breakdowns.
    """
    risk = calculate_quantum_risk(*args, **kwargs)
    return risk["overall_success_pct"]


