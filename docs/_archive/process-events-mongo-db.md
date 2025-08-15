# Konzept: Event-Verwaltung mit MongoDB und externe Zugriffsmöglichkeit

## Einleitung

Dieses Dokument beschreibt das Konzept für die Optimierung der Event-Verarbeitung des Common Secretary Services. Die aktuelle Implementierung speichert Event-Aufträge nur im Speicher und verliert bei einem Server-Neustart alle ausstehenden Aufträge. Außerdem sind die verarbeiteten Ergebnisse nur im lokalen Filesystem zugänglich und können nicht leicht von externen Systemen abgerufen werden.

Die Lösung sieht vor:
1. Speichern der Event-Aufträge in einer MongoDB
2. Persistente Statusverwaltung der Event-Verarbeitung
3. Bereitstellung der Ergebnisse über externe URLs
4. REST-API für den Zugriff auf die verarbeiteten Events

## Problembeschreibung

Aktuell bestehen folgende Herausforderungen:

1. **Fehlende Persistenz**: Alle Event-Aufträge existieren nur im Arbeitsspeicher des Servers. Bei einem Neustart gehen alle Informationen über ausstehende und laufende Aufträge verloren.
2. **Begrenzte Skalierbarkeit**: Die sequentielle Verarbeitung ohne robustes Queueing-System limitiert die Möglichkeit, viele Events zu verarbeiten (z.B. 1000 Events mit je 5-10 Minuten Verarbeitungszeit).
3. **Eingeschränkte Zugriffsmöglichkeit**: Die verarbeiteten Events (Markdown-Dateien, Bilder) sind nur im lokalen Filesystem des Servers verfügbar.
4. **Fehlendes zentrales Monitoring**: Kein einfacher Überblick über den Status aller laufenden und abgeschlossenen Event-Verarbeitungen.

## Architekturkonzept

Das folgende Konzept adressiert diese Herausforderungen:

### 1. MongoDB als persistente Job-Queue

```
+-------------+     +----------------+     +-------------+
| API-Request |---->| MongoDB Queue  |<----| Worker      |
+-------------+     | - job_id       |     | Prozesse    |
                    | - status       |     +-------------+
                    | - parameters   |           |
                    | - timestamps   |           |
                    | - results      |           |
                    +----------------+           |
                            ^                    |
                            |                    |
                    +----------------+           |
                    | Status-Updates |<----------+
                    +----------------+
```

### 2. Datenbankschema

#### Event-Job Collection

```javascript
{
  "_id": ObjectId("..."),                // MongoDB ID
  "job_id": "unique-job-id",            // Eindeutige Job-ID
  "status": "pending",                   // pending, processing, completed, failed
  "created_at": ISODate("..."),          // Erstellungszeitpunkt
  "updated_at": ISODate("..."),          // Letztes Update
  "started_at": ISODate("..."),          // Startzeitpunkt (wenn gestartet)
  "completed_at": ISODate("..."),        // Abschlusszeitpunkt (wenn abgeschlossen)
  "parameters": {                        // Event-Parameter
    "event": "Event Name",
    "session": "Session Name",
    "url": "https://example.com/event",
    "filename": "event.md",
    "track": "Track Name",
    "day": "2023-01-01",
    "starttime": "10:00",
    "endtime": "11:00",
    "speakers": ["Speaker 1", "Speaker 2"],
    "video_url": "https://example.com/video",
    "attachments_url": "https://example.com/attachments",
    "source_language": "en",
    "target_language": "de"
  },
  "webhook": {                           // Optional: Webhook-Konfiguration
    "url": "https://example.com/webhook",
    "headers": {"Authorization": "..."},
    "include_markdown": true,
    "include_metadata": true
  },
  "batch_id": "batch-123",               // Optional: ID des Batches
  "progress": {                          // Fortschrittsinformationen
    "step": "downloading_video",         // Aktueller Verarbeitungsschritt
    "percent": 60,                       // Prozentualer Fortschritt
    "message": "Video wird verarbeitet"  // Statusmeldung
  },
  "results": {                           // Ergebnisse (wenn abgeschlossen)
    "markdown_file": "/events/track/session/event.md",  // Dateipfad
    "markdown_url": "/api/events/files/track/session/event.md",  // Externe URL
    "assets": [                          // Verarbeitete Assets
      {
        "type": "image",
        "path": "/events/track/session/assets/image1.jpg",
        "url": "/api/events/files/track/session/assets/image1.jpg"
      }
    ],
    "metadata": {                        // Sonstige Metadaten
      "processed_at": ISODate("..."),
      "duration": 300,
      "tokens_used": 1500
    }
  },
  "error": {                             // Fehlerinformationen (wenn fehlgeschlagen)
    "code": "PROCESSING_ERROR",
    "message": "Fehler bei der Verarbeitung: ...",
    "details": {...}
  },
  "logs": [                              // Detaillierte Log-Einträge
    {
      "timestamp": ISODate("..."),
      "level": "info",
      "message": "Event-Verarbeitung gestartet"
    },
    {
      "timestamp": ISODate("..."),
      "level": "error",
      "message": "Fehler beim Herunterladen des Videos"
    }
  ],
  "worker_id": "worker-1",               // ID des verarbeitenden Workers
  "retries": 0,                          // Anzahl der Wiederholungsversuche
  "priority": 1,                          // Priorität des Jobs (optional)
  "user_id": "user-123",                 // ID des Benutzers, der den Job erstellt hat
  "access_control": {                    // Zugriffssteuerung (optional)
    "visibility": "private",             // private, team, public
    "read_access": ["user-456", "team-marketing"], // Benutzer/Gruppen mit Lesezugriff
    "write_access": ["user-123"],        // Benutzer/Gruppen mit Schreibzugriff
    "admin_access": ["user-123"]         // Benutzer/Gruppen mit Admin-Zugriff
  }
}
```

