#!/usr/bin/env python3
"""
Agentic targeted outreach — find listing agents, draft human outreach emails, attach PDF reports.

Agent 1 (gemma-4-31b-it + search): listing agent name + email from public listing data.
Agent 2 (gemma-4-26b-a4b-it): personalized subject/body referencing the agent and property.

Run on your harvester machine (long-running; needs local Gmail OAuth once):
    python targeted_outreach_pipeline.py --dry-run --limit 5
    python targeted_outreach_pipeline.py --limit 10

Credentials: st.secrets / .streamlit/secrets.toml (GEMINI_API_KEY, Supabase, Google OAuth).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import sys
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import streamlit as st
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client, create_client

from engine import (
    PROPERTY_VALUE_TRIGGERED_MODEL,
    PROPERTY_VALUE_MODEL,
    _extract_json,
    _model_supports_grounding,
    generate_with_retry,
    matches_property_value_trigger,
    safe_float,
)
from finance import analyze_investment, calculate_10yr_appreciation
from knowledge_base import get_ai_baseline_maint, get_ai_baseline_rent
from pdf_generator import generate_property_pdf

GMAIL_SCOPES = ("https://www.googleapis.com/auth/gmail.compose",)
TOKEN_PATH = Path(__file__).resolve().parent / ".gmail_oauth_token.json"
SECRETS_PATH = Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
APP_URL = "https://realestateanalyzer.streamlit.app"
SIGNATURE_LINE = "Shaker HS 2027"

AGENT1_MODEL = PROPERTY_VALUE_TRIGGERED_MODEL  # gemma-4-31b-it — search grounding
AGENT2_MODEL = PROPERTY_VALUE_MODEL  # gemma-4-26b-a4b-it — drafting

DEFAULT_DOWN_PAYMENT_PCT = 25.0
DEFAULT_INTEREST_RATE = 6.0
DEFAULT_LOAN_TERM = 30
DEFAULT_CLOSING_COSTS_PCT = 3.0
DEFAULT_INTER_PROPERTY_DELAY_SEC = 4.0

CLOSING_LINES = (
    "Sincerely",
    "Best regards",
    "Warm regards",
    "Thanks so much",
    "All the best",
    "Kind regards",
)

_VALUE_ADD_PATTERN = re.compile(r"\bvalue[\s-]*add\b", re.IGNORECASE)
_APPRECIATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bhigh[\s-]*(?:growth|appreciation|demand|yield)\b", re.IGNORECASE),
    re.compile(r"\bcore\s+appreciation\b", re.IGNORECASE),
    re.compile(r"\bappreciation\s+play\b", re.IGNORECASE),
    re.compile(r"\bappreciation\b", re.IGNORECASE),
)
_EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def _bootstrap_streamlit_secrets() -> None:
    os.environ.setdefault("STREAMLIT_SECRETS_FILE", str(SECRETS_PATH))
    if not SECRETS_PATH.is_file():
        raise FileNotFoundError(
            f"Missing {SECRETS_PATH}. Add Supabase, Gemini, and Google OAuth keys first."
        )
    _ = st.secrets  # force load


def _require_secret(*names: str) -> str:
    for name in names:
        try:
            value = st.secrets[name]
        except (KeyError, TypeError):
            continue
        if value is not None and str(value).strip():
            return str(value).strip()
    raise KeyError(
        f"None of {list(names)!r} found in Streamlit secrets. Add one to {SECRETS_PATH}."
    )


def _normalize_strategy_tag(tag: str | None) -> str:
    return re.sub(r"[\s_-]+", " ", str(tag or "").strip().lower())


def _is_value_add_strategy(tag: str | None) -> bool:
    normalized = _normalize_strategy_tag(tag)
    return bool(normalized and _VALUE_ADD_PATTERN.search(normalized))


def _matches_appreciation_strategy(tag: str | None) -> bool:
    normalized = _normalize_strategy_tag(tag)
    if not normalized or _is_value_add_strategy(normalized):
        return False
    return any(pattern.search(normalized) for pattern in _APPRECIATION_PATTERNS)


def is_outreach_eligible(tag: str | None) -> bool:
    if not tag or _is_value_add_strategy(tag):
        return False
    return matches_property_value_trigger(tag) or _matches_appreciation_strategy(tag)


def resolve_predicted_value(row: dict[str, Any]) -> float:
    predicted = safe_float(row.get("predicted_value"))
    if predicted > 0:
        return predicted
    comps = row.get("comps_analysis")
    if isinstance(comps, dict):
        comp_value = safe_float(comps.get("comp_suggested_value"))
        if comp_value > 0:
            return comp_value
    return 0.0


def resolve_monthly_cash_flow(row: dict[str, Any]) -> float:
    stored = row.get("monthly_net_cash_flow")
    if stored is not None:
        return safe_float(stored)

    price = safe_float(row.get("price"))
    rent = get_ai_baseline_rent(row)
    if price <= 0 or rent <= 0:
        return 0.0

    analysis = analyze_investment(
        price=price,
        down_payment_pct=DEFAULT_DOWN_PAYMENT_PCT,
        interest_rate=DEFAULT_INTEREST_RATE,
        loan_term=DEFAULT_LOAN_TERM,
        closing_costs_pct=DEFAULT_CLOSING_COSTS_PCT,
        tax_rate=safe_float(row.get("tax_rate")),
        monthly_insurance=safe_float(row.get("insurance")),
        monthly_hoa=safe_float(row.get("hoa")),
        maint_percent=get_ai_baseline_maint(row),
        monthly_rent=rent,
        vacancy_reserve_pct=safe_float(row.get("ai_vacancy_rate"), 5.0),
        management_fee_pct=safe_float(row.get("ai_management_fee"), 10.0),
    )
    return safe_float(analysis["monthly_net_cash_flow"])


def passes_financial_filters(row: dict[str, Any]) -> bool:
    price = safe_float(row.get("price"))
    if price <= 0:
        return False
    predicted = resolve_predicted_value(row)
    if predicted <= price:
        return False
    return resolve_monthly_cash_flow(row) > 0


def passes_all_filters(row: dict[str, Any]) -> bool:
    tag = row.get("strategy_tag") or row.get("property_label")
    return is_outreach_eligible(tag) and passes_financial_filters(row)


def _pick_closing(property_id: str) -> str:
    digest = hashlib.sha256(property_id.encode()).hexdigest()
    return CLOSING_LINES[int(digest[:8], 16) % len(CLOSING_LINES)]


def _listing_urls(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    maps_uri = str(row.get("maps_uri") or "").strip()
    if maps_uri:
        urls.append(maps_uri)
    sources = row.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    for item in sources:
        url = str(item or "").strip()
        if url.startswith("http"):
            urls.append(url)
    return list(dict.fromkeys(urls))


def _agent1_find_listing_agent_prompt(row: dict[str, Any]) -> str:
    address = str(row.get("address") or "").strip()
    urls = _listing_urls(row)
    url_block = "\n".join(f"- {u}" for u in urls[:8]) or "- (none on file — search by address)"
    return f"""You are a real-estate research assistant. Find the LISTING agent (not buyer's agent)
for this property currently for sale or recently listed.

Property address: {address}
Known listing URLs:
{url_block}

Search Zillow, Redfin, Realtor.com, and brokerage sites. Return ONLY valid JSON:
{{
  "agent_name": "First Last",
  "agent_email": "email@brokerage.com or empty string if not found",
  "brokerage": "company name or empty",
  "listing_url": "best public listing URL",
  "confidence": "high|medium|low",
  "notes": "brief source note"
}}

Rules:
- agent_email must be a direct professional email if publicly listed; otherwise "".
- Do not invent emails. If unsure, leave agent_email empty and set confidence to low.
- Prefer the agent shown on the active listing page for this exact address.
"""


def _agent2_draft_email_prompt(
    row: dict[str, Any],
    agent: dict[str, Any],
    *,
    closing: str,
) -> str:
    address = str(row.get("address") or "").strip()
    tag = str(row.get("strategy_tag") or row.get("property_label") or "").strip()
    price = safe_float(row.get("price"))
    predicted = resolve_predicted_value(row)
    cash_flow = resolve_monthly_cash_flow(row)
    summary = str(row.get("summary") or "").strip()[:600]
    agent_name = str(agent.get("agent_name") or "there").strip()
    first_name = agent_name.split()[0] if agent_name and agent_name != "there" else "there"

    return f"""Write a short outreach email from a motivated high school student who analyzes
investment properties with an AI underwriting tool. The student attends Shaker High School
(class of 2027) but do NOT mention college plans or Stanford — only the high schooler angle.

Recipient: {agent_name} (listing agent for {address})
Greeting: use "{first_name}" if that looks like a normal first name, else "Hi there"

Property context:
- Address: {address}
- List price: ${price:,.0f}
- Our estimated value: ${predicted:,.0f}
- Modeled monthly net cash flow: ${cash_flow:,.0f}
- Strategy tag: {tag}
- Summary snippet: {summary or "n/a"}

Voice rules:
- Sound like a real teenager: curious, respectful, not corporate or robotic.
- 120–180 words in the body (excluding sign-off).
- Reference their specific listing naturally (you saw it online / came across their listing).
- Mention you built a small analysis tool and are attaching a PDF report you prepared.
- Include the app link once in the body: {APP_URL}
- Do NOT use bullet points or markdown.
- Do NOT say "I hope this email finds you well" or other cliché openers.

Sign-off MUST end exactly like this (keep line breaks):
{closing},
[student first name if OUTREACH_SENDER_FIRST_NAME is unknown use a natural single name like "Jordan"]
{SIGNATURE_LINE}
{APP_URL}

Return ONLY JSON:
{{
  "subject": "short natural subject line, no ALL CAPS",
  "body": "full plain-text email including the sign-off block above"
}}
"""


def run_agent1_find_listing_agent(row: dict[str, Any], *, model: str) -> dict[str, Any]:
    raw = generate_with_retry(
        model,
        _agent1_find_listing_agent_prompt(row),
        use_search=_model_supports_grounding(model),
    )
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        return {
            "agent_name": "",
            "agent_email": "",
            "brokerage": "",
            "listing_url": "",
            "confidence": "low",
            "notes": "parse_failed",
        }
    return {
        "agent_name": str(parsed.get("agent_name") or "").strip(),
        "agent_email": str(parsed.get("agent_email") or "").strip(),
        "brokerage": str(parsed.get("brokerage") or "").strip(),
        "listing_url": str(parsed.get("listing_url") or "").strip(),
        "confidence": str(parsed.get("confidence") or "low").strip().lower(),
        "notes": str(parsed.get("notes") or "").strip(),
    }


def run_agent2_draft_email(
    row: dict[str, Any],
    agent: dict[str, Any],
    *,
    model: str,
    closing: str,
) -> dict[str, str]:
    raw = generate_with_retry(
        model,
        _agent2_draft_email_prompt(row, agent, closing=closing),
        use_search=False,
    )
    parsed = _extract_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Agent 2 did not return valid JSON")
    subject = str(parsed.get("subject") or "").strip()
    body = str(parsed.get("body") or "").strip()
    if not subject or not body:
        raise ValueError("Agent 2 returned empty subject or body")
    return {"subject": subject, "body": body}


def _ensure_signature(body: str, closing: str) -> str:
    """Ensure app link and Shaker HS line appear even if the model omitted them."""
    text = body.rstrip()
    if APP_URL not in text:
        text += f"\n\n{APP_URL}"
    if SIGNATURE_LINE not in text:
        text += f"\n{SIGNATURE_LINE}"
    if not any(text.endswith(closer) or f"\n{closer}," in text for closer in CLOSING_LINES):
        text += f"\n\n{closing},\n{SIGNATURE_LINE}\n{APP_URL}"
    return text


def build_property_pdf_bytes(row: dict[str, Any]) -> bytes:
    address = str(row.get("address") or "Property").strip()
    price = safe_float(row.get("price"))
    rent = get_ai_baseline_rent(row)
    location_score = safe_float(row.get("location_score"), 5.0)

    analysis = analyze_investment(
        price=price,
        down_payment_pct=DEFAULT_DOWN_PAYMENT_PCT,
        interest_rate=DEFAULT_INTEREST_RATE,
        loan_term=DEFAULT_LOAN_TERM,
        closing_costs_pct=DEFAULT_CLOSING_COSTS_PCT,
        tax_rate=safe_float(row.get("tax_rate")),
        monthly_insurance=safe_float(row.get("insurance")),
        monthly_hoa=safe_float(row.get("hoa")),
        maint_percent=get_ai_baseline_maint(row),
        monthly_rent=rent,
        vacancy_reserve_pct=safe_float(row.get("ai_vacancy_rate"), 5.0),
        management_fee_pct=safe_float(row.get("ai_management_fee"), 10.0),
    )
    op = analysis["operating_expenses"]
    monthly_mortgage = analysis["monthly_mortgage"]
    monthly_net = analysis["monthly_net_cash_flow"]
    cap_rate, cash_on_cash = analysis["cap_rate"], analysis["cash_on_cash"]
    total_investment = analysis["total_investment"]

    from engine import calculate_quantum_risk

    forecast = calculate_10yr_appreciation(price, location_score, row.get("market_city"))
    quantum = calculate_quantum_risk(
        monthly_net,
        forecast["annual_rate"],
        location_score,
    )

    table_data = {
        "Description": [
            "Gross Monthly Rent",
            "Mortgage Payment (P&I)",
            "Property Taxes",
            "Insurance",
            "HOA Fee",
            "Maintenance (CapEx)",
            "Vacancy Reserve",
            "Management Fee",
            "Total Costs",
            "Cash Flow Monthly",
        ],
        "Amount": [
            f"${rent:,.2f}",
            f"-${monthly_mortgage:,.2f}",
            f"-${op['monthly_taxes']:,.2f}",
            f"-${safe_float(row.get('insurance')):,.2f}",
            f"-${safe_float(row.get('hoa')):,.2f}",
            f"-${op['monthly_maintenance']:,.2f}",
            f"-${op['vacancy_reserve']:,.2f}",
            f"-${op['management_fee']:,.2f}",
            f"${analysis['total_monthly_expenses']:,.2f}",
            f"${monthly_net:,.2f}",
        ],
    }
    params = {
        "Offer Amount": f"${price:,.0f}",
        "Down Payment": f"{DEFAULT_DOWN_PAYMENT_PCT:.1f}% (${price * DEFAULT_DOWN_PAYMENT_PCT / 100:,.0f})",
        "Interest Rate": f"{DEFAULT_INTEREST_RATE}%",
        "Loan Term": f"{DEFAULT_LOAN_TERM} Years",
    }
    pdf_metrics = {
        "Risk-Adjusted Cap Rate": f"{cap_rate:.2f}%",
        "Cash on Cash Return": f"{cash_on_cash:.2f}%",
        "Monthly Net Cash Flow": f"${monthly_net:,.2f}",
        "Total Cash Required": f"${total_investment:,.2f}",
    }
    return generate_property_pdf(
        address,
        row,
        pdf_metrics,
        table_data,
        params,
        location_score,
        quantum_risk=quantum,
        forecast_display=forecast,
    )


def get_supabase_client() -> Client:
    url = _require_secret("SUPABASE_URL")
    key = _require_secret("SUPABASE_ANON_KEY", "SUPABASE_KEY")
    return create_client(url, key)


def fetch_outreach_candidates(supabase: Client, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Scan undrafted properties in timestamp order until enough pass all filters."""
    eligible: list[dict[str, Any]] = []
    page_size = 200
    offset = 0
    target = limit if limit is not None else None

    while target is None or len(eligible) < target:
        end = offset + page_size - 1
        rows = (
            supabase.table("properties")
            .select("*")
            .eq("email_drafted", False)
            .order("timestamp", desc=False)
            .range(offset, end)
            .execute()
            .data
            or []
        )
        if not rows:
            break
        for row in rows:
            if passes_all_filters(row):
                eligible.append(row)
                if target is not None and len(eligible) >= target:
                    return eligible[:target]
        if len(rows) < page_size:
            break
        offset += page_size

    return eligible if target is None else eligible[:target]


def mark_email_drafted(supabase: Client, property_id: str) -> None:
    supabase.table("properties").update({"email_drafted": True}).eq("id", property_id).execute()


def build_google_client_config() -> dict[str, Any]:
    return {
        "installed": {
            "client_id": _require_secret("GOOGLE_CLIENT_ID"),
            "client_secret": _require_secret("GOOGLE_CLIENT_SECRET"),
            "project_id": _require_secret("GOOGLE_PROJECT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": ["http://localhost:8080/", "http://127.0.0.1:8080/"],
        }
    }


def get_gmail_service():
    creds: Credentials | None = None
    if TOKEN_PATH.is_file():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), GMAIL_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            print(
                "\nGmail sign-in required — a browser will open on http://localhost:8080\n"
                "Sign in with the Gmail account where you want DRAFTS saved.\n"
                "(Drafts appear under Gmail → Drafts, not the Inbox.)\n"
            )
            flow = InstalledAppFlow.from_client_config(build_google_client_config(), GMAIL_SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=True)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    print(f"Gmail authenticated as: {profile.get('emailAddress')} (drafts → Drafts folder)\n")
    return service


def create_gmail_draft_with_attachment(
    gmail_service: Any,
    *,
    subject: str,
    body: str,
    to_email: str,
    pdf_bytes: bytes,
    pdf_filename: str,
) -> str:
    message = MIMEMultipart()
    message["subject"] = subject
    message["to"] = to_email
    message.attach(MIMEText(body, "plain", "utf-8"))
    attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    attachment.add_header("Content-Disposition", "attachment", filename=pdf_filename)
    message.attach(attachment)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    draft = (
        gmail_service.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw}})
        .execute()
    )
    return str(draft.get("id") or "")


