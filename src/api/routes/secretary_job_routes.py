"""
Secretary Job API-Routen (neues System)

Minimal: Enqueue einzelner Job, Enqueue Batch, Get Job, Get Batch.
"""

from typing import Any, Dict, List, Optional, Union, Tuple, cast

from flask import request, Response
from flask_restx import Namespace, Resource, fields  # type: ignore

from src.core.mongodb import SecretaryJobRepository
import json
from datetime import datetime
import os
import io
import zipfile


secretary_ns = Namespace('jobs', description='Secretary Job Worker – Routen')


# Modelle (vereinfachte Schemata)
enqueue_job_model = secretary_ns.model('EnqueueJob', {  # type: ignore
    'job_type': fields.String(required=True),
    'parameters': fields.Raw(required=True),
    'user_id': fields.String(required=False),
})

enqueue_batch_model = secretary_ns.model('EnqueueBatch', {  # type: ignore
    'batch_name': fields.String(required=False),
    'jobs': fields.List(fields.Nested(enqueue_job_model), required=True),
})


def get_repo() -> SecretaryJobRepository:
    return SecretaryJobRepository()


class DateTimeEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def json_response(data: Dict[str, Any], status_code: int = 200) -> Tuple[Dict[str, Any], int]:
    json_data = json.loads(json.dumps(data, cls=DateTimeEncoder))
    return json_data, status_code

