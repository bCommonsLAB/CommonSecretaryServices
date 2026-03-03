"""
@fileoverview Video Handler - Asynchroner Video-Verarbeitungs-Handler für Secretary Job Worker

@description
Video-Handler für Secretary Job Worker. Verarbeitet Video-Jobs asynchron:
- Liest Parameter aus dem Job (filename oder url)
- Führt VideoProcessor.process(...) aus (Audio-Extraktion + Transkription)
- Speichert Ergebnisse im Job-Repository
- Sendet bei konfiguriertem Webhook Progress- und Completed/Error-Callbacks

Design:
- Analog zu audio_handler.py und office_handler.py
- Unterstützt Datei-Upload (filename) und URL-basierte Verarbeitung (url)
- Webhook optional; bei phase=completed wird das Transkriptionsergebnis geliefert
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict, Optional, cast

import requests  # type: ignore

from src.core.models.enums import ProcessingStatus
from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.models.video import VideoSource
from src.core.resource_tracking import ResourceCalculator
from src.processors.video_processor import VideoProcessor


async def handle_video_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
    """
    Verarbeitet einen Video-Job asynchron.

    Erwartete Parameter (in job.parameters):
    - filename: Pfad zur Video-Datei (bei Datei-Upload)
    - url: Video-URL (bei URL-basierter Verarbeitung)
    - source_language, target_language, template, use_cache, force_refresh
    - webhook: { url, token, jobId } (optional)
    """
    params = getattr(job, "parameters", None)
    if not params:
        raise ValueError("Keine Parameter im Job gefunden")

    # Quelle: Datei oder URL
    file_path: Optional[str] = getattr(params, "filename", None)
    url: Optional[str] = getattr(params, "url", None)
    if not file_path and not url:
        extra = getattr(params, "extra", {}) or {}
        if isinstance(extra, dict):
            file_path = str(extra.get("file_path", "")) or None
            url = str(extra.get("url", "")) or None
    if not file_path and not url:
        raise ValueError("Weder filename noch url gesetzt")

    # Optionale Parameter
    source_language = str(getattr(params, "source_language", "auto") or "auto")
    target_language = str(getattr(params, "target_language", "de") or "de")
    template: Optional[str] = getattr(params, "template", None)
    use_cache: bool = bool(getattr(params, "use_cache", True))
    # force_refresh: für zukünftige VideoProcessor-Erweiterung; aktuell nicht genutzt
    _ = bool(getattr(params, "force_refresh", False))

    # Webhook-Config
    callback_url: Optional[str] = None
    callback_token: Optional[str] = None
    _client_job_id: Optional[str] = None
    webhook_any: Any = getattr(job.parameters, "webhook", None)
    if isinstance(webhook_any, dict):
        webhook_dict: Dict[str, Any] = cast(Dict[str, Any], webhook_any)
        callback_url = webhook_dict.get("url") if isinstance(webhook_dict.get("url"), str) else None
        callback_token = webhook_dict.get("token") if isinstance(webhook_dict.get("token"), str) else None
        _client_job_id = webhook_dict.get("jobId") if isinstance(webhook_dict.get("jobId"), str) else None

    def _post_progress(_step: str, progress: int, message: str) -> None:
        if not callback_url:
            return
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if callback_token:
            headers["Authorization"] = f"Bearer {callback_token}"
            headers["X-Callback-Token"] = str(callback_token)
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
            pass

    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="initializing", percent=5, message="Video-Job initialisiert"),
    )
    _post_progress("initializing", 5, "Video-Job initialisiert")

    processor = VideoProcessor(resource_calculator=resource_calculator, process_id=job.job_id)

    try:
        repo.update_job_status(
            job_id=job.job_id,
            status="processing",
            progress=JobProgress(step="processing", percent=20, message="Video-Verarbeitung gestartet"),
        )
        _post_progress("running", 20, "Video-Verarbeitung gestartet")

        # VideoSource und binary_data je nach Quelle
        binary_data: Optional[bytes] = None
        if file_path:
            normalized_path = os.path.abspath(os.path.normpath(str(file_path).replace("\\", "/")))
            if not os.path.exists(normalized_path):
                raise FileNotFoundError(f"Video-Datei nicht gefunden: {normalized_path}")
            with open(normalized_path, "rb") as f:
                binary_data = f.read()
            file_name = os.path.basename(normalized_path)
            source = VideoSource(
                file_name=file_name,
                file_size=len(binary_data),
                upload_timestamp=None,
            )
        else:
            source = VideoSource(url=url)

        result = await processor.process(
            source=source,
            binary_data=binary_data,
            target_language=target_language,
            source_language=source_language,
            template=template,
            use_cache=use_cache,
        )

        status_value = getattr(result, "status", None)
        if status_value == ProcessingStatus.ERROR:
            err = getattr(result, "error", None)
            err_msg = getattr(err, "message", "Video-Verarbeitung fehlgeschlagen")
            err_code = getattr(err, "code", "PROCESSING_ERROR")
            raise RuntimeError(f"{err_code}: {err_msg}")

        # Ergebnis für Persistenz + Webhook
        to_dict_attr: Any = getattr(result, "to_dict", None)
        result_dict: Dict[str, Any] = (
            cast(Dict[str, Any], to_dict_attr()) if callable(to_dict_attr) else {}
        )

        transcript_text: Optional[str] = None
        data_any: Any = result_dict.get("data")
        if isinstance(data_any, dict):
            transcription_any: Any = data_any.get("transcription")
            if isinstance(transcription_any, dict):
                transcript_text = cast(Optional[str], transcription_any.get("text"))
            elif hasattr(transcription_any, "text"):
                transcript_text = str(getattr(transcription_any, "text", "") or "")

        repo.update_job_status(
            job_id=job.job_id,
            status="processing",
            progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
            results=JobResults(
                markdown_file=None,
                markdown_content=transcript_text,
                assets=[],
                web_text=None,
                video_transcript=transcript_text,
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

        if callback_url:
            headers_final: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
            if callback_token:
                headers_final["Authorization"] = f"Bearer {callback_token}"
                headers_final["X-Callback-Token"] = str(callback_token)
            payload_final: Dict[str, Any] = {
                "phase": "completed",
                "message": "Video-Verarbeitung abgeschlossen",
                "job": {"id": _client_job_id or job.job_id},
                "data": {
                    "transcription": {"text": transcript_text},
                    "result": result_dict,
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
        if callback_url:
            try:
                error_headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
                if callback_token:
                    error_headers["Authorization"] = f"Bearer {callback_token}"
                    error_headers["X-Callback-Token"] = str(callback_token)
                error_payload: Dict[str, Any] = {
                    "phase": "error",
                    "message": "Video-Verarbeitung fehlgeschlagen",
                    "job": {"id": _client_job_id or job.job_id},
                    "error": {
                        "code": type(e).__name__,
                        "message": str(e),
                        "details": {"traceback": traceback.format_exc()},
                    },
                    "data": None,
                }
                repo.add_log_entry(job.job_id, "info", f"Sende Error-Webhook an {callback_url}")
                requests.post(url=str(callback_url), json=error_payload, headers=error_headers, timeout=30)
            except Exception as webhook_err:
                repo.add_log_entry(job.job_id, "error", f"Error-Webhook fehlgeschlagen: {str(webhook_err)}")
        raise
