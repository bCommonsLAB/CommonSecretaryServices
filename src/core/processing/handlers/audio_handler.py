"""
@fileoverview Audio Handler - Asynchronous audio processing handler for Secretary Job Worker

@description
Audio handler for Secretary Job Worker. This handler processes audio jobs asynchronously
by reading parameters from the job, executing audio processing via AudioProcessor, and
storing results in the job repository. If a webhook is configured, it sends progress
and a final completed/error callback to the client.

Design:
- Orientiert sich an `pdf_handler.py`, damit der Client Audio wie PDF behandeln kann.
- Keine Manipulation des Inputs. Wir verwenden die Datei so, wie sie hochgeladen wurde.
- Webhook ist optional. Wenn gesetzt, wird am Ende ein `phase=completed` Payload gesendet.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, cast
import os
import traceback

import requests  # type: ignore

from src.core.models.enums import ProcessingStatus
from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.resource_tracking import ResourceCalculator
from src.processors.audio_processor import AudioProcessor


async def handle_audio_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
    """
    Verarbeitet einen Audio-Job asynchron.

    Erwartete Parameter (flach in `job.parameters`):
    - filename: Pfad zur Audio-Datei (absolut, bevorzugt POSIX-Form)
    - source_language, target_language
    - template (optional)
    - use_cache
    - webhook: { url, token, jobId } (optional)
    """
    params = getattr(job, "parameters", None)
    if not params:
        raise ValueError("Keine Parameter im Job gefunden")

    # Datei-Pfad bestimmen
    file_path: Optional[str] = getattr(params, "filename", None) or getattr(params, "url", None)
    if not file_path:
        extra = getattr(params, "extra", {}) or {}
        if isinstance(extra, dict):
            file_path = str(extra.get("file_path", "")) or None
    if not file_path:
        raise ValueError("Weder filename/url noch extra.file_path gesetzt")

    # Pfad normalisieren (analog PDF)
    posix_path = str(file_path).replace("\\", "/")
    normalized_path = os.path.abspath(os.path.normpath(posix_path))

    # Optionale Parameter
    source_language = str(getattr(params, "source_language", "de") or "de")
    target_language = str(getattr(params, "target_language", source_language) or source_language)
    template: Optional[str] = getattr(params, "template", None)
    use_cache: bool = bool(getattr(params, "use_cache", True))
    # source_info/context: wir nehmen, was kommt; AudioProcessor nutzt es als Kontext für Template
    source_info_any: Any = getattr(params, "context", None)
    source_info: Dict[str, Any] = source_info_any if isinstance(source_info_any, dict) else {}

    # Webhook-Config
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

    def _post_progress(_step: str, progress: int, message: str) -> None:
        if not callback_url:
            return
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if callback_token:
            headers["Authorization"] = f"Bearer {callback_token}"
            headers["X-Callback-Token"] = str(callback_token)
        # Standard-Contract: phase=progress|completed|error (keine zusätzlichen Top-Level Keys,
        # damit strikte Parser (additionalProperties=false) nicht brechen).
        payload: Dict[str, Any] = {
            "phase": "progress",
            "message": message,
            "job": {"id": _client_job_id or job.job_id},
            "data": {"progress": progress},
        }
        try:
            repo.add_log_entry(job.job_id, "info", f"Webhook-Progress: progress={progress}")
            requests.post(url=str(callback_url), json=payload, headers=headers, timeout=15)
        except Exception:
            # Progress-Fehler nicht fatal
            pass

    # Initialer Fortschritt
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="initializing", percent=5, message="Job initialisiert"),
    )
    _post_progress("initializing", 5, "Job initialisiert")

    processor = AudioProcessor(resource_calculator=resource_calculator, process_id=job.job_id)

    try:
        repo.update_job_status(
            job_id=job.job_id,
            status="processing",
            progress=JobProgress(step="processing", percent=20, message="Audio-Verarbeitung gestartet"),
        )
        _post_progress("running", 20, "Audio-Verarbeitung gestartet")

        result = await processor.process(
            audio_source=normalized_path,
            source_info=source_info,
            source_language=source_language,
            target_language=target_language,
            template=template,
            use_cache=use_cache,
        )

        status_value = getattr(result, "status", None)
        if status_value == ProcessingStatus.ERROR:
            err = getattr(result, "error", None)
            err_msg = getattr(err, "message", "Audio-Verarbeitung fehlgeschlagen")
            err_code = getattr(err, "code", "PROCESSING_ERROR")
            raise RuntimeError(f"{err_code}: {err_msg}")

        # Ergebnis für Persistenz + Webhook extrahieren
        to_dict_attr: Any = getattr(result, "to_dict", None)
        if callable(to_dict_attr):
            result_any: Any = to_dict_attr()
        else:
            result_any = {}
        result_dict: Dict[str, Any] = cast(Dict[str, Any], result_any) if isinstance(result_any, dict) else {}

        # Transkript text für "leichtgewichtigen" Webhook-Payload
        transcript_text: Optional[str] = None
        data_any: Any = result_dict.get("data")
        if isinstance(data_any, dict):
            transcription_any: Any = data_any.get("transcription")
            if isinstance(transcription_any, dict):
                transcript_text = cast(Optional[str], transcription_any.get("text"))

        repo.update_job_status(
            job_id=job.job_id,
            status="processing",
            progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
            results=JobResults(
                markdown_file=None,
                markdown_content=transcript_text,  # für Clients, die "markdown_content" erwarten
                assets=[],
                web_text=None,
                video_transcript=None,
                attachments_text=None,
                context=None,
                attachments_url=None,
                archive_data=None,
                archive_filename=None,
                structured_data=result_dict,
                target_dir=None,
                page_texts=[],
                asset_dir=None,
            ),
        )
        _post_progress("postprocessing", 95, "Ergebnisse werden gespeichert")

        # Finaler Webhook (analog PDF)
        if callback_url:
            headers_final: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
            if callback_token:
                headers_final["Authorization"] = f"Bearer {callback_token}"
                headers_final["X-Callback-Token"] = str(callback_token)
            payload_final: Dict[str, Any] = {
                "phase": "completed",
                "message": "Audio-Verarbeitung abgeschlossen",
                "job": {"id": _client_job_id or job.job_id},
                "data": {
                    "transcription": {"text": transcript_text},
                },
            }
            try:
                repo.add_log_entry(job.job_id, "info", f"Sende Webhook-Callback an {callback_url}")
                resp = requests.post(url=str(callback_url), json=payload_final, headers=headers_final, timeout=30)
                repo.add_log_entry(
                    job.job_id,
                    "info",
                    f"Webhook Antwort: {getattr(resp, 'status_code', None)} ok={getattr(resp, 'ok', None)}",
                )
            except Exception as post_err:
                repo.add_log_entry(job.job_id, "error", f"Webhook-POST fehlgeschlagen: {str(post_err)}")

    except Exception as e:
        # Fehler-Webhook senden (analog PDF), dann Fehler weiterwerfen → Manager setzt FAILED
        if callback_url:
            try:
                error_headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
                if callback_token:
                    error_headers["Authorization"] = f"Bearer {callback_token}"
                    error_headers["X-Callback-Token"] = str(callback_token)
                error_payload: Dict[str, Any] = {
                    "phase": "error",
                    "message": "Audio-Verarbeitung fehlgeschlagen",
                    "job": {"id": _client_job_id or job.job_id},
                    "error": {
                        "code": type(e).__name__,
                        "message": str(e),
                        "details": {"traceback": traceback.format_exc()},
                    },
                    "data": None,
                }
                repo.add_log_entry(job.job_id, "info", f"Sende Error-Webhook an {callback_url}")
                resp = requests.post(url=str(callback_url), json=error_payload, headers=error_headers, timeout=30)
                repo.add_log_entry(job.job_id, "info", f"Error-Webhook Antwort: {getattr(resp, 'status_code', None)}")
            except Exception as webhook_err:
                repo.add_log_entry(job.job_id, "error", f"Error-Webhook fehlgeschlagen: {str(webhook_err)}")
        raise