#### Event-Batch Collection

```javascript
{
  "_id": ObjectId("..."),                // MongoDB ID
  "batch_id": "batch-123",               // Eindeutige Batch-ID
  "status": "processing",                // processing, completed, failed, partial
  "created_at": ISODate("..."),          // Erstellungszeitpunkt
  "updated_at": ISODate("..."),          // Letztes Update
  "job_ids": ["job-1", "job-2", "job-3"], // IDs der zugehörigen Jobs
  "total_jobs": 10,                      // Gesamtzahl der Jobs
  "completed_jobs": 3,                   // Abgeschlossene Jobs
  "failed_jobs": 1,                      // Fehlgeschlagene Jobs
  "webhook": {                           // Optional: Webhook-Konfiguration
    "url": "https://example.com/webhook",
    "headers": {"Authorization": "..."}
  },
  "parameters": {...},                   // Gemeinsame Parameter
  "summary": {                           // Zusammenfassung
    "duration": 1500,                    // Gesamtdauer in Sekunden
    "tokens_used": 15000                 // Gesamtzahl verwendeter Tokens
  }
}
```

### 3. Systemkomponenten

#### Event-Job-Manager

- Verantwortlich für die Verwaltung der Event-Jobs
- Schnittstelle zur MongoDB
- CRUD-Operationen für Jobs
- Statusaktualisierungen

#### Event-Worker-Manager

- Überwacht die Job-Queue
- Startet Worker-Prozesse für ausstehende Jobs
- Stellt sicher, dass nicht zu viele Jobs gleichzeitig bearbeitet werden
- Aktualisiert den Job-Status

#### Event-Result-Manager

- Verwaltet die Speicherung der Verarbeitungsergebnisse
- Generiert URLs für den Zugriff auf die Ergebnisse
- Stellt die Schnittstelle für externe Zugriffe bereit

#### API-Erweiterungen

- Endpunkte für die Jobverwaltung
- Endpunkte für den Zugriff auf Ergebnisse
- Endpunkte für Statusabfragen und Monitoring

## Implementierungsplan

### 1. Datenzugriffslayer für MongoDB

