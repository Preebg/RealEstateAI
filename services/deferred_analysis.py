"""Progressive / deferred heavy computations for Individual Search."""

from __future__ import annotations

from typing import Any

import streamlit as st

from engine import calculate_quantum_risk, fetch_comparable_properties, safe_float
from finance import calculate_10yr_appreciation

TASK_LABELS: dict[str, str] = {
    "comps": "Checking comparable sales",
    "quantum": "Running quantum alignment simulation",
    "forecast_chart": "Building appreciation forecast chart",
}


def _has_comps(property_data: dict[str, Any]) -> bool:
    comps = property_data.get("comps_analysis")
    return bool(
        isinstance(comps, dict) and comps.get("comparable_properties")
    )


def build_deferred_task_queue(
    property_data: dict[str, Any],
    *,
    guest_mode: bool = False,
) -> list[str]:
    """Return ordered list of background tasks still needed for *property_data*."""
    tasks: list[str] = []
    if not guest_mode and not _has_comps(property_data):
        tasks.append("comps")
    if not property_data.get("quantum_risk"):
        tasks.append("quantum")
    if not property_data.get("_forecast_display_cache"):
        tasks.append("forecast_chart")
    return tasks


def finance_task_signature(
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> str:
    return f"{monthly_net_cash_flow:.2f}|{forecast_rate:.4f}|{location_score:.2f}"


def sync_quantum_recompute_queue(
    property_info: dict[str, Any],
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> None:
    """Re-queue quantum simulation when underwriting inputs change."""
    signature = finance_task_signature(
        monthly_net_cash_flow=monthly_net_cash_flow,
        forecast_rate=forecast_rate,
        location_score=location_score,
    )
    prior = st.session_state.get("quantum_finance_sig")
    if prior is None or prior == signature:
        return

    property_info.pop("quantum_risk", None)
    property_info.pop("quantum_risk_score", None)
    queue = list(st.session_state.get("deferred_tasks") or [])
    if "quantum" not in queue:
        insert_at = 0
        if "comps" in queue:
            insert_at = queue.index("comps") + 1
        queue.insert(insert_at, "quantum")
    st.session_state.deferred_tasks = queue
    st.session_state.quantum_finance_sig = None


def _run_comps_task(address: str, property_info: dict[str, Any]) -> None:
    updated = fetch_comparable_properties(address, property_info)
    property_info.update(updated)
    if property_info.pop("_forecast_display_cache", None) is not None:
        queue = list(st.session_state.get("deferred_tasks") or [])
        if "forecast_chart" not in queue:
            queue.append("forecast_chart")
            st.session_state.deferred_tasks = queue


def _run_quantum_task(
    property_info: dict[str, Any],
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> None:
    quantum = calculate_quantum_risk(
        monthly_net_cash_flow,
        forecast_rate,
        location_score,
    )
    property_info["quantum_risk"] = quantum
    property_info["quantum_risk_score"] = quantum["overall_success_pct"]
    st.session_state.quantum_finance_sig = finance_task_signature(
        monthly_net_cash_flow=monthly_net_cash_flow,
        forecast_rate=forecast_rate,
        location_score=location_score,
    )


def _run_forecast_chart_task(property_info: dict[str, Any]) -> None:
    predicted_value = safe_float(property_info.get("predicted_value"))
    location_score = safe_float(property_info.get("location_score"))
    market_city = property_info.get("market_city")
    property_info["_forecast_display_cache"] = calculate_10yr_appreciation(
        predicted_value,
        location_score,
        market_city,
    )


def _execute_task(
    task: str,
    *,
    address: str,
    property_info: dict[str, Any],
    finance_context: dict[str, Any] | None,
) -> None:
    if task == "comps":
        _run_comps_task(address, property_info)
    elif task == "quantum":
        if finance_context is None:
            raise ValueError("finance_context is required for quantum task")
        _run_quantum_task(
            property_info,
            monthly_net_cash_flow=finance_context["monthly_net_cash_flow"],
            forecast_rate=finance_context["forecast_rate"],
            location_score=finance_context["location_score"],
        )
    elif task == "forecast_chart":
        _run_forecast_chart_task(property_info)
    else:
        raise ValueError(f"Unknown deferred task: {task}")


def pending_tasks() -> list[str]:
    return list(st.session_state.get("deferred_tasks") or [])


def is_task_pending(task: str) -> bool:
    return task in pending_tasks()


def render_deferred_progress() -> None:
    """Show a slim progress bar while background tasks remain."""
    queue = pending_tasks()
    if not queue:
        return

    total = int(st.session_state.get("deferred_tasks_total") or len(queue))
    completed = max(total - len(queue), 0)
    current = TASK_LABELS.get(queue[0], queue[0])
    st.progress(
        completed / total if total else 0.0,
        text=f"Background: {current} ({completed}/{total} complete)",
    )


def process_next_deferred_task(
    *,
    address: str,
    finance_context: dict[str, Any] | None = None,
) -> bool:
    """
    Run the next queued heavy task and rerun the app.

    Returns True when a task was executed (the page will rerun).
    """
    queue = pending_tasks()
    if not queue:
        return False

    property_info = st.session_state.get("property_data")
    if not isinstance(property_info, dict):
        st.session_state.deferred_tasks = []
        return False

    task = queue[0]
    label = TASK_LABELS.get(task, task)

    with st.status(f"⏳ {label}...", expanded=True) as status:
        try:
            _execute_task(
                task,
                address=address,
                property_info=property_info,
                finance_context=finance_context,
            )
            st.session_state.property_data = property_info
            st.session_state.deferred_tasks = queue[1:]
            status.update(label=f"✅ {label}", state="complete")
        except Exception as exc:
            st.warning(f"Could not complete {label.lower()}: {exc}")
            st.session_state.deferred_tasks = queue[1:]
            status.update(label=f"⚠️ {label} skipped", state="error")

    st.rerun()
    return True
