"""Pure parsers for Realtor.com search responses."""

from __future__ import annotations

from typing import Any

from discovery.models import ListingSeed

REALTOR_BASE_URL = "https://www.realtor.com"


def parse_realtor_search_payload(
    payload: Any,
    *,
    market_city: str,
    max_price: float,
) -> list[ListingSeed]:
    """Parse Realtor GraphQL home_search results into listing seeds."""
    results = _extract_results(payload)
    seeds: list[ListingSeed] = []
    seen: set[str] = set()

    for result in results:
        seed = _result_to_seed(result, market_city=market_city, max_price=max_price)
        if seed is None:
            continue
        dedupe_key = seed.external_id or seed.listing_url or seed.address.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        seeds.append(seed)
    return seeds


def _extract_results(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    home_search = data.get("home_search")
    if not isinstance(home_search, dict):
        return []
    results = home_search.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]
    return []


def _result_to_seed(
    result: dict[str, Any],
    *,
    market_city: str,
    max_price: float,
) -> ListingSeed | None:
    list_price = _coerce_price(
        result.get("list_price")
        or result.get("list_price_min")
        or result.get("price")
    )
    if list_price <= 0 or list_price > max_price:
        return None

    location = result.get("location")
    address_info: dict[str, Any] = {}
    if isinstance(location, dict):
        nested = location.get("address")
        if isinstance(nested, dict):
            address_info = nested

    street = str(
        address_info.get("line")
        or address_info.get("street")
        or result.get("street_address")
        or ""
    ).strip()
    city = str(address_info.get("city") or result.get("city") or "").strip()
    state = str(address_info.get("state_code") or result.get("state_code") or "").strip()
    zip_code = str(address_info.get("postal_code") or result.get("postal_code") or "").strip()
    if not street:
        return None

    locality = ", ".join(part for part in (city, state) if part)
    address = f"{street}, {locality} {zip_code}".strip() if locality else street

    permalink = str(result.get("permalink") or result.get("href") or "").strip()
    listing_url = _absolute_realtor_url(permalink)
    property_id = str(result.get("property_id") or result.get("propertyId") or "").strip()
    listing_id = str(result.get("listing_id") or result.get("listingId") or "").strip()
    external_id = property_id or listing_id
    if not external_id and listing_url:
        external_id = listing_url.rstrip("/").split("/")[-1]

    thumbnail = ""
    primary_photo = result.get("primary_photo")
    if isinstance(primary_photo, dict):
        thumbnail = str(primary_photo.get("href") or primary_photo.get("url") or "").strip()
    if not thumbnail:
        photos = result.get("photos")
        if isinstance(photos, list) and photos:
            first = photos[0]
            if isinstance(first, dict):
                thumbnail = str(first.get("href") or first.get("url") or "").strip()

    if not listing_url and not external_id:
        return None

    return ListingSeed(
        address=address,
        city=market_city,
        list_price=list_price,
        listing_url=listing_url,
        source="realtor",
        external_id=external_id,
        thumbnail_url=thumbnail,
    )


def _absolute_realtor_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    if not path.startswith("/"):
        path = f"/realestateandhomes-detail/{path}"
    return f"{REALTOR_BASE_URL}{path}"


def _coerce_price(value: Any) -> float:
    if isinstance(value, dict):
        value = value.get("max") or value.get("min") or value.get("value")
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
