"""
@fileoverview Booklet Handler - Asynchronous booklet (Projektheft) handler for Secretary Job Worker

@description
Handler for job_type `booklet`. Reads the page list from the job parameters,
validates it against the booklet schema, runs BookletProcessor.prepare_images
and stores the produced files and the per-page report in the job results.

Job parameters (see src.core.models.booklet.BOOKLET_PARAMETERS_SCHEMA):
- template: name of the page template set (default bcoop-heft-120)
- title: booklet title
- pages: list of pages in reading order
- webhook: optional {url, token, jobId} for the final callback

Results:
- results.asset_dir: work directory of the job
- results.assets: relative file names (images/<page-id>.jpg, report.json)
- results.structured_data: BookletResult.to_dict() with summary and per-page report

@module core.processing.handlers.booklet_handler

@exports
- handle_booklet_job(): Awaitable[None] - Async handler for booklet jobs

@usedIn
- src.core.processing.__init__: Registered as handler for "booklet"
- src.core.mongodb.secretary_worker_manager: Executed by SecretaryWorkerManager

@dependencies
- Internal: src.processors.booklet_processor - BookletProcessor
- Internal: src.core.models.booklet - BookletRequest
- Internal: src.core.models.job_models - Job, JobProgress
"""
from __future__ import annotations

from typing import Any, Dict, Optional, cast

from src.core.models.booklet import BookletRequest
from src.core.models.job_models import Job, JobProgress
from src.core.resource_tracking import ResourceCalculator
from src.processors.booklet_processor import BookletProcessor


def _raw_parameters(job: Job) -> Dict[str, Any]:
    """
    Baut die rohen Booklet-Parameter aus JobParameters zusammen.

    `template` und `webhook` sind bekannte Felder von JobParameters, alles andere
    (title, pages) landet in `extra`.
    """
    params = job.parameters
    raw: Dict[str, Any] = dict(cast(Dict[str, Any], getattr(params, "extra", None) or {}))
    template = getattr(params, "template", None)
    if template and "template" not in raw:
        raw["template"] = template
    webhook = getattr(params, "webhook", None)
    if isinstance(webhook, dict) and "webhook" not in raw:
        raw["webhook"] = webhook
    return raw


def _webhook_headers(token: Optional[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-Callback-Token"] = str(token)
    return headers


async def handle_booklet_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
    raw = _raw_parameters(job)
    request = BookletRequest.from_dict(raw)  # wirft ValidationError bei ungültigen Parametern

    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="initializing", percent=5, message="Booklet-Job initialisiert"),
    )
    repo.add_log_entry(
        job.job_id,
        "info",
        f"Booklet: {len(request.pages)} Seiten, Template {request.template}",
    )

    processor = BookletProcessor(resource_calculator=resource_calculator, process_id=job.job_id)
    work_dir = processor.work_dir_for(job.job_id)

    def _progress(percent: int, message: str) -> None:
        repo.update_job_status(
            job_id=job.job_id,
            status="processing",
            progress=JobProgress(step="images", percent=percent, message=message),
        )

    result = processor.prepare_images(request, work_dir=work_dir, progress=_progress)

    for report in result.images:
        if report.warnings:
            repo.add_log_entry(job.job_id, "warning", f"{report.page_id}: {'; '.join(report.warnings)}")

    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
        results={
            "asset_dir": str(work_dir),
            "assets": list(result.assets),
            "structured_data": result.to_dict(),
        },
    )

    webhook = request.webhook or {}
    callback_url = webhook.get("url") if isinstance(webhook.get("url"), str) else None
    if callback_url:
        payload: Dict[str, Any] = {
            "phase": "completed",
            "message": "Booklet-Bildaufbereitung abgeschlossen",
            "process": {"id": job.job_id},
            "jobId": webhook.get("jobId"),
            "data": {
                "stage": result.stage,
                "summary": result.summary,
                "assets": list(result.assets),
            },
        }
        try:
            repo.add_log_entry(job.job_id, "info", f"Sende Webhook-Callback an {callback_url}")
            from src.utils.metrics_trace import traced_webhook_post
            traced_webhook_post(
                job.job_id,
                str(callback_url),
                json=payload,
                headers=_webhook_headers(webhook.get("token")),
                timeout=30,
            )
        except Exception:
            repo.add_log_entry(job.job_id, "error", "Webhook-POST fehlgeschlagen")
