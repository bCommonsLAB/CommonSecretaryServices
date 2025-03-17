"""
MongoDB-Repository für Session-Jobs.
Verwaltet die Speicherung und Abfrage von Session-Jobs in der MongoDB.
"""

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.results import UpdateResult, DeleteResult
from typing import Dict, Any, List, Optional, Union
import datetime
import logging
import json
import time

from src.core.models.job_models import Job, Batch, JobStatus, LogEntry, JobProgress, JobError, JobResults
from .connection import get_mongodb_database

# Logger initialisieren
logger = logging.getLogger(__name__)

class SessionJobRepository:
    """
    Repository für die Verwaltung von Session-Jobs in MongoDB.
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
        
        logger.info("SessionJobRepository initialisiert")
    
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
            job_id: Die ID des Jobs
            status: Der neue Status
            progress: Optional, Fortschrittsinformationen
            results: Optional, Ergebnisse
            error: Optional, Fehlerinformationen
        
        Returns:
            bool: True bei Erfolg, False bei Fehler
        """
        # Status in String-Form für MongoDB umwandeln
        status_value = status.value if isinstance(status, JobStatus) else JobStatus(status).value
        
        # Aktualisierungs-Dictionary erstellen
        now = datetime.datetime.now(datetime.UTC)
        update_dict: Dict[str, Any] = {
            "status": status_value,
            "updated_at": now
        }
        
        # Wenn Status auf "processing" gesetzt wird, setze processing_started_at
        if status == JobStatus.PROCESSING:
            update_dict["processing_started_at"] = now
        
        # Wenn Status auf "completed" oder "failed" gesetzt wird, setze completed_at
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            update_dict["completed_at"] = now
        
        # Progress hinzufügen, falls vorhanden
        if progress:
            if isinstance(progress, dict):
                update_dict["progress"] = progress
            else:
                update_dict["progress"] = progress.to_dict()
                
        # Results hinzufügen, falls vorhanden
        if results:
            if isinstance(results, dict):
                update_dict["results"] = results
            else:
                update_dict["results"] = results.to_dict()
                
        # Error hinzufügen, falls vorhanden
        if error:
            if isinstance(error, dict):
                update_dict["error"] = error
            else:
                update_dict["error"] = error.to_dict()
        
        # Job in der Datenbank aktualisieren
        result = self.jobs.update_one(
            {"job_id": job_id},
            {"$set": update_dict}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Job-Status aktualisiert: {job_id} -> {status_value}")
            
            # Wenn der Job Teil eines Batches ist, aktualisiere auch den Batch-Fortschritt
            job_data = self.get_job(job_id)
            if job_data and job_data.batch_id:
                self.update_batch_progress(job_data.batch_id)
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
        # Start der Zeitmessung
        start_time = time.time()
        
        # Jobs abfragen
        start_find = time.time()
        
        # Projektion verwenden, um nur die benötigten Felder zu laden
        # Dies reduziert die Datenmenge, die übertragen werden muss
        projection = {
            "job_id": 1,
            "status": 1,
            "job_name": 1,
            "created_at": 1,
            "updated_at": 1,
            "completed_at": 1,
            "processing_started_at": 1,
            "progress": 1,
            "error": 1,
            "batch_id": 1,
            "user_id": 1,
            "_id": 0  # _id nicht benötigt
        }
        
        job_data = self.jobs.find(
            {"batch_id": batch_id},
            projection=projection
        ).sort("created_at", DESCENDING).skip(skip).limit(limit)
        
        find_time = time.time() - start_find
        
        # Start der Konvertierung
        start_convert = time.time()
        
        # Jobs in Objekte umwandeln
        jobs = [Job.from_dict(job) for job in job_data]
        
        # Ende der Konvertierung
        convert_time = time.time() - start_convert
        
        # Ende der Zeitmessung
        total_time = time.time() - start_time
        
        # Performance-Logging
        logger.warning(
            f"DB_PERF: get_jobs_for_batch | batch_id={batch_id} | jobs={len(jobs)} | "
            f"find_time={round(find_time * 1000, 2)}ms | "
            f"convert_time={round(convert_time * 1000, 2)}ms | "
            f"total_time={round(total_time * 1000, 2)}ms"
        )
        
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
        
        result: UpdateResult = self.batches.update_one(
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
            result: DeleteResult = self.jobs.delete_many({"batch_id": batch_id})
            
            deleted_count = result.deleted_count
            logger.info(f"Gelöschte Jobs für Batch {batch_id}: {deleted_count}")
            
            return deleted_count
        except Exception as e:
            logger.error(f"Fehler beim Löschen der Jobs für Batch {batch_id}: {str(e)}", exc_info=True)
            raise
    
    def get_batch_with_current_stats(self, batch_id: str) -> Optional[Batch]:
        """
        Gibt einen Batch anhand seiner ID zurück und füllt die aktuellen Statistiken aus.
        Zählt die Jobs in verschiedenen Status (pending, processing, completed, failed).
        
        Args:
            batch_id: Batch-ID
            
        Returns:
            Optional[Batch]: Batch-Objekt mit aktuellen Statistiken oder None, wenn nicht gefunden
        """
        batch = self.get_batch(batch_id)
        
        if not batch:
            logger.warning(f"Batch nicht gefunden: {batch_id}")
            return None
        
        # Zähle Jobs nach Status
        completed_jobs = self.jobs.count_documents({
            "batch_id": batch_id,
            "status": JobStatus.COMPLETED.value
        })
        
        failed_jobs = self.jobs.count_documents({
            "batch_id": batch_id,
            "status": JobStatus.FAILED.value
        })
        
        pending_jobs = self.jobs.count_documents({
            "batch_id": batch_id,
            "status": JobStatus.PENDING.value
        })
        
        processing_jobs = self.jobs.count_documents({
            "batch_id": batch_id,
            "status": JobStatus.PROCESSING.value
        })
        
        # Batch-Objekt aktualisieren (ohne in der DB zu speichern)
        batch.completed_jobs = completed_jobs
        batch.failed_jobs = failed_jobs
        batch.pending_jobs = pending_jobs
        batch.processing_jobs = processing_jobs
        
        # Berechne auch den Gesamtfortschritt neu
        total_jobs = completed_jobs + failed_jobs + pending_jobs + processing_jobs
        if total_jobs > 0:
            batch.total_jobs = total_jobs
        
        return batch
    
    def reset_stalled_jobs(self, max_processing_time_minutes: int = 10) -> int:
        """
        Setzt "hängengebliebene" Jobs zurück, die sich länger als die angegebene Zeit im Status PROCESSING befinden.
        
        Args:
            max_processing_time_minutes: Maximale Zeit in Minuten, die ein Job im Status PROCESSING sein darf
            
        Returns:
            int: Anzahl der zurückgesetzten Jobs
        """
        now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
        
        # Berechne den Zeitpunkt, ab dem Jobs als "hängengeblieben" gelten
        cutoff_time = now - datetime.timedelta(minutes=max_processing_time_minutes)
        
        # Suche Jobs, die sich im Status PROCESSING befinden und seit längerem keine Aktualisierung hatten
        query = {
            "status": JobStatus.PROCESSING.value,
            "processing_started_at": {"$lt": cutoff_time}
        }
        
        # Aktualisierung, um den Status auf FAILED zu setzen und eine Fehlermeldung hinzuzufügen
        update = {
            "$set": {
                "status": JobStatus.FAILED.value,
                "updated_at": now,
                "completed_at": now,
                "error": {
                    "code": "PROCESSING_TIMEOUT",
                    "message": f"Der Job wurde automatisch beendet, da er länger als {max_processing_time_minutes} Minuten im processing-Status war.",
                    "details": {
                        "timeout_minutes": max_processing_time_minutes,
                        "processing_started_at": {"$toString": "$processing_started_at"}
                    }
                }
            }
        }
        
        try:
            # Führe die Aktualisierung durch
            result: UpdateResult = self.jobs.update_many(query, update)
            reset_count = result.modified_count
            
            if reset_count > 0:
                logger.info(f"{reset_count} hängengebliebene Jobs zurückgesetzt (Timeout: {max_processing_time_minutes} min)")
                
                # Aktualisiere die Batch-Fortschritte für betroffene Batches
                affected_batches: set[str] = set()
                stalled_jobs = self.jobs.find({"status": JobStatus.FAILED.value, "error.code": "PROCESSING_TIMEOUT"})
                
                for job in stalled_jobs:
                    if "batch_id" in job and job["batch_id"]:
                        affected_batches.add(job["batch_id"])
                
                for batch_id in affected_batches:
                    self.update_batch_progress(batch_id)
            
            return reset_count
            
        except Exception as e:
            logger.error(f"Fehler beim Zurücksetzen hängengebliebener Jobs: {str(e)}", exc_info=True)
            return 0
    
    def update_batch_status(self, batch_id: str, status: Union[str, JobStatus]) -> bool:
        """
        Aktualisiert den Status eines Batches.
        
        Args:
            batch_id: Die ID des Batches
            status: Der neue Status
            
        Returns:
            bool: True bei Erfolg, False bei Fehler
        """
        # Status in String-Form für MongoDB umwandeln
        status_value = status.value if isinstance(status, JobStatus) else JobStatus(status).value
        
        # Aktualisierungs-Dictionary erstellen
        now = datetime.datetime.now(datetime.UTC)
        update_dict: Dict[str, Any] = {
            "status": status_value,
            "updated_at": now
        }
        
        # Wenn Status auf "completed" oder "failed" gesetzt wird, setze completed_at
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            update_dict["completed_at"] = now
        
        # Batch in der Datenbank aktualisieren
        result = self.batches.update_one(
            {"batch_id": batch_id},
            {"$set": update_dict}
        )
        
        success = result.modified_count > 0
        
        if success:
            logger.info(f"Batch-Status aktualisiert: {batch_id} -> {status_value}")
        else:
            logger.warning(f"Batch-Status konnte nicht aktualisiert werden: {batch_id}")
            
        return success
    
    def update_jobs_status_by_batch(self, batch_id: str, status: Union[str, JobStatus]) -> int:
        """
        Aktualisiert den Status aller Jobs eines Batches.
        
        Args:
            batch_id: Die ID des Batches
            status: Der neue Status
            
        Returns:
            int: Anzahl der aktualisierten Jobs
        """
        # Status in String-Form für MongoDB umwandeln
        status_value = status.value if isinstance(status, JobStatus) else JobStatus(status).value
        
        # Aktualisierungs-Dictionary erstellen
        now = datetime.datetime.now(datetime.UTC)
        update_dict: Dict[str, Any] = {
            "status": status_value,
            "updated_at": now
        }
        
        # Wenn Status auf "completed" oder "failed" gesetzt wird, setze completed_at
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            update_dict["completed_at"] = now
        
        # Alle Jobs des Batches aktualisieren
        result = self.jobs.update_many(
            {"batch_id": batch_id},
            {"$set": update_dict}
        )
        
        modified_count = result.modified_count
        
        if modified_count > 0:
            logger.info(f"{modified_count} Jobs für Batch {batch_id} auf Status {status_value} gesetzt")
        else:
            logger.warning(f"Keine Jobs für Batch {batch_id} gefunden oder aktualisiert")
            
        return modified_count 