"""
@fileoverview Office-via-PDF Handler - Asynchronous Office→PDF→PDFProcessor handler for Secretary Job Worker

@description
Pipeline B aus `docs/architecture/office-endpoints.md`:
1) Office-Datei (DOCX/XLSX/PPTX) wird via LibreOffice headless zu PDF konvertiert
2) Danach wird die bestehende PDF-Logik verwendet (`PDFProcessor.process(...)`)

Wichtig:
- Parametrisierung wird 1:1 aus dem Job übernommen (Pass-through wie `/api/pdf/process`)
- Große Felder (Base64-ZIPs, `mistral_ocr_raw`) werden nicht in MongoDB gespeichert,
  sondern als Dateien im process_dir abgelegt. Der Job speichert nur Referenzen/URLs.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any, Dict, Optional, cast, List

import requests  # type: ignore

from src.core.exceptions import ProcessingError
from src.core.models.enums import ProcessingStatus
from src.core.models.job_models import Job, JobProgress, JobResults
from src.core.resource_tracking import ResourceCalculator
from src.processors.pdf_processor import PDFProcessor
from src.processors.office._common import guess_soffice_path


def _convert_office_to_pdf(input_path: Path, output_dir: Path) -> Path:
    """Konvertiert Office nach PDF via LibreOffice headless."""
    soffice = guess_soffice_path()

    # Existence check: Windows hat einen festen Pfad; unter Linux/Mac ist `soffice` typischerweise im PATH.
    if os.name == "nt":
        if not os.path.exists(soffice):
            raise ProcessingError("LibreOffice ist nicht installiert (soffice.exe nicht gefunden).")
    else:
        # `soffice` im PATH?
        import shutil

        if shutil.which(soffice) is None:
            raise ProcessingError("LibreOffice ist nicht installiert (soffice nicht im PATH).")

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = [
        soffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        raise ProcessingError("LibreOffice-Konvertierung Timeout")
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        raise ProcessingError(f"LibreOffice-Konvertierung fehlgeschlagen: {stderr or e}")

    pdf_path = output_dir / f"{input_path.stem}.pdf"
    if not pdf_path.exists():
        # LibreOffice kann gelegentlich andere Namen schreiben; suche im Output dir.
        cands = sorted(output_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
        if cands:
            return cands[0]
        raise ProcessingError("Konvertierung abgeschlossen, aber keine PDF-Datei gefunden")
    return pdf_path


async def handle_office_via_pdf_job(job: Job, repo: Any, resource_calculator: ResourceCalculator) -> None:
    start = time.time()
    repo.add_log_entry(job.job_id, "info", f"Office-via-PDF Handler gestartet für Job {job.job_id}")

    params = getattr(job, "parameters", None)
    if not params:
        raise ValueError("Keine Parameter im Job gefunden")

    # Datei kommt aus Upload-Flow; in Jobs wird üblicherweise `filename` gesetzt
    file_path: Optional[str] = getattr(params, "filename", None)
    if not file_path:
        extra_any: Any = getattr(params, "extra", {}) or {}
        extra = cast(Dict[str, Any], extra_any) if isinstance(extra_any, dict) else {}
        file_path = cast(Optional[str], extra.get("file_path"))
    if not file_path:
        raise ValueError("Kein filename gesetzt (Office-via-PDF benötigt lokale Datei)")

    normalized_path = os.path.abspath(os.path.normpath(str(file_path).replace("\\", "/")))
    if not os.path.exists(normalized_path):
        raise ProcessingError("Datei existiert nicht (noch nicht geschrieben?)")

    # Parameter-Pass-through wie `/api/pdf/process`
    extraction_method: str = str(getattr(params, "extraction_method", None) or "mistral_ocr")
    template: Optional[str] = getattr(params, "template", None)
    context_any: Any = getattr(params, "context", None)
    context: Optional[Dict[str, Any]] = None
    if isinstance(context_any, dict):
        context = cast(Dict[str, Any], context_any)
    elif isinstance(context_any, str) and context_any.strip():
        try:
            parsed = json.loads(context_any)
            if isinstance(parsed, dict):
                context = cast(Dict[str, Any], parsed)
        except Exception:
            context = None

    use_cache: bool = bool(getattr(params, "use_cache", True))
    include_images: bool = bool(getattr(params, "include_images", False))
    force_refresh: bool = bool(getattr(params, "force_refresh", False))
    page_start = getattr(params, "page_start", None)
    page_end = getattr(params, "page_end", None)

    # Fortschritt initialisieren
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="initializing", percent=5, message="Office-via-PDF Job initialisiert"),
    )

    # Webhook Konfig (wie pdf_handler)
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

    _post_progress("processing", 15, "Office wird nach PDF konvertiert")
    # Konvertierung in job-spezifischen Temp-Ordner (unterhalb pdf temp)
    temp_out = Path("cache") / "office_via_pdf" / "temp" / job.job_id
    pdf_path = _convert_office_to_pdf(Path(normalized_path), temp_out)

    _post_progress("processing", 40, f"PDF wird verarbeitet (extraction_method={extraction_method})")

    processor = PDFProcessor(resource_calculator=resource_calculator, process_id=job.job_id)
    pdf_response = await processor.process(
        file_path=pdf_path,
        template=template,
        context=context,
        extraction_method=extraction_method,
        use_cache=use_cache,
        file_hash=None,
        force_overwrite=force_refresh,
        include_images=include_images,
        page_start=int(page_start) if isinstance(page_start, int) else None,
        page_end=int(page_end) if isinstance(page_end, int) else None,
    )

    # Fehlerpfad
    if getattr(pdf_response, "status", None) == ProcessingStatus.ERROR:
        err = getattr(pdf_response, "error", None)
        err_msg = getattr(err, "message", "PDF-Verarbeitung fehlgeschlagen")
        err_code = getattr(err, "code", "PROCESSING_ERROR")
        raise RuntimeError(f"{err_code}: {err_msg}")

    data = getattr(pdf_response, "data", None)
    if not data:
        raise RuntimeError("Keine Daten vom PDFProcessor")

    meta = getattr(data, "metadata", None)
    process_dir = getattr(meta, "process_dir", None) if meta else None
    if not process_dir:
        # fallback: nutze Konvertierungs-Ordner
        process_dir = str(temp_out)

    _post_progress("postprocessing", 90, "Ergebnisse werden gespeichert")

    # Markdown-Datei schreiben (für Office-Download-Endpoint)
    extracted_text_any: Any = getattr(data, "extracted_text", "")
    extracted_text = str(extracted_text_any or "")
    markdown_filename = f"output_{job.job_id}.md"
    markdown_path = os.path.join(process_dir, markdown_filename)
    try:
        os.makedirs(process_dir, exist_ok=True)
        with open(markdown_path, "w", encoding="utf-8") as f:
            f.write(extracted_text)
    except Exception as e:
        repo.add_log_entry(job.job_id, "warning", f"Konnte Markdown-Datei nicht schreiben: {str(e)}")

    # Archive Base64 persistieren (analog pdf_handler)
    try:
        archive_filename_any: Any = getattr(data, "images_archive_filename", None)
        archive_b64_any: Any = getattr(data, "images_archive_data", None)
        if process_dir and archive_filename_any and isinstance(archive_b64_any, str) and archive_b64_any:
            zip_path = os.path.join(process_dir, str(archive_filename_any))
            with open(zip_path, "wb") as f:
                f.write(base64.b64decode(archive_b64_any))
    except Exception:
        pass

    # mistral_ocr_raw als Datei speichern (wichtig bei extraction_method=mistral_ocr)
    mistral_raw_any: Any = getattr(data, "mistral_ocr_raw", None)
    mistral_raw_file: Optional[str] = None
    if process_dir and isinstance(mistral_raw_any, dict) and mistral_raw_any:
        try:
            mistral_raw_file = f"mistral_ocr_raw_{job.job_id}.json"
            raw_path = os.path.join(process_dir, mistral_raw_file)
            with open(raw_path, "w", encoding="utf-8") as f:
                json.dump(mistral_raw_any, f, ensure_ascii=False, indent=2)
        except Exception as e:
            repo.add_log_entry(job.job_id, "warning", f"mistral_ocr_raw konnte nicht gespeichert werden: {str(e)}")

    # structured_data bereinigen (keine großen Felder)
    response_dict_any: Any = getattr(pdf_response, "to_dict", None)
    if callable(response_dict_any):
        result_dict_any = response_dict_any()
    else:
        result_dict_any = {}
    result_dict: Dict[str, Any] = cast(Dict[str, Any], result_dict_any) if isinstance(result_dict_any, dict) else {}

    # Entferne große Felder aus data
    data_obj_any: Any = result_dict.get("data", {})
    if isinstance(data_obj_any, dict):
        d = cast(Dict[str, Any], data_obj_any)
        d.pop("images_archive_data", None)
        d.pop("pages_archive_data", None)
        d.pop("mistral_ocr_raw", None)

    # Assets extrahieren
    image_paths: List[str] = []
    try:
        meta_any: Any = d.get("metadata") if isinstance(data_obj_any, dict) else None
        if isinstance(meta_any, dict):
            image_paths_any: Any = meta_any.get("image_paths", [])
            if isinstance(image_paths_any, list):
                image_paths = [str(p) for p in cast(List[Any], image_paths_any)]
    except Exception:
        image_paths = []

    # Results persistieren
    duration_ms = int((time.time() - start) * 1000)
    repo.update_job_status(
        job_id=job.job_id,
        status="processing",
        progress=JobProgress(step="postprocessing", percent=95, message="Ergebnisse werden gespeichert"),
        results=JobResults(
            markdown_file=markdown_path,
            markdown_content=None,
            assets=image_paths,
            structured_data=result_dict,
            target_dir=process_dir,
            asset_dir=process_dir,
            archive_filename=getattr(data, "images_archive_filename", None),
        ),
    )

    # Finaler Webhook: URLs statt großer Payloads
    if callback_url:
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if callback_token:
            headers["Authorization"] = f"Bearer {callback_token}"
            headers["X-Callback-Token"] = str(callback_token)
        data_section: Dict[str, Any] = {
            "extracted_text": extracted_text,
            "metadata": {"text_contents": cast(Dict[str, Any], data_obj_any).get("metadata", {}).get("text_contents") if isinstance(data_obj_any, dict) else None},
            "markdown_url": f"/api/office/jobs/{job.job_id}/markdown",
        }
        if mistral_raw_file:
            data_section["mistral_ocr_raw_url"] = f"/api/office/jobs/{job.job_id}/mistral-ocr-raw"
        if include_images:
            data_section["images_archive_url"] = f"/api/jobs/{job.job_id}/download-archive"
        payload_final: Dict[str, Any] = {
            "phase": "completed",
            "message": f"Office-via-PDF abgeschlossen (duration_ms={duration_ms})",
            "data": data_section,
        }
        try:
            requests.post(url=str(callback_url), json=payload_final, headers=headers, timeout=30)
        except Exception:
            repo.add_log_entry(job.job_id, "error", "Webhook-POST fehlgeschlagen")






