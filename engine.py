from __future__ import annotations

import json
import os
import time
from typing import Any

from google import genai
from google.genai import errors, types
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator

from finance import calculate_10yr_appreciation
from knowledge_base import get_kb_context, get_kb_raw_data

# --- Model routing (harvester + underwriter) ---
DISCOVERY_MODEL = "gemini-2.5-flash"
RESEARCH_MODEL = "google/gemma-4-31b-it"
SYNTHESIS_MODEL = "gemini-3.1-flash-lite-preview"

# Underwriter search failover (UI path)
PRIMARY_SEARCH_MODEL = "google/gemma-4-31b-it"
SECONDARY_SEARCH_MODEL = "gemini-2.5-flash"

HOT_MARKETS: list[tuple[str, str, int]] = [
    ("Rochester", "Rochester, NY", 10),
    ("Syracuse", "Syracuse, NY", 10),
]
MAX_DISCOVERY_PRICE = 250_000
MAX_SYNTHESIS_PRICE = 400_000
RATE_LIMIT_BACKOFF_SEC = 60
MAX_API_RETRIES = 5

_client: genai.Client | None = None


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


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=_get_api_key())
    return _client


def generate_with_retry(
    model: str,
    contents: str,
    *,
    use_search: bool = False,
    max_retries: int = MAX_API_RETRIES,
) -> str:
    """Call Gemini with 60s backoff on HTTP 429."""
    config = None
    if use_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = get_client().models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
            return response.text or ""
        except errors.ClientError as e:
            last_error = e
            if e.code == 429:
                print(
                    f"429 rate limit on {model}. "
                    f"Backing off {RATE_LIMIT_BACKOFF_SEC}s "
                    f"(attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(RATE_LIMIT_BACKOFF_SEC)
                continue
            raise
        except (errors.ServerError, errors.APIError) as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(RATE_LIMIT_BACKOFF_SEC)
                continue
            raise

    raise RuntimeError(f"Max retries exceeded for {model}") from last_error


def _extract_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Helper to extract JSON from LLM responses."""
    try:
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        return json.loads(text)
    except (json.JSONDecodeError, IndexError, AttributeError):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "").strip()
        return float(value)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Harvester pipeline (3 stages — single grounded discovery call)
# ---------------------------------------------------------------------------


def discover_hot_market_listings(
    max_price: float = MAX_DISCOVERY_PRICE,
) -> list[dict[str, Any]]:
    """
    Stage 1 (Discovery): ONE Search Grounding call for Rochester + Syracuse.
    Returns up to 20 listings (< max_price).
    """
    markets_desc = ", ".join(
        f"{count} in {location}" for _, location, count in HOT_MARKETS
    )
    prompt = f"""You are a real estate discovery agent for Upstate NY hot markets.

Find residential properties CURRENTLY FOR SALE:
- {markets_desc}
- Each listing price must be strictly under ${max_price:,.0f}

Return ONLY a JSON array (no markdown) with exactly 20 objects when possible:
[
  {{
    "address": "full street address with city and state",
    "city": "Rochester" or "Syracuse",
    "list_price": number
  }}
]

Rules:
- Use live listing data from Zillow, Redfin, Realtor.com, or MLS.
- No duplicates. Real addresses only.
- list_price is the active asking price in USD (no symbols)."""

    raw = generate_with_retry(DISCOVERY_MODEL, prompt, use_search=True)
    parsed = _extract_json(raw)

    listings: list[dict[str, Any]] = []
    if isinstance(parsed, list):
        for item in parsed:
            if not isinstance(item, dict):
                continue
            addr = str(item.get("address", "")).strip()
            if not addr:
                continue
            city = str(item.get("city", "")).strip()
            if city not in ("Rochester", "Syracuse"):
                if "rochester" in addr.lower():
                    city = "Rochester"
                elif "syracuse" in addr.lower():
                    city = "Syracuse"
                else:
                    continue
            listings.append(
                {
                    "address": addr,
                    "city": city,
                    "list_price": _safe_float(item.get("list_price")),
                }
            )

    if not listings:
        listings = _parse_discovery_fallback(raw)

    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in listings:
        key = item["address"].lower()
        if key in seen:
            continue
        seen.add(key)
        if item["list_price"] <= max_price or item["list_price"] == 0:
            unique.append(item)

    return unique[:20]


def _parse_discovery_fallback(text: str) -> list[dict[str, Any]]:
    """Parse plain-text address lines when JSON discovery fails."""
    results: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip().lstrip("-•*0123456789.) ")
        if len(line) < 10 or "," not in line:
            continue
        city = "Rochester" if "rochester" in line.lower() else (
            "Syracuse" if "syracuse" in line.lower() else ""
        )
        if city:
            results.append({"address": line, "city": city, "list_price": 0.0})
    return results


def research_property(address: str) -> dict[str, Any]:
    """
    Stage 2 (Research): Gemma extraction — no Search Grounding (1500 RPD).
    """
    prompt = f"""Research the residential property at: {address}

Extract ONLY these fields from public listing data you know:
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

    raw = generate_with_retry(RESEARCH_MODEL, prompt, use_search=False)
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
    data["price"] = _safe_float(data.get("price"))
    data["taxes"] = _safe_float(data.get("taxes"))
    data["hoa"] = _safe_float(data.get("hoa"))
    data["square_footage"] = int(_safe_float(data.get("square_footage")))
    condition = str(data.get("property_condition", "Unknown")).strip()
    data["property_condition"] = condition
    return data


def should_skip_synthesis(research: dict[str, Any]) -> bool:
    """Skip Stage 3 if condition is Poor or price exceeds cap."""
    condition = str(research.get("property_condition", "")).strip().lower()
    price = _safe_float(research.get("price"))
    return condition == "poor" or price > MAX_SYNTHESIS_PRICE


def synthesize_harvest_property(
    address: str,
    research: dict[str, Any],
    market_city: str,
) -> dict[str, Any]:
    """
    Stage 3 (Synthesis): Investment summary from research data only.
    """
    kb_context = get_kb_context()
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

    raw = generate_with_retry(SYNTHESIS_MODEL, prompt, use_search=False)
    data = _extract_json(raw)
    if not isinstance(data, dict):
        price = _safe_float(research.get("price"))
        taxes = _safe_float(research.get("taxes"))
        data = {
            "price": price,
            "year": 1980,
            "rent": 0.0,
            "tax_rate": (taxes / price * 100) if price > 0 else 0.0,
            "hoa": _safe_float(research.get("hoa")),
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
    return enrich_with_forecast(data)


def enrich_with_forecast(property_data: dict[str, Any]) -> dict[str, Any]:
    """Attach appreciation forecast and AI fee defaults."""
    property_data["ai_vacancy_rate"] = property_data.get("vacancy_rate", 5.0)
    property_data["ai_management_fee"] = property_data.get("management_fee", 10.0)

    forecast = calculate_10yr_appreciation(
        _safe_float(property_data.get("predicted_value")),
        _safe_float(property_data.get("location_score")),
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
        _safe_float(property_data.get("forecast_rate")),
        _safe_float(property_data.get("location_score")),
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
    kb_data = get_kb_raw_data()
    if address in kb_data:
        return kb_data[address], True, None

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


def calculate_quantum_probability(
    cash_flow: float, forecast_rate: float, location_score: float
) -> float:
    """
    Simulates the probability of investment success using a quantum circuit.
    Maps financial metrics to qubit rotations.
    """
    cf_norm = min(max(cash_flow / 1000, 0), 1)
    rate_norm = min(max(forecast_rate / 10, 0), 1)
    loc_norm = location_score / 10

    qc = QuantumCircuit(1)
    qc.ry(cf_norm * 3.14159, 0)
    qc.ry(rate_norm * 3.14159, 0)
    qc.ry(loc_norm * 3.14159, 0)
    qc.measure_all()

    simulator = AerSimulator()
    compiled_circuit = transpile(qc, simulator)
    job = simulator.run(compiled_circuit, shots=1024)
    result = job.result().get_counts()

    success_count = result.get("1", 0)
    return (success_count / 1024) * 100
