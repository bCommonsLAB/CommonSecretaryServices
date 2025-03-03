"""
Event-Job API-Routen.
Enthält alle Endpoints zur Verwaltung von Event-Jobs in der MongoDB.
"""
from flask import request, send_file
from flask_restx import Model, Namespace, OrderedModel, Resource, fields  # type: ignore
from typing import Dict, Any, List, Union, Tuple, Optional
import os
import mimetypes
import traceback
import json
from datetime import datetime
import time

from pymongo.results import UpdateResult

from core.models.job_models import Batch, Job
from core.mongodb.repository import EventJobRepository
from src.core.mongodb import get_job_repository
from src.utils.logger import get_logger
from utils.logger import ProcessingLogger

# Initialisiere Logger
logger: ProcessingLogger = get_logger(process_id="event-job-api")

# Erstelle Namespace
event_job_ns = Namespace('event-job', description='Event-Job-Verwaltungs-Operationen')  # type: ignore

# Definiere einen benutzerdefinierten JSON-Encoder für datetime-Objekte
class DateTimeEncoder(json.JSONEncoder):
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)

# Hilfsfunktion für JSON-Antworten mit datetime-Unterstützung
def json_response(data: Dict[str, Any], status_code: int = 200) -> Tuple[Dict[str, Any], int]:
    """
    Erstellt eine JSON-Antwort mit Unterstützung für datetime-Objekte.
    
    Args:
        data: Die zu serialisierenden Daten
        status_code: HTTP-Statuscode (Standard: 200)
        
    Returns:
        Tuple[Dict[str, Any], int]: Tupel aus Daten und Statuscode
    """
    # Konvertiere datetime-Objekte in Strings
    json_data = json.loads(json.dumps(data, cls=DateTimeEncoder))
    return json_data, status_code

# Hilfsfunktion für Fehlerbehandlung
def handle_error(error: Exception) -> Dict[str, Any]:
    """
    Behandelt Fehler und gibt eine standardisierte Fehlerantwort zurück.
    
    Args:
        error: Die aufgetretene Exception
        
    Returns:
        Dict[str, Any]: Fehlerantwort
    """
    logger.error(f"Fehler bei der Verarbeitung: {str(error)}")
    logger.debug(traceback.format_exc())
    
    return {
        "status": "error",
        "message": str(error),
        "details": {
            "type": type(error).__name__,
            "traceback": traceback.format_exc()
        }
    }

# Input-Modelle
job_parameters_model: Model | OrderedModel = event_job_ns.model('JobParameters', {  # type: ignore
    'event': fields.String(required=True, description='Name der Veranstaltung'),
    'session': fields.String(required=True, description='Name der Session'),
    'url': fields.String(required=True, description='URL zur Event-Seite'),
    'filename': fields.String(required=True, description='Zieldateiname für die Markdown-Datei'),
    'track': fields.String(required=True, description='Track/Kategorie der Session'),
    'day': fields.String(required=False, description='Veranstaltungstag im Format YYYY-MM-DD'),
    'starttime': fields.String(required=False, description='Startzeit im Format HH:MM'),
    'endtime': fields.String(required=False, description='Endzeit im Format HH:MM'),
    'speakers': fields.List(fields.String, required=False, description='Liste der Vortragenden'),
    'video_url': fields.String(required=False, description='URL zum Video'),
    'attachments_url': fields.String(required=False, description='URL zu Anhängen'),
    'source_language': fields.String(required=False, default='en', description='Quellsprache'),
    'target_language': fields.String(required=False, default='de', description='Zielsprache')
})

webhook_model: Model | OrderedModel = event_job_ns.model('Webhook', {  # type: ignore
    'url': fields.String(required=True, description='Webhook-URL für Callbacks'),
    'headers': fields.Raw(required=False, description='HTTP-Header für den Webhook-Request'),
    'include_markdown': fields.Boolean(required=False, default=True, description='Markdown-Inhalt im Callback einschließen'),
    'include_metadata': fields.Boolean(required=False, default=True, description='Metadaten im Callback einschließen')
})

