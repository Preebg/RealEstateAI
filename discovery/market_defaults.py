"""Per-market underwriting defaults not scraped from portals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketDefaults:
    vacancy_rate: float
    management_fee: float
    insurance_monthly_default: float


@dataclass(frozen=True, slots=True)
class MarketLocation:
    """Search coordinates for Realtor/Zillow portal queries."""

    search_label: str
    state_code: str
    zillow_bbox: dict[str, float]


# Approximate city bounding boxes for Zillow async search.
MARKET_LOCATIONS: dict[str, MarketLocation] = {
    "Rochester": MarketLocation(
        search_label="Rochester, NY",
        state_code="NY",
        zillow_bbox={"west": -77.72, "east": -77.52, "south": 43.12, "north": 43.25},
    ),
    "Syracuse": MarketLocation(
        search_label="Syracuse, NY",
        state_code="NY",
        zillow_bbox={"west": -76.22, "east": -76.08, "south": 43.00, "north": 43.08},
    ),
    "Buffalo": MarketLocation(
        search_label="Buffalo, NY",
        state_code="NY",
        zillow_bbox={"west": -78.92, "east": -78.78, "south": 42.85, "north": 43.00},
    ),
    "Albany": MarketLocation(
        search_label="Albany, NY",
        state_code="NY",
        zillow_bbox={"west": -73.82, "east": -73.72, "south": 42.62, "north": 42.70},
    ),
    "Philadelphia": MarketLocation(
        search_label="Philadelphia, PA",
        state_code="PA",
        zillow_bbox={"west": -75.28, "east": -75.08, "south": 39.88, "north": 40.08},
    ),
    "Pittsburgh": MarketLocation(
        search_label="Pittsburgh, PA",
        state_code="PA",
        zillow_bbox={"west": -80.05, "east": -79.88, "south": 40.38, "north": 40.48},
    ),
    "Orlando": MarketLocation(
        search_label="Orlando, FL",
        state_code="FL",
        zillow_bbox={"west": -81.45, "east": -81.25, "south": 28.45, "north": 28.58},
    ),
    "Tampa": MarketLocation(
        search_label="Tampa, FL",
        state_code="FL",
        zillow_bbox={"west": -82.55, "east": -82.35, "south": 27.90, "north": 28.08},
    ),
    "Miami": MarketLocation(
        search_label="Miami, FL",
        state_code="FL",
        zillow_bbox={"west": -80.35, "east": -80.10, "south": 25.70, "north": 25.90},
    ),
    "Charlotte": MarketLocation(
        search_label="Charlotte, NC",
        state_code="NC",
        zillow_bbox={"west": -80.95, "east": -80.75, "south": 35.15, "north": 35.35},
    ),
    "Raleigh": MarketLocation(
        search_label="Raleigh, NC",
        state_code="NC",
        zillow_bbox={"west": -78.72, "east": -78.55, "south": 35.72, "north": 35.85},
    ),
    "Charleston": MarketLocation(
        search_label="Charleston, SC",
        state_code="SC",
        zillow_bbox={"west": -80.05, "east": -79.88, "south": 32.70, "north": 32.85},
    ),
}


# Vacancy/management are percent-of-rent values matching synthesis conventions.
MARKET_DEFAULTS: dict[str, MarketDefaults] = {
    "Rochester": MarketDefaults(vacancy_rate=6.0, management_fee=10.0, insurance_monthly_default=95.0),
    "Syracuse": MarketDefaults(vacancy_rate=6.5, management_fee=10.0, insurance_monthly_default=90.0),
    "Buffalo": MarketDefaults(vacancy_rate=7.0, management_fee=10.0, insurance_monthly_default=88.0),
    "Albany": MarketDefaults(vacancy_rate=6.0, management_fee=10.0, insurance_monthly_default=92.0),
    "Philadelphia": MarketDefaults(vacancy_rate=5.5, management_fee=10.0, insurance_monthly_default=110.0),
    "Pittsburgh": MarketDefaults(vacancy_rate=6.0, management_fee=9.0, insurance_monthly_default=85.0),
    "Orlando": MarketDefaults(vacancy_rate=7.5, management_fee=10.0, insurance_monthly_default=130.0),
    "Tampa": MarketDefaults(vacancy_rate=7.0, management_fee=10.0, insurance_monthly_default=125.0),
    "Miami": MarketDefaults(vacancy_rate=6.5, management_fee=12.0, insurance_monthly_default=150.0),
    "Charlotte": MarketDefaults(vacancy_rate=6.0, management_fee=9.0, insurance_monthly_default=105.0),
    "Raleigh": MarketDefaults(vacancy_rate=5.5, management_fee=9.0, insurance_monthly_default=100.0),
    "Charleston": MarketDefaults(vacancy_rate=6.5, management_fee=10.0, insurance_monthly_default=115.0),
}

# Redfin region_id (region_type=6 city) per HOT_MARKET key.
REDFIN_REGION_IDS: dict[str, int] = {
    "Rochester": 17663,
    "Syracuse": 17671,
    "Buffalo": 17629,
    "Albany": 17625,
    "Philadelphia": 13852,
    "Pittsburgh": 17149,
    "Orlando": 13826,
    "Tampa": 13855,
    "Miami": 11458,
    "Charlotte": 3105,
    "Raleigh": 3570,
    "Charleston": 3103,
}


def get_market_defaults(market_city: str) -> MarketDefaults:
    """Return defaults for a HOT_MARKET key, with sensible fallbacks."""
    return MARKET_DEFAULTS.get(
        market_city,
        MarketDefaults(vacancy_rate=6.0, management_fee=10.0, insurance_monthly_default=100.0),
    )


def get_market_location(market_city: str) -> MarketLocation | None:
    """Return Realtor/Zillow search coordinates for a HOT_MARKET key."""
    return MARKET_LOCATIONS.get(market_city)
