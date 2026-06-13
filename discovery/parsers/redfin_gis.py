"""Pure parsers for Redfin GIS search responses."""

from __future__ import annotations

from typing import Any

from discovery.models import ListingSeed

REDFIN_BASE_URL = "https://www.redfin.com"


def parse_redfin_gis_payload(
    payload: Any,
    *,
    market_city: str,
    max_price: float,
) -> list[ListingSeed]:
    """Parse a Redfin /stingray/api/gis JSON payload into listing seeds."""
    homes = _extract_homes(payload)
    seeds: list[ListingSeed] = []
    seen: set[str] = set()

    for home in homes:
        seed = _home_to_seed(home, market_city=market_city, max_price=max_price)
        if seed is None:
            continue
        dedupe_key = seed.external_id or seed.listing_url or seed.address.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        seeds.append(seed)
    return seeds


def _extract_homes(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    homes = payload.get("homes")
    if isinstance(homes, list):
        return [item for item in homes if isinstance(item, dict)]
    inner = payload.get("payload")
    if isinstance(inner, dict):
        nested = inner.get("homes")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def _home_to_seed(
    home: dict[str, Any],
    *,
    market_city: str,
    max_price: float,
) -> ListingSeed | None:
    price = _unwrap_number(home.get("price"))
    if price <= 0 or price > max_price:
        return None

    street = _unwrap_text(home.get("streetLine")) or str(home.get("streetAddress", "")).strip()
    city = _unwrap_text(home.get("city")) or str(home.get("cityName", "")).strip()
    state = _unwrap_text(home.get("state")) or str(home.get("stateCode", "")).strip()
    zip_code = _unwrap_text(home.get("zip")) or str(home.get("postalCode", "")).strip()
    if not street:
        return None

    address_parts = [street]
    locality = ", ".join(part for part in (city, state) if part)
    if locality:
        address_parts.append(locality)
    if zip_code:
        address_parts[-1] = f"{address_parts[-1]} {zip_code}".strip()
    address = ", ".join(address_parts)

    url_path = str(home.get("url") or home.get("listingUrl") or "").strip()
    listing_url = _absolute_redfin_url(url_path)
    external_id = str(
        home.get("propertyId")
        or home.get("listingId")
        or home.get("mlsId")
        or ""
    ).strip()
    if not external_id and listing_url:
        external_id = listing_url.rstrip("/").split("/")[-1]

    thumbnail = _extract_thumbnail(home)
    if not listing_url and not external_id:
        return None

    return ListingSeed(
        address=address,
        city=market_city,
        list_price=price,
        listing_url=listing_url,
        source="redfin",
        external_id=external_id,
        thumbnail_url=thumbnail,
    )


def _absolute_redfin_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{REDFIN_BASE_URL}{path}"


def _extract_thumbnail(home: dict[str, Any]) -> str:
    photos = home.get("photos")
    if isinstance(photos, dict):
        primary = photos.get("primaryPhoto") or photos.get("value")
        if isinstance(primary, str) and primary.startswith("http"):
            return primary
    sashes = home.get("sashes")
    if isinstance(sashes, list):
        for sash in sashes:
            if isinstance(sash, dict):
                img = sash.get("url") or sash.get("photo")
                if isinstance(img, str) and img.startswith("http"):
                    return img
    return ""


def _unwrap_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("value", "")).strip()
    return str(value or "").strip()


def _unwrap_number(value: Any) -> float:
    if isinstance(value, dict):
        return float(value.get("value", 0) or 0)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