job_create_model: Model | OrderedModel = event_job_ns.model('JobCreate', {  # type: ignore
    'parameters': fields.Nested(job_parameters_model, required=True, description='Job-Parameter'),
    'webhook': fields.Nested(webhook_model, required=False, description='Webhook-Konfiguration'),
    'user_id': fields.String(required=False, description='Benutzer-ID'),
    'job_name': fields.String(required=False, description='Benutzerfreundlicher Job-Name')
})

batch_create_model: Model | OrderedModel = event_job_ns.model('BatchCreate', {  # type: ignore
    'jobs': fields.List(fields.Nested(job_create_model), required=True, description='Liste der zu erstellenden Jobs'),
    'webhook': fields.Nested(webhook_model, required=False, description='Webhook-Konfiguration für den gesamten Batch'),
    'batch_name': fields.String(required=False, description='Benutzerfreundlicher Batch-Name'),
    'batch_id': fields.String(required=False, description='Benutzerdefinierte Batch-ID')
})

# Output-Modelle
job_progress_model: Model | OrderedModel = event_job_ns.model('JobProgress', {  # type: ignore
    'step': fields.String(required=True, description='Aktueller Verarbeitungsschritt'),
    'percent': fields.Integer(required=True, description='Prozentualer Fortschritt'),
    'message': fields.String(required=False, description='Statusmeldung')
})

job_results_model: Model | OrderedModel = event_job_ns.model('JobResults', {  # type: ignore
    'markdown_file': fields.String(required=False, description='Pfad zur Markdown-Datei'),
    'markdown_url': fields.String(required=False, description='URL zur Markdown-Datei'),
    'assets': fields.List(fields.Raw, required=False, description='Liste der Assets')
})

job_error_model: Model | OrderedModel = event_job_ns.model('JobError', {  # type: ignore
    'code': fields.String(required=True, description='Fehlercode'),
    'message': fields.String(required=True, description='Fehlermeldung'),
    'details': fields.Raw(required=False, description='Detaillierte Fehlerinformationen')
})

log_entry_model: Model | OrderedModel = event_job_ns.model('LogEntry', {  # type: ignore
    'timestamp': fields.DateTime(required=True, description='Zeitstempel'),
    'level': fields.String(required=True, description='Log-Level'),
    'message': fields.String(required=True, description='Log-Nachricht')
})

job_model: Model | OrderedModel = event_job_ns.model('Job', {  # type: ignore
    'job_id': fields.String(required=True, description='Job-ID'),
    'status': fields.String(required=True, description='Job-Status'),
    'created_at': fields.DateTime(required=True, description='Erstellungszeitpunkt'),
    'updated_at': fields.DateTime(required=True, description='Letztes Update'),
    'started_at': fields.DateTime(required=False, description='Startzeitpunkt'),
    'completed_at': fields.DateTime(required=False, description='Abschlusszeitpunkt'),
    'parameters': fields.Nested(job_parameters_model, required=True, description='Job-Parameter'),
    'progress': fields.Nested(job_progress_model, required=False, description='Fortschrittsinformationen'),
    'results': fields.Nested(job_results_model, required=False, description='Ergebnisse'),
    'error': fields.Nested(job_error_model, required=False, description='Fehlerinformationen'),
    'logs': fields.List(fields.Nested(log_entry_model), required=False, description='Log-Einträge'),
    'batch_id': fields.String(required=False, description='Batch-ID'),
    'job_name': fields.String(required=False, description='Benutzerfreundlicher Job-Name')
})

batch_model: Model | OrderedModel = event_job_ns.model('Batch', {  # type: ignore
    'batch_id': fields.String(required=True, description='Batch-ID'),
    'batch_name': fields.String(required=False, description='Benutzerfreundlicher Batch-Name'),
    'status': fields.String(required=True, description='Batch-Status'),
    'created_at': fields.DateTime(required=True, description='Erstellungszeitpunkt'),
    'updated_at': fields.DateTime(required=True, description='Letztes Update'),
    'completed_at': fields.DateTime(required=False, description='Abschlusszeitpunkt'),
    'total_jobs': fields.Integer(required=True, description='Gesamtzahl der Jobs'),
    'completed_jobs': fields.Integer(required=True, description='Anzahl abgeschlossener Jobs'),
    'failed_jobs': fields.Integer(required=True, description='Anzahl fehlgeschlagener Jobs'),
    'archived': fields.Boolean(required=False, description='Archivierungsstatus')
})

