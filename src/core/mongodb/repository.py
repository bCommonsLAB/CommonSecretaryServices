"""
MongoDB-Repository für Event-Jobs.
Verwaltet die Speicherung und Abfrage von Event-Jobs in der MongoDB.
"""

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.results import UpdateResult, DeleteResult
from typing import Dict, Any, List, Optional, Union
import datetime
import logging
import json

from src.core.models.job_models import Job, Batch, JobStatus, LogEntry, JobProgress, JobError, JobResults
from .connection import get_mongodb_database

# Logger initialisieren
logger = logging.getLogger(__name__)

class EventJobRepository:
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
        self.db: Database[Any] = get_mongodb_database(db_name)
        self.jobs: Collection[Any] = self.db.event_jobs
        self.batches: Collection[Any] = self.db.event_batches
        
        # Indizes erstellen
        self._create_indexes()
        
        logger.info("EventJobRepository initialisiert")
    
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
    
    def update_job_status(
        self, 
        job_id: str, 
        status: Union[str, JobStatus], 
        progress: Optional[Union[Dict[str, Any], JobProgress]] = None, 
        results: Optional[Union[Dict[str, Any], JobResults]] = None, 
        error: Optional[Union[Dict[str, Any], JobError]] = None
    ) -> bool:
        """
        Aktualisiert den Status eines Jobs.
        
        Args:
            job_id: Job-ID
            status: Neuer Status (pending, processing, completed, failed)
            progress: Optional, Fortschrittsinformationen
            results: Optional, Ergebnisse
            error: Optional, Fehlerinformationen
            
        Returns:
            bool: True, wenn der Job aktualisiert wurde, sonst False
        """
        # Status zu Enum konvertieren, falls es ein String ist
        if type(status) is not JobStatus:
            status = JobStatus(status)
        
        # Aktuelle Zeit für die Aktualisierung
        now = datetime.datetime.now(datetime.UTC)
        
        # Aktualisierungsdaten vorbereiten
        update_data: Dict[str, Any] = {
            "status": status.value,
            "updated_at": now
        }
        
        # Startzeit setzen, wenn der Job gestartet wird
        job = self.get_job(job_id)
        if job and status == JobStatus.PROCESSING and not job.started_at:
            update_data["started_at"] = now
        
        # Endzeit setzen, wenn der Job abgeschlossen oder fehlgeschlagen ist
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            update_data["completed_at"] = now
        
        # Optionale Daten hinzufügen
        if progress:
            if isinstance(progress, dict):
                progress = JobProgress.from_dict(progress)
            update_data["progress"] = progress.to_dict()
            
        if results:
            if isinstance(results, dict):
                results = JobResults.from_dict(results)
            update_data["results"] = results.to_dict()
            
        if error:
            if isinstance(error, dict):
                error = JobError.from_dict(error)
            update_data["error"] = error.to_dict()
        
        # Job aktualisieren
        result: UpdateResult = self.jobs.update_one(
            {"job_id": job_id},
            {"$set": update_data}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Job-Status aktualisiert: {job_id} -> {status.value}")
            logger.debug(f"Update-Daten: {json.dumps(update_data, default=str)}")
        else:
            logger.warning(f"Job-Status konnte nicht aktualisiert werden: {job_id}")
        
        return success
    
    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        """
        Fügt einen Log-Eintrag zu einem Job hinzu.
        
        Args:
            job_id: Job-ID
            level: Log-Level (debug, info, warning, error, critical)
            message: Log-Nachricht
            
        Returns:
            bool: True, wenn der Log-Eintrag hinzugefügt wurde, sonst False
        """
        # Sicherstellen, dass Level ein gültiger Wert ist
        valid_level = level
        if level not in ("debug", "info", "warning", "error", "critical"):
            valid_level = "info"
            logger.warning(f"Ungültiges Log-Level '{level}' auf 'info' gesetzt")
        
        log_entry = LogEntry(
            timestamp=datetime.datetime.now(datetime.UTC),
            level=valid_level,  # type: ignore
            message=message
        )
        
        # Log-Eintrag zum Job hinzufügen
        result: UpdateResult = self.jobs.update_one(
            {"job_id": job_id},
            {
                "$push": {"logs": log_entry.to_dict()},
                "$set": {"updated_at": log_entry.timestamp}
            }
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.debug(f"Log-Eintrag hinzugefügt zu Job {job_id}: [{level}] {message}")
        else:
            logger.warning(f"Log-Eintrag konnte nicht zu Job {job_id} hinzugefügt werden")
        
        return success
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """
        Gibt einen Job anhand seiner ID zurück.
        
        Args:
            job_id: Job-ID
            
        Returns:
            Optional[Job]: Job-Objekt oder None, wenn nicht gefunden
        """
        job_data = self.jobs.find_one({"job_id": job_id})
        
        if job_data:
            return Job.from_dict(job_data)
        
        logger.warning(f"Job nicht gefunden: {job_id}")
        return None
    
    def get_jobs_for_user(
        self, 
        user_id: str, 
        status: Optional[Union[str, JobStatus]] = None, 
        limit: int = 100, 
        skip: int = 0
    ) -> List[Job]:
        """
        Gibt eine Liste von Jobs zurück, auf die der Benutzer Zugriff hat.
        
        Args:
            user_id: Benutzer-ID
            status: Optional, Status-Filter
            limit: Maximale Anzahl der zurückzugebenden Jobs
            skip: Anzahl der zu überspringenden Jobs (für Paginierung)
            
        Returns:
            List[Job]: Liste der Jobs
        """
        # Basisabfrage: Jobs, auf die der Benutzer Zugriff hat
        query: Dict[str, Any] = {
            "$or": [
                {"user_id": user_id},  # Eigene Jobs
                {"access_control.read_access": user_id},  # Expliziter Lesezugriff
                {"access_control.visibility": "public"}  # Öffentliche Jobs
            ]
        }
        
        # Status-Filter hinzufügen, falls angegeben
        if status:
            status_value = status.value if isinstance(status, JobStatus) else status
            query["status"] = status_value
        
        # Jobs abfragen
        job_data = list(
            self.jobs.find(query)
            .sort("created_at", DESCENDING)
            .skip(skip)
            .limit(limit)
        )
        
        jobs = [Job.from_dict(data) for data in job_data]
        
        logger.debug(f"{len(jobs)} Jobs für Benutzer {user_id} gefunden")
        
        return jobs
    
    def delete_job(self, job_id: str) -> bool:
        """
        Löscht einen Job und gibt zurück, ob der Job gelöscht wurde.
        
        Args:
            job_id: Job-ID
            
        Returns:
            bool: True, wenn der Job gelöscht wurde, sonst False
        """
        result: DeleteResult = self.jobs.delete_one({"job_id": job_id})
        
        success = result.deleted_count > 0
        
        if success:
            logger.info(f"Job gelöscht: {job_id}")
        else:
            logger.warning(f"Job konnte nicht gelöscht werden: {job_id}")
        
        return success
    
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
    
    def get_batch(self, batch_id: str) -> Optional[Batch]:
        """
        Gibt einen Batch anhand seiner ID zurück.
        
        Args:
            batch_id: Batch-ID
            
        Returns:
            Optional[Batch]: Batch-Objekt oder None, wenn nicht gefunden
        """
        batch_data = self.batches.find_one({"batch_id": batch_id})
        
        if batch_data:
            return Batch.from_dict(batch_data)
        
        logger.warning(f"Batch nicht gefunden: {batch_id}")
        return None
    
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
            logger.warning(f"Batch für Fortschrittsaktualisierung nicht gefunden: {batch_id}")
            return False
        
        # Jobs zählen
        jobs_completed = self.jobs.count_documents({
            "batch_id": batch_id,
            "status": JobStatus.COMPLETED.value
        })
        
        jobs_failed = self.jobs.count_documents({
            "batch_id": batch_id,
            "status": JobStatus.FAILED.value
        })
        
        # Status bestimmen
        status = JobStatus.PROCESSING
        now = datetime.datetime.now(datetime.UTC)
        update_data: Dict[str, Any] = {
            "completed_jobs": jobs_completed,
            "failed_jobs": jobs_failed,
            "updated_at": now
        }
        
        # Wenn alle Jobs abgeschlossen oder fehlgeschlagen sind, ist der Batch abgeschlossen
        if jobs_completed + jobs_failed >= batch.total_jobs:
            status = JobStatus.COMPLETED
            update_data["status"] = status.value
            update_data["completed_at"] = now
        
        # Batch aktualisieren
        result: UpdateResult = self.batches.update_one(
            {"batch_id": batch_id},
            {"$set": update_data}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Batch-Fortschritt aktualisiert: {batch_id} -> {status.value} ({jobs_completed}/{batch.total_jobs} abgeschlossen, {jobs_failed}/{batch.total_jobs} fehlgeschlagen)")
        else:
            logger.warning(f"Batch-Fortschritt konnte nicht aktualisiert werden: {batch_id}")
        
        return success
    
    def delete_batch(self, batch_id: str) -> bool:
        """
        Löscht einen Batch und alle zugehörigen Jobs.
        
        Args:
            batch_id: Die ID des zu löschenden Batches
            
        Returns:
            bool: True, wenn der Batch und alle zugehörigen Jobs erfolgreich gelöscht wurden, sonst False
        """
        try:
            # Zuerst alle Jobs des Batches finden und löschen
            job_ids = [
                job.get("_id") for job in self.jobs.find({"batch_id": batch_id}, {"_id": 1})
            ]
            
            if job_ids:
                # Alle Jobs löschen
                job_delete_result = self.jobs.delete_many({"batch_id": batch_id})
                logger.info(f"Gelöschte Jobs für Batch {batch_id}: {job_delete_result.deleted_count} von {len(job_ids)}")
            
            # Dann den Batch selbst löschen
            batch_delete_result = self.batches.delete_one({"batch_id": batch_id})
            
            # Wenn der Batch nicht existierte, aber trotzdem True zurückgeben, damit die Anfrage erfolgreich ist
            # (idempotentes Verhalten)
            if batch_delete_result.deleted_count == 0:
                logger.warning(f"Batch {batch_id} existierte nicht oder wurde bereits gelöscht")
            else:
                logger.info(f"Batch {batch_id} erfolgreich gelöscht")
            
            return True
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Batches {batch_id}: {str(e)}", exc_info=True)
            return False
    
    def get_jobs(
        self, 
        status: Optional[Union[str, JobStatus]] = None, 
        batch_id: Optional[str] = None,
        archived: Optional[bool] = None,
        limit: int = 100, 
        skip: int = 0, 
        sort_by: str = "created_at", 
        sort_order: int = DESCENDING
    ) -> List[Job]:
        """
        Gibt eine Liste von Jobs zurück, gefiltert nach den angegebenen Kriterien.
        
        Args:
            status: Optional, filtere nach Status
            batch_id: Optional, filtere nach Batch-ID
            archived: Optional, filtere nach dem archived-Flag
            limit: Maximale Anzahl von Jobs
            skip: Anzahl der zu überspringenden Jobs
            sort_by: Feld, nach dem sortiert werden soll
            sort_order: Sortierreihenfolge (pymongo.ASCENDING oder pymongo.DESCENDING)
            
        Returns:
            List[Job]: Liste von Job-Objekten
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {}
        
        if status is not None:
            # Status in String umwandeln, falls es ein Enum ist
            if isinstance(status, JobStatus):
                status = status.value
            filter_dict["status"] = status
        
        if batch_id is not None:
            filter_dict["batch_id"] = batch_id
        
        if archived is not None:
            filter_dict["archived"] = archived
        
        # Jobs aus der Datenbank abrufen
        jobs_cursor = self.jobs.find(
            filter_dict
        ).sort(sort_by, sort_order).skip(skip).limit(limit)
        
        # Jobs in Job-Objekte umwandeln
        jobs: List[Job] = []
        for job_dict in jobs_cursor:
            jobs.append(Job.from_dict(job_dict))
        
        return jobs
    
    def count_jobs(
        self, 
        status: Optional[Union[str, JobStatus]] = None, 
        batch_id: Optional[str] = None,
        archived: Optional[bool] = None
    ) -> int:
        """
        Zählt die Anzahl der Jobs, gefiltert nach den angegebenen Kriterien.
        
        Args:
            status: Optional, filtere nach Status
            batch_id: Optional, filtere nach Batch-ID
            archived: Optional, filtere nach dem archived-Flag
            
        Returns:
            int: Anzahl der Jobs
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {}
        
        if status is not None:
            # Status in String umwandeln, falls es ein Enum ist
            if isinstance(status, JobStatus):
                status = status.value
            filter_dict["status"] = status
            
        if batch_id is not None:
            filter_dict["batch_id"] = batch_id
            
        if archived is not None:
            filter_dict["archived"] = archived
        
        # Jobs zählen
        return self.jobs.count_documents(filter_dict)
    
    def get_jobs_for_batch(
        self, 
        batch_id: str, 
        limit: int = 100, 
        skip: int = 0
    ) -> List[Job]:
        """
        Gibt eine Liste von Jobs für einen Batch zurück.
        
        Args:
            batch_id: Batch-ID
            limit: Maximale Anzahl der zurückzugebenden Jobs
            skip: Anzahl der zu überspringenden Jobs (für Paginierung)
            
        Returns:
            List[Job]: Liste der Jobs
        """
        # Jobs abfragen
        job_data = self.jobs.find({"batch_id": batch_id}).sort("created_at", DESCENDING).skip(skip).limit(limit)
        
        # Jobs in Objekte umwandeln
        jobs = [Job.from_dict(job) for job in job_data]
        
        logger.debug(f"{len(jobs)} Jobs für Batch {batch_id} abgefragt")
        
        return jobs
    
    def count_jobs_for_batch(self, batch_id: str) -> int:
        """
        Zählt die Anzahl der Jobs für einen Batch.
        
        Args:
            batch_id: Batch-ID
            
        Returns:
            int: Anzahl der Jobs
        """
        # Jobs zählen
        count = self.jobs.count_documents({"batch_id": batch_id})
        
        logger.debug(f"{count} Jobs für Batch {batch_id} gezählt")
        
        return count
    
    def count_jobs_for_user(self, user_id: str, status: Optional[Union[str, JobStatus]] = None) -> int:
        """
        Zählt die Anzahl der Jobs für einen Benutzer.
        
        Args:
            user_id: Benutzer-ID
            status: Optional, Status-Filter
            
        Returns:
            int: Anzahl der Jobs
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {
            "$or": [
                {"user_id": user_id},
                {"access_control.read_access": user_id}
            ]
        }
        
        # Status-Filter hinzufügen, falls vorhanden
        if status:
            # Status zu Enum konvertieren, falls es ein String ist
            if type(status) is not JobStatus:
                status = JobStatus(status)
            filter_dict["status"] = status.value
        
        # Jobs zählen
        count = self.jobs.count_documents(filter_dict)
        
        logger.debug(f"{count} Jobs für Benutzer {user_id} gezählt")
        
        return count
    
    def get_batches(
        self, 
        status: Optional[Union[str, JobStatus]] = None, 
        archived: Optional[bool] = None,
        limit: int = 100, 
        skip: int = 0
    ) -> List[Batch]:
        """
        Gibt eine Liste von Batches zurück.
        
        Args:
            status: Optional, Status-Filter
            archived: Optional, Filtere nach dem archived-Flag
            limit: Maximale Anzahl der zurückzugebenden Batches
            skip: Anzahl der zu überspringenden Batches (für Paginierung)
            
        Returns:
            List[Batch]: Liste der Batches
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {}
        
        # Status-Filter hinzufügen, falls vorhanden
        if status:
            # Status zu Enum konvertieren, falls es ein String ist
            if type(status) is not JobStatus:
                status = JobStatus(status)
            filter_dict["status"] = status.value
        
        # Archived-Filter hinzufügen, falls vorhanden
        if archived is not None:
            filter_dict["archived"] = archived
        
        # Batches abfragen
        batch_data = self.batches.find(filter_dict).sort("created_at", DESCENDING).skip(skip).limit(limit)
        
        # Batches in Objekte umwandeln
        batches = [Batch.from_dict(batch) for batch in batch_data]
        
        logger.debug(f"{len(batches)} Batches abgefragt")
        
        return batches
    
    def count_batches(self, status: Optional[Union[str, JobStatus]] = None, archived: Optional[bool] = None) -> int:
        """
        Zählt die Anzahl der Batches.
        
        Args:
            status: Optional, Status-Filter
            archived: Optional, Filtere nach dem archived-Flag
            
        Returns:
            int: Anzahl der Batches
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {}
        
        # Status-Filter hinzufügen, falls vorhanden
        if status:
            # Status zu Enum konvertieren, falls es ein String ist
            if type(status) is not JobStatus:
                status = JobStatus(status)
            filter_dict["status"] = status.value
        
        # Archived-Filter hinzufügen, falls vorhanden
        if archived is not None:
            filter_dict["archived"] = archived
        
        # Batches zählen
        count = self.batches.count_documents(filter_dict)
        
        logger.debug(f"{count} Batches gezählt")
        
        return count
    
    def get_batches_for_user(
        self, 
        user_id: str, 
        status: Optional[Union[str, JobStatus]] = None, 
        limit: int = 100, 
        skip: int = 0
    ) -> List[Batch]:
        """
        Gibt eine Liste von Batches zurück, auf die der Benutzer Zugriff hat.
        
        Args:
            user_id: Benutzer-ID
            status: Optional, Status-Filter
            limit: Maximale Anzahl der zurückzugebenden Batches
            skip: Anzahl der zu überspringenden Batches (für Paginierung)
            
        Returns:
            List[Batch]: Liste der Batches
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {
            "$or": [
                {"user_id": user_id},
                {"access_control.read_access": user_id}
            ]
        }
        
        # Status-Filter hinzufügen, falls vorhanden
        if status:
            # Status zu Enum konvertieren, falls es ein String ist
            if type(status) is not JobStatus:
                status = JobStatus(status)
            filter_dict["status"] = status.value
        
        # Batches abfragen
        batch_data = self.batches.find(filter_dict).sort("created_at", DESCENDING).skip(skip).limit(limit)
        
        # Batches in Objekte umwandeln
        batches = [Batch.from_dict(batch) for batch in batch_data]
        
        logger.debug(f"{len(batches)} Batches für Benutzer {user_id} abgefragt")
        
        return batches
    
    def count_batches_for_user(self, user_id: str, status: Optional[Union[str, JobStatus]] = None) -> int:
        """
        Zählt die Anzahl der Batches für einen Benutzer.
        
        Args:
            user_id: Benutzer-ID
            status: Optional, Status-Filter
            
        Returns:
            int: Anzahl der Batches
        """
        # Filter erstellen
        filter_dict: Dict[str, Any] = {
            "$or": [
                {"user_id": user_id},
                {"access_control.read_access": user_id}
            ]
        }
        
        # Status-Filter hinzufügen, falls vorhanden
        if status:
            # Status zu Enum konvertieren, falls es ein String ist
            if type(status) is not JobStatus:
                status = JobStatus(status)
            filter_dict["status"] = status.value
        
        # Batches zählen
        count = self.batches.count_documents(filter_dict)
        
        logger.debug(f"{count} Batches für Benutzer {user_id} gezählt")
        
        return count
    
    def archive_batch(self, batch_id: str) -> bool:
        """
        Archiviert einen Batch durch Setzen des archived-Flags.
        
        Args:
            batch_id: Die ID des Batches, der archiviert werden soll.
            
        Returns:
            bool: True, wenn der Batch erfolgreich archiviert wurde, sonst False.
        """
        now = datetime.datetime.now(datetime.UTC)
        
        result = self.batches.update_one(
            {"batch_id": batch_id},
            {
                "$set": {
                    "archived": True,
                    "updated_at": now
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Batch archiviert: {batch_id}")
            return True
        else:
            logger.warning(f"Batch konnte nicht archiviert werden: {batch_id}")
            return False
    
    def delete_jobs_by_batch(self, batch_id: str) -> int:
        """
        Löscht alle Jobs eines bestimmten Batches in einem Schritt.
        
        Args:
            batch_id: Die ID des Batches, dessen Jobs gelöscht werden sollen
            
        Returns:
            int: Die Anzahl der gelöschten Jobs
        """
        try:
            # Alle Jobs des Batches mit einem einzigen Aufruf löschen
            result = self.jobs.delete_many({"batch_id": batch_id})
            
            deleted_count = result.deleted_count
            logger.info(f"Gelöschte Jobs für Batch {batch_id}: {deleted_count}")
            
            return deleted_count
        except Exception as e:
            logger.error(f"Fehler beim Löschen der Jobs für Batch {batch_id}: {str(e)}", exc_info=True)
            raise 