```python
# MongoDB-Integration
from pymongo import MongoClient
from bson import ObjectId
import datetime

class EventJobRepository:
    def __init__(self, mongo_uri: str, db_name: str):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.jobs = self.db.event_jobs
        self.batches = self.db.event_batches
        
        # Indizes erstellen
        self.jobs.create_index("job_id", unique=True)
        self.jobs.create_index("status")
        self.jobs.create_index("batch_id")
        self.jobs.create_index("created_at")
        self.batches.create_index("batch_id", unique=True)
    
    def create_job(self, job_data: dict) -> str:
        """Erstellt einen neuen Job und gibt die Job-ID zurück."""
        job_id = f"job-{ObjectId()}"
        job_data["job_id"] = job_id
        job_data["status"] = "pending"
        job_data["created_at"] = datetime.datetime.utcnow()
        job_data["updated_at"] = job_data["created_at"]
        
        self.jobs.insert_one(job_data)
        return job_id
        
    def update_job_status(self, job_id: str, status: str, 
                         progress: dict = None, 
                         results: dict = None, 
                         error: dict = None) -> bool:
        """Aktualisiert den Status eines Jobs."""
        update_data = {
            "status": status,
            "updated_at": datetime.datetime.utcnow()
        }
        
        if status == "processing" and "started_at" not in self.get_job(job_id):
            update_data["started_at"] = update_data["updated_at"]
        
        if status == "completed" or status == "failed":
            update_data["completed_at"] = update_data["updated_at"]
        
        if progress:
            update_data["progress"] = progress
            
        if results:
            update_data["results"] = results
            
        if error:
            update_data["error"] = error
            
        result = self.jobs.update_one(
            {"job_id": job_id},
            {"$set": update_data}
        )
        
        return result.modified_count > 0
        
    def get_job(self, job_id: str) -> dict:
        """Gibt einen Job anhand seiner ID zurück."""
        return self.jobs.find_one({"job_id": job_id})
    
    def get_pending_jobs(self, limit: int = 10) -> list:
        """Gibt eine Liste ausstehender Jobs zurück."""
        return list(self.jobs.find({"status": "pending"})
                   .sort("created_at", 1)
                   .limit(limit))
                   
    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        """Fügt einen Log-Eintrag zu einem Job hinzu."""
        log_entry = {
            "timestamp": datetime.datetime.utcnow(),
            "level": level,
            "message": message
        }
        
        result = self.jobs.update_one(
            {"job_id": job_id},
            {"$push": {"logs": log_entry}}
        )
        
        return result.modified_count > 0
        
    def create_batch(self, batch_data: dict) -> str:
        """Erstellt einen neuen Batch und gibt die Batch-ID zurück."""
        batch_id = f"batch-{ObjectId()}"
        batch_data["batch_id"] = batch_id
        batch_data["status"] = "processing"
        batch_data["created_at"] = datetime.datetime.utcnow()
        batch_data["updated_at"] = batch_data["created_at"]
        batch_data["completed_jobs"] = 0
        batch_data["failed_jobs"] = 0
        
        self.batches.insert_one(batch_data)
        return batch_id
        
    def update_batch_progress(self, batch_id: str) -> bool:
        """Aktualisiert den Fortschritt eines Batches."""
        batch = self.batches.find_one({"batch_id": batch_id})
        if not batch:
            return False
            
        # Zähle Jobs nach Status
        total = len(batch["job_ids"])
        completed = self.jobs.count_documents({"job_id": {"$in": batch["job_ids"]}, "status": "completed"})
        failed = self.jobs.count_documents({"job_id": {"$in": batch["job_ids"]}, "status": "failed"})
        
        # Aktualisiere Batch-Status
        status = "processing"
        if completed + failed == total:
            status = "completed" if failed == 0 else "partial" if completed > 0 else "failed"
            
        result = self.batches.update_one(
            {"batch_id": batch_id},
            {"$set": {
                "status": status,
                "completed_jobs": completed,
                "failed_jobs": failed,
                "updated_at": datetime.datetime.utcnow()
            }}
        )
        
        return result.modified_count > 0
```

### 2. EventWorkerManager

