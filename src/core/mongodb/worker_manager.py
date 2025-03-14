"""
Worker-Manager für Session-Jobs.
Verwaltet die Verarbeitung von Session-Jobs aus der MongoDB.
"""

import time
import threading
import asyncio
import traceback
from typing import Dict, Optional, List
import logging
from pathlib import Path

from src.core.models.session import SessionResponse
from src.core.models.job_models import Job, JobStatus, JobProgress, JobError, JobResults
# Entferne den zirkulären Import
# from src.core.mongodb import get_job_repository
from src.processors.session_processor import SessionProcessor
from src.core.resource_tracking import ResourceCalculator

# Logger initialisieren
logger: logging.Logger = logging.getLogger(__name__)

# Verzögerter Import innerhalb der Funktionen
def _get_job_repository():
    """Verzögerter Import des JobRepository, um zirkuläre Importe zu vermeiden."""
    from src.core.mongodb import get_job_repository
    return get_job_repository()

class SessionWorkerManager:
    """
    Manager für die Verarbeitung von Session-Jobs aus der MongoDB.
    Überwacht die Job-Queue und startet Worker-Threads für ausstehende Jobs.
    """
    
    def __init__(self, max_concurrent_workers: int = 5, poll_interval_sec: int = 5):
        """
        Initialisiert den Worker-Manager.
        
        Args:
            max_concurrent_workers: Maximale Anzahl gleichzeitiger Worker
            poll_interval_sec: Intervall in Sekunden, in dem die Job-Queue abgefragt wird
        """
        self.max_concurrent_workers = max_concurrent_workers
        self.poll_interval_sec = poll_interval_sec
        self.running_workers: Dict[str, threading.Thread] = {}
        self.stop_flag = False
        self.monitor_thread: Optional[threading.Thread] = None
        self.job_repo = _get_job_repository()
        self.resource_calculator = ResourceCalculator()
        
        # Einstellungen für die Erkennung hängengebliebener Jobs
        self.stalled_job_check_interval = 60  # Sekunden zwischen Prüfungen
        self.max_processing_time_minutes = 10  # Jobs gelten nach 10 Minuten als hängengeblieben
        self.last_stalled_job_check = 0  # Timestamp der letzten Prüfung
        
        logger.info(f"SessionWorkerManager initialisiert (max_workers={max_concurrent_workers}, poll_interval={poll_interval_sec}s)")
    
    def start(self) -> None:
        """
        Startet den Worker-Manager.
        """
        if self.monitor_thread and self.monitor_thread.is_alive():
            logger.warning("Worker-Manager läuft bereits")
            return
        
        self.stop_flag = False
        
        # Beim Start hängengebliebene Jobs bereinigen
        self._cleanup_stalled_jobs()
        
        self.monitor_thread = threading.Thread(target=self._monitor_jobs)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info("Worker-Manager gestartet")
    
    def stop(self) -> None:
        """
        Stoppt den Worker-Manager.
        """
        if not self.monitor_thread or not self.monitor_thread.is_alive():
            logger.warning("Worker-Manager läuft nicht")
            return
        
        logger.info("Worker-Manager wird gestoppt...")
        self.stop_flag = True
        
        # Warte auf das Ende des Monitor-Threads
        if self.monitor_thread:
            self.monitor_thread.join(timeout=10.0)
            if self.monitor_thread.is_alive():
                logger.warning("Monitor-Thread konnte nicht beendet werden")
            else:
                logger.info("Monitor-Thread beendet")
        
        # Warte auf das Ende aller Worker-Threads
        if self.running_workers:
            logger.info(f"Warte auf das Ende von {len(self.running_workers)} Worker-Threads...")
            for job_id, thread in list(self.running_workers.items()):
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.warning(f"Worker-Thread für Job {job_id} konnte nicht beendet werden")
                else:
                    logger.debug(f"Worker-Thread für Job {job_id} beendet")
        
        logger.info("Worker-Manager gestoppt")
    
    def _monitor_jobs(self) -> None:
        """
        Überwachungsschleife für Jobs.
        Prüft regelmäßig, ob neue Jobs vorhanden sind und startet Worker für sie.
        """
        self.last_stalled_job_check = time.time()
        
        while not self.stop_flag:
            try:
                current_time = time.time()
                
                # Prüfe auf hängengebliebene Jobs
                if current_time - self.last_stalled_job_check > self.stalled_job_check_interval:
                    self._cleanup_stalled_jobs()
                    self.last_stalled_job_check = current_time
                
                # Bereinige beendete Worker
                self._cleanup_workers()
                
                # Wenn noch Kapazität vorhanden ist, suche nach neuen Jobs
                available_slots = self.max_concurrent_workers - len(self.running_workers)
                if available_slots > 0:
                    # Hole ausstehende Jobs
                    pending_jobs = self.job_repo.get_jobs(
                        status=JobStatus.PENDING,
                        limit=available_slots
                    )
                    
                    if pending_jobs:
                        logger.info(f"{len(pending_jobs)} ausstehende Jobs gefunden")
                        
                        # Starte Worker für jeden Job
                        for job in pending_jobs:
                            self._start_worker(job)
                    else:
                        logger.debug("Keine ausstehenden Jobs gefunden")
                else:
                    logger.debug(f"Keine freien Worker-Slots verfügbar ({len(self.running_workers)}/{self.max_concurrent_workers} belegt)")
            
            except Exception as e:
                logger.error(f"Fehler im Job-Monitor: {str(e)}")
                logger.debug(traceback.format_exc())
            
            # Warte vor dem nächsten Durchlauf
            for _ in range(self.poll_interval_sec):
                if self.stop_flag:
                    break
                time.sleep(1)
        
        logger.info("Job-Monitor beendet")
    
    def _cleanup_workers(self) -> None:
        """
        Entfernt beendete Worker aus der Liste.
        """
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
    
    def _run_worker_process(self, job: Job) -> None:
        """
        Führt den eigentlichen Worker-Prozess aus.
        
        Args:
            job: Job-Objekt
        """
        job_id = job.job_id
        batch_id = job.batch_id
        
        try:
            # Führe den Session-Processor aus
            asyncio.run(self._process_session(job))
            
            # Aktualisiere den Batch-Status, falls vorhanden
            if batch_id:
                self.job_repo.update_batch_progress(batch_id)
                
        except Exception as e:
            # Bei Fehler den Job-Status aktualisieren
            error_info = JobError(
                code=type(e).__name__,
                message=str(e),
                details={"traceback": traceback.format_exc()}
            )
            
            self.job_repo.update_job_status(
                job_id=job_id,
                status=JobStatus.FAILED,
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
            
            logger.error(f"Fehler bei der Verarbeitung von Job {job_id}: {str(e)}")
            logger.debug(traceback.format_exc())
    
    async def _process_session(self, job: Job) -> None:
        """
        Verarbeitet eine Session mit dem SessionProcessor.
        
        Args:
            job: Job-Objekt
        """
        job_id = job.job_id
        params = job.parameters
        
        # Initialisiere den Session-Processor
        processor = SessionProcessor(
            resource_calculator=self.resource_calculator,
            process_id=job_id
        )
        
        # Aktualisiere den Job-Status
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
        event = params.event or ""
        session = params.session or ""
        url = params.url or ""
        filename = params.filename or ""
        track = params.track or ""
        day = getattr(params, "day", None)
        starttime = getattr(params, "starttime", None)
        endtime = getattr(params, "endtime", None)
        speakers = getattr(params, "speakers", [])
        video_url = getattr(params, "video_url", None)
        attachments_url = getattr(params, "attachments_url", None)
        source_language = getattr(params, "source_language", "en")
        target_language = getattr(params, "target_language", "de")
        use_cache = getattr(params, "use_cache", True)
        
        # Verarbeite die Session
        result: SessionResponse = await processor.process_session(
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
            use_cache=use_cache
        )
        
        # Verarbeite das Ergebnis
        if result.status == "success" and result.data:
            # Erstelle URLs für die Ergebnisse
            markdown_file = result.data.output.markdown_file
            
            # Sammle Asset-URLs
            assets: List[str] = []
            if hasattr(result.data.output, "attachments") and result.data.output.attachments:
                # Statt die Asset-URLs aus den Parametern zu generieren,
                # extrahieren wir sie direkt aus dem tatsächlichen Dateipfad 
                # der Markdown-Datei, der bereits existiert
                
                # Konvertiere Markdown-Dateipfad zum API-Pfad
                # Beispiel: "sessions/FOSDEM 2025/Open-Research-22/Beyond-.../Beyond-...md" 
                # wird zu "/api/session-job/files/FOSDEM 2025/Open-Research-22/Beyond-..."
                
                # 1. Entferne das 'sessions/' Präfix und den Dateinamen am Ende
                markdown_path = Path(markdown_file)
                relative_dir = str(markdown_path.parent).replace('sessions/', '', 1)
                
                # 2. Ersetze Backslashes durch Forward Slashes für Web-URLs
                relative_dir = relative_dir.replace('\\', '/')
                
                # WICHTIG: Wir dürfen kein "sessions/" in der URL haben, da die API dies bereits hinzufügt
                # Stelle sicher, dass kein "sessions/" am Anfang des Pfads steht
                if relative_dir.startswith("sessions/"):
                    relative_dir = relative_dir[9:]  # Entferne "sessions/"
                
                # Prüfe, ob das Verzeichnis existiert
                file_system_dir = markdown_path.parent
                logger.info(f"Prüfe Verzeichnis: {file_system_dir}")
                
                # Prüfe, ob das Assets-Verzeichnis existiert
                assets_dir = file_system_dir / "assets"
                if not assets_dir.exists():
                    logger.warning(f"Assets-Verzeichnis existiert nicht: {assets_dir}")
                else:
                    logger.info(f"Assets-Verzeichnis gefunden: {assets_dir}")
                    # Liste Dateien im Verzeichnis auf (für Debug-Zwecke)
                    logger.info(f"Assets im Verzeichnis: {list(assets_dir.glob('*'))}")
                
                # 3. Erstelle Asset-URLs
                for asset_path in result.data.output.attachments:
                    # Verwende den relativen Pfad direkt, wie er vom PDF Processor geliefert wird
                    # Der PDF Processor liefert bereits Pfade im Format "assets/preview_001.png"
                    assets.append(f"{relative_dir}/{asset_path}")
                    
                # Protokolliere die generierten Asset-URLs
                logger.info(f"Generierte Asset-URLs für Job {job_id}: {assets}")
            
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
                    markdown_content=result.data.output.markdown_content,
                    assets=assets,
                    web_text=result.data.output.web_text if hasattr(result.data.output, "web_text") else None,
                    video_transcript=result.data.output.video_transcript if hasattr(result.data.output, "video_transcript") else None,
                    attachments_text=result.data.output.attachments_text if hasattr(result.data.output, "attachments_text") else None,
                    context=result.data.output.context if hasattr(result.data.output, "context") else None,
                    attachments_url=result.data.output.attachments_url if hasattr(result.data.output, "attachments_url") else None
                )
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="info",
                message="Session-Verarbeitung erfolgreich abgeschlossen"
            )
            
            logger.info(f"Job {job_id} erfolgreich abgeschlossen")
            
            # Webhook-Callback senden, falls konfiguriert
            # TODO: Webhook-Callback implementieren
        else:
            # Fehlerfall
            error_info = JobError(
                code=result.error.code if hasattr(result, "error") and result.error else "PROCESSING_ERROR",
                message=result.error.message if hasattr(result, "error") and result.error else "Unbekannter Fehler",
                details=result.error.details if hasattr(result, "error") and result.error and hasattr(result.error, "details") else {}
            )
            
            self.job_repo.update_job_status(
                job_id=job_id,
                status=JobStatus.FAILED,
                error=error_info
            )
            
            # Log-Eintrag hinzufügen
            self.job_repo.add_log_entry(
                job_id=job_id,
                level="error",
                message=f"Fehler bei der Verarbeitung: {error_info.message}"
            )
            
            logger.error(f"Job {job_id} fehlgeschlagen: {error_info.message}")
    
    def _cleanup_stalled_jobs(self) -> None:
        """
        Bereinigt Jobs, die im processing-Status hängengeblieben sind.
        """
        try:
            reset_count = self.job_repo.reset_stalled_jobs(self.max_processing_time_minutes)
            if reset_count > 0:
                logger.info(f"{reset_count} hängengebliebene Jobs zurückgesetzt (älter als {self.max_processing_time_minutes} min)")
        except Exception as e:
            logger.error(f"Fehler beim Bereinigen hängengebliebener Jobs: {str(e)}", exc_info=True)

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
        max_concurrent = worker_config.get('max_concurrent', 5)
        poll_interval_sec = worker_config.get('poll_interval_sec', 5)
        
        _worker_manager = SessionWorkerManager(
            max_concurrent_workers=max_concurrent,
            poll_interval_sec=poll_interval_sec
        )
        logger.info(f"SessionWorkerManager wurde initialisiert (active=True, max_workers={max_concurrent})")
    
    return _worker_manager 