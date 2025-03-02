"""
Vereinfachter Worker Manager für Tests.
Vermeidet zirkuläre Importe.
"""

import logging
import threading
import time
import uuid
from typing import Dict, Any, Optional
import traceback
import random
from dataclasses import dataclass, asdict

from test_repository import TestEventJobRepository
from src.core.models.job_models import Job, JobStatus

# Logger initialisieren
logger = logging.getLogger(__name__)

# Angepasste Version der JobProgress-Klasse ohne step-Parameter
@dataclass
class SimpleJobProgress:
    """Vereinfachte Version der JobProgress-Klasse ohne step-Parameter."""
    percent: int = 0
    message: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert den Fortschritt nach der Initialisierung."""
        if self.percent < 0 or self.percent > 100:
            raise ValueError("Prozent muss eine Ganzzahl zwischen 0 und 100 sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Fortschritt in ein Dictionary."""
        return asdict(self)

class TestEventWorkerManager:
    """
    Vereinfachter Worker Manager für die Verarbeitung von Event-Jobs.
    Vermeidet zirkuläre Importe und interagiert direkt mit dem TestEventJobRepository.
    """
    
    def __init__(
        self,
        max_workers: int = 5,
        poll_interval: int = 5,
        job_timeout: int = 300,
        repository: Optional[TestEventJobRepository] = None
    ):
        """
        Initialisiert den Worker Manager.
        
        Args:
            max_workers: Maximale Anzahl gleichzeitiger Worker
            poll_interval: Intervall in Sekunden, in dem nach neuen Jobs gesucht wird
            job_timeout: Timeout in Sekunden für Jobs
            repository: Optional, Repository für die Jobverwaltung
        """
        self.max_workers = max_workers
        self.poll_interval = poll_interval
        self.job_timeout = job_timeout
        
        # Repository initialisieren oder übernehmen
        self.repository = repository or TestEventJobRepository()
        
        # Worker-Verwaltung
        self.active_workers: Dict[str, threading.Thread] = {}
        self.worker_job_ids: Dict[str, str] = {}  # worker_id -> job_id
        self.job_worker_ids: Dict[str, str] = {}  # job_id -> worker_id
        
        # Steuerung
        self.running = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.lock = threading.RLock()
        
        logger.info(f"TestEventWorkerManager initialisiert (max_workers={max_workers}, "
                   f"poll_interval={poll_interval}s, job_timeout={job_timeout}s)")
    
    def start(self) -> None:
        """
        Startet den Worker Manager.
        """
        with self.lock:
            if self.running:
                logger.warning("Worker Manager läuft bereits")
                return
                
            self.running = True
            
            # Monitor-Thread starten
            self.monitor_thread = threading.Thread(
                target=self._monitor_jobs,
                name="WorkerMonitor",
                daemon=True
            )
            self.monitor_thread.start()
            
            logger.info("Worker Manager gestartet")
    
    def stop(self) -> None:
        """
        Stoppt den Worker Manager.
        """
        with self.lock:
            if not self.running:
                logger.warning("Worker Manager läuft nicht")
                return
                
            self.running = False
            
            # Auf Monitor-Thread warten
            if self.monitor_thread:
                self.monitor_thread.join(timeout=10)
                
            # Aktive Worker beenden
            worker_ids = list(self.active_workers.keys())
            for worker_id in worker_ids:
                self._cleanup_worker(worker_id)
                
            logger.info("Worker Manager gestoppt")
    
    def _monitor_jobs(self) -> None:
        """
        Überwacht Jobs und startet Worker für ausstehende Jobs.
        """
        logger.info("Job-Monitor gestartet")
        
        while self.running:
            try:
                # Aktive Worker bereinigen
                self._cleanup_completed_workers()
                
                # Neue Jobs starten, wenn Kapazität vorhanden
                self._start_pending_jobs()
                
                # Auf nächsten Durchlauf warten
                time.sleep(self.poll_interval)
            except Exception as e:
                logger.error(f"Fehler im Job-Monitor: {str(e)}")
                logger.debug(traceback.format_exc())
                
                # Kurze Pause bei Fehlern
                time.sleep(1)
                
        logger.info("Job-Monitor beendet")
    
    def _cleanup_completed_workers(self) -> None:
        """
        Bereinigt abgeschlossene Worker.
        """
        with self.lock:
            # Abgeschlossene Worker identifizieren
            completed_worker_ids = [
                worker_id for worker_id, thread in self.active_workers.items()
                if not thread.is_alive()
            ]
            
            # Abgeschlossene Worker bereinigen
            for worker_id in completed_worker_ids:
                self._cleanup_worker(worker_id)
    
    def _cleanup_worker(self, worker_id: str) -> None:
        """
        Bereinigt einen Worker.
        
        Args:
            worker_id: Worker-ID
        """
        with self.lock:
            # Thread entfernen
            if worker_id in self.active_workers:
                del self.active_workers[worker_id]
                
            # Job-ID abrufen und Zuordnung entfernen
            job_id = self.worker_job_ids.pop(worker_id, None)
            
            if job_id:
                # Worker-Zuordnung entfernen
                self.job_worker_ids.pop(job_id, None)
                
                logger.debug(f"Worker {worker_id} für Job {job_id} bereinigt")
    
    def _start_pending_jobs(self) -> None:
        """
        Startet Worker für ausstehende Jobs.
        """
        with self.lock:
            # Verfügbare Worker-Slots berechnen
            available_slots = self.max_workers - len(self.active_workers)
            
            if available_slots <= 0:
                return
                
            # Ausstehende Jobs abrufen
            pending_jobs = self.repository.get_jobs_by_status(JobStatus.PENDING, limit=available_slots)
            
            if not pending_jobs:
                return
                
            logger.info(f"{len(pending_jobs)} ausstehende Jobs gefunden, starte Worker")
            
            # Worker für jeden ausstehenden Job starten
            for job in pending_jobs:
                self._start_worker_for_job(job)
    
    def _start_worker_for_job(self, job: Job) -> None:
        """
        Startet einen Worker für einen Job.
        
        Args:
            job: Job-Objekt
        """
        with self.lock:
            # Prüfen, ob bereits ein Worker für diesen Job läuft
            if job.job_id in self.job_worker_ids:
                logger.warning(f"Job {job.job_id} wird bereits verarbeitet")
                return
                
            # Worker-ID generieren
            worker_id = str(uuid.uuid4())
            
            # Job als in Bearbeitung markieren
            progress_dict = SimpleJobProgress(
                percent=0,
                message="Job wird gestartet"
            ).to_dict()
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=progress_dict
            )
            
            # Worker-Thread starten
            thread = threading.Thread(
                target=self._process_job,
                args=(worker_id, job),
                name=f"Worker-{worker_id[:8]}",
                daemon=True
            )
            
            # Worker registrieren
            self.active_workers[worker_id] = thread
            self.worker_job_ids[worker_id] = job.job_id
            self.job_worker_ids[job.job_id] = worker_id
            
            # Thread starten
            thread.start()
            
            logger.info(f"Worker {worker_id[:8]} für Job {job.job_id} gestartet")
    
    def _process_job(self, worker_id: str, job: Job) -> None:
        """
        Verarbeitet einen Job.
        
        Args:
            worker_id: Worker-ID
            job: Job-Objekt
        """
        logger.info(f"Verarbeite Job {job.job_id}")
        
        try:
            # Job-Start protokollieren
            self.repository.add_log_entry(
                job_id=job.job_id,
                level="info",
                message=f"Job-Verarbeitung gestartet"
            )
            
            # Fortschritt aktualisieren
            progress_dict = SimpleJobProgress(
                percent=10,
                message="Verarbeitung gestartet"
            ).to_dict()
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=progress_dict
            )
            
            # Event-Daten abrufen
            # Wir verwenden hier ein Dictionary, um die Typprüfung zu umgehen
            job_dict = job.to_dict()
            parameters = job_dict.get("parameters", {})
            input_data = parameters.get("input_data", {})
            event_data = input_data.get("event", {})
            event_id = str(event_data.get("id", "unbekannt"))
            event_title = str(event_data.get("title", "Unbekanntes Event"))
            
            logger.info(f"Verarbeite Event: {event_title} (ID: {event_id})")
            
            # Simuliere Verarbeitung mit zufälliger Dauer
            processing_time = random.randint(2, 10)
            
            # Fortschritt aktualisieren
            progress_dict = SimpleJobProgress(
                percent=30,
                message=f"Event-Daten werden verarbeitet"
            ).to_dict()
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=progress_dict
            )
            
            # Verarbeitung simulieren
            time.sleep(processing_time)
            
            # Fortschritt aktualisieren
            progress_dict = SimpleJobProgress(
                percent=70,
                message="Markdown-Datei wird erstellt"
            ).to_dict()
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=progress_dict
            )
            
            # Dateipfad für Markdown-Datei
            markdown_path = f"output/events/{event_id}.md"
            
            # Fortschritt aktualisieren
            progress_dict = SimpleJobProgress(
                percent=90,
                message="Ergebnisse werden gespeichert"
            ).to_dict()
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=progress_dict
            )
            
            # Ergebnisse erstellen
            results_dict = {
                "markdown_file": markdown_path,
                "markdown_url": f"http://localhost:5001/api/files/{event_id}.md",
                "assets": [
                    f"output/images/{event_id}.png"
                ]
            }
            
            # Job als abgeschlossen markieren
            progress_dict = SimpleJobProgress(
                percent=100,
                message="Verarbeitung abgeschlossen"
            ).to_dict()
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.COMPLETED,
                progress=progress_dict,
                results=results_dict
            )
            
            # Job-Ende protokollieren
            self.repository.add_log_entry(
                job_id=job.job_id,
                level="info",
                message=f"Job erfolgreich abgeschlossen"
            )
            
            # Batch-Fortschritt aktualisieren
            if job.batch_id:
                self.repository.update_batch_progress(job.batch_id)
                
            logger.info(f"Job {job.job_id} erfolgreich abgeschlossen")
            
        except Exception as e:
            # Fehler protokollieren
            error_message = str(e)
            error_traceback = traceback.format_exc()
            
            logger.error(f"Fehler bei der Verarbeitung von Job {job.job_id}: {error_message}")
            logger.debug(error_traceback)
            
            # Fehler im Job protokollieren
            self.repository.add_log_entry(
                job_id=job.job_id,
                level="error",
                message=f"Fehler bei der Verarbeitung: {error_message}"
            )
            
            # Job als fehlgeschlagen markieren
            error_dict = {
                "code": "processing_error",
                "message": error_message,
                "details": {"traceback": error_traceback}
            }
            
            self.repository.update_job_status(
                job_id=job.job_id,
                status=JobStatus.FAILED,
                error=error_dict
            )
            
            # Batch-Fortschritt aktualisieren
            if job.batch_id:
                self.repository.update_batch_progress(job.batch_id)
        
        finally:
            # Worker wird automatisch durch _cleanup_completed_workers bereinigt
            pass 