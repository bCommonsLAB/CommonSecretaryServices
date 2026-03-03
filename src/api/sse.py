"""
@fileoverview SSE (Server-Sent Events) Helper - Formatierung und Streaming fuer Job-Updates

@description
Hilfsfunktionen fuer Server-Sent Events (SSE). Ermoeglicht es Offline-Clients,
Job-Updates in Echtzeit zu empfangen, ohne dass der Client per Webhook erreichbar
sein muss. Der Client oeffnet eine langlebige HTTP-Verbindung, der Server pusht
Events bei Statusaenderungen.

Das SSE-Event-Format orientiert sich am bestehenden Webhook-Payload-Schema,
damit Clients ein einheitliches Datenformat verarbeiten koennen.

@module api.sse

@exports
- format_sse: Formatiert ein SSE-Event als String
- job_event_stream: Generator fuer Job-Updates via MongoDB-Polling

@usedIn
- src.api.routes.secretary_job_routes: SSE-Stream-Endpoint

@dependencies
- Internal: src.core.mongodb - SecretaryJobRepository
- Internal: src.core.models.job_models - Job, JobStatus
"""
import json
import time
import logging
from typing import Any, Dict, Generator, Optional
from datetime import datetime

from src.core.mongodb import SecretaryJobRepository
from src.core.models.job_models import Job, JobStatus

logger = logging.getLogger(__name__)

# Maximale Wartezeit bevor der Stream geschlossen wird (5 Minuten)
MAX_STREAM_DURATION_SEC = 300

# Polling-Intervall fuer MongoDB-Abfragen (Sekunden)
POLL_INTERVAL_SEC = 2

# Heartbeat-Intervall um die Verbindung offen zu halten (Sekunden)
HEARTBEAT_INTERVAL_SEC = 15


class DateTimeEncoder(json.JSONEncoder):
    """JSON-Encoder fuer datetime-Objekte."""
    def default(self, o: Any) -> Any:
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)


def format_sse(data: Dict[str, Any], event: Optional[str] = None) -> str:
    """Formatiert ein SSE-Event als String gemaess SSE-Spezifikation.

    Args:
        data: Payload als Dictionary (wird zu JSON serialisiert)
        event: Optionaler Event-Typ (z.B. 'progress', 'completed', 'error')

    Returns:
        SSE-formatierter String mit abschliessendem Doppel-Newline
    """
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    json_str = json.dumps(data, cls=DateTimeEncoder, ensure_ascii=False)
    lines.append(f"data: {json_str}")
    lines.append("")  # Leerzeile als Event-Trenner
    lines.append("")
    return "\n".join(lines)


def build_event_from_job(job: Job) -> Dict[str, Any]:
    """Erstellt ein SSE-Event-Payload aus einem Job-Objekt.

    Orientiert sich am bestehenden Webhook-Payload-Format fuer Konsistenz.
    Oeffentlich, da auch von Tests und ggf. anderen Modulen genutzt.
    """
    event_data: Dict[str, Any] = {
        "job": {"id": job.job_id},
        "process": {"id": job.job_id, "main_processor": job.job_type},
    }

    if job.status == JobStatus.COMPLETED:
        event_data["phase"] = "completed"
        event_data["message"] = "Verarbeitung abgeschlossen"
        event_data["data"] = {
            "results": job.results.to_dict() if job.results else None
        }
    elif job.status == JobStatus.FAILED:
        event_data["phase"] = "error"
        event_data["message"] = "Verarbeitung fehlgeschlagen"
        event_data["error"] = job.error.to_dict() if job.error else {
            "code": "unknown_error",
            "message": "Unbekannter Fehler"
        }
        event_data["data"] = None
    elif job.status == JobStatus.PROCESSING:
        event_data["phase"] = "running"
        if job.progress:
            event_data["message"] = job.progress.message or f"Verarbeitung laeuft ({job.progress.percent}%)"
            event_data["data"] = {"progress": job.progress.percent}
        else:
            event_data["message"] = "Verarbeitung gestartet"
            event_data["data"] = {"progress": 0}
    else:
        # PENDING
        event_data["phase"] = "pending"
        event_data["message"] = "Job wartet auf Verarbeitung"
        event_data["data"] = {"progress": 0}

    return event_data


def event_type_for_status(status: JobStatus) -> str:
    """Mappt JobStatus auf SSE-Event-Typ."""
    mapping = {
        JobStatus.PENDING: "pending",
        JobStatus.PROCESSING: "progress",
        JobStatus.COMPLETED: "completed",
        JobStatus.FAILED: "error",
    }
    return mapping.get(status, "progress")


def job_event_stream(job_id: str) -> Generator[str, None, None]:
    """Generator fuer SSE-Events eines Jobs.

    Pollt MongoDB in regelmaessigen Intervallen und sendet Events
    bei Statusaenderungen. Schliesst den Stream wenn der Job
    abgeschlossen oder fehlgeschlagen ist, oder nach MAX_STREAM_DURATION_SEC.

    Args:
        job_id: Die Job-ID fuer die Updates gestreamt werden sollen

    Yields:
        SSE-formatierte Strings
    """
    repo = SecretaryJobRepository()
    start_time = time.monotonic()
    last_status: Optional[str] = None
    last_progress_percent: Optional[int] = None
    last_heartbeat = time.monotonic()

    logger.info(f"SSE-Stream gestartet fuer Job {job_id}")

    # Initialen Job-Status senden
    job = repo.get_job(job_id)
    if not job:
        yield format_sse(
            {"phase": "error", "message": "Job nicht gefunden", "job": {"id": job_id}},
            event="error"
        )
        return

    # Initialen Status senden
    event_data = build_event_from_job(job)
    event_type = event_type_for_status(job.status)
    yield format_sse(event_data, event=event_type)
    last_status = job.status.value
    last_progress_percent = job.progress.percent if job.progress else None

    # Sofort beenden wenn Job bereits fertig ist
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
        logger.info(f"SSE-Stream fuer Job {job_id}: Job bereits {job.status.value}")
        return

    # Polling-Loop
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > MAX_STREAM_DURATION_SEC:
            yield format_sse(
                {"phase": "timeout", "message": f"Stream-Timeout nach {MAX_STREAM_DURATION_SEC}s", "job": {"id": job_id}},
                event="timeout"
            )
            logger.warning(f"SSE-Stream Timeout fuer Job {job_id} nach {MAX_STREAM_DURATION_SEC}s")
            break

        time.sleep(POLL_INTERVAL_SEC)

        # Heartbeat senden um Proxy-Timeouts zu vermeiden
        now = time.monotonic()
        if now - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
            yield ": heartbeat\n\n"
            last_heartbeat = now

        job = repo.get_job(job_id)
        if not job:
            yield format_sse(
                {"phase": "error", "message": "Job nicht mehr gefunden", "job": {"id": job_id}},
                event="error"
            )
            break

        current_status = job.status.value
        current_progress = job.progress.percent if job.progress else None

        # Nur senden wenn sich etwas geaendert hat
        if current_status != last_status or current_progress != last_progress_percent:
            event_data = build_event_from_job(job)
            event_type = event_type_for_status(job.status)
            yield format_sse(event_data, event=event_type)
            last_status = current_status
            last_progress_percent = current_progress

        # Stream beenden wenn Job abgeschlossen
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            logger.info(f"SSE-Stream fuer Job {job_id} beendet: {job.status.value}")
            break

    logger.info(f"SSE-Stream fuer Job {job_id} geschlossen nach {time.monotonic() - start_time:.1f}s")
