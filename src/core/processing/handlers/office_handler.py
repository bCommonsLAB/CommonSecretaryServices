"""
@fileoverview Office Handler - Asynchronous Office processing handler (python-only) for Secretary Job Worker

@description
Dieser Handler implementiert Pipeline A:
- DOCX/XLSX/PPTX → Markdown + Images + Thumbnail-Previews (python-only)
- Ergebnisse werden im Job gespeichert (structured_data) + Artefakte im Filesystem.
- Webhooks (progress + completed/error) analog zu `pdf_handler`.
"""

from __future__ import annotations

import os
import time
import zipfile
from datetime import datetime, UTC
from typing import Any, Dict, Optional, cast, List

import requests  # type: ignore

from src.core.models.base import RequestInfo, ProcessInfo
from src.core.models.enums import ProcessingStatus
from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.resource_tracking import ResourceCalculator
from src.core.exceptions import ProcessingError
from src.processors.office_processor import OfficeProcessor


async def handle_office_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
    start = time.time()
    repo.add_log_entry(job.job_id, "info", f"Office-Handler gestartet für Job {job.job_id}")

    params = getattr(job, "parameters", None)
    if not params:
        raise ValueError("Keine Parameter im Job gefunden")

    file_path: Optional[str] = getattr(params, "filename", None) or getattr(params, "url", None)
    if not file_path:
        extra_any: Any = getattr(params, "extra", {}) or {}
        extra = cast(Dict[str, Any], extra_any) if isinstance(extra_any, dict) else {}
        file_path = str(extra.get("file_path", ""))
    if not file_path:
        raise ValueError("Weder filename/url noch extra.file_path gesetzt")

    # Pfad normalisieren (Windows/Posix)
    normalized_path = os.path.abspath(os.path.normpath(file_path.replace("\\", "/")))
    if not os.path.exists(normalized_path):
        raise ProcessingError("Datei existiert nicht (noch nicht geschrieben?)")

    include_images: bool = bool(getattr(params, "include_images", True))
    include_previews: bool = bool(getattr(params, "include_previews", True))
    use_cache: bool = bool(getattr(params, "use_cache", True))
    force_refresh: bool = bool(getattr(params, "force_refresh", False))

    # Fortschritt initialisieren
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="initializing", percent=5, message="Office-Job initialisiert"),
    )

    # Webhook-Konfiguration (wie im pdf_handler)
    callback_url: Optional[str] = None
    callback_token: Optional[str] = None
    webhook_any: Any = getattr(job.parameters, "webhook", None)
    if isinstance(webhook_any, dict):
        webhook = cast(Dict[str, Any], webhook_any)
        callback_url = webhook.get("url") if isinstance(webhook.get("url"), str) else None
        callback_token = webhook.get("token") if isinstance(webhook.get("token"), str) else None

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
            requests.post(url=str(callback_url), json=payload, headers=headers, timeout=15)
        except Exception:
            pass

    _post_progress("initializing", 5, "Office-Verarbeitung startet")
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="processing", percent=30, message="Office wird in Markdown transformiert"),
    )

    processor = OfficeProcessor(process_id=job.job_id)
    result = await processor.process(
        normalized_path,
        include_images=include_images,
        include_previews=include_previews,
        use_cache=use_cache,
        force_overwrite=force_refresh,
    )

    _post_progress("postprocessing", 90, "Artefakte werden gepackt/gespeichert")

    # ZIP erstellen (damit /api/jobs/{id}/download-archive direkt streamen kann)
    process_dir = result.process_dir
    zip_filename = f"office_{job.job_id}.zip"
    zip_path = os.path.join(process_dir, zip_filename)
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            # output.md
            md_path = result.markdown_path
            if os.path.exists(md_path) and os.path.isfile(md_path):
                zf.write(md_path, arcname="output.md")
            # images/ + previews/ (wenn vorhanden)
            for folder in ("images", "previews"):
                abs_folder = os.path.join(process_dir, folder)
                if not os.path.isdir(abs_folder):
                    continue
                for root, _dirs, files in os.walk(abs_folder):
                    for fname in files:
                        full = os.path.join(root, fname)
                        rel = os.path.relpath(full, process_dir)
                        zf.write(full, arcname=rel)
    except Exception as e:
        repo.add_log_entry(job.job_id, "warning", f"ZIP-Erstellung fehlgeschlagen: {str(e)}")

    # Standardisierte structured_data (ähnlich BaseResponse.to_dict)
    now_iso = datetime.now(UTC).isoformat()
    request_info = RequestInfo(
        processor="office",
        timestamp=now_iso,
        parameters={
            "include_images": include_images,
            "include_previews": include_previews,
            "use_cache": use_cache,
            "force_refresh": force_refresh,
        },
    )
    process_info = ProcessInfo(
        id=job.job_id,
        main_processor="office",
        started=now_iso,
        duration=float(int((time.time() - start) * 1000)),  # ms als float (Repo nutzt float-Feld)
        is_from_cache=result.is_from_cache,
    )

    structured_data: Dict[str, Any] = {
        "status": ProcessingStatus.SUCCESS.value,
        "request": request_info.to_dict(),
        "process": process_info.to_dict(),
        "error": None,
        "data": result.data.to_dict(),
    }

    # Results persistieren
    assets: List[str] = []
    try:
        meta = result.data.metadata
        assets = list(meta.image_paths) + list(meta.preview_paths)
    except Exception:
        assets = []

    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
        results=JobResults(
            markdown_file=result.markdown_path,
            markdown_content=None,
            assets=assets,
            structured_data=structured_data,
            target_dir=process_dir,
            asset_dir=process_dir,
            archive_filename=zip_filename,
        ),
    )

    # Finaler Webhook (kompakt, URLs statt großer Payloads)
    if callback_url:
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if callback_token:
            headers["Authorization"] = f"Bearer {callback_token}"
            headers["X-Callback-Token"] = str(callback_token)
        payload_final: Dict[str, Any] = {
            "phase": "completed",
            "message": "Office-Extraktion abgeschlossen",
            "data": {
                "extracted_text": result.data.extracted_text,
                "metadata": {"text_contents": [tc.to_dict() for tc in result.data.metadata.text_contents]},
                "markdown_url": f"/api/office/jobs/{job.job_id}/markdown",
                "archive_url": f"/api/jobs/{job.job_id}/download-archive",
            },
        }
        try:
            requests.post(url=str(callback_url), json=payload_final, headers=headers, timeout=30)
        except Exception as e:
            repo.add_log_entry(job.job_id, "error", f"Webhook-POST fehlgeschlagen: {str(e)}")






