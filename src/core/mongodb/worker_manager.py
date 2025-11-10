"""
@fileoverview Session Worker Manager - Background worker for session job processing

@description
Worker manager for asynchronous processing of session jobs. Manages worker threads
for each job and monitors their execution. This manager specifically handles session
processing jobs using the SessionProcessor.

Main functionality:
- Polls MongoDB for pending session jobs
- Creates worker threads for each job
- Manages concurrent job processing
- Tracks job progress and status
- Handles job errors and logging
- Integrates with SessionProcessor for job execution

Features:
- Thread-based parallel processing
- Configurable concurrency limits
- Automatic job status updates
- Progress tracking integration
- Error handling and logging
- Resource tracking support

@module core.mongodb.worker_manager

@exports
- SessionWorkerManager: Class - Worker manager for session jobs

@usedIn
- src.dashboard.app: Starts SessionWorkerManager on app initialization (if enabled)
- src.core.mongodb: Exported via __init__.py

@dependencies
- External: pymongo - MongoDB driver for Python
- Internal: src.processors.session_processor - SessionProcessor for job execution
- Internal: src.core.models.job_models - Job, JobStatus, JobProgress models
- Internal: src.core.mongodb.repository - SessionJobRepository
- Internal: src.core.resource_tracking - ResourceCalculator
"""

import asyncio
import logging
import threading
import time
import traceback
from datetime import datetime, UTC
from typing import Dict, Optional

from src.processors.session_processor import SessionProcessor
from src.core.models.job_models import Job, JobStatus, JobProgress, JobError, JobResults
from src.core.resource_tracking import ResourceCalculator
from .repository import SessionJobRepository

# Logger initialisieren
logger = logging.getLogger(__name__)

