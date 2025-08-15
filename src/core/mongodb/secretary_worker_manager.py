"""
Secretary Job Worker Manager

Generischer Hintergrund-Worker, der `jobs` pollt und je nach `job_type` über die
Registry Handler ausführt. Parallele Verarbeitung via Threads, Async-Workload in
jeweiligen Handlern.
"""

import asyncio
import logging
import threading
import time
import traceback
from datetime import datetime, UTC
from typing import Dict, Optional

from src.core.models.job_models import Job, JobStatus, JobProgress, JobError
from src.core.resource_tracking import ResourceCalculator
from src.core.processing import registry
from .secretary_repository import SecretaryJobRepository


logger = logging.getLogger(__name__)


class SecretaryWorkerManager:
    def __init__(
        self,
        job_repo: SecretaryJobRepository,
        resource_calculator: ResourceCalculator,
        max_concurrent_workers: int = 3,
        poll_interval_sec: int = 5,
    ) -> None:
        self.job_repo = job_repo
        self.resource_calculator = resource_calculator
        self.max_concurrent_workers = max_concurrent_workers
        self.poll_interval_sec = poll_interval_sec
        self.running_workers: Dict[str, threading.Thread] = {}
        self.stop_flag = False
        self.monitor_thread = threading.Thread(target=self._monitor_jobs, daemon=True)
        logger.info(
            f"SecretaryWorkerManager init (max_workers={max_concurrent_workers}, poll={poll_interval_sec}s)"
        )

    def start(self) -> None:
        logger.info("Starte SecretaryWorkerManager")
        self.stop_flag = False
        self.monitor_thread.start()

    def stop(self) -> None:
        logger.info("Stoppe SecretaryWorkerManager")
        self.stop_flag = True
        self.monitor_thread.join()
        for t in self.running_workers.values():
            t.join()

    def _monitor_jobs(self) -> None:
        logger.info("Secretary-Job-Monitor gestartet")
        while not self.stop_flag:
            try:
                self._cleanup_workers()
                if len(self.running_workers) < self.max_concurrent_workers:
                    pending_jobs = self.job_repo.get_jobs(status=JobStatus.PENDING)
                    for job in pending_jobs:
                        if len(self.running_workers) >= self.max_concurrent_workers:
                            break
                        if job.job_id not in self.running_workers:
                            self._start_worker(job)
            except Exception as e:
                logger.error(f"Fehler im Secretary-Job-Monitor: {e}", exc_info=True)
            for _ in range(self.poll_interval_sec):
                if self.stop_flag:
                    break
                time.sleep(1)
        logger.info("Secretary-Job-Monitor beendet")

    def _cleanup_workers(self) -> None:
        completed = [jid for jid, th in self.running_workers.items() if not th.is_alive()]
        for jid in completed:
            del self.running_workers[jid]

    def _start_worker(self, job: Job) -> None:
        # Set processing status
        self.job_repo.update_job_status(
            job_id=job.job_id,
            status=JobStatus.PROCESSING,
            progress=JobProgress(step="initializing", percent=0, message="Job wird initialisiert"),
        )
        self.job_repo.add_log_entry(job.job_id, "info", "Job-Verarbeitung gestartet")
        th = threading.Thread(target=self._run_worker, args=(job,), daemon=True)
        th.start()
        self.running_workers[job.job_id] = th

    def _run_worker(self, job: Job) -> None:
        try:
            asyncio.run(self._process_job(job))
        except Exception as e:
            logger.error(f"Fehler im Secretary-Worker-Thread: {e}", exc_info=True)

    async def _process_job(self, job: Job) -> None:
        start_time = datetime.now(UTC)
        try:
            handler = registry.get_handler(job.job_type)
            if not handler:
                raise ValueError(f"Unbekannter job_type: {job.job_type}")

            # Fortschritt aktualisieren
            self.job_repo.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=JobProgress(step="processing", percent=10, message="Verarbeitung läuft"),
            )

            await handler(job, self.job_repo, self.resource_calculator)

            self.job_repo.update_job_status(
                job_id=job.job_id,
                status=JobStatus.COMPLETED,
                progress=JobProgress(step="completed", percent=100, message="Verarbeitung abgeschlossen"),
            )
            if job.batch_id:
                self.job_repo.update_batch_progress(job.batch_id)
        except Exception as e:
            error_info = JobError(
                code=type(e).__name__,
                message=str(e),
                details={"traceback": traceback.format_exc(), "duration_ms": int((datetime.now(UTC) - start_time).total_seconds() * 1000)},
            )
            self.job_repo.update_job_status(
                job_id=job.job_id,
                status=JobStatus.FAILED,
                progress=JobProgress(step="error", percent=0, message=str(e)),
                error=error_info,
            )
            if job.batch_id:
                self.job_repo.update_batch_progress(job.batch_id)


_secretary_manager: Optional[SecretaryWorkerManager] = None


def get_secretary_worker_manager() -> Optional[SecretaryWorkerManager]:
    """Singleton-Zugriff, nur wenn `generic_worker.active` True ist."""
    global _secretary_manager
    from src.core.config import Config
    cfg = Config()
    wcfg = cfg.get("generic_worker", {})
    if not wcfg.get("active", False):
        return None
    if _secretary_manager is None:
        # Sanity check Mongo URI existiert implizit in get_mongodb_database
        job_repo = SecretaryJobRepository()
        res_calc = ResourceCalculator()
        _secretary_manager = SecretaryWorkerManager(
            job_repo=job_repo,
            resource_calculator=res_calc,
            max_concurrent_workers=wcfg.get("max_concurrent", 3),
            poll_interval_sec=wcfg.get("poll_interval_sec", 5),
        )
    return _secretary_manager


