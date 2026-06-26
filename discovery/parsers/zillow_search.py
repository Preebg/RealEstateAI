"""Pure parsers for Zillow search responses."""

from __future__ import annotations

from typing import Any

from discovery.models import ListingSeed

ZILLOW_BASE_URL = "https://www.zillow.com"


def parse_zillow_search_payload(
    payload: Any,
    *,
    market_city: str,
    max_price: float,
) -> list[ListingSeed]:
    """Parse Zillow async search results into listing seeds."""
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
    cat1 = payload.get("cat1")
    if not isinstance(cat1, dict):
        return []
    search_results = cat1.get("searchResults")
    if not isinstance(search_results, dict):
        return []
    merged: list[dict[str, Any]] = []
    for key in ("listResults", "mapResults"):
        bucket = search_results.get(key)
        if isinstance(bucket, list):
            merged.extend(item for item in bucket if isinstance(item, dict))
    return merged


def _result_to_seed(
    result: dict[str, Any],
    *,
    market_city: str,
    max_price: float,
) -> ListingSeed | None:
    list_price = _coerce_price(
        result.get("unformattedPrice")
        or result.get("price")
        or (
            result.get("hdpData", {}).get("homeInfo", {}).get("price")
            if isinstance(result.get("hdpData"), dict)
            else None
        )
    )
    if list_price <= 0 or list_price > max_price:
        return None

    address = str(result.get("address") or "").strip()
    if not address:
        address = _format_address(result)
    if not address:
        return None

    detail_url = str(result.get("detailUrl") or result.get("url") or "").strip()
    listing_url = _absolute_zillow_url(detail_url)
    external_id = str(result.get("zpid") or "").strip()
    if not external_id and listing_url:
        tail = listing_url.rstrip("/").split("/")[-1]
        if tail.endswith("_zpid"):
            external_id = tail.replace("_zpid", "")

    thumbnail = str(result.get("imgSrc") or result.get("carouselPhotos", [{}])[0].get("url") or "").strip()
    if not listing_url and not external_id:
        return None

    return ListingSeed(
        address=address,
        city=market_city,
        list_price=list_price,
        listing_url=listing_url,
        source="zillow",
        external_id=external_id,
        thumbnail_url=thumbnail,
    )


def _format_address(result: dict[str, Any]) -> str:
    street = str(result.get("streetAddress") or "").strip()
    city = str(result.get("addressCity") or result.get("city") or "").strip()
    state = str(result.get("addressState") or result.get("state") or "").strip()
    zip_code = str(result.get("addressZipcode") or result.get("zipcode") or "").strip()
    if not street:
        return ""
    locality = ", ".join(part for part in (city, state) if part)
    if locality and zip_code:
        return f"{street}, {locality} {zip_code}".strip()
    if locality:
        return f"{street}, {locality}".strip()
    return street


def _absolute_zillow_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{ZILLOW_BASE_URL}{path}"


def _coerce_price(value: Any) -> float:
    if isinstance(value, str):
        value = value.replace("$", "").replace(",", "").strip()
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