def _valid_agent_email(email: str) -> bool:
    return bool(email and _EMAIL_PATTERN.match(email))


def process_property(
    row: dict[str, Any],
    *,
    agent1_model: str,
    agent2_model: str,
    gmail_service: Any | None,
    supabase: Client,
    dry_run: bool,
    agents_only: bool,
) -> dict[str, Any]:
    property_id = str(row.get("id") or "")
    address = str(row.get("address") or property_id)
    tag = row.get("strategy_tag") or row.get("property_label")
    closing = _pick_closing(property_id)

    result: dict[str, Any] = {
        "id": property_id,
        "address": address,
        "strategy": tag,
        "status": "pending",
    }

    print(f"\n--- {address} ({tag}) ---")
    print(f"  Agent 1 ({agent1_model}): finding listing agent...")
    agent = run_agent1_find_listing_agent(row, model=agent1_model)
    result["agent"] = agent
    print(f"  Found: {agent.get('agent_name') or '?'} <{agent.get('agent_email') or 'no email'}> "
          f"[{agent.get('confidence')}]")

    if not _valid_agent_email(agent.get("agent_email", "")):
        result["status"] = "skipped_no_email"
        print("  Skipped — no verified listing agent email.")
        return result

    print(f"  Agent 2 ({agent2_model}): drafting email...")
    draft = run_agent2_draft_email(row, agent, model=agent2_model, closing=closing)
    body = _ensure_signature(draft["body"], closing)
    result["subject"] = draft["subject"]
    result["body_preview"] = body[:200] + ("..." if len(body) > 200 else "")

    pdf_bytes = build_property_pdf_bytes(row)
    pdf_name = f"Analysis_{re.sub(r'[^A-Za-z0-9]+', '_', address)[:60]}.pdf"
    result["pdf_bytes"] = len(pdf_bytes)

    if dry_run or agents_only:
        result["status"] = "dry_run" if dry_run else "agents_only"
        print(f"  Subject: {draft['subject']}")
        print(f"  PDF: {pdf_name} ({len(pdf_bytes):,} bytes)")
        return result

    draft_id = create_gmail_draft_with_attachment(
        gmail_service,
        subject=draft["subject"],
        body=body,
        to_email=agent["agent_email"],
        pdf_bytes=pdf_bytes,
        pdf_filename=pdf_name,
    )
    mark_email_drafted(supabase, property_id)
    result["status"] = "drafted"
    result["draft_id"] = draft_id
    print(f"  Gmail draft created (id={draft_id}) → {agent['agent_email']}")
    return result