# Response-Modelle
job_response_model: Model | OrderedModel = event_job_ns.model('JobResponse', {  # type: ignore
    'status': fields.String(required=True, description='Response-Status'),
    'job': fields.Nested(job_model, required=False, description='Job-Informationen'),
    'message': fields.String(required=False, description='Statusmeldung')
})

jobs_list_response_model: Model | OrderedModel = event_job_ns.model('JobsListResponse', {  # type: ignore
    'status': fields.String(required=True, description='Response-Status'),
    'total': fields.Integer(required=True, description='Gesamtzahl der Jobs'),
    'jobs': fields.List(fields.Nested(job_model), required=True, description='Liste der Jobs')
})

batch_response_model: Model | OrderedModel = event_job_ns.model('BatchResponse', {  # type: ignore
    'status': fields.String(required=True, description='Response-Status'),
    'batch': fields.Nested(batch_model, required=False, description='Batch-Informationen'),
    'message': fields.String(required=False, description='Statusmeldung')
})

batches_list_response_model: Model | OrderedModel = event_job_ns.model('BatchesListResponse', {  # type: ignore
    'status': fields.String(required=True, description='Response-Status'),
    'total': fields.Integer(required=True, description='Gesamtzahl der Batches'),
    'batches': fields.List(fields.Nested(batch_model), required=True, description='Liste der Batches')
})

error_response_model: Model | OrderedModel = event_job_ns.model('ErrorResponse', {  # type: ignore
    'status': fields.String(required=True, description='Response-Status'),
    'message': fields.String(required=True, description='Fehlermeldung'),
    'details': fields.Raw(required=False, description='Detaillierte Fehlerinformationen')
})

