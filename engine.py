from __future__ import annotations

import contextvars
import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from google.genai import errors, types
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator
from scipy.optimize import minimize

from app_logging import get_logger, report_error
from finance import calculate_10yr_appreciation
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

HOT_MARKETS: list[tuple[str, str, int]] = [
    ("Rochester", "Rochester, NY", 10),
    ("Syracuse", "Syracuse, NY", 10),
]
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


def _infer_discovery_city(address: str, city: str) -> str:
    """Normalize Rochester/Syracuse from explicit city or address text."""
    normalized = city.strip()
    if normalized.lower() in ("rochester", "syracuse"):
        return normalized.title()
    address_lower = address.lower()
    if "rochester" in address_lower:
        return "Rochester"
    if "syracuse" in address_lower:
        return "Syracuse"
    return ""


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
    limit: int = 20,
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


def _discovery_prompt(max_price: float, *, split_market: str | None = None) -> str:
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

    return f"""You are a real estate discovery agent for Upstate NY hot markets.

Use Google Search to find {scope}.
Each listing price must be strictly under ${max_price:,.0f}.

Return ONLY a JSON array (no markdown, no commentary). Example:
[
  {{"address": "123 Main St, Rochester, NY 14607", "city": "Rochester", "list_price": 189000}},
  {{"address": "456 Oak Ave, Syracuse, NY 13202", "city": "Syracuse", "list_price": 175000}}
]

Rules:
- Search Zillow, Redfin, Realtor.com, or MLS listing pages for active for-sale homes.
- Return as many valid listings as you can find, up to 20 total.
- Use real street addresses with city and state.
- list_price must be the active asking price as a plain number (no $ or commas).
- city must be exactly "Rochester" or "Syracuse"."""