```python
import time
import threading
import asyncio
from typing import List, Dict, Any, Optional

class EventWorkerManager:
    def __init__(self, job_repository: EventJobRepository, 
                max_concurrent_workers: int = 5):
        self.job_repo = job_repository
        self.max_concurrent_workers = max_concurrent_workers
        self.running_workers: Dict[str, threading.Thread] = {}
        self.stop_flag = False
        self.monitor_thread = None
        
    def start(self):
        """Startet den Worker-Manager."""
        self.stop_flag = False
        self.monitor_thread = threading.Thread(target=self._monitor_jobs)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
    def stop(self):
        """Stoppt den Worker-Manager."""
        self.stop_flag = True
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
            
    def _monitor_jobs(self):
        """Überwacht die Job-Queue und startet Worker."""
        while not self.stop_flag:
            try:
                # Bereinige beendete Worker
                self._cleanup_workers()
                
                # Wenn noch Kapazität vorhanden ist, suche nach neuen Jobs
                if len(self.running_workers) < self.max_concurrent_workers:
                    available_slots = self.max_concurrent_workers - len(self.running_workers)
                    pending_jobs = self.job_repo.get_pending_jobs(limit=available_slots)
                    
                    for job in pending_jobs:
                        self._start_worker(job)
                        
            except Exception as e:
                print(f"Fehler im Job-Monitor: {str(e)}")
                
            # Warte kurz vor dem nächsten Durchlauf
            time.sleep(5)
    
    def _cleanup_workers(self):
        """Entfernt beendete Worker aus der Liste."""
        completed_workers = [job_id for job_id, thread in self.running_workers.items() 
                            if not thread.is_alive()]
        for job_id in completed_workers:
            del self.running_workers[job_id]
    
    def _start_worker(self, job: Dict[str, Any]):
        """Startet einen neuen Worker für einen Job."""
        job_id = job["job_id"]
        
        # Aktualisiere den Job-Status
        self.job_repo.update_job_status(
            job_id=job_id,
            status="processing",
            progress={"step": "initializing", "percent": 0, "message": "Job wird initialisiert"}
        )
        
        # Starte den Worker in einem eigenen Thread
        worker_thread = threading.Thread(
            target=self._run_worker_process,
            args=(job,)
        )
        worker_thread.daemon = True
        worker_thread.start()
        
        # Speichere den Worker
        self.running_workers[job_id] = worker_thread
        
    def _run_worker_process(self, job: Dict[str, Any]):
        """Führt den eigentlichen Worker-Prozess aus."""
        job_id = job["job_id"]
        batch_id = job.get("batch_id")
        
        try:
            # Führe den Event-Processor aus
            asyncio.run(self._process_event(job))
            
            # Aktualisiere den Batch-Status, falls vorhanden
            if batch_id:
                self.job_repo.update_batch_progress(batch_id)
                
        except Exception as e:
            # Bei Fehler den Job-Status aktualisieren
            error_info = {
                "code": type(e).__name__,
                "message": str(e),
                "details": {"traceback": traceback.format_exc()}
            }
            
            self.job_repo.update_job_status(
                job_id=job_id,
                status="failed",
                error=error_info
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="error",
                message=f"Fehler bei der Verarbeitung: {str(e)}"
            )
            
            # Batch aktualisieren
            if batch_id:
                self.job_repo.update_batch_progress(batch_id)
    
    async def _process_event(self, job: Dict[str, Any]):
        """Verarbeitet ein Event mit dem EventProcessor."""
        from src.processors.event_processor import EventProcessor
        from src.core.resource_calculator import ResourceCalculator
        
        job_id = job["job_id"]
        params = job["parameters"]
        
        # Initialisiere den Event-Processor
        processor = EventProcessor(
            resource_calculator=ResourceCalculator(),
            process_id=job_id
        )
        
        # Aktualisiere den Job-Status
        self.job_repo.update_job_status(
            job_id=job_id,
            status="processing",
            progress={"step": "processing", "percent": 10, "message": "Event-Verarbeitung läuft"}
        )
        
        # Verarbeite das Event
        result = await processor.process_event(
            event=params["event"],
            session=params["session"],
            url=params["url"],
            filename=params["filename"],
            track=params["track"],
            day=params.get("day"),
            starttime=params.get("starttime"),
            endtime=params.get("endtime"),
            speakers=params.get("speakers", []),
            video_url=params.get("video_url"),
            attachments_url=params.get("attachments_url"),
            source_language=params.get("source_language", "en"),
            target_language=params.get("target_language", "de")
        )
        
        # Verarbeite das Ergebnis
        if result.status == "success" and result.data:
            # Erstelle URLs für die Ergebnisse
            markdown_file = result.data.output.markdown_file
            base_path = "/events/"
            relative_path = markdown_file.replace(base_path, "")
            markdown_url = f"/api/events/files/{relative_path}"
            
            # Sammle Asset-URLs
            assets = []
            if "gallery" in result.data.output.metadata:
                for asset_path in result.data.output.metadata["gallery"]:
                    asset_url = f"/api/events/files/{relative_path}/{asset_path}"
                    assets.append({
                        "type": "image",
                        "path": asset_path,
                        "url": asset_url
                    })
            
            # Aktualisiere den Job-Status mit den Ergebnissen
            self.job_repo.update_job_status(
                job_id=job_id,
                status="completed",
                progress={"step": "completed", "percent": 100, "message": "Verarbeitung abgeschlossen"},
                results={
                    "markdown_file": markdown_file,
                    "markdown_url": markdown_url,
                    "assets": assets,
                    "metadata": result.data.output.metadata
                }
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="info",
                message="Event-Verarbeitung erfolgreich abgeschlossen"
            )
            
            # Webhook-Callback senden, falls konfiguriert
            if "webhook" in job:
                await self._send_webhook_callback(job, result)
        else:
            # Fehlerfall
            error_info = {
                "code": result.error.code if result.error else "PROCESSING_ERROR",
                "message": result.error.message if result.error else "Unbekannter Fehler",
                "details": result.error.details if result.error and hasattr(result.error, "details") else {}
            }
            
            self.job_repo.update_job_status(
                job_id=job_id,
                status="failed",
                error=error_info
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="error",
                message=f"Fehler bei der Verarbeitung: {error_info['message']}"
            )
    
    async def _send_webhook_callback(self, job: Dict[str, Any], result: Any):
        """Sendet einen Webhook-Callback."""
        # Implementierung ähnlich wie in EventProcessor._send_webhook_callback
        pass
```