@secretary_ns.route('/')  # type: ignore
class SecretaryJobCreateEndpoint(Resource):
    @secretary_ns.expect(enqueue_job_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        data = request.get_json(force=True)
        job_type = str(data.get('job_type'))
        parameters = data.get('parameters', {})
        user_id: Optional[str] = data.get('user_id')
        job_dict: Dict[str, Any] = {
            'job_type': job_type,
            'parameters': parameters,
        }
        repo = get_repo()
        job_id = repo.create_job(job_dict, user_id=user_id)
        job = repo.get_job(job_id)
        return json_response({'status': 'success', 'data': {'job_id': job_id, 'job': job.to_dict() if job else None}})


@secretary_ns.route('/batch')  # type: ignore
class SecretaryBatchCreateEndpoint(Resource):
    @secretary_ns.expect(enqueue_batch_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        data = request.get_json(force=True)
        jobs: List[Dict[str, Any]] = data.get('jobs', [])
        batch_name: Optional[str] = data.get('batch_name')
        repo = get_repo()
        batch_id = repo.create_batch({'batch_name': batch_name, 'total_jobs': len(jobs)})
        job_ids: List[str] = []
        for j in jobs:
            job_data = {
                'job_type': j.get('job_type'),
                'parameters': j.get('parameters', {}),
                'batch_id': batch_id,
            }
            job_ids.append(repo.create_job(job_data))
        batch = repo.get_batch(batch_id)
        return json_response({'status': 'success', 'data': {'batch_id': batch_id, 'job_ids': job_ids, 'batch': batch.to_dict() if batch else None}})


@secretary_ns.route('/<string:job_id>')  # type: ignore
class SecretaryJobGetEndpoint(Resource):
    def get(self, job_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        repo = get_repo()
        job = repo.get_job(job_id)
        if not job:
            return json_response({'status': 'error', 'error': {'message': 'job not found'}}, 404)
        return json_response({'status': 'success', 'data': job.to_dict()})


@secretary_ns.route('/batch/<string:batch_id>')  # type: ignore
class SecretaryBatchGetEndpoint(Resource):
    def get(self, batch_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        repo = get_repo()
        batch = repo.get_batch(batch_id)
        if not batch:
            return json_response({'status': 'error', 'error': {'message': 'batch not found'}}, 404)
        return json_response({'status': 'success', 'data': batch.to_dict()})


@secretary_ns.route('/<string:job_id>/download-archive')  # type: ignore
class SecretaryJobArchiveDownloadEndpoint(Resource):
    def get(self, job_id: str) -> Union[Response, Tuple[Dict[str, Any], int]]:
        """Lädt das ZIP-Archiv eines Secretary-Jobs herunter (falls vorhanden)."""
        try:
            repo = get_repo()
            job = repo.get_job(job_id)
            if not job:
                return json_response({"error": "Job nicht gefunden"}, 404)
            if not job.results:
                # Wenn der Job noch läuft, signalisiere dem Client: später erneut versuchen
                status_any: Any = getattr(job, 'status', 'processing')
                try:
                    status_str: str = str(status_any.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str = str(status_any)
                if status_str in ("pending", "processing"):
                    return json_response({"status": "processing", "message": "Archiv noch nicht bereit, bitte später erneut versuchen"}, 202)
                return json_response({"error": "Job hat keine Ergebnisse"}, 400)
            # On-demand ZIP aus dem Filesystem erstellen
            asset_dir: Optional[str] = getattr(job.results, 'asset_dir', None)
            assets: List[str] = list(getattr(job.results, 'assets', []) or [])
            # Fallback: aus structured_data extrahieren, wenn assets leer sind
            if not assets:
                try:
                    structured_data_any: Any = getattr(job.results, 'structured_data', {}) or {}
                    structured_data: Dict[str, Any] = structured_data_any if isinstance(structured_data_any, dict) else {}
                    data_section_any: Any = structured_data.get('data', {})
                    data_section: Dict[str, Any] = data_section_any if isinstance(data_section_any, dict) else {}
                    metadata_any: Any = data_section.get('metadata', {})
                    metadata_dict: Dict[str, Any] = metadata_any if isinstance(metadata_any, dict) else {}
                    img_paths_any: Any = metadata_dict.get('image_paths', [])
                    img_paths: List[str]
                    if isinstance(img_paths_any, list):
                        img_paths = [str(path_item) for path_item in cast(List[Any], img_paths_any)]
                    else:
                        img_paths = []
                    assets = img_paths
                except Exception:
                    assets = []
            # Dateien zusammensuchen
            buffer: io.BytesIO = io.BytesIO()
            written_files = 0
            # Wenn bereits ein ZIP im Cache liegt, direkt streamen
            asset_dir_safe: Optional[str] = asset_dir if (asset_dir and os.path.isdir(asset_dir)) else None
            zip_candidates: List[str] = []
            if asset_dir_safe:
                for fname in os.listdir(asset_dir_safe):
                    if fname.lower().endswith('.zip'):
                        zip_candidates.append(os.path.join(asset_dir_safe, fname))
            if zip_candidates:
                try:
                    zip_path = sorted(zip_candidates, key=lambda p: os.path.getmtime(p), reverse=True)[0]
                    with open(zip_path, 'rb') as f:
                        archive_bytes = f.read()
                    filename = os.path.basename(zip_path)
                    return Response(
                        archive_bytes,
                        mimetype='application/zip',
                        headers={
                            'Content-Disposition': f'attachment; filename="{filename}"',
                            'Content-Length': str(len(archive_bytes))
                        }
                    )
                except Exception:
                    # Fallback auf on-the-fly unten
                    pass
            # Fallback: wenn assets leer sind, alle Bild-Dateien im asset_dir rekursiv einsammeln
            if not assets and asset_dir and os.path.isdir(asset_dir):
                for root, _dirs, files in os.walk(asset_dir):
                    for fname in files:
                        lower = fname.lower()
                        if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                            assets.append(os.path.join(root, fname))
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                for p in assets:
                    try:
                        path_str: str = str(p)
                        full_path = path_str
                        if asset_dir and not os.path.isabs(full_path):
                            full_path = os.path.join(asset_dir, full_path)
                        if os.path.exists(full_path) and os.path.isfile(full_path):
                            arcname: str = os.path.join('images', os.path.basename(full_path))
                            zf.write(full_path, arcname=arcname)
                            written_files += 1
                    except Exception:
                        # Einzelne fehlende Dateien ignorieren
                        continue
            if written_files == 0:
                # Status berücksichtigen – möglicherweise kommt der Request zu früh
                status_any2: Any = getattr(job, 'status', 'processing')
                try:
                    status_str2: str = str(status_any2.value)  # type: ignore[attr-defined]
                except Exception:
                    status_str2 = str(status_any2)
                if status_str2 in ("pending", "processing"):
                    return json_response({"status": "processing", "message": "Keine Bilddateien gefunden – Verarbeitung läuft noch"}, 202)
                return json_response({"error": "Keine Bilddateien zum Archivieren gefunden"}, 400)
            archive_bytes = buffer.getvalue()
            filename = getattr(job.results, 'archive_filename', None) or f"job-{job_id}-images.zip"
            return Response(
                archive_bytes,
                mimetype='application/zip',
                headers={
                    'Content-Disposition': f'attachment; filename="{filename}"',
                    'Content-Length': str(len(archive_bytes))
                }
            )
        except Exception as e:
            return json_response({"error": f"Fehler beim Download: {str(e)}"}, 500)


