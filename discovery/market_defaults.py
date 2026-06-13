"""Per-market underwriting defaults not scraped from portals."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketDefaults:
    vacancy_rate: float
    management_fee: float
    insurance_monthly_default: float


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