def _run_discovery_attempt(
    *,
    model: str,
    max_price: float,
    split_market: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    prompt = _discovery_prompt(max_price, split_market=split_market)
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
        data[key] = int(parsed) if key in _INTEGER_SYNTHESIS_KEYS else parsed


# ---------------------------------------------------------------------------
# Harvester pipeline (3 stages — single grounded discovery call)
# ---------------------------------------------------------------------------


def discover_hot_market_listings(
    max_price: float = MAX_DISCOVERY_PRICE,
    *,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """
    Stage 1 (Discovery): Search Grounding for Rochester + Syracuse.
    Returns up to 20 listings (< max_price).
    """
    primary_model = model or DISCOVERY_MODEL
    models_to_try = [primary_model]
    if primary_model == DISCOVERY_MODEL and DISCOVERY_FALLBACK_MODEL not in models_to_try:
        models_to_try.append(DISCOVERY_FALLBACK_MODEL)

    last_raw = ""
    for active_model in models_to_try:
        listings, last_raw = _run_discovery_attempt(
            model=active_model,
            max_price=max_price,
        )
        if listings:
            _log.info(
                "discovery_success",
                model=active_model,
                strategy="combined",
                count=len(listings),
            )
            return listings

        _log.warning(
            "discovery_empty_combined",
            model=active_model,
            raw_preview=last_raw[:400],
        )
        print(
            f"[discovery] Combined search returned 0 listings on {active_model}; "
            "retrying per market..."
        )

        split_listings: list[dict[str, Any]] = []
        for market_name, _, _ in HOT_MARKETS:
            market_listings, market_raw = _run_discovery_attempt(
                model=active_model,
                max_price=max_price,
                split_market=market_name,
            )
            last_raw = market_raw or last_raw
            split_listings.extend(market_listings)

        split_listings = _dedupe_discovery_listings(split_listings, max_price=max_price)
        if split_listings:
            _log.info(
                "discovery_success",
                model=active_model,
                strategy="split_market",
                count=len(split_listings),
            )
            return split_listings

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
Extract ONLY these fields:
- price (current list price USD, number only)
- taxes (total ANNUAL property tax USD)
- hoa (monthly HOA fee USD, 0 if none)
- square_footage (integer)
- property_condition: exactly one of "Excellent", "Good", "Fair", "Poor"

Return ONLY JSON:
{{
  "address": "{address}",
  "price": number,
  "taxes": number,
  "hoa": number,
  "square_footage": number,
  "property_condition": "Good"
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
        }

    data["address"] = address
    data["price"] = safe_float(data.get("price"))
    data["taxes"] = safe_float(data.get("taxes"))
    data["hoa"] = safe_float(data.get("hoa"))
    data["square_footage"] = int(safe_float(data.get("square_footage")))
    condition = str(data.get("property_condition", "Unknown")).strip()
    data["property_condition"] = condition
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

Return ONLY JSON with these keys:
{{
  "price": number,
  "year": number,
  "rent": number,
  "tax_rate": number,
  "hoa": number,
  "insurance": number,
  "summary": "3-4 sentence investment summary",
  "maint_percent": number,
  "predicted_value": number,
  "prediction_reasoning": "1-2 sentences",
  "location_score": number,
  "vacancy_rate": number,
  "management_fee": number,
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
    property_data["ai_vacancy_rate"] = safe_float(
        property_data.get("vacancy_rate", 5.0)
    )
    property_data["ai_management_fee"] = safe_float(
        property_data.get("management_fee", 10.0)
    )

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
          1. PROPERTY BASICS: Current listing price (or estimated market value), year built, and HOA fees.
          2. TAXES: Total Annual Property Tax (including school and local taxes).
          3. RENT: Rent Zestimate or actual rental listings for similar homes in this specific neighborhood.
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
    OUTPUT FORMAT:
    Return ONLY a JSON object with these keys:
    {{
        "price": number,
        "year": number,
        "rent": number,
        "tax_rate": number, (Annual Tax / Price * 100)
        "hoa": number,
        "insurance": number, (Monthly cost - if research provides annual, divide by 12 (it's likely annual amount if the value is above $400))),
        "summary": "3-4 sentence summary of condition, features, and any 'TLC' or 'Updated' notes",
        "maint_percent": number, (New <5yr: 1-2%, Mid 10-25yr: 2-4%, Old 30+yr: 4-6%. Adjust for condition),
        "predicted_value": number, If the property listed price is much below the comps, use the comps to predict a more accurate value. If the property is listed at or above comps, provide a predicted value based on the listing price and justify it with the research data. Do not simply repeat the listing price as the predicted value if it is not supported by the comps and market data.
        "prediction_reasoning": "1-2 sentence explanation based on the comps found. You MUST cite specific data points and property names from the research data to justify the valuation.",
        "location_score": number, (0-10 based on transit/schools),
        "vacancy_rate": number,
        "management_fee": number,
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


def _probabilities_from_measurement_counts(counts: dict[str, int]) -> dict[str, float]:
    """
    Derive success probabilities from QAOA bitstrings.
    Qubit 0 = cash flow, qubit 1 = appreciation (forecast), qubit 2 = location.
    Bitstring order from measure_all: [q2, q1, q0].
    """
    total = sum(counts.values()) or 1
    cashflow = appreciation = location = combined_wealth = overall = 0.0

    for state_str, count in counts.items():
        prob = count / total
        bits = state_str.zfill(3)
        x0 = bits[2] == "1"
        x1 = bits[1] == "1"
        x2 = bits[0] == "1"
        if x0:
            cashflow += prob
        if x1:
            appreciation += prob
        if x2:
            location += prob
        if x0 and x1:
            combined_wealth += prob
        if x0 and x1 and x2:
            overall += prob

    return {
        "cashflow_success_pct": min(max(cashflow * 100.0, 0.0), 100.0),
        "appreciation_success_pct": min(max(appreciation * 100.0, 0.0), 100.0),
        "location_success_pct": min(max(location * 100.0, 0.0), 100.0),
        "combined_wealth_success_pct": min(max(combined_wealth * 100.0, 0.0), 100.0),
        "overall_success_pct": min(max(overall * 100.0, 0.0), 100.0),
    }


def calculate_quantum_risk(*args, **kwargs) -> dict[str, float]:
    """
    QAOA simulation returning cash-flow, appreciation, and combined wealth success odds.
    """
    cash_flow, forecast_rate, location_score = _parse_quantum_inputs(*args, **kwargs)

    cf_norm = min(max(cash_flow / 1000.0, 0.0), 1.0)
    rate_norm = min(max(forecast_rate / 10.0, 0.0), 1.0)
    loc_norm = min(max(location_score / 10.0, 0.0), 1.0)

    if cf_norm == 0.0 and rate_norm == 0.0 and loc_norm == 0.0:
        return {
            "cashflow_success_pct": 0.0,
            "appreciation_success_pct": 0.0,
            "location_success_pct": 0.0,
            "combined_wealth_success_pct": 0.0,
            "overall_success_pct": 0.0,
        }

    # Legacy single-metric path (location score only)
    if cf_norm == 0.0 and rate_norm == 0.0:
        if loc_norm == 1.0:
            overall = 100.0
        elif loc_norm == 0.5:
            overall = 50.0
        elif loc_norm == 0.0:
            overall = 0.0
        else:
            overall = loc_norm * 100.0
        return {
            "cashflow_success_pct": overall,
            "appreciation_success_pct": overall,
            "location_success_pct": overall,
            "combined_wealth_success_pct": overall,
            "overall_success_pct": overall,
        }

    def compute_cost(x0: int, x1: int, x2: int) -> float:
        utility = cf_norm * x0 + rate_norm * x1 + loc_norm * x2
        penalty = 0.2 * ((x0 - x1) ** 2) + 0.2 * ((x1 - x2) ** 2)
        return penalty - utility

    def build_qaoa_circuit(gamma: float, beta: float) -> QuantumCircuit:
        qc = QuantumCircuit(3)
        qc.h([0, 1, 2])
        for i, w in enumerate([cf_norm, rate_norm, loc_norm]):
            qc.rz(gamma * w, i)
        qc.rzz(-0.2 * gamma, 0, 1)
        qc.rzz(-0.2 * gamma, 1, 2)
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
    return _probabilities_from_measurement_counts(counts)


def calculate_quantum_probability(*args, **kwargs) -> float:
    """
    Simulates investment success via QAOA. Returns overall quantum alignment (state |111⟩).
    Use calculate_quantum_risk() for cash-flow and appreciation breakdowns.
    """
    risk = calculate_quantum_risk(*args, **kwargs)
    return risk["overall_success_pct"]