### 3. API-Erweiterungen

#### Neue API-Endpoints

```python
@api.route('/events/jobs')
class EventJobsEndpoint(Resource):
    @api.expect(api.model('EventJobRequest', {...}))
    @api.response(200, 'Erfolg', api.model('EventJobResponse', {...}))
    def post(self):
        """Erstellt einen neuen Event-Job."""
        data = request.get_json()
        # Job erstellen und in MongoDB speichern
        job_id = event_job_repository.create_job(data)
        return {"status": "success", "job_id": job_id}
        
    @api.response(200, 'Erfolg', api.model('EventJobsList', {...}))
    def get(self):
        """Gibt eine Liste aller Event-Jobs zurück."""
        # Parameter für Filterung und Paginierung
        status = request.args.get("status")
        batch_id = request.args.get("batch_id")
        limit = int(request.args.get("limit", 100))
        skip = int(request.args.get("skip", 0))
        
        # Jobs abfragen
        # ...
        return {"status": "success", "total": total, "jobs": jobs}

@api.route('/events/jobs/<string:job_id>')
class EventJobDetailsEndpoint(Resource):
    @api.response(200, 'Erfolg', api.model('EventJobDetail', {...}))
    @api.response(404, 'Job nicht gefunden')
    def get(self, job_id):
        """Gibt Details zu einem Event-Job zurück."""
        job = event_job_repository.get_job(job_id)
        if not job:
            return {"status": "error", "message": "Job nicht gefunden"}, 404
        return {"status": "success", "job": job}
        
    @api.expect(api.model('EventJobUpdate', {...}))
    @api.response(200, 'Erfolg')
    @api.response(404, 'Job nicht gefunden')
    def put(self, job_id):
        """Aktualisiert einen Event-Job."""
        # ...
        
    @api.response(200, 'Erfolg')
    @api.response(404, 'Job nicht gefunden')
    def delete(self, job_id):
        """Löscht einen Event-Job."""
        # ...

@api.route('/events/batches')
class EventBatchesEndpoint(Resource):
    # Ähnliche Implementierung wie für Jobs
    pass

@api.route('/events/files/<path:file_path>')
class EventFilesEndpoint(Resource):
    @api.response(200, 'Erfolg')
    @api.response(404, 'Datei nicht gefunden')
    def get(self, file_path):
        """Gibt eine Event-Datei zurück."""
        full_path = os.path.join("events", file_path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            return {"status": "error", "message": "Datei nicht gefunden"}, 404
            
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
```

