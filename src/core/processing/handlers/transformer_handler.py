"""
@fileoverview Transformer Handler - Asynchronous template transformation handler for Secretary Job Worker

@description
Transformer template handler for Secretary Job Worker. This handler processes
transformation jobs asynchronously by reading parameters from the job and executing
template-based text transformation via TransformerProcessor.

Main functionality:
- Reads job parameters (text, url, template, context, etc.)
- Executes template transformation via TransformerProcessor
- Handles progress updates and webhook notifications
- Stores processing results in job repository
- Supports both text input and URL-based input

Features:
- Asynchronous job processing
- Progress tracking with percentage updates
- Webhook support for progress notifications
- Template-based text transformation
- Context-aware processing
- Caching support

@module core.processing.handlers.transformer_handler

@exports
- handle_transformer_template_job(): Awaitable[None] - Async handler function for transformer jobs

@usedIn
- src.core.processing.registry: Registered as handler for "transformer" job_type
- src.core.mongodb.secretary_worker_manager: Executed by SecretaryWorkerManager

@dependencies
- External: requests - HTTP requests for webhook notifications
- Internal: src.processors.transformer_processor - TransformerProcessor for text transformation
- Internal: src.core.models.job_models - Job, JobProgress models
- Internal: src.core.resource_tracking - ResourceCalculator
"""

from typing import Any, Dict, Optional, cast
import requests  # type: ignore

from src.core.models.job_models import Job, JobProgress
from src.core.resource_tracking import ResourceCalculator
from src.core.models.enums import ProcessingStatus
from src.processors.transformer_processor import TransformerProcessor


async def handle_transformer_template_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:



    params = getattr(job, "parameters", None)
    if not params:
        raise ValueError("Keine Parameter im Job gefunden")

    # Eingabeparameter (Text oder URL)
    text: Optional[str] = getattr(params, "text", None)
    url: Optional[str] = getattr(params, "url", None)
    template: Optional[str] = getattr(params, "template", None)
    template_content: Optional[str] = getattr(params, "template_content", None)
    context: Optional[Dict[str, Any]] = getattr(params, "context", None)
    additional_field_descriptions: Optional[Dict[str, str]] = getattr(params, "additional_field_descriptions", None)
    use_cache: bool = bool(getattr(params, "use_cache", True))

    # Fortschritt initialisieren
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="initializing", percent=5, message="Job initialisiert"),
    )

    # Optionaler Progress-Webhook (explizit, zusätzlich zum Log-Observer)
    callback_url: Optional[str] = None
    callback_token: Optional[str] = None
    _client_job_id: Optional[str] = None
    webhook_any: Any = getattr(job.parameters, "webhook", None)
    if isinstance(webhook_any, dict):
        webhook_dict: Dict[str, Any] = cast(Dict[str, Any], webhook_any)
        url_val = webhook_dict.get("url")
        token_val = webhook_dict.get("token")
        jobid_val = webhook_dict.get("jobId")
        callback_url = url_val if isinstance(url_val, str) else None
        callback_token = token_val if isinstance(token_val, str) else None
        _client_job_id = jobid_val if isinstance(jobid_val, str) else None

    def _post_progress(phase: str, progress: int, message: str) -> None:
        if not callback_url:
            return
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if callback_token:
            headers["Authorization"] = f"Bearer {callback_token}"
            headers["X-Callback-Token"] = str(callback_token)
        payload: Dict[str, Any] = {
            "phase": phase,
            "progress": progress,
            "message": message,
            "process": {"id": job.job_id},
        }
        try:
            repo.add_log_entry(job.job_id, "info", f"Webhook-Progress: phase={phase} progress={progress}")
            requests.post(url=str(callback_url), json=payload, headers=headers, timeout=15)
        except Exception:
            # Progress-Fehler nicht fatal
            pass

    _post_progress("initializing", 5, "Job initialisiert")

    processor = TransformerProcessor(resource_calculator=resource_calculator, process_id=job.job_id)

    # Validierung (analog zum Endpoint): entweder text oder url; und template oder template_content
    if not text and not url:
        raise ValueError("Entweder text oder url muss angegeben werden")
    if text and url:
        raise ValueError("Nur entweder text oder url darf angegeben werden, nicht beide")
    if not template and not template_content:
        raise ValueError("Entweder template oder template_content muss angegeben werden")
    if template and template_content:
        raise ValueError("Nur entweder template oder template_content darf angegeben werden, nicht beide")

    # Mittlerer Fortschritt
    _post_progress("processing", 50, "Template-Transformation läuft")

    if url:
        result = processor.transformByUrl(
            url=url,
            source_language=getattr(params, "source_language", "de"),
            target_language=getattr(params, "target_language", "de"),
            template=template,
            template_content=template_content,
            context=context,
            additional_field_descriptions=additional_field_descriptions,
            use_cache=use_cache,
        )
    else:
        result = processor.transformByTemplate(
            text=text or "",
            source_language=getattr(params, "source_language", "de"),
            target_language=getattr(params, "target_language", "de"),
            template=template,
            template_content=template_content,
            context=context,
            additional_field_descriptions=additional_field_descriptions,
            use_cache=use_cache,
        )

    _post_progress("postprocessing", 95, "Ergebnisse werden gespeichert")

    status_value = getattr(result, "status", None)
    if status_value == ProcessingStatus.ERROR:
        err = getattr(result, "error", None)
        err_msg = getattr(err, "message", "Transformation fehlgeschlagen")
        err_code = getattr(err, "code", "PROCESSING_ERROR")
        raise RuntimeError(f"{err_code}: {err_msg}")

    # Ergebnisse kurz in Job speichern (structured_data), analog pdf_handler
    to_dict_attr: Any = getattr(result, "to_dict", None)
    result_any: Any
    if callable(to_dict_attr):
        result_any = to_dict_attr()
    else:
        result_any = {}
    result_dict: Dict[str, Any] = cast(Dict[str, Any], result_any) if isinstance(result_any, dict) else {}

    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
        results={
            "structured_data": result_dict,
        },
    )

    # Finale Webhook-Nachricht (kompakt)
    if callback_url:
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if callback_token:
            headers["Authorization"] = f"Bearer {callback_token}"
            headers["X-Callback-Token"] = str(callback_token)
        payload_final: Dict[str, Any] = {
            "phase": "completed",
            "message": "Template-Transformation abgeschlossen",
            "data": {},
        }
        try:
            repo.add_log_entry(job.job_id, "info", f"Sende Webhook-Callback an {callback_url}")
            requests.post(url=str(callback_url), json=payload_final, headers=headers, timeout=30)
        except Exception:
            repo.add_log_entry(job.job_id, "error", "Webhook-POST fehlgeschlagen")


