"""Shared httpx transport with retries and host backoff."""

from __future__ import annotations

import asyncio
import socket
from typing import Any
from urllib.parse import urlparse

import httpx

from discovery.transport.rate_limiter import HostRateLimiter

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class ScraperHttpClient:
    """httpx.AsyncClient wrapper with per-host rate limiting and retries."""

    def __init__(
        self,
        *,
        timeout_sec: float = 30.0,
        max_retries: int = 4,
        rate_limiter: HostRateLimiter | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout_sec = timeout_sec
        self._max_retries = max_retries
        self._rate_limiter = rate_limiter or HostRateLimiter(rate=1.0, capacity=2.0)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=httpx.Timeout(timeout_sec),
            follow_redirects=True,
        )

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_text(self, url: str) -> str:
        response = await self._request("GET", url)
        return response.text

    async def get_json(self, url: str) -> Any:
        text = await self.get_text(url)
        return _decode_stingray_json(text)

    async def post_json(
        self,
        url: str,
        body: Any,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> Any:
        import json

        request_headers = dict(headers or {})
        if "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"
        response = await self._request(
            "POST",
            url,
            content=json.dumps(body),
            headers=request_headers,
            params=params,
        )
        return json.loads(response.text)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        content: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        host = httpx.URL(url).host or "unknown"
        last_error: BaseException | None = None
        for attempt in range(self._max_retries):
            await self._rate_limiter.acquire(host)
            try:
                response = await self._client.request(
                    method,
                    url,
                    content=content,
                    headers=headers,
                    params=params,
                )
            except httpx.ConnectError as exc:
                last_error = exc
                if attempt == 0 and "getaddrinfo" in str(exc).lower():
                    _raise_dns_hint(url, host, exc)
                await asyncio.sleep(min(2 ** attempt, 16))
                continue
            except httpx.HTTPError as exc:
                last_error = exc
                await asyncio.sleep(min(2 ** attempt, 16))
                continue

            if response.status_code in {429, 503} and attempt < self._max_retries - 1:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt
                await asyncio.sleep(min(delay, 32))
                continue

            response.raise_for_status()
            return response

        if isinstance(last_error, httpx.ConnectError) and "getaddrinfo" in str(last_error).lower():
            _raise_dns_hint(url, host, last_error)
        raise RuntimeError(f"HTTP request failed after {self._max_retries} attempts: {url}") from last_error


def _raise_dns_hint(url: str, host: str, exc: BaseException) -> None:
    """Turn opaque getaddrinfo failures into actionable harvest-machine guidance."""
    parsed_host = urlparse(url).hostname or host
    hint = (
        f"DNS lookup failed for {parsed_host!r} while requesting {url}. "
        "On the harvest machine, verify internet access, DNS/firewall settings, "
        "and that no proxy is required."
    )
    try:
        socket.getaddrinfo(parsed_host, None, socket.AF_INET, socket.SOCK_STREAM)
    except socket.gaierror as dns_exc:
        raise OSError(f"{hint} ({dns_exc})") from exc
    raise OSError(hint) from exc


def _decode_stingray_json(text: str) -> Any:
    """Strip Redfin {}&& prefix and parse JSON."""
    import json

    cleaned = text.strip()
    if cleaned.startswith("{}&&"):
        cleaned = cleaned[4:]
    return json.loads(cleaned)