## Integration in bestehenden Code

Die bestehende `_process_many_events_async_task`-Methode sollte durch eine MongoDB-basierte Implementierung ersetzt werden:

```python
async def _process_many_events_async_task(self, input_data: AsyncBatchEventInput) -> None:
    """
    Task für die asynchrone Verarbeitung mehrerer Events.
    
    Erstellt Jobs in der MongoDB und startet den Worker-Manager.
    
    Args:
        input_data: Eingabedaten für die Event-Verarbeitung
    """
    from src.core.mongodb import get_job_repository
    
    self.logger.info(
        "Starte asynchrone Batchverarbeitung über MongoDB",
        event_count=len(input_data.events)
    )
    
    # Job-Repository holen
    job_repo = get_job_repository()
    
    # Batch erstellen
    batch_id = job_repo.create_batch({
        "total_jobs": len(input_data.events),
        "webhook": input_data.webhook.to_dict() if input_data.webhook else None,
        "parameters": {}  # Gemeinsame Parameter, falls vorhanden
    })
    
    # Jobs für jedes Event erstellen
    for event_index, event in enumerate(input_data.events):
        # Event-Daten validieren
        event_data = self._validate_event_data(event)
        if not event_data:
            self.logger.warning(
                f"Ungültige Event-Daten, überspringe Event {event_index}",
                event_id=event_index
            )
            continue
            
        # Job erstellen
        job_repo.create_job({
            "batch_id": batch_id,
            "parameters": event_data,
            "webhook": input_data.webhook.to_dict() if input_data.webhook else None
        })
        
    self.logger.info(
        f"Batch-Job erstellt mit ID {batch_id}, {len(input_data.events)} Events in die Queue eingereiht"
    )
    
    return
```

## Überwachung und Monitoring

Für die Überwachung der Event-Jobs soll ein einfaches Monitoring-Dashboard implementiert werden:

```python
@app.route('/monitoring/events')
def event_monitoring_dashboard():
    """Rendert das Event-Monitoring-Dashboard."""
    return render_template('event_monitoring.html')

@app.route('/api/monitoring/events/stats')
def event_monitoring_stats():
    """Gibt Statistiken zu den Event-Jobs zurück."""
    job_repo = get_job_repository()
    
    # Statistiken abrufen
    total_jobs = job_repo.jobs.count_documents({})
    pending_jobs = job_repo.jobs.count_documents({"status": "pending"})
    processing_jobs = job_repo.jobs.count_documents({"status": "processing"})
    completed_jobs = job_repo.jobs.count_documents({"status": "completed"})
    failed_jobs = job_repo.jobs.count_documents({"status": "failed"})
    
    # Batch-Statistiken
    total_batches = job_repo.batches.count_documents({})
    active_batches = job_repo.batches.count_documents({"status": "processing"})
    
    # Nach Track gruppieren
    track_stats = list(job_repo.jobs.aggregate([
        {"$group": {
            "_id": "$parameters.track",
            "count": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}}
        }}
    ]))
    
    return {
        "status": "success",
        "stats": {
            "jobs": {
                "total": total_jobs,
                "pending": pending_jobs,
                "processing": processing_jobs,
                "completed": completed_jobs,
                "failed": failed_jobs
            },
            "batches": {
                "total": total_batches,
                "active": active_batches
            },
            "tracks": track_stats
        }
    }
```

## Konfiguration

Die MongoDB-Konfiguration sollte in der Anwendungskonfiguration hinzugefügt werden:

```python
# Konfigurationsbeispiel
MONGODB_URI = "mongodb://localhost:27017/"
MONGODB_DB_NAME = "event_processing"
MONGODB_MAX_POOL_SIZE = 50
MONGODB_CONNECT_TIMEOUT_MS = 5000

# Worker-Konfiguration
EVENT_WORKER_MAX_CONCURRENT = 5
EVENT_WORKER_POLL_INTERVAL_SEC = 5
```

## Deployment-Überlegungen

