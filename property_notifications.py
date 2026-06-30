"""Discord alerts when a property meets deal-quality underwriting thresholds."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import urlparse

from app_logging import configure_logging, report_error
from config_secrets import normalize_secret_value
from engine import parse_year_built, safe_float
from finance import analyze_investment
from knowledge_base import get_ai_baseline_maint, get_ai_baseline_rent

log = configure_logging("property_notifications")

MIN_YEAR_BUILT_EXCLUSIVE = 1980
GREAT_MATCH_YEAR_EXCLUSIVE = 2010
MIN_CASH_ON_CASH_PCT = 5.0

DEFAULT_DOWN_PAYMENT_PCT = 25.0
DEFAULT_INTEREST_RATE = 6.0
DEFAULT_LOAN_TERM = 30
DEFAULT_CLOSING_COSTS_PCT = 3.0
DEFAULT_APP_URL = "https://capeigen.streamlit.app"

_TRUSTED_LISTING_HOSTS = frozenset(
    {
        "zillow.com",
        "redfin.com",
        "realtor.com",
    }
)


def qualifies_for_deal_alert(
    *,
    monthly_net_cash_flow: float,
    cash_on_cash: float,
    year_built: int | None,
) -> bool:
    """True when cash flow is positive, CoC > 5%, and built after 1980."""
    if year_built is None or year_built <= MIN_YEAR_BUILT_EXCLUSIVE:
        return False
    if monthly_net_cash_flow <= 0:
        return False
    return cash_on_cash > MIN_CASH_ON_CASH_PCT


def is_great_match(year_built: int | None) -> bool:
    """True when the property was built after 2010."""
    return year_built is not None and year_built > GREAT_MATCH_YEAR_EXCLUSIVE


def resolve_listing_url(property_data: dict[str, Any]) -> str | None:
    """Return a Zillow/Redfin/Realtor listing URL when present on the record."""
    for key in ("listing_url", "source_url"):
        url = str(property_data.get(key) or "").strip()
        if url and _is_trusted_listing_url(url):
            return url
    return None


def _is_trusted_listing_url(url: str) -> bool:
    host = urlparse(url.strip()).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return any(host == domain or host.endswith(f".{domain}") for domain in _TRUSTED_LISTING_HOSTS)


def resolve_discord_webhook_url() -> str | None:
    """Read DISCORD_WEBHOOK_URL from the environment or Streamlit secrets."""
    env_value = normalize_secret_value(os.getenv("DISCORD_WEBHOOK_URL"))
    if env_value:
        return env_value
    try:
        import streamlit as st

        secret_value = normalize_secret_value(st.secrets.get("DISCORD_WEBHOOK_URL"))
    except Exception:
        return None
    return secret_value


def _resolve_app_base_url() -> str:
    from authenticate import _is_localhost_url, _normalize_app_url

    for key in ("APP_URL", "OAUTH_REDIRECT_URL"):
        raw = normalize_secret_value(os.getenv(key))
        if not raw:
            try:
                import streamlit as st

                raw = normalize_secret_value(st.secrets.get(key))
            except Exception:
                raw = None
        if not raw:
            continue
        normalized = _normalize_app_url(raw)
        if normalized and not _is_localhost_url(normalized):
            return normalized
    return DEFAULT_APP_URL


def compute_default_finance_metrics(property_data: dict[str, Any]) -> dict[str, float]:
    """Recompute underwriting metrics using shared default loan assumptions."""
    price = safe_float(property_data.get("price"))
    monthly_rent = safe_float(property_data.get("rent"))
    if monthly_rent <= 0:
        monthly_rent = get_ai_baseline_rent(property_data)

    maint_percent = safe_float(property_data.get("maint_percent"))
    if maint_percent <= 0:
        maint_percent = get_ai_baseline_maint(property_data) or 4.0

    vacancy = safe_float(property_data.get("vacancy_rate"))
    if vacancy <= 0:
        vacancy = safe_float(property_data.get("ai_vacancy_rate"), 5.0)
    management = safe_float(property_data.get("management_fee"))
    if management <= 0:
        management = safe_float(property_data.get("ai_management_fee"), 10.0)

    analysis = analyze_investment(
        price=price,
        down_payment_pct=DEFAULT_DOWN_PAYMENT_PCT,
        interest_rate=DEFAULT_INTEREST_RATE,
        loan_term=DEFAULT_LOAN_TERM,
        closing_costs_pct=DEFAULT_CLOSING_COSTS_PCT,
        tax_rate=safe_float(property_data.get("tax_rate")),
        monthly_insurance=safe_float(property_data.get("insurance")),
        monthly_hoa=safe_float(property_data.get("hoa")),
        maint_percent=maint_percent,
        monthly_rent=monthly_rent,
        vacancy_reserve_pct=vacancy,
        management_fee_pct=management,
    )
    return {
        "monthly_net_cash_flow": round(analysis["monthly_net_cash_flow"], 2),
        "cash_on_cash": round(analysis["cash_on_cash"], 2),
        "cap_rate": round(analysis["cap_rate"], 2),
    }


def build_discord_payload(
    *,
    address: str,
    property_data: dict[str, Any],
    monthly_net_cash_flow: float,
    cash_on_cash: float,
    year_built: int | None,
    share_url: str | None,
    listing_url: str | None,
) -> dict[str, Any]:
    """Build a Discord webhook JSON body with embeds and links."""
    price = safe_float(property_data.get("price"))
    headline = "Great match!" if is_great_match(year_built) else "Qualified deal"
    content = f"**{headline}** — {address}"

    link_lines: list[str] = []
    if share_url:
        link_lines.append(f"[CapEigen share link]({share_url})")
    if listing_url:
        link_lines.append(f"[Listing]({listing_url})")
    description = "\n".join(link_lines) if link_lines else "Links unavailable."

    fields: list[dict[str, Any]] = [
        {"name": "Monthly cash flow", "value": f"${monthly_net_cash_flow:,.2f}", "inline": True},
        {"name": "Cash on cash", "value": f"{cash_on_cash:.2f}%", "inline": True},
    ]
    if year_built is not None:
        fields.append({"name": "Year built", "value": str(year_built), "inline": True})
    if price > 0:
        fields.append({"name": "List price", "value": f"${price:,.0f}", "inline": True})

    embed: dict[str, Any] = {
        "title": address,
        "description": description,
        "color": 0x2ECC71 if is_great_match(year_built) else 0x3498DB,
        "fields": fields,
    }
    if share_url:
        embed["url"] = share_url

    return {"content": content, "embeds": [embed]}


def send_discord_webhook(payload: dict[str, Any], *, webhook_url: str) -> bool:
    """POST a JSON payload to a Discord incoming webhook."""
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "CapEigen-PropertyAlerts/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return 200 <= response.status < 300
    except urllib.error.HTTPError as exc:
        report_error(
            log,
            "discord_webhook_http_error",
            exc,
            status=getattr(exc, "code", None),
            level="warning",
        )
        return False
    except urllib.error.URLError as exc:
        report_error(log, "discord_webhook_network_error", exc, level="warning")
        return False


def _already_sent_discord_alert(property_id: str) -> bool:
    from authenticate import get_service_client

    client = get_service_client()
    if client is None:
        return False
    try:
        response = (
            client.table("properties")
            .select("discord_alert_sent_at")
            .eq("id", property_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        report_error(log, "discord_alert_dedup_lookup_failed", exc, level="warning")
        return False
    rows = response.data or []
    if not rows:
        return False
    return bool(rows[0].get("discord_alert_sent_at"))


def _mark_discord_alert_sent(property_id: str) -> None:
    from datetime import datetime, timezone

    from authenticate import get_service_client

    client = get_service_client()
    if client is None:
        return
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        client.table("properties").update({"discord_alert_sent_at": stamp}).eq(
            "id", property_id
        ).execute()
    except Exception as exc:
        report_error(log, "discord_alert_mark_sent_failed", exc, level="warning")


def maybe_send_qualified_deal_alert(
    property_data: dict[str, Any],
    *,
    property_id: str | None = None,
    finance_metrics: dict[str, float] | None = None,
) -> bool:
    """
    Send a Discord alert when the property meets deal thresholds.

    Returns True when a message was posted successfully.
    """
    webhook_url = resolve_discord_webhook_url()
    if not webhook_url:
        log.info("discord_alert_skipped", reason="webhook_not_configured")
        return False

    resolved_id = str(property_id or property_data.get("id") or "").strip() or None
    if resolved_id and _already_sent_discord_alert(resolved_id):
        log.info("discord_alert_skipped", reason="already_sent", property_id=resolved_id)
        return False

    metrics = finance_metrics or compute_default_finance_metrics(property_data)
    monthly_net_cash_flow = safe_float(metrics.get("monthly_net_cash_flow"))
    cash_on_cash = safe_float(metrics.get("cash_on_cash"))
    year_built = parse_year_built(property_data)

    if not qualifies_for_deal_alert(
        monthly_net_cash_flow=monthly_net_cash_flow,
        cash_on_cash=cash_on_cash,
        year_built=year_built,
    ):
        log.info(
            "discord_alert_skipped",
            reason="criteria_not_met",
            address=property_data.get("address"),
            monthly_net_cash_flow=monthly_net_cash_flow,
            cash_on_cash=cash_on_cash,
            year_built=year_built,
        )
        return False

    address = str(property_data.get("address") or "Unknown address").strip()
    listing_url = resolve_listing_url(property_data)
    share_url: str | None = None
    if resolved_id:
        from share_access import create_headless_property_share_url

        share_url = create_headless_property_share_url(
            resolved_id,
            property_data,
            app_base_url=_resolve_app_base_url(),
            include_assumptions=False,
            expires_days=90,
        )

    payload = build_discord_payload(
        address=address,
        property_data=property_data,
        monthly_net_cash_flow=monthly_net_cash_flow,
        cash_on_cash=cash_on_cash,
        year_built=year_built,
        share_url=share_url,
        listing_url=listing_url,
    )
    if not send_discord_webhook(payload, webhook_url=webhook_url):
        return False

    if resolved_id:
        _mark_discord_alert_sent(resolved_id)

    log.info(
        "discord_alert_sent",
        address=address,
        property_id=resolved_id,
        great_match=is_great_match(year_built),
        monthly_net_cash_flow=monthly_net_cash_flow,
        cash_on_cash=cash_on_cash,
    )
    return True
