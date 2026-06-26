"""Default multi-portal discovery source registry."""

from __future__ import annotations

from discovery.sources.base import AbstractListingSource
from discovery.sources.redfin import RedfinListingSource
from discovery.sources.realtor import RealtorListingSource
from discovery.sources.zillow import ZillowListingSource
from discovery.transport.http_client import ScraperHttpClient


def build_default_sources(http_client: ScraperHttpClient) -> list[AbstractListingSource]:
    """Return Redfin, Realtor, and Zillow sources sharing one HTTP client."""
    return [
        RedfinListingSource(http_client),
        RealtorListingSource(http_client),
        ZillowListingSource(http_client),
    ]