1. **MongoDB-Setup**: Für Produktionsumgebungen sollte eine MongoDB mit Replikation eingerichtet werden.
2. **Worker-Skalierung**: Die Worker könnten in separaten Prozessen/Containern laufen, um die Verarbeitung zu skalieren.
3. **Datensicherung**: Regelmäßige Backups der MongoDB-Datenbank sollten eingerichtet werden.
4. **Ressourcenplanung**: Ausreichend Speicherplatz für die verarbeiteten Events (Markdown, Bilder) sicherstellen.

## Fazit

Die vorgeschlagene Lösung ermöglicht:

1. **Robustheit**: Keine Datenverluste bei Server-Neustarts
2. **Skalierbarkeit**: Effiziente Verarbeitung großer Event-Mengen
3. **Zugänglichkeit**: Einfacher externer Zugriff auf verarbeitete Events
4. **Transparenz**: Umfassende Überwachung des Verarbeitungsstatus

Die Implementierung sollte schrittweise erfolgen, beginnend mit der MongoDB-Integration, gefolgt von den Worker-Komponenten und schließlich den API-Erweiterungen.

## Erweiterungen und Klarstellungen

### Benutzer-Autorisierung

Um Event-Jobs mit unterschiedlichen Autorisierungsstufen zu verwalten, wird ein `userId` eingeführt. Dies ermöglicht eine benutzerbasierte Zugriffskontrolle.

#### Datenbankschema-Erweiterung

```javascript
{
  // Bestehende Felder...
  "user_id": "user-123",                 // ID des Benutzers, der den Job erstellt hat
  "access_control": {                    // Zugriffssteuerung (optional)
    "visibility": "private",             // private, team, public
    "read_access": ["user-456", "team-marketing"], // Benutzer/Gruppen mit Lesezugriff
    "write_access": ["user-123"],        // Benutzer/Gruppen mit Schreibzugriff
    "admin_access": ["user-123"]         // Benutzer/Gruppen mit Admin-Zugriff
  }
}
```

### Überflüssige API-Endpunkte und Prozesse

Folgende bestehende Komponenten werden durch die MongoDB-Lösung ersetzt oder modifiziert:

- **API-Endpunkte:**
  - `/process-events-async` (ersetzt durch `/events/jobs`)
  - `/process-many-events` (ersetzt durch `/events/batches`)
  - `/test-webhook-callback` (modifiziert für Tests)
  - `/test-webhook-logs` (ersetzt durch Monitoring-API)

- **Prozesse:**
  - `_process_many_events_async_task` (ersetzt durch MongoDB-basierte Job-Verwaltung)
  - Isolierte Prozess-Verarbeitung via Subprocess (ersetzt durch Worker-Manager)

### Konfiguration in config.yaml

Die Datenbankparameter werden in der `config.yaml` gespeichert:

```yaml
mongodb:
  uri: "mongodb://localhost:27017/"
  db_name: "event_processing"
  max_pool_size: 50
  connect_timeout_ms: 5000

event_worker:
  max_concurrent: 5
  poll_interval_sec: 5
```

### Architektur der Datenbankkomponente

Die MongoDB-Komponente wird als Core-Komponente implementiert:

```
src/
  core/
    mongodb/
      __init__.py
      repository.py
      connection.py
  processors/
    event_processor.py
  utils/
    performance_tracker.py
```

## Umsetzungsplan

### Schritt 1: MongoDB-Integration
- MongoDB-Verbindung und Repository implementieren
- Datenbankschema definieren und Indizes erstellen

### Schritt 2: Benutzer-Autorisierung
- `userId` und Zugriffskontrolle implementieren
- API-Endpunkte anpassen

### Schritt 3: Worker-Manager
- Worker-Manager implementieren
- Job-Verarbeitung und Statusaktualisierung integrieren

### Schritt 4: API-Erweiterungen
- Neue API-Endpunkte für Job- und Batch-Verwaltung erstellen
- Externe URL-Zugriffe ermöglichen

### Schritt 5: Monitoring und Dashboard
- Monitoring-Dashboard implementieren
- Statistiken und Statusinformationen bereitstellen

### Schritt 6: Deployment und Tests
- MongoDB-Setup und Worker-Skalierung planen
- Umfangreiche Tests durchführen

