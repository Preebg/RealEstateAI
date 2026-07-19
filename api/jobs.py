"""In-process analysis job store and deferred task worker."""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from services.deferred_analysis import (
    TASK_LABELS,
    build_deferred_task_queue,
    execute_deferred_task,
    finance_task_signature,
)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="capeigen-job")
_lock = threading.RLock()
_jobs: dict[str, AnalysisJob] = {}


@dataclass
class AnalysisJob:
    job_id: str
    user_id: str | None
    address: str
    status: str = "queued"
    property_data: dict[str, Any] | None = None
    deferred_tasks: list[str] = field(default_factory=list)
    deferred_tasks_total: int = 0
    completed_tasks: list[str] = field(default_factory=list)
    finance_context: dict[str, Any] | None = None
    quantum_finance_sig: str | None = None
    error: str | None = None
    from_kb: bool = False
    guest_mode: bool = False


def create_job(
    *,
    address: str,
    user_id: str | None,
    guest_mode: bool = False,
) -> AnalysisJob:
    job_id = str(uuid.uuid4())
    job = AnalysisJob(
        job_id=job_id,
        user_id=user_id,
        address=address.strip(),
        guest_mode=guest_mode,
        status="queued",
    )
    with _lock:
        _jobs[job_id] = job
    return job


def get_job(job_id: str) -> AnalysisJob | None:
    with _lock:
        return _jobs.get(job_id)


def job_to_dict(job: AnalysisJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "property_data": deepcopy(job.property_data) if job.property_data else None,
        "deferred_tasks": list(job.deferred_tasks),
        "deferred_tasks_total": job.deferred_tasks_total,
        "completed_tasks": list(job.completed_tasks),
        "error": job.error,
        "address": job.address,
        "from_kb": job.from_kb,
    }


def _run_deferred_queue(job_id: str) -> None:
    while True:
        with _lock:
            job = _jobs.get(job_id)
            if job is None or not job.deferred_tasks or job.property_data is None:
                if job is not None and job.status == "running" and not job.deferred_tasks:
                    job.status = "done"
                return
            task = job.deferred_tasks[0]
            property_info = job.property_data
            finance_context = job.finance_context
            address = job.address

        try:
            follow_ups = execute_deferred_task(
                task,
                address=address,
                property_info=property_info,
                finance_context=finance_context,
            )
            error: str | None = None
        except Exception as exc:  # noqa: BLE001 — isolate background failures
            follow_ups = []
            error = str(exc)

        with _lock:
            job = _jobs.get(job_id)
            if job is None:
                return
            job.property_data = property_info
            if job.deferred_tasks and job.deferred_tasks[0] == task:
                job.deferred_tasks = job.deferred_tasks[1:]
            for name in follow_ups:
                if name not in job.deferred_tasks and name not in job.completed_tasks:
                    job.deferred_tasks.append(name)
                    job.deferred_tasks_total = max(
                        job.deferred_tasks_total, len(job.completed_tasks) + len(job.deferred_tasks)
                    )
            if error:
                job.error = f"{TASK_LABELS.get(task, task)}: {error}"
            else:
                job.completed_tasks.append(task)
                if task == "quantum" and finance_context:
                    job.quantum_finance_sig = finance_task_signature(
                        monthly_net_cash_flow=finance_context["monthly_net_cash_flow"],
                        forecast_rate=finance_context["forecast_rate"],
                        location_score=finance_context["location_score"],
                    )
            # Allow newly appended tasks (e.g. forecast after comps)
            if not job.deferred_tasks:
                job.status = "done"
                return


def schedule_deferred_work(job_id: str) -> None:
    _executor.submit(_run_deferred_queue, job_id)


def seed_job_from_analysis(
    job: AnalysisJob,
    *,
    property_data: dict[str, Any],
    from_kb: bool,
    guest_mode: bool = False,
) -> None:
    queue = build_deferred_task_queue(property_data, guest_mode=guest_mode)
    with _lock:
        job.property_data = property_data
        job.from_kb = from_kb
        job.deferred_tasks = queue
        job.deferred_tasks_total = len(queue)
        job.status = "running" if queue else "done"
    if queue:
        schedule_deferred_work(job.job_id)


def update_finance_context(
    job_id: str,
    *,
    monthly_net_cash_flow: float,
    forecast_rate: float,
    location_score: float,
) -> bool:
    """Update finance context and re-queue quantum if inputs changed. Returns True if requeued."""
    signature = finance_task_signature(
        monthly_net_cash_flow=monthly_net_cash_flow,
        forecast_rate=forecast_rate,
        location_score=location_score,
    )
    requeued = False
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.property_data is None:
            return False
        job.finance_context = {
            "monthly_net_cash_flow": monthly_net_cash_flow,
            "forecast_rate": forecast_rate,
            "location_score": location_score,
        }
        prior = job.quantum_finance_sig
        if prior is not None and prior != signature:
            job.property_data.pop("quantum_risk", None)
            job.property_data.pop("quantum_risk_score", None)
            queue = list(job.deferred_tasks)
            if "quantum" not in queue:
                insert_at = 0
                if "comps" in queue:
                    insert_at = queue.index("comps") + 1
                queue.insert(insert_at, "quantum")
                job.deferred_tasks = queue
                job.deferred_tasks_total = max(job.deferred_tasks_total, len(queue))
                job.status = "running"
                job.quantum_finance_sig = None
                requeued = True
    if requeued:
        schedule_deferred_work(job_id)
    return requeued


def mark_job_error(job: AnalysisJob, message: str) -> None:
    with _lock:
        job.status = "error"
        job.error = message
