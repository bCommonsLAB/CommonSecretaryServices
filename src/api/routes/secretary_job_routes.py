"""
Secretary Job API-Routen (neues System)

Minimal: Enqueue einzelner Job, Enqueue Batch, Get Job, Get Batch.
"""

from typing import Any, Dict, List, Optional, Union, Tuple

from flask import request, Response
from flask_restx import Namespace, Resource, fields  # type: ignore

from src.core.mongodb import SecretaryJobRepository
import base64
import json
from datetime import datetime


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
                return json_response({"error": "Job hat keine Ergebnisse"}, 400)
            if not job.results.archive_data:
                return json_response({"error": "Kein ZIP-Archiv für diesen Job verfügbar"}, 400)

            # Base64-Daten dekodieren
            try:
                archive_bytes = base64.b64decode(job.results.archive_data)
            except Exception:
                return json_response({"error": "Fehlerhafte Archive-Daten"}, 400)

            filename = job.results.archive_filename or f"job-{job_id}.zip"
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