## Fazit

Die vorgeschlagene Lösung bietet eine robuste, skalierbare und transparente Event-Verwaltung mit benutzerbasierter Autorisierung und externem Zugriff auf Ergebnisse. Die schrittweise Implementierung gewährleistet eine reibungslose Integration in die bestehende Infrastruktur. 

# Zusammenfassung der Anforderungen

## Zielsetzung

Die Event-Verwaltung des Common Secretary Services soll optimiert werden, um:

1. Persistente Speicherung der Event-Aufträge in einer MongoDB zu gewährleisten.
2. Statusinformationen der Event-Verarbeitung dauerhaft zu speichern und zu aktualisieren.
3. Ergebnisse (Markdown-Dateien, Bilder) über externe URLs zugänglich zu machen.
4. Benutzerbasierte Autorisierung und Zugriffskontrolle zu ermöglichen.
5. Ein zentrales Monitoring und eine REST-API für den Zugriff auf verarbeitete Events bereitzustellen.

## Anforderungen im Detail

### 1. Persistente Speicherung
- Speicherung aller Event-Aufträge in einer MongoDB.
- Sicherstellung, dass bei Server-Neustarts keine Daten verloren gehen.

### 2. Statusverwaltung
- Speicherung und Aktualisierung des Verarbeitungsstatus (pending, processing, completed, failed).
- Speicherung detaillierter Fortschrittsinformationen und Logs.

### 3. Externe Zugänglichkeit
- Bereitstellung der Ergebnisse (Markdown-Dateien, Bilder) über externe URLs.
- Implementierung neuer API-Endpunkte für den Zugriff auf diese Ergebnisse.

### 4. Benutzer-Autorisierung
- Einführung eines `userId` zur Verwaltung von Event-Jobs.
- Implementierung einer Zugriffssteuerung mit Sichtbarkeitsstufen (private, team, public).
- Verwaltung von Lese-, Schreib- und Admin-Zugriffen.

### 5. Monitoring und Dashboard
- Implementierung eines zentralen Monitoring-Dashboards.
- Bereitstellung von Statistiken und Statusinformationen zu Event-Jobs und Batches.

### 6. API-Erweiterungen
- Neue API-Endpunkte für Job- und Batch-Verwaltung.
- Anpassung bestehender API-Endpunkte und Entfernung überflüssiger Endpunkte.

### 7. Konfiguration
- Speicherung der MongoDB- und Worker-Konfiguration in der `config.yaml`.

### 8. Architektur
- Implementierung der MongoDB-Komponente als Core-Komponente.
- Klare Trennung zwischen Core-, Processor- und Utils-Komponenten.

## Umsetzungsplan

### Schritt 1: MongoDB-Integration
- Implementierung der MongoDB-Verbindung und des Repositories.
- Definition des Datenbankschemas und Erstellung notwendiger Indizes.

### Schritt 2: Benutzer-Autorisierung
- Implementierung von `userId` und Zugriffskontrolle.
- Anpassung der API-Endpunkte für benutzerbasierte Zugriffe.

### Schritt 3: Worker-Manager
- Implementierung eines Worker-Managers zur Verwaltung der Job-Verarbeitung.
- Integration der Statusaktualisierung und Fortschrittsverfolgung.

### Schritt 4: API-Erweiterungen
- Erstellung neuer API-Endpunkte für Job- und Batch-Verwaltung.
- Implementierung externer URL-Zugriffe auf Ergebnisse.

### Schritt 5: Monitoring und Dashboard
- Entwicklung eines Monitoring-Dashboards.
- Bereitstellung von Statistiken und Statusinformationen.

### Schritt 6: Deployment und Tests
- Planung des MongoDB-Setups und der Worker-Skalierung.
- Durchführung umfangreicher Tests zur Sicherstellung der Stabilität.

## Fazit

Die Umsetzung dieser Anforderungen gewährleistet eine robuste, skalierbare und transparente Event-Verwaltung mit benutzerbasierter Autorisierung und externem Zugriff auf Ergebnisse. Die schrittweise Implementierung ermöglicht eine reibungslose Integration in die bestehende Infrastruktur. 