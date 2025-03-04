"""
Kopie der Repository-Klasse für Tests.
Vermeidet zirkuläre Importe.
"""

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from typing import Dict, Any, List, Optional, Union, Literal
import logging
import json
import os
from datetime import datetime

from src.core.models.job_models import Job, Batch, JobStatus, JobProgress, JobError, JobResults, LogEntry

# Logger initialisieren
logger = logging.getLogger(__name__)

# Definiere LogLevel-Typ
LogLevel = Literal['debug', 'info', 'warning', 'error', 'critical']

class TestEventJobRepository:
    """
    Repository für die Verwaltung von Event-Jobs in MongoDB.
    Verwendet typisierte Dataclasses für die Datenmodellierung.
    """
    
    def __init__(self, db_name: Optional[str] = None):
        """
        Initialisiert das Repository.
        
        Args:
            db_name: Optional, Name der Datenbank. Wenn nicht angegeben, wird der Name aus der Konfiguration verwendet.
        """
        # MongoDB-Verbindung direkt herstellen
        mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        db_name = db_name or os.environ.get("MONGODB_DB", "event_processor")
        
        self.client: MongoClient[Dict[str, Any]] = MongoClient(mongo_uri)
        self.db: Database[Dict[str, Any]] = self.client[db_name]
        self.jobs: Collection[Dict[str, Any]] = self.db.event_jobs
        self.batches: Collection[Dict[str, Any]] = self.db.event_batches
        
        # Indizes erstellen
        self._create_indexes()
        
        logger.info("TestEventJobRepository initialisiert")
    
    def _create_indexes(self) -> None:
        """
        Erstellt die notwendigen Indizes für die Collections.
        """
        # Indizes für Jobs
        self.jobs.create_index([("job_id", ASCENDING)], unique=True)
        self.jobs.create_index([("status", ASCENDING)])
        self.jobs.create_index([("batch_id", ASCENDING)])
        self.jobs.create_index([("created_at", ASCENDING)])
        self.jobs.create_index([("user_id", ASCENDING)])
        
        # Indizes für Batches
        self.batches.create_index([("batch_id", ASCENDING)], unique=True)
        self.batches.create_index([("status", ASCENDING)])
        self.batches.create_index([("created_at", ASCENDING)])
        self.batches.create_index([("user_id", ASCENDING)])
        
        logger.debug("MongoDB-Indizes erstellt")
    
    def create_job(self, job_data: Union[Dict[str, Any], Job], user_id: Optional[str] = None) -> str:
        """
        Erstellt einen neuen Job und gibt die Job-ID zurück.
        
        Args:
            job_data: Job-Daten als Dictionary oder Job-Objekt
            user_id: Optional, ID des Benutzers, der den Job erstellt
            
        Returns:
            str: Job-ID
        """
        # Job-Objekt erstellen, falls ein Dictionary übergeben wurde
        if isinstance(job_data, dict):
            # Benutzer-ID aus dem Argument übernehmen, falls vorhanden
            if user_id and "user_id" not in job_data:
                job_data["user_id"] = user_id
            
            job = Job.from_dict(job_data)
        else:
            job = job_data
            
            # Benutzer-ID aus dem Argument übernehmen, falls nicht im Job gesetzt
            if user_id and not job.user_id:
                job.user_id = user_id
        
        # Job in die Datenbank einfügen
        job_dict = job.to_dict()
        self.jobs.insert_one(job_dict)
        
        logger.info(f"Job erstellt: {job.job_id}")
        logger.debug(f"Job-Daten: {json.dumps(job_dict, default=str)}")
        
        return job.job_id
    
    def create_batch(self, batch_data: Union[Dict[str, Any], Batch], user_id: Optional[str] = None) -> str:
        """
        Erstellt einen neuen Batch und gibt die Batch-ID zurück.
        
        Args:
            batch_data: Batch-Daten als Dictionary oder Batch-Objekt
            user_id: Optional, ID des Benutzers, der den Batch erstellt
            
        Returns:
            str: Batch-ID
        """
        # Batch-Objekt erstellen, falls ein Dictionary übergeben wurde
        if isinstance(batch_data, dict):
            # Benutzer-ID aus dem Argument übernehmen, falls vorhanden
            if user_id and "user_id" not in batch_data:
                batch_data["user_id"] = user_id
            
            batch = Batch.from_dict(batch_data)
        else:
            batch = batch_data
            
            # Benutzer-ID aus dem Argument übernehmen, falls nicht im Batch gesetzt
            if user_id and not batch.user_id:
                batch.user_id = user_id
        
        # Batch in die Datenbank einfügen
        batch_dict = batch.to_dict()
        self.batches.insert_one(batch_dict)
        
        logger.info(f"Batch erstellt: {batch.batch_id}")
        logger.debug(f"Batch-Daten: {json.dumps(batch_dict, default=str)}")
        
        return batch.batch_id
    
    def update_batch_job_ids(self, batch_id: str, job_ids: List[str]) -> bool:
        """
        Aktualisiert die Job-IDs eines Batches.
        
        Args:
            batch_id: Batch-ID
            job_ids: Liste von Job-IDs
            
        Returns:
            bool: True, wenn der Batch aktualisiert wurde, sonst False
        """
        result = self.batches.update_one(
            {"batch_id": batch_id},
            {"$set": {"job_ids": job_ids}}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Job-IDs für Batch {batch_id} aktualisiert: {len(job_ids)} Jobs")
        else:
            logger.warning(f"Batch {batch_id} nicht gefunden oder Job-IDs nicht aktualisiert")
        
        return success
        
    def get_jobs_by_status(self, status: Union[str, JobStatus], batch_id: Optional[str] = None, limit: int = 100) -> List[Job]:
        """
        Gibt Jobs mit einem bestimmten Status zurück.
        
        Args:
            status: Status der Jobs
            batch_id: Optional, Batch-ID für die Filterung
            limit: Maximale Anzahl der zurückzugebenden Jobs
            
        Returns:
            Liste von Job-Objekten
        """
        # Status in String umwandeln, falls es ein Enum ist
        if isinstance(status, JobStatus):
            status = status.value
            
        # Filter erstellen
        filter_dict = {"status": status}
        if batch_id:
            filter_dict["batch_id"] = batch_id
            
        # Jobs abfragen
        job_docs = self.jobs.find(filter_dict).limit(limit)
        
        # Job-Objekte erstellen
        jobs = [Job.from_dict(job_doc) for job_doc in job_docs]
        
        logger.info(f"{len(jobs)} Jobs mit Status '{status}' gefunden" + 
                   (f" für Batch {batch_id}" if batch_id else ""))
        
        return jobs
        
    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Gibt einen Job anhand seiner ID zurück.
        
        Args:
            job_id: Job-ID
            
        Returns:
            Job-Objekt oder None, wenn der Job nicht gefunden wurde
        """
        job_doc = self.jobs.find_one({"job_id": job_id})
        
        if job_doc:
            return Job.from_dict(job_doc)
        else:
            logger.warning(f"Job {job_id} nicht gefunden")
            return None
            
    def get_batch(self, batch_id: str) -> Optional[Batch]:
        """
        Gibt einen Batch anhand seiner ID zurück.
        
        Args:
            batch_id: Batch-ID
            
        Returns:
            Batch-Objekt oder None, wenn der Batch nicht gefunden wurde
        """
        batch_doc = self.batches.find_one({"batch_id": batch_id})
        
        if batch_doc:
            return Batch.from_dict(batch_doc)
        else:
            logger.warning(f"Batch {batch_id} nicht gefunden")
            return None
            
    def update_job_status(
        self, 
        job_id: str, 
        status: Union[str, JobStatus], 
        progress: Optional[Union[Dict[str, Any], JobProgress]] = None, 
        error: Optional[Union[Dict[str, Any], JobError]] = None,
        results: Optional[Union[Dict[str, Any], JobResults]] = None
    ) -> bool:
        """
        Aktualisiert den Status eines Jobs.
        
        Args:
            job_id: Job-ID
            status: Neuer Status
            progress: Optional, Fortschrittsinformationen
            error: Optional, Fehlerinformationen
            results: Optional, Ergebnisse
            
        Returns:
            bool: True, wenn der Job aktualisiert wurde, sonst False
        """
        # Status in String umwandeln, falls es ein Enum ist
        if isinstance(status, JobStatus):
            status = status.value
            
        # Update-Dictionary erstellen
        update_dict: Dict[str, Any] = {"status": status}
        
        # Fortschrittsinformationen hinzufügen, falls vorhanden
        if progress:
            if isinstance(progress, JobProgress):
                update_dict["progress"] = progress.to_dict()
            else:
                update_dict["progress"] = progress
                
        # Fehlerinformationen hinzufügen, falls vorhanden
        if error:
            if isinstance(error, JobError):
                update_dict["error"] = error.to_dict()
            else:
                update_dict["error"] = error
                
        # Ergebnisse hinzufügen, falls vorhanden
        if results:
            if isinstance(results, JobResults):
                update_dict["results"] = results.to_dict()
            else:
                update_dict["results"] = results
                
        # Job aktualisieren
        result = self.jobs.update_one(
            {"job_id": job_id},
            {"$set": update_dict}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Status von Job {job_id} aktualisiert: {status}")
        else:
            logger.warning(f"Job {job_id} nicht gefunden oder Status nicht aktualisiert")
            
        return success
        
    def add_log_entry(self, job_id: str, level: LogLevel, message: str) -> bool:
        """
        Fügt einen Log-Eintrag zu einem Job hinzu.
        
        Args:
            job_id: Job-ID
            level: Log-Level (debug, info, warning, error, critical)
            message: Log-Nachricht
            
        Returns:
            bool: True, wenn der Log-Eintrag hinzugefügt wurde, sonst False
        """
        # Log-Eintrag erstellen
        log_entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            message=message
        )
        
        # Log-Eintrag zum Job hinzufügen
        result = self.jobs.update_one(
            {"job_id": job_id},
            {"$push": {"log_entries": log_entry.to_dict()}}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.debug(f"Log-Eintrag zu Job {job_id} hinzugefügt: [{level}] {message}")
        else:
            logger.warning(f"Job {job_id} nicht gefunden oder Log-Eintrag nicht hinzugefügt")
            
        return success
        
    def update_batch_progress(self, batch_id: str) -> bool:
        """
        Aktualisiert den Fortschritt eines Batches basierend auf den zugehörigen Jobs.
        
        Args:
            batch_id: Batch-ID
            
        Returns:
            bool: True, wenn der Batch aktualisiert wurde, sonst False
        """
        # Batch abrufen
        batch = self.get_batch(batch_id)
        if not batch:
            logger.warning(f"Batch {batch_id} nicht gefunden")
            return False
            
        # Jobs abrufen
        jobs: List[Job] = []
        for job_id in batch.job_ids:
            job = self.get_job(job_id)
            if job:
                jobs.append(job)
                
        if not jobs:
            logger.warning(f"Keine Jobs für Batch {batch_id} gefunden")
            return False
            
        # Zähle Jobs nach Status
        completed_count = sum(1 for job in jobs if job.status == JobStatus.COMPLETED)
        failed_count = sum(1 for job in jobs if job.status == JobStatus.FAILED)
        total_count = len(jobs)
        
        # Bestimme den Batch-Status
        if completed_count + failed_count == total_count:
            if failed_count == 0:
                batch_status = JobStatus.COMPLETED
            elif completed_count == 0:
                batch_status = JobStatus.FAILED
            else:
                batch_status = JobStatus.COMPLETED  # Teilweise erfolgreich, aber als abgeschlossen markieren
        else:
            batch_status = JobStatus.PROCESSING
            
        # Aktualisiere den Batch
        update_data: Dict[str, Any] = {
            "status": batch_status.value,
            "completed_jobs": completed_count,
            "failed_jobs": failed_count
        }
        
        result = self.batches.update_one(
            {"batch_id": batch_id},
            {"$set": update_data}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Fortschritt von Batch {batch_id} aktualisiert: "
                       f"{completed_count}/{total_count} abgeschlossen, {failed_count}/{total_count} fehlgeschlagen")
        else:
            logger.warning(f"Batch {batch_id} nicht gefunden oder Fortschritt nicht aktualisiert")
            
        return success 