def list_eligible_properties(supabase: Client, *, limit: int = 20) -> None:
    candidates = fetch_outreach_candidates(supabase, limit=limit)
    print(f"Eligible properties (showing up to {limit}): {len(candidates)}")
    for row in candidates:
        tag = row.get("strategy_tag") or row.get("property_label")
        print(
            f"  - {row.get('address')} | {tag} | "
            f"price ${safe_float(row.get('price')):,.0f} | "
            f"est ${resolve_predicted_value(row):,.0f} | "
            f"CF ${resolve_monthly_cash_flow(row):,.0f}/mo"
        )


def run_pipeline(
    *,
    dry_run: bool = False,
    agents_only: bool = False,
    list_only: bool = False,
    limit: int | None = None,
    delay_sec: float = DEFAULT_INTER_PROPERTY_DELAY_SEC,
    agent1_model: str = AGENT1_MODEL,
    agent2_model: str = AGENT2_MODEL,
) -> dict[str, Any]:
    _bootstrap_streamlit_secrets()
    _require_secret("GEMINI_API_KEY")

    supabase = get_supabase_client()
    candidates = fetch_outreach_candidates(supabase, limit=limit)

    report: dict[str, Any] = {
        "candidates": len(candidates),
        "gmail_drafts": [],
        "dry_run": [],
        "skipped": [],
        "errors": [],
    }
    if not candidates:
        print("No properties match outreach filters (strategy + undervalued + positive cash flow).")
        return report

    if list_only:
        list_eligible_properties(supabase, limit=limit or 20)
        return report

    if dry_run:
        print("DRY-RUN mode — no Gmail drafts will be created and email_drafted will NOT be updated.\n")
    elif agents_only:
        print("AGENTS-ONLY mode — agents + PDFs only; no Gmail or Supabase updates.\n")

    gmail_service = None
    if not dry_run and not agents_only:
        gmail_service = get_gmail_service()

    for index, row in enumerate(candidates):
        try:
            outcome = process_property(
                row,
                agent1_model=agent1_model,
                agent2_model=agent2_model,
                gmail_service=gmail_service,
                supabase=supabase,
                dry_run=dry_run,
                agents_only=agents_only,
            )
            if outcome["status"] == "drafted":
                report["gmail_drafts"].append(outcome)
            elif outcome["status"] in {"dry_run", "agents_only"}:
                report["dry_run"].append(outcome)
            else:
                report["skipped"].append(outcome)
        except Exception as exc:
            msg = f"{row.get('address')}: {exc}"
            print(f"  ERROR: {msg}", file=sys.stderr)
            report["errors"].append({"address": row.get("address"), "error": str(exc)})

        if index < len(candidates) - 1 and delay_sec > 0:
            time.sleep(delay_sec)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Agentic outreach: find listing agents, draft emails, attach PDF reports."
    )
    parser.add_argument("--dry-run", action="store_true", help="Run agents only; no Gmail or DB updates.")
    parser.add_argument(
        "--agents-only",
        action="store_true",
        help="Run both agents and build PDFs; skip Gmail and Supabase updates.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List eligible properties only (no Gemini, no Gmail).",
    )
    parser.add_argument("--limit", type=int, default=None, help="Max eligible properties to process.")
    parser.add_argument(
        "--delay",
        type=float,
        default=DEFAULT_INTER_PROPERTY_DELAY_SEC,
        help="Seconds between properties (API rate limits).",
    )
    parser.add_argument("--model-agent1", default=AGENT1_MODEL, help="Listing agent lookup model.")
    parser.add_argument("--model-agent2", default=AGENT2_MODEL, help="Email drafting model.")
    args = parser.parse_args()

    report = run_pipeline(
        dry_run=args.dry_run,
        agents_only=args.agents_only,
        list_only=args.list,
        limit=args.limit,
        delay_sec=args.delay,
        agent1_model=args.model_agent1,
        agent2_model=args.model_agent2,
    )
    if args.list:
        return 0

    gmail_count = len(report["gmail_drafts"])
    skipped = len(report["skipped"])
    errors = len(report["errors"])
    print(
        f"\nDone — eligible: {report['candidates']}, "
        f"gmail_drafts_created: {gmail_count}, "
        f"skipped_no_agent_email: {skipped}, "
        f"errors: {errors}"
    )
    if args.dry_run and report.get("dry_run"):
        print("Reminder: --dry-run never writes to Gmail. Re-run without --dry-run to create drafts.")
    elif gmail_count == 0 and not args.dry_run and not args.agents_only:
        print(
            "No Gmail drafts were created. Common causes:\n"
            "  1) Agent could not find a listing-agent email (check skipped count above)\n"
            "  2) Gmail OAuth was cancelled or used a different account\n"
            "  3) Look in Gmail → Drafts (left sidebar), not Inbox"
        )
    elif gmail_count > 0:
        print(f"Open Gmail → Drafts to review {gmail_count} draft(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