class SessionWorkerManager:
    """
    Verwaltet die asynchrone Verarbeitung von Session-Jobs.
    Startet Worker-Threads für jeden Job und überwacht deren Ausführung.
    """
    
    def __init__(
        self,
        job_repo: SessionJobRepository,
        resource_calculator: ResourceCalculator,
        max_concurrent_workers: int = 5,
        poll_interval_sec: int = 5
    ):
        """
        Initialisiert den Worker-Manager.
        
        Args:
            job_repo: Repository für Job-Verwaltung
            resource_calculator: Calculator für Ressourcen-Berechnungen
            max_concurrent_workers: Maximale Anzahl gleichzeitiger Worker
            poll_interval_sec: Intervall für Job-Polling in Sekunden
        """
        self.job_repo = job_repo
        self.resource_calculator = resource_calculator
        self.max_concurrent_workers = max_concurrent_workers
        self.poll_interval_sec = poll_interval_sec
        
        self.running_workers: Dict[str, threading.Thread] = {}
        self.stop_flag = False
        
        # Monitoring-Thread starten
        self.monitor_thread = threading.Thread(target=self._monitor_jobs)
        self.monitor_thread.daemon = True
        
        logger.info(
            f"Worker-Manager initialisiert (max_workers={max_concurrent_workers}, "
            f"poll_interval={poll_interval_sec}s)"
        )
    
    def start(self) -> None:
        """Startet den Worker-Manager."""
        logger.info("Starte Worker-Manager")
        self.stop_flag = False
        self.monitor_thread.start()
    
    def stop(self) -> None:
        """Stoppt den Worker-Manager."""
        logger.info("Stoppe Worker-Manager")
        self.stop_flag = True
        self.monitor_thread.join()
        
        # Warte auf alle laufenden Worker
        for worker in self.running_workers.values():
            worker.join()
    
    def _monitor_jobs(self) -> None:
        """Überwacht Jobs und startet neue Worker bei Bedarf."""
        logger.info("Job-Monitor gestartet")
        
        while not self.stop_flag:
            try:
                # Entferne beendete Worker
                self._cleanup_workers()
                
                # Prüfe, ob neue Worker gestartet werden können
                if len(self.running_workers) < self.max_concurrent_workers:
                    # Hole ausstehende Jobs
                    pending_jobs = self.job_repo.get_jobs(status=JobStatus.PENDING)
                    
                    for job in pending_jobs:
                        if len(self.running_workers) >= self.max_concurrent_workers:
                            break
                            
                        if job.job_id not in self.running_workers:
                            self._start_worker(job)
                            
            except Exception as e:
                logger.error(f"Fehler im Job-Monitor: {str(e)}", exc_info=True)
            
            # Warte vor dem nächsten Durchlauf
            for _ in range(self.poll_interval_sec):
                if self.stop_flag:
                    break
                time.sleep(1)
        
        logger.info("Job-Monitor beendet")
    
    def _cleanup_workers(self) -> None:
        """Entfernt beendete Worker aus der Liste."""
        completed_workers = [job_id for job_id, thread in self.running_workers.items() 
                           if not thread.is_alive()]
        
        for job_id in completed_workers:
            logger.debug(f"Worker für Job {job_id} beendet, entferne aus der Liste")
            del self.running_workers[job_id]
    
    def _start_worker(self, job: Job) -> None:
        """
        Startet einen neuen Worker für einen Job.
        
        Args:
            job: Job-Objekt
        """
        job_id = job.job_id
        
        # Prüfen, ob bereits ein Worker für diesen Job läuft
        if job_id in self.running_workers:
            logger.warning(f"Worker für Job {job_id} läuft bereits")
            return
        
        # Aktualisiere den Job-Status
        self.job_repo.update_job_status(
            job_id=job_id,
            status=JobStatus.PROCESSING,
            progress=JobProgress(
                step="initializing",
                percent=0,
                message="Job wird initialisiert"
            )
        )
        
        # Füge einen Log-Eintrag hinzu
        self.job_repo.add_log_entry(
            job_id=job_id,
            level="info",
            message="Job-Verarbeitung gestartet"
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
        
        logger.info(f"Worker für Job {job_id} gestartet")
    
    async def _process_session(self, job: Job) -> None:
        """
        Verarbeitet eine Session mit dem SessionProcessor.
        
        Args:
            job: Job-Objekt
        """
        job_id = job.job_id
        start_time = datetime.now(UTC)
        
        try:
            # Initialisiere den Session-Processor
            processor = SessionProcessor(
                resource_calculator=self.resource_calculator,
                process_id=job_id
            )
            
            # Aktualisiere den Job-Status mit initialen Performance-Metriken
            self.job_repo.update_job_status(
                job_id=job_id,
                status=JobStatus.PROCESSING,
                progress=JobProgress(
                    step="processing",
                    percent=10,
                    message="Session-Verarbeitung läuft"
                )
            )
            
            # Extrahiere die Parameter aus dem Job
            params = getattr(job, 'parameters', None)
            if not params:
                raise ValueError("Keine Parameter im Job gefunden")
                
            # Parameter sicher extrahieren mit Standardwerten
            event = str(getattr(params, "event", "") or "")
            session = str(getattr(params, "session", "") or "")
            url = str(getattr(params, "url", "") or "")
            filename = str(getattr(params, "filename", "") or "")
            track = str(getattr(params, "track", "") or "")
            day = getattr(params, "day", None)
            starttime = getattr(params, "starttime", None)
            endtime = getattr(params, "endtime", None)
            speakers = list(getattr(params, "speakers", []) or [])
            video_url = str(getattr(params, "video_url", "") or "")
            attachments_url = str(getattr(params, "attachments_url", "") or "")
            source_language = str(getattr(params, "source_language", "en"))
            target_language = str(getattr(params, "target_language", "de"))
            use_cache = bool(getattr(params, "use_cache", True))
            
            # ZIP-Archiv-Parameter extrahieren (Standard: True für Job-Verarbeitung)
            create_archive = bool(getattr(params, "create_archive", True))
            
            # Verarbeite die Session
            result = await processor.process_session(
                event=event,
                session=session,
                url=url,
                filename=filename,
                track=track,
                day=day,
                starttime=starttime,
                endtime=endtime,
                speakers=speakers,
                video_url=video_url,
                attachments_url=attachments_url,
                source_language=source_language,
                target_language=target_language,
                use_cache=use_cache,
                create_archive=create_archive
            )
            
            # Performance-Metriken erfassen
            end_time = datetime.now(UTC)
            
            # Ergebnisse sicher extrahieren
            output = getattr(result, 'data', None)
            if output:
                output = getattr(output, 'output', None)
            
            if not output:
                raise ValueError("Keine Ausgabedaten vom Processor erhalten")
                
            # Sichere Extraktion der Attribute
            markdown_file = getattr(output, 'markdown_file', None)
            markdown_content = getattr(output, 'markdown_content', None)
            assets = getattr(output, 'attachments', []) or []  # Korrigiert: attachments statt assets
            web_text = getattr(output, 'web_text', None)
            video_transcript = getattr(output, 'video_transcript', None)
            attachments_text = getattr(output, 'attachments_text', None)
            attachments_url = getattr(output, 'attachments_url', None)
            # Neue Archive-Felder
            archive_data = getattr(output, 'archive_data', None)
            archive_filename = getattr(output, 'archive_filename', None)
            structured_data = getattr(output, 'structured_data', None)
            target_dir = getattr(output, 'target_dir', None)
            page_texts = getattr(output, 'page_texts', []) or []
            asset_dir = getattr(output, 'asset_dir', None)
            
            # Aktualisiere den Job-Status mit den Ergebnissen
            self.job_repo.update_job_status(
                job_id=job_id,
                status=JobStatus.COMPLETED,
                progress=JobProgress(
                    step="completed",
                    percent=100,
                    message="Verarbeitung abgeschlossen"
                ),
                results=JobResults(
                    markdown_file=markdown_file,
                    markdown_content=markdown_content,
                    assets=assets,
                    web_text=web_text,
                    video_transcript=video_transcript,
                    attachments_text=attachments_text,
                    attachments_url=attachments_url,
                    archive_data=archive_data,
                    archive_filename=archive_filename,
                    structured_data=structured_data,
                    target_dir=target_dir,
                    page_texts=page_texts,
                    asset_dir=asset_dir
                )
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="info",
                message=f"Session-Verarbeitung erfolgreich abgeschlossen (Dauer: {round((end_time - start_time).total_seconds(), 2)}s)"
            )
            
            logger.info(f"Job {job_id} erfolgreich abgeschlossen")
            
        except Exception as e:
            end_time = datetime.now(UTC)
            # Bei Fehler den Job-Status aktualisieren
            error_info = JobError(
                code=type(e).__name__,
                message=str(e),
                details={
                    "traceback": traceback.format_exc(),
                    "duration_ms": int((end_time - start_time).total_seconds() * 1000)
                }
            )
            
            self.job_repo.update_job_status(
                job_id=job_id,
                status=JobStatus.FAILED,
                progress=JobProgress(
                    step="error",
                    percent=0,
                    message=str(e)
                ),
                error=error_info
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="error",
                message=f"Fehler bei der Verarbeitung: {str(e)}"
            )
            
            # Batch aktualisieren
            if job.batch_id:
                self.job_repo.update_batch_progress(job.batch_id)
            
            logger.error(f"Fehler bei der Verarbeitung von Job {job_id}: {str(e)}")
            logger.debug(traceback.format_exc())
            
    def _run_worker_process(self, job: Job) -> None:
        """
        Führt den Worker-Prozess aus.
        
        Args:
            job: Job-Objekt
        """
        try:
            # Führe die Session-Verarbeitung in einer asyncio Event-Loop aus
            asyncio.run(self._process_session(job))
            
            # Aktualisiere den Batch-Status, falls vorhanden
            if job.batch_id:
                self.job_repo.update_batch_progress(job.batch_id)
                
        except Exception as e:
            logger.error(f"Fehler im Worker-Prozess: {str(e)}", exc_info=True)

# Singleton-Instanz des Worker-Managers
_worker_manager = None

def get_worker_manager() -> Optional[SessionWorkerManager]:
    """
    Gibt eine Singleton-Instanz des SessionWorkerManager zurück, wenn in der
    Konfiguration session_worker.active=True gesetzt ist. Ansonsten None.
    
    Returns:
        Optional[SessionWorkerManager]: Worker-Manager-Instanz oder None
    """
    global _worker_manager
    
    # Konfiguration laden
    from src.core.config import Config
    config = Config()
    worker_config = config.get('session_worker', {})
    
    # Prüfen, ob der Worker aktiv sein soll
    is_active = worker_config.get('active', False)
    
    if not is_active:
        logger.info("SessionWorkerManager ist deaktiviert (session_worker.active=False in config.yaml)")
        return None
    
    # Worker-Manager nur initialisieren, wenn er aktiv sein soll
    if _worker_manager is None and is_active:
        try:
            # Prüfe MongoDB-Konfiguration vor der Initialisierung
            mongodb_config = config.get('mongodb', {})
            mongodb_uri = mongodb_config.get('uri', '')
            
            if not mongodb_uri or mongodb_uri == '${MONGODB_URI}':
                logger.error("MONGODB_URI Umgebungsvariable ist nicht gesetzt oder leer")
                logger.error("Bitte setze die MONGODB_URI Umgebungsvariable in deiner .env Datei oder Umgebung")
                return None
            
            logger.info(f"MongoDB URI gefunden: {mongodb_uri[:20]}...")
            
            max_concurrent = worker_config.get('max_concurrent', 5)
            poll_interval_sec = worker_config.get('poll_interval_sec', 5)
            
            # Repository und ResourceCalculator initialisieren
            from src.core.mongodb import get_job_repository
            from src.core.resource_tracking import ResourceCalculator
            
            job_repo = get_job_repository()
            resource_calculator = ResourceCalculator()
            
            _worker_manager = SessionWorkerManager(
                job_repo=job_repo,
                resource_calculator=resource_calculator,
                max_concurrent_workers=max_concurrent,
                poll_interval_sec=poll_interval_sec
            )
            logger.info(f"SessionWorkerManager wurde initialisiert (active=True, max_workers={max_concurrent})")
            
        except Exception as e:
            logger.error(f"Fehler bei der Initialisierung des SessionWorkerManager: {str(e)}")
            logger.error("Worker-Manager wird nicht gestartet")
            return None
    
    return _worker_manager 