"""
MongoDB-Repository für generische Secretary-Jobs.
Eigene Collections: `jobs`, `batches`.
API analog zu SessionJobRepository, um Migration zu vereinfachen.
"""

from typing import Any, Dict, List, Optional, Union
import datetime
import logging

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.results import UpdateResult

from src.core.models.job_models import Job, Batch, JobStatus, LogEntry, JobProgress, JobError, JobResults
from .connection import get_mongodb_database


logger = logging.getLogger(__name__)


class SecretaryJobRepository:
    """Repository für generische Secretary-Jobs."""

    def __init__(self) -> None:
        # Option A: DB-Name ausschließlich aus der URI
        self.db: Database[Any] = get_mongodb_database()
        self.jobs: Collection[Any] = self.db.jobs
        self.batches: Collection[Any] = self.db.batches
        self._create_indexes()
        logger.info("SecretaryJobRepository initialisiert")

    def _create_indexes(self) -> None:
        self.jobs.create_index([("job_id", ASCENDING)], unique=True)
        self.jobs.create_index([("status", ASCENDING)])
        self.jobs.create_index([("batch_id", ASCENDING)])
        self.jobs.create_index([("created_at", DESCENDING)])
        self.batches.create_index([("batch_id", ASCENDING)], unique=True)
        self.batches.create_index([("status", ASCENDING)])
        self.batches.create_index([("created_at", DESCENDING)])

    # CRUD / Listing (API analog SessionJobRepository)
    def create_job(self, job_data: Union[Dict[str, Any], Job], user_id: Optional[str] = None) -> str:
        if isinstance(job_data, dict):
            if user_id and "user_id" not in job_data:
                job_data["user_id"] = user_id
            job = Job.from_dict(job_data)
        else:
            job = job_data
            if user_id and not job.user_id:
                job.user_id = user_id
        self.jobs.insert_one(job.to_dict())
        logger.info(f"Job erstellt: {job.job_id}")
        return job.job_id

    def update_job_status(
        self,
        job_id: str,
        status: Union[str, JobStatus],
        progress: Optional[Union[Dict[str, Any], JobProgress]] = None,
        results: Optional[Union[Dict[str, Any], JobResults]] = None,
        error: Optional[Union[Dict[str, Any], JobError]] = None,
    ) -> bool:
        status_value = status.value if isinstance(status, JobStatus) else JobStatus(status).value
        now = datetime.datetime.now(datetime.UTC)
        update_dict: Dict[str, Any] = {"status": status_value, "updated_at": now}
        if status == JobStatus.PROCESSING:
            update_dict["processing_started_at"] = now
        if status in [JobStatus.COMPLETED, JobStatus.FAILED]:
            update_dict["completed_at"] = now
        if progress:
            update_dict["progress"] = progress if isinstance(progress, dict) else progress.to_dict()
        if results:
            update_dict["results"] = results if isinstance(results, dict) else results.to_dict()
        if error:
            update_dict["error"] = error if isinstance(error, dict) else error.to_dict()
        result = self.jobs.update_one({"job_id": job_id}, {"$set": update_dict})
        ok = result.modified_count > 0
        if ok:
            job = self.get_job(job_id)
            if job and job.batch_id:
                self.update_batch_progress(job.batch_id)
        return ok

    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        # Level auf gültige Literale mappen
        valid = {"debug", "info", "warning", "error", "critical"}
        lvl = level if level in valid else "info"
        # Typ narrowing für Literal: casten über Literal-Typ
        from typing import cast, Literal
        literal_level = cast(Literal["debug", "info", "warning", "error", "critical"], lvl)
        entry = LogEntry(timestamp=datetime.datetime.now(datetime.UTC), level=literal_level, message=message)
        result: UpdateResult = self.jobs.update_one(
            {"job_id": job_id}, {"$push": {"logs": entry.to_dict()}, "$set": {"updated_at": entry.timestamp}}
        )
        return result.modified_count > 0

    def get_job(self, job_id: str) -> Optional[Job]:
        doc = self.jobs.find_one({"job_id": job_id})
        return Job.from_dict(doc) if doc else None

    def get_jobs(
        self,
        status: Optional[Union[str, JobStatus]] = None,
        batch_id: Optional[str] = None,
        limit: int = 100,
        skip: int = 0,
        sort_by: str = "created_at",
        sort_order: int = DESCENDING,
    ) -> List[Job]:
        q: Dict[str, Any] = {}
        if status is not None:
            q["status"] = status.value if isinstance(status, JobStatus) else status
        if batch_id is not None:
            q["batch_id"] = batch_id
        cur = self.jobs.find(q).sort(sort_by, sort_order).skip(skip).limit(limit)
        return [Job.from_dict(d) for d in cur]

    def create_batch(self, batch_data: Union[Dict[str, Any], Batch], user_id: Optional[str] = None) -> str:
        if isinstance(batch_data, dict):
            if user_id and "user_id" not in batch_data:
                batch_data["user_id"] = user_id
            batch = Batch.from_dict(batch_data)
        else:
            batch = batch_data
            if user_id and not batch.user_id:
                batch.user_id = user_id
        self.batches.insert_one(batch.to_dict())
        return batch.batch_id

    def get_batch(self, batch_id: str) -> Optional[Batch]:
        doc = self.batches.find_one({"batch_id": batch_id})
        return Batch.from_dict(doc) if doc else None

    def update_batch_progress(self, batch_id: str) -> bool:
        batch = self.get_batch(batch_id)
        if not batch:
            return False
        jobs_completed = self.jobs.count_documents({"batch_id": batch_id, "status": JobStatus.COMPLETED.value})
        jobs_failed = self.jobs.count_documents({"batch_id": batch_id, "status": JobStatus.FAILED.value})
        status = JobStatus.PROCESSING
        now = datetime.datetime.now(datetime.UTC)
        update_data: Dict[str, Any] = {
            "completed_jobs": jobs_completed,
            "failed_jobs": jobs_failed,
            "updated_at": now,
        }
        if jobs_completed + jobs_failed >= batch.total_jobs:
            status = JobStatus.COMPLETED
            update_data["status"] = status.value
            update_data["completed_at"] = now
        result: UpdateResult = self.batches.update_one({"batch_id": batch_id}, {"$set": update_data})
        return result.modified_count > 0


