"""
@fileoverview Office API Routes - Flask-RESTX endpoints for Office processing (DOCX/XLSX/PPTX)

@description
Zwei Endpoints zum Qualitätsvergleich:
- POST /api/office/process: Pipeline A (python-only) → Job enqueue (job_type=office)
- POST /api/office/process-via-pdf: Pipeline B (LibreOffice→PDF→PDFProcessor) → Job enqueue (job_type=office_via_pdf)

Zusätzlich:
- GET /api/office/jobs/{job_id}/markdown: Download der erzeugten Markdown-Datei
- GET /api/office/jobs/{job_id}/mistral-ocr-raw: Download der gespeicherten Mistral-OCR Rohdaten (Pipeline B)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Dict, Optional, Tuple, Union, cast

from flask import Response, request  # type: ignore
from flask_restx import Namespace, Resource, fields, inputs  # type: ignore
from werkzeug.datastructures import FileStorage

from src.core.mongodb.secretary_repository import SecretaryJobRepository
from src.core.models.job_models import JobStatus
from src.utils.logger import get_logger


logger = get_logger(process_id="office_routes", processor_name="office_routes")
office_ns = Namespace("office", description="Office-Verarbeitung (DOCX/XLSX/PPTX)")


def _mask_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return token
    t = str(token)
    if len(t) <= 6:
        return "***"
    return f"{t[:4]}...{t[-4:]}"


def _raw_form_with_redaction() -> Dict[str, Any]:
    try:
        form_dict: Dict[str, Any] = dict(request.form)  # type: ignore
    except Exception:
        form_dict = {}
    if "callback_token" in form_dict:
        form_dict["callback_token"] = _mask_token(form_dict.get("callback_token"))
    return form_dict


office_process_parser = office_ns.parser()
office_process_parser.add_argument("file", type=FileStorage, location="files", required=True, help="Office-Datei (DOCX/XLSX/PPTX)")  # type: ignore
office_process_parser.add_argument("useCache", location="form", type=inputs.boolean, default=True)  # type: ignore
office_process_parser.add_argument("includeImages", location="form", type=inputs.boolean, default=True)  # type: ignore
office_process_parser.add_argument("includePreviews", location="form", type=inputs.boolean, default=True)  # type: ignore
office_process_parser.add_argument("callback_url", type=str, location="form", required=False)  # type: ignore
office_process_parser.add_argument("callback_token", type=str, location="form", required=False)  # type: ignore
office_process_parser.add_argument("jobId", type=str, location="form", required=False)  # type: ignore
office_process_parser.add_argument("force_refresh", location="form", type=inputs.boolean, required=False)  # type: ignore
office_process_parser.add_argument("wait_ms", location="form", type=int, required=False, default=0)  # type: ignore


# Pipeline B: Parameter analog zu /api/pdf/process, aber erweitert um mistral_ocr
office_via_pdf_parser = office_ns.parser()
office_via_pdf_parser.add_argument("file", type=FileStorage, location="files", required=True, help="Office-Datei (DOCX/XLSX/PPTX)")  # type: ignore
office_via_pdf_parser.add_argument(
    "extraction_method",
    type=str,
    location="form",
    default="mistral_ocr",
    # PDF swagger list + Erweiterung
    choices=[
        "native",
        "tesseract_ocr",
        "both",
        "preview",
        "preview_and_native",
        "llm",
        "llm_and_native",
        "llm_and_ocr",
        "mistral_ocr",
        "preview_and_mistral_ocr",
    ],
    help="Extraktionsmethode (wie /api/pdf/process; Default für Office-via-PDF: mistral_ocr)",
)  # type: ignore
office_via_pdf_parser.add_argument("page_start", type=int, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("page_end", type=int, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("template", type=str, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("context", type=str, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("useCache", location="form", type=inputs.boolean, default=True)  # type: ignore
office_via_pdf_parser.add_argument("includeImages", location="form", type=inputs.boolean, default=False)  # type: ignore
office_via_pdf_parser.add_argument("target_language", type=str, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("callback_url", type=str, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("callback_token", type=str, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("jobId", type=str, location="form", required=False)  # type: ignore
office_via_pdf_parser.add_argument("force_refresh", location="form", type=inputs.boolean, required=False)  # type: ignore
office_via_pdf_parser.add_argument("wait_ms", location="form", type=int, required=False, default=0)  # type: ignore


def _save_upload_to_temp(file: FileStorage, base_dir: str) -> str:
    os.makedirs(base_dir, exist_ok=True)
    filename = file.filename or "upload.bin"
    out_path = os.path.join(base_dir, filename)
    file.save(out_path)
    return out_path


def _json_response(data: Dict[str, Any], status_code: int = 200) -> Tuple[Dict[str, Any], int]:
    return data, status_code


@office_ns.route("/process")  # type: ignore
class OfficeProcessEndpoint(Resource):
    @office_ns.expect(office_process_parser)  # type: ignore
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        process_id = str(uuid.uuid4())
        try:
            logger.info(
                "Eingehende Office-Anfrage (multipart)",
                headers={"Content-Type": request.headers.get("Content-Type")},  # type: ignore
                form=_raw_form_with_redaction(),
            )
        except Exception:
            pass

        args = cast(Dict[str, Any], office_process_parser.parse_args())  # type: ignore
        up: FileStorage = cast(FileStorage, args.get("file"))

        use_cache = bool(args.get("useCache", True))
        include_images = bool(args.get("includeImages", True))
        include_previews = bool(args.get("includePreviews", True))
        callback_url = str(args.get("callback_url", "")) if args.get("callback_url") else None
        callback_token = str(args.get("callback_token", "")) if args.get("callback_token") else None
        job_id_form = str(args.get("jobId", "")) if args.get("jobId") else None
        force_refresh = bool(args.get("force_refresh", False))
        wait_ms = int(args.get("wait_ms", 0) or 0)

        temp_dir = os.path.join("cache", "uploads", "office", process_id)
        temp_file_path = _save_upload_to_temp(up, temp_dir)

        job_repo = SecretaryJobRepository()
        job_webhook: Optional[Dict[str, Any]] = None
        if callback_url:
            job_webhook = {"url": callback_url, "token": callback_token, "jobId": job_id_form or None}

        params: Dict[str, Any] = {
            "filename": temp_file_path,
            "use_cache": use_cache,
            "include_images": include_images,
            "include_previews": include_previews,
            "force_refresh": force_refresh,
        }
        if job_webhook:
            params["webhook"] = job_webhook

        created_job_id = job_repo.create_job({"job_type": "office", "parameters": params})

        if callback_url:
            return _json_response(
                {
                    "status": "accepted",
                    "worker": "secretary",
                    "process": {
                        "id": process_id,
                        "main_processor": "office",
                        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "is_from_cache": False,
                    },
                    "job": {"id": created_job_id},
                    "webhook": {"delivered_to": callback_url},
                    "error": None,
                },
                202,
            )

        # Optional wait_ms (polling)
        if wait_ms > 0:
            deadline = time.time() + (wait_ms / 1000.0)
            while time.time() < deadline:
                job = job_repo.get_job(created_job_id)
                if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    break
                time.sleep(0.25)
            job = job_repo.get_job(created_job_id)
            if job and job.status == JobStatus.COMPLETED and job.results and job.results.structured_data:
                return cast(Dict[str, Any], job.results.structured_data)
            if job and job.status == JobStatus.FAILED and job.error:
                return _json_response(
                    {"status": "error", "error": {"code": job.error.code, "message": job.error.message, "details": job.error.details or {}}},
                    400,
                )

        return _json_response(
            {
                "status": "accepted",
                "worker": "secretary",
                "process": {
                    "id": process_id,
                    "main_processor": "office",
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "is_from_cache": False,
                },
                "job": {"id": created_job_id},
                "webhook": None,
                "error": None,
            },
            202,
        )


@office_ns.route("/process-via-pdf")  # type: ignore
class OfficeViaPdfEndpoint(Resource):
    @office_ns.expect(office_via_pdf_parser)  # type: ignore
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        process_id = str(uuid.uuid4())
        try:
            logger.info(
                "Eingehende Office-via-PDF Anfrage (multipart)",
                headers={"Content-Type": request.headers.get("Content-Type")},  # type: ignore
                form=_raw_form_with_redaction(),
            )
        except Exception:
            pass

        args = cast(Dict[str, Any], office_via_pdf_parser.parse_args())  # type: ignore
        up: FileStorage = cast(FileStorage, args.get("file"))

        extraction_method = str(args.get("extraction_method", "mistral_ocr"))
        template = str(args.get("template", "")) if args.get("template") else None
        context_str = str(args.get("context", "")) if args.get("context") else None
        context: Optional[Dict[str, Any]] = None
        if context_str:
            try:
                parsed = json.loads(context_str)
                if isinstance(parsed, dict):
                    context = cast(Dict[str, Any], parsed)
            except Exception:
                context = None

        use_cache = bool(args.get("useCache", True))
        include_images = bool(args.get("includeImages", False))
        target_language = str(args.get("target_language", "")) if args.get("target_language") else None
        callback_url = str(args.get("callback_url", "")) if args.get("callback_url") else None
        callback_token = str(args.get("callback_token", "")) if args.get("callback_token") else None
        job_id_form = str(args.get("jobId", "")) if args.get("jobId") else None
        force_refresh = bool(args.get("force_refresh", False))
        wait_ms = int(args.get("wait_ms", 0) or 0)

        page_start = args.get("page_start")
        page_end = args.get("page_end")

        temp_dir = os.path.join("cache", "uploads", "office_via_pdf", process_id)
        temp_file_path = _save_upload_to_temp(up, temp_dir)

        job_repo = SecretaryJobRepository()
        job_webhook: Optional[Dict[str, Any]] = None
        if callback_url:
            job_webhook = {"url": callback_url, "token": callback_token, "jobId": job_id_form or None}

        params: Dict[str, Any] = {
            "filename": temp_file_path,
            "extraction_method": extraction_method,
            "template": template,
            "context": context,  # als dict, damit handler nicht JSON parsen muss
            "use_cache": use_cache,
            "include_images": include_images,
            "target_language": target_language,
            "force_refresh": force_refresh,
        }
        if page_start is not None:
            params["page_start"] = int(page_start)
        if page_end is not None:
            params["page_end"] = int(page_end)
        if job_webhook:
            params["webhook"] = job_webhook

        created_job_id = job_repo.create_job({"job_type": "office_via_pdf", "parameters": params})

        if callback_url:
            return _json_response(
                {
                    "status": "accepted",
                    "worker": "secretary",
                    "process": {
                        "id": process_id,
                        "main_processor": "office_via_pdf",
                        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "is_from_cache": False,
                    },
                    "job": {"id": created_job_id},
                    "webhook": {"delivered_to": callback_url},
                    "error": None,
                },
                202,
            )

        if wait_ms > 0:
            deadline = time.time() + (wait_ms / 1000.0)
            while time.time() < deadline:
                job = job_repo.get_job(created_job_id)
                if job and job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    break
                time.sleep(0.25)
            job = job_repo.get_job(created_job_id)
            if job and job.status == JobStatus.COMPLETED and job.results and job.results.structured_data:
                return cast(Dict[str, Any], job.results.structured_data)
            if job and job.status == JobStatus.FAILED and job.error:
                return _json_response(
                    {"status": "error", "error": {"code": job.error.code, "message": job.error.message, "details": job.error.details or {}}},
                    400,
                )

        return _json_response(
            {
                "status": "accepted",
                "worker": "secretary",
                "process": {
                    "id": process_id,
                    "main_processor": "office_via_pdf",
                    "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "is_from_cache": False,
                },
                "job": {"id": created_job_id},
                "webhook": None,
                "error": None,
            },
            202,
        )


@office_ns.route("/jobs/<string:job_id>/markdown")  # type: ignore
class OfficeMarkdownDownloadEndpoint(Resource):
    def get(self, job_id: str) -> Union[Response, Tuple[Dict[str, Any], int]]:
        repo = SecretaryJobRepository()
        job = repo.get_job(job_id)
        if not job:
            return _json_response({"status": "error", "error": {"code": "NotFound", "message": "Job nicht gefunden", "details": {}}}, 404)
        if not job.results:
            # noch in Arbeit?
            st_any: Any = getattr(job, "status", "processing")
            st = str(getattr(st_any, "value", st_any))
            if st in ("pending", "processing"):
                return _json_response({"status": "processing", "message": "Markdown noch nicht bereit"}, 202)
            return _json_response({"status": "error", "error": {"code": "NoResults", "message": "Job hat keine Ergebnisse", "details": {}}}, 400)
        md_path = getattr(job.results, "markdown_file", None)
        if not md_path or not os.path.exists(str(md_path)):
            st_any2: Any = getattr(job, "status", "processing")
            st2 = str(getattr(st_any2, "value", st_any2))
            if st2 in ("pending", "processing"):
                return _json_response({"status": "processing", "message": "Markdown noch nicht bereit"}, 202)
            return _json_response({"status": "error", "error": {"code": "NoMarkdown", "message": "Keine Markdown-Datei gefunden", "details": {}}}, 400)
        with open(str(md_path), "rb") as f:
            content = f.read()
        filename = os.path.basename(str(md_path))
        return Response(
            content,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename=\"{filename}\"', "Content-Length": str(len(content))},
        )


@office_ns.route("/jobs/<string:job_id>/mistral-ocr-raw")  # type: ignore
class OfficeMistralOcrRawDownloadEndpoint(Resource):
    def get(self, job_id: str) -> Union[Response, Tuple[Dict[str, Any], int]]:
        repo = SecretaryJobRepository()
        job = repo.get_job(job_id)
        if not job:
            return _json_response({"status": "error", "error": {"code": "NotFound", "message": "Job nicht gefunden", "details": {}}}, 404)
        # File liegt im asset_dir (process_dir)
        asset_dir = getattr(getattr(job, "results", None), "asset_dir", None)
        if not asset_dir or not os.path.isdir(str(asset_dir)):
            st_any: Any = getattr(job, "status", "processing")
            st = str(getattr(st_any, "value", st_any))
            if st in ("pending", "processing"):
                return _json_response({"status": "processing", "message": "mistral_ocr_raw noch nicht bereit"}, 202)
            return _json_response({"status": "error", "error": {"code": "NoAssetDir", "message": "Kein Asset-Verzeichnis gefunden", "details": {}}}, 400)
        cands = sorted(Path(str(asset_dir)).glob(f"mistral_ocr_raw_{job_id}.json"), reverse=True)
        if not cands:
            st_any2: Any = getattr(job, "status", "processing")
            st2 = str(getattr(st_any2, "value", st_any2))
            if st2 in ("pending", "processing"):
                return _json_response({"status": "processing", "message": "mistral_ocr_raw noch nicht bereit"}, 202)
            return _json_response({"status": "error", "error": {"code": "NoRaw", "message": "Keine mistral_ocr_raw Datei gefunden", "details": {}}}, 400)
        raw_path = cands[0]
        with open(raw_path, "rb") as f:
            content = f.read()
        return Response(
            content,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename=\"{raw_path.name}\"',
                "Content-Length": str(len(content)),
            },
        )