# API-Endpunkte
@event_job_ns.route('/jobs')  # type: ignore
class EventJobsEndpoint(Resource):
    @event_job_ns.expect(job_create_model)  # type: ignore
    @event_job_ns.response(201, 'Job erstellt', job_response_model)  # type: ignore
    @event_job_ns.response(400, 'Validierungsfehler', error_response_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Erstellt einen neuen Event-Job."""
        try:
            # Daten aus dem Request holen
            data = request.get_json()
            
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Benutzer-ID aus dem Request oder den Headern holen
            user_id = data.get('user_id')
            if not user_id and 'X-User-ID' in request.headers:
                user_id = request.headers.get('X-User-ID')
            
            # Job erstellen
            job_id = job_repo.create_job(data, user_id=user_id)
            
            # Job abrufen
            job = job_repo.get_job(job_id)
            
            if job:
                return json_response({
                    "status": "success",
                    "job": job.to_dict(),
                    "message": f"Job {job_id} erfolgreich erstellt"
                }, 201)
            else:
                return json_response({
                    "status": "error",
                    "message": f"Job {job_id} konnte nicht erstellt werden"
                }, 500)
                
        except Exception as e:
            return json_response(handle_error(e), 400)
    
    @event_job_ns.response(200, 'Erfolg', jobs_list_response_model)  # type: ignore
    @event_job_ns.response(400, 'Fehler', error_response_model)  # type: ignore
    def get(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Gibt eine Liste aller Event-Jobs zurück."""
        try:
            # Start der Zeitmessung für den gesamten Endpunkt
            start_time_total = time.time()
            
            # Parameter für Filterung und Paginierung
            status = request.args.get("status")
            batch_id = request.args.get("batch_id")
            user_id = request.args.get("user_id")
            if not user_id and 'X-User-ID' in request.headers:
                user_id = request.headers.get('X-User-ID')
                
            limit = int(request.args.get("limit", 100))
            skip = int(request.args.get("skip", 0))
            
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Zeitmessung für die Datenbankabfrage starten
            start_time_db = time.time()
            
            # Jobs abfragen
            if user_id:
                # Jobs für einen bestimmten Benutzer abfragen
                jobs: List[Job] = job_repo.get_jobs_for_user(
                    user_id=user_id,
                    status=status,
                    limit=limit,
                    skip=skip
                )
                total = job_repo.count_jobs_for_user(user_id=user_id, status=status)
            elif batch_id:
                # Jobs für einen bestimmten Batch abfragen
                jobs = job_repo.get_jobs_for_batch(
                    batch_id=batch_id,
                    limit=limit,
                    skip=skip
                )
                total = job_repo.count_jobs_for_batch(batch_id=batch_id)
            else:
                # Alle Jobs abfragen
                jobs = job_repo.get_jobs(
                    status=status,
                    limit=limit,
                    skip=skip
                )
                total = job_repo.count_jobs(status=status)
            
            # Ende der Zeitmessung für die Datenbankabfrage
            db_query_time = time.time() - start_time_db
            
            # Startzeit für die Serialisierung
            start_time_serialize = time.time()
            
            # Jobs in Dictionaries umwandeln
            job_dicts: List[Dict[str, Any]] = [job.to_dict() for job in jobs]
            
            # Ende der Zeitmessung für die Serialisierung
            serialize_time = time.time() - start_time_serialize
            
            # Ende der Zeitmessung für den gesamten Endpunkt
            total_time = time.time() - start_time_total
            
            # Performance-Logging
            perf_log = {
                "endpoint": "/api/event-job/jobs",
                "batch_id": batch_id,
                "user_id": user_id,
                "status": status,
                "total_jobs": total,
                "returned_jobs": len(jobs),
                "db_query_time_ms": round(db_query_time * 1000, 2),
                "serialize_time_ms": round(serialize_time * 1000, 2),
                "total_time_ms": round(total_time * 1000, 2)
            }
            
            logger.warning(f"PERFORMANCE_LOG: {json.dumps(perf_log)}")
            
            return json_response({
                "status": "success",
                "total": total,
                "jobs": job_dicts,
                # Zusätzliche Performance-Informationen (optional)
                "performance": {
                    "db_query_time_ms": round(db_query_time * 1000, 2),
                    "total_time_ms": round(total_time * 1000, 2)
                }
            })
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/jobs/<string:job_id>')  # type: ignore
class EventJobDetailsEndpoint(Resource):
    @event_job_ns.response(200, 'Erfolg', job_response_model)  # type: ignore
    @event_job_ns.response(404, 'Job nicht gefunden', error_response_model)  # type: ignore
    def get(self, job_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Gibt Details zu einem Event-Job zurück."""
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Job abrufen
            job = job_repo.get_job(job_id)
            
            if not job:
                return json_response({
                    "status": "error",
                    "message": f"Job {job_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and job.user_id and job.user_id != user_id:
                # Prüfen, ob der Benutzer Lesezugriff hat
                if user_id not in job.access_control.read_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung für Job {job_id}"
                    }, 403)
            
            return json_response({
                "status": "success",
                "job": job.to_dict()
            })
                
        except Exception as e:
            return json_response(handle_error(e), 400)
    
    @event_job_ns.response(200, 'Erfolg', job_response_model)  # type: ignore
    @event_job_ns.response(404, 'Job nicht gefunden', error_response_model)  # type: ignore
    def delete(self, job_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Löscht einen Event-Job."""
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Job abrufen
            job = job_repo.get_job(job_id)
            
            if not job:
                return json_response({
                    "status": "error",
                    "message": f"Job {job_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and job.user_id and job.user_id != user_id:
                # Prüfen, ob der Benutzer Schreibzugriff hat
                if user_id not in job.access_control.write_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung zum Löschen von Job {job_id}"
                    }, 403)
            
            # Job löschen
            success = job_repo.delete_job(job_id)
            
            if success:
                return json_response({
                    "status": "success",
                    "message": f"Job {job_id} erfolgreich gelöscht"
                })
            else:
                return json_response({
                    "status": "error",
                    "message": f"Job {job_id} konnte nicht gelöscht werden"
                }, 500)
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/batches')  # type: ignore
class EventBatchesEndpoint(Resource):
    @event_job_ns.expect(batch_create_model)  # type: ignore
    @event_job_ns.response(201, 'Batch erstellt', batch_response_model)  # type: ignore
    @event_job_ns.response(400, 'Validierungsfehler', error_response_model)  # type: ignore
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Erstellt einen neuen Batch von Event-Jobs."""
        try:
            # Daten aus dem Request holen
            data = request.get_json()
            
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Benutzer-ID aus dem Request oder den Headern holen
            user_id = data.get('user_id')
            if not user_id and 'X-User-ID' in request.headers:
                user_id = request.headers.get('X-User-ID')
            
            # Batch erstellen
            jobs = data.get('jobs', [])
            webhook = data.get('webhook')
            batch_name = data.get('batch_name')
            custom_batch_id = data.get('batch_id')
            
            # Batch-Objekt erstellen
            batch_data = {
                "total_jobs": len(jobs),
                "user_id": user_id
            }
            
            # Batch-Name hinzufügen, falls vorhanden
            if batch_name:
                batch_data["batch_name"] = batch_name
                
            # Benutzerdefinierte Batch-ID hinzufügen, falls vorhanden
            if custom_batch_id:
                batch_data["batch_id"] = custom_batch_id
            
            # Batch in der Datenbank erstellen
            batch_id = job_repo.create_batch(batch_data)
            
            # Jobs erstellen und mit dem Batch verknüpfen
            job_ids: List[str] = []
            for job_data in jobs:
                # Webhook aus dem Batch übernehmen, falls nicht im Job definiert
                if webhook and 'webhook' not in job_data:
                    job_data['webhook'] = webhook
                
                # Batch-ID hinzufügen
                job_data['batch_id'] = batch_id
                
                # Benutzer-ID hinzufügen
                if user_id:
                    job_data['user_id'] = user_id
                
                # Job-Name aus den Parametern generieren, falls nicht vorhanden
                if 'job_name' not in job_data and 'parameters' in job_data:
                    params: Dict[str, Any] = job_data['parameters']
                    parts: List[str] = []
                    if 'event' in params:
                        parts.append(params['event'])
                    if 'track' in params:
                        parts.append(params['track'])
                    if 'session' in params:
                        parts.append(params['session'])
                    
                    if parts:
                        job_data['job_name'] = " - ".join(parts)
                
                # Job erstellen
                job_id = job_repo.create_job(job_data)
                job_ids.append(job_id)
            
            # Batch abrufen
            batch: Batch | None = job_repo.get_batch(batch_id)
            
            if batch:
                return json_response({
                    "status": "success",
                    "batch": batch.to_dict(),
                    "message": f"Batch {batch_id} mit {len(job_ids)} Jobs erfolgreich erstellt"
                }, 201)
            else:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} konnte nicht erstellt werden"
                }, 500)
                
        except Exception as e:
            return json_response(handle_error(e), 400)
    
    @event_job_ns.response(200, 'Erfolg', batches_list_response_model)  # type: ignore
    @event_job_ns.response(400, 'Fehler', error_response_model)  # type: ignore
    def get(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Gibt eine Liste aller Batches zurück."""
        try:
            # Parameter für Filterung und Paginierung
            status = request.args.get("status")
            archived = request.args.get("archived") 
            if archived == "true":
                archived = True
            else:
                archived = False
                
            user_id = request.args.get("user_id")
            if not user_id and 'X-User-ID' in request.headers:
                user_id = request.headers.get('X-User-ID')
                
            limit = int(request.args.get("limit", 100))
            skip = int(request.args.get("skip", 0))
            
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Batches abfragen
            if user_id:
                # Batches für einen bestimmten Benutzer abfragen
                batches: List[Batch] = job_repo.get_batches_for_user(
                    user_id=user_id,
                    status=status,
                    limit=limit,
                    skip=skip
                )
                total: int = job_repo.count_batches_for_user(user_id=user_id, status=status)
            else:
                # Alle Batches abfragen
                batches = job_repo.get_batches(
                    status=status,
                    archived=archived,
                    limit=limit,
                    skip=skip
                )
                total = job_repo.count_batches(status=status)
            
            # Batches in Dictionaries umwandeln
            batch_dicts: List[Dict[str, Any]] = [batch.to_dict() for batch in batches]
            
            response_data = {
                "status": "success",
                "total": total,
                "batches": batch_dicts
            }
            
            # Verwende den benutzerdefinierten JSON-Encoder
            return json_response(response_data)
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/batches/<string:batch_id>')  # type: ignore
class EventBatchDetailsEndpoint(Resource):
    @event_job_ns.response(200, 'Erfolg', batch_response_model)  # type: ignore
    @event_job_ns.response(404, 'Batch nicht gefunden', error_response_model)  # type: ignore
    def get(self, batch_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """Gibt Details zu einem Batch zurück."""
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Batch abrufen
            batch: Batch | None = job_repo.get_batch(batch_id)
            
            if not batch:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and batch.user_id and batch.user_id != user_id:
                # Prüfen, ob der Benutzer Lesezugriff hat
                if user_id not in batch.access_control.read_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung für Batch {batch_id}"
                    }, 403)
            
            return json_response({
                "status": "success",
                "batch": batch.to_dict()
            })
                
        except Exception as e:
            return json_response(handle_error(e), 400)
    
    @event_job_ns.response(200, 'Erfolg', batch_response_model)  # type: ignore
    @event_job_ns.response(404, 'Batch nicht gefunden', error_response_model)  # type: ignore
    def delete(self, batch_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Löscht einen Batch und alle zugehörigen Jobs.
        
        Diese Methode löscht alle Jobs eines Batches in einem effizienten Schritt
        und dann den Batch selbst.
        """
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Batch abrufen
            batch: Batch | None = job_repo.get_batch(batch_id)
            
            if not batch:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and batch.user_id and batch.user_id != user_id:
                # Prüfen, ob der Benutzer Schreibzugriff hat
                if user_id not in batch.access_control.write_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung zum Löschen von Batch {batch_id}"
                    }, 403)
            
            # Zunächst alle Jobs des Batches in einem effizienten Schritt löschen
            deleted_jobs_count = job_repo.delete_jobs_by_batch(batch_id)
            
            # Dann den Batch selbst löschen
            batch_delete_result = job_repo.batches.delete_one({"batch_id": batch_id})
            batch_deleted = batch_delete_result.deleted_count > 0
            
            if batch_deleted:
                logger.info(f"Batch {batch_id} erfolgreich gelöscht")
                return json_response({
                    "status": "success",
                    "message": f"Batch {batch_id} und {deleted_jobs_count} zugehörige Jobs erfolgreich gelöscht"
                })
            else:
                logger.warning(f"Batch {batch_id} konnte nicht gelöscht werden")
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} konnte nicht gelöscht werden"
                }, 500)
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/files/<path:file_path>')  # type: ignore
class EventFilesEndpoint(Resource):
    @event_job_ns.response(200, 'Erfolg')  # type: ignore
    @event_job_ns.response(404, 'Datei nicht gefunden', error_response_model)  # type: ignore
    def get(self, file_path: str) -> Any:
        """Gibt eine Event-Datei zurück."""
        try:
            # Pfad zur Datei erstellen
            full_path = os.path.join("events", file_path)
            
            # Prüfen, ob die Datei existiert
            if not os.path.exists(full_path) or not os.path.isfile(full_path):
                return json_response({
                    "status": "error",
                    "message": f"Datei {file_path} nicht gefunden"
                }, 404)
            
            # MIME-Typ bestimmen
            mime_type, _ = mimetypes.guess_type(full_path)
            if not mime_type:
                mime_type = 'application/octet-stream'
            
            # Datei senden
            return send_file(
                full_path,
                mimetype=mime_type,
                as_attachment=False,
                download_name=os.path.basename(full_path)
            )
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/<string:job_id>/restart')  # type: ignore
class EventJobRestartEndpoint(Resource):
    @event_job_ns.response(200, 'Erfolg', job_response_model)  # type: ignore
    @event_job_ns.response(404, 'Job nicht gefunden', error_response_model)  # type: ignore
    def post(self, job_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Startet einen Job neu, indem der Status zurückgesetzt wird.
        
        Diese Methode setzt den Status eines Jobs auf "pending" zurück, damit er erneut
        von der Job-Queue verarbeitet werden kann. Alle bisherigen Ergebnisse, Fehler und
        der Fortschritt werden gelöscht.
        
        Args:
            job_id: Die ID des Jobs, der neu gestartet werden soll.
            
        Returns:
            Response mit Erfolgs- oder Fehlermeldung.
        """
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Job abrufen
            job = job_repo.get_job(job_id)
            
            if not job:
                return json_response({
                    "status": "error",
                    "message": f"Job {job_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and job.user_id and job.user_id != user_id:
                # Prüfen, ob der Benutzer Schreibzugriff hat
                if user_id not in job.access_control.write_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung zum Neustarten von Job {job_id}"
                    }, 403)
            
            # Batch-ID aus dem Request-Body extrahieren (falls vorhanden und gültiger JSON)
            batch_id: Optional[str] = None
            try:
                if request.is_json:
                    data: Dict[str, Any] = request.get_json() or {}
                    batch_id = data.get('batch_id')
            except Exception as e:
                logger.warning(f"Fehler beim Parsen der JSON-Daten: {str(e)}")
                # Ignoriere den Fehler und fahre mit batch_id=None fort
            
            # Verwende die Batch-ID aus dem Job, wenn keine angegeben wurde
            batch_id = job.batch_id if not batch_id else batch_id
            
            # Setze den Job zurück (inkl. Status, Fortschritt, Ergebnisse und Fehler)
            try:
                # Setze den Job-Status zurück auf "pending"
                updated = job_repo.update_job_status(job_id, "pending")
                
                if not updated:
                    return json_response({
                        "status": "error",
                        "message": f"Job {job_id} konnte nicht zurückgesetzt werden"
                    }, 500)
                
                # Aktualisierte Job-Daten abrufen
                updated_job = job_repo.get_job(job_id)
                
                if not updated_job:
                    return json_response({
                        "status": "error",
                        "message": f"Aktualisierter Job {job_id} konnte nicht abgerufen werden"
                    }, 500)
                
                # Erfolgsantwort zurückgeben
                return json_response({
                    "status": "success",
                    "message": f"Job {job_id} wurde erfolgreich für den Neustart zurückgesetzt",
                    "job": updated_job.to_dict()
                })
            except Exception as db_error:
                logger.error(f"Datenbank-Fehler beim Aktualisieren des Jobs: {str(db_error)}")
                return json_response({
                    "status": "error",
                    "message": f"Fehler beim Zurücksetzen des Jobs: {str(db_error)}"
                }, 500)
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/batches/<string:batch_id>/archive')  # type: ignore
class EventBatchArchiveEndpoint(Resource):
    @event_job_ns.response(200, 'Erfolg', batch_response_model)  # type: ignore
    @event_job_ns.response(404, 'Batch nicht gefunden', error_response_model)  # type: ignore
    def post(self, batch_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Archiviert einen Batch durch Setzen des archived-Flags.
        
        Diese Methode setzt das archived-Flag eines Batches auf True, wodurch er in der
        regulären Ansicht ausgeblendet und in einer separaten Archiv-Ansicht angezeigt wird.
        Die Ergebnisse und Daten des Batches (einschließlich Status) bleiben erhalten.
        
        Args:
            batch_id: Die ID des Batches, der archiviert werden soll.
            
        Returns:
            Response mit Erfolgs- oder Fehlermeldung.
        """
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Batch abrufen
            batch = job_repo.get_batch(batch_id)
            
            if not batch:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and batch.user_id and batch.user_id != user_id:
                # Prüfen, ob der Benutzer Schreibzugriff hat
                if user_id not in batch.access_control.write_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung zum Archivieren von Batch {batch_id}"
                    }, 403)
            
            # Batch archivieren durch Setzen des archived-Flags
            success = job_repo.archive_batch(batch_id)
            
            if not success:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} konnte nicht archiviert werden"
                }, 500)
            
            # Aktualisierte Batch-Daten abrufen
            updated_batch = job_repo.get_batch(batch_id)
            
            if not updated_batch:
                return json_response({
                    "status": "error",
                    "message": f"Aktualisierter Batch {batch_id} konnte nicht abgerufen werden"
                }, 500)
            
            # Erfolgsantwort zurückgeben
            return json_response({
                "status": "success",
                "message": f"Batch {batch_id} wurde erfolgreich archiviert",
                "batch": updated_batch.to_dict()
            })
                
        except Exception as e:
            return json_response(handle_error(e), 400)

@event_job_ns.route('/batches/<string:batch_id>/toggle-active')  # type: ignore
class EventBatchToggleActiveEndpoint(Resource):
    @event_job_ns.response(200, 'Erfolg', batch_response_model)  # type: ignore
    @event_job_ns.response(404, 'Batch nicht gefunden', error_response_model)  # type: ignore
    def post(self, batch_id: str) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        """
        Schaltet den isActive-Status eines Batches um.
        
        Diese Methode wechselt den isActive-Status eines Batches zwischen True und False,
        was die Verarbeitung des Batches steuert. Wenn isActive=False ist, werden keine 
        weiteren Jobs aus diesem Batch verarbeitet.
        
        Args:
            batch_id: Die ID des Batches, dessen Status umgeschaltet werden soll.
            
        Returns:
            Response mit Erfolgs- oder Fehlermeldung und dem aktualisierten Batch.
        """
        try:
            # Repository holen
            job_repo: EventJobRepository = get_job_repository()
            
            # Batch abrufen
            batch = job_repo.get_batch(batch_id)
            
            if not batch:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} nicht gefunden"
                }, 404)
            
            # Benutzer-ID aus den Headern holen
            user_id = request.headers.get('X-User-ID')
            
            # Zugriffsrechte prüfen, falls Benutzer-ID vorhanden
            if user_id and batch.user_id and batch.user_id != user_id:
                # Prüfen, ob der Benutzer Schreibzugriff hat
                if user_id not in batch.access_control.write_access:
                    return json_response({
                        "status": "error",
                        "message": f"Keine Berechtigung zum Ändern des Status von Batch {batch_id}"
                    }, 403)
            
            # Aktuellen isActive-Status aus dem MongoDB-Dokument abrufen
            batch_doc = job_repo.batches.find_one({"batch_id": batch_id})
            current_active_status = batch_doc.get("isActive", True) if batch_doc else True
            
            # Wenn das Feld auf oberster Ebene existiert, diesen Wert verwenden
            if batch_doc and "isActive" in batch_doc:
                current_active_status = batch_doc.get("isActive", True)
                
            new_active_status = not current_active_status
            
            # Metadaten und oberste Ebene aktualisieren (Doppelte Speicherung während der Migration)
            update_result: UpdateResult = job_repo.batches.update_one(
                {"batch_id": batch_id},
                {"$set": {
                    "isActive": new_active_status
                }}
            )
            
            if update_result.modified_count == 0:
                return json_response({
                    "status": "error",
                    "message": f"Batch {batch_id} konnte nicht aktualisiert werden"
                }, 500)
            
            # Aktualisierte Batch-Daten abrufen
            updated_batch = job_repo.get_batch(batch_id)
            
            if not updated_batch:
                return json_response({
                    "status": "error",
                    "message": f"Aktualisierter Batch {batch_id} konnte nicht abgerufen werden"
                }, 500)
            
            # Erfolgsantwort zurückgeben
            return json_response({
                "status": "success",
                "message": f"Batch {batch_id} Active-Status wurde auf {new_active_status} gesetzt",
                "batch": updated_batch.to_dict()
            })
            
        except Exception as e:
            logger.error(f"Fehler beim Umschalten des Active-Status: {str(e)}")
            return json_response(handle_error(e), 500) 