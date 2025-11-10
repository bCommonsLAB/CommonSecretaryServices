"""
@fileoverview Secretary Worker Manager - Generic background worker for secretary job processing

@description
Secretary Job Worker Manager. Generic background worker that polls `jobs` collection
and executes handlers via registry based on `job_type`. Parallel processing via threads,
async workload in respective handlers.

Main functionality:
- Polls MongoDB for pending jobs
- Routes jobs to appropriate handlers via processor registry
- Manages concurrent job processing with thread pool
- Tracks job progress and status
- Handles job errors and logging
- Supports webhook notifications

Features:
- Generic job type support (not limited to specific processors)
- Thread-based parallel processing
- Configurable concurrency limits
- Automatic retry logic
- Progress tracking integration
- Webhook support for job completion notifications

@module core.mongodb.secretary_worker_manager

@exports
- SecretaryWorkerManager: Class - Generic worker manager for secretary jobs

@usedIn
- src.dashboard.app: Starts SecretaryWorkerManager on app initialization
- src.core.mongodb: Exported via __init__.py

@dependencies
- External: pymongo - MongoDB driver for Python
- Internal: src.core.models.job_models - Job, JobStatus, JobProgress models
- Internal: src.core.processing.registry - Processor registry for job routing
- Internal: src.core.mongodb.secretary_repository - SecretaryJobRepository
- Internal: src.core.resource_tracking - ResourceCalculator
- Internal: src.utils.logger - Logging system
"""

import asyncio
import logging
import threading
import time
import traceback
from datetime import datetime, UTC
from typing import Dict, Optional, Any, cast, Callable
import requests  # type: ignore
import json
try:
    from bson import BSON  # type: ignore
except Exception:  # pragma: no cover
    BSON = None  # type: ignore

from src.core.models.job_models import Job, JobStatus, JobProgress, JobError
from src.core.resource_tracking import ResourceCalculator
from src.core.processing import registry
from .secretary_repository import SecretaryJobRepository
from src.utils.logger import register_log_observer, unregister_log_observer


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
        print("[SECRETARY-WORKER] Manager start")
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
                            logger.info(f"Starte Worker-Thread für Job {job.job_id} (type={job.job_type})")
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
            logger.info(f"Starte Job {job.job_id} (type={job.job_type})")
            handler = registry.get_handler(job.job_type)
            if not handler:
                raise ValueError(f"Unbekannter job_type: {job.job_type}")

            # Fortschritt aktualisieren
            self.job_repo.update_job_status(
                job_id=job.job_id,
                status=JobStatus.PROCESSING,
                progress=JobProgress(step="processing", percent=10, message="Verarbeitung läuft"),
            )
            logger.info(f"Dispatch an Handler für Job {job.job_id}")

            # Callback-Infos (falls vorhanden) lesen
            callback_url: Optional[str] = None
            callback_token: Optional[str] = None
            client_job_id: Optional[str] = None
            webhook_cfg_any: Any = getattr(job.parameters, "webhook", None)
            if isinstance(webhook_cfg_any, dict):
                webhook_cfg_dict: Dict[str, Any] = cast(Dict[str, Any], webhook_cfg_any)
                url_val = webhook_cfg_dict.get("url")
                token_val = webhook_cfg_dict.get("token")
                jobid_val = webhook_cfg_dict.get("jobId")
                callback_url = url_val if isinstance(url_val, str) else None
                callback_token = token_val if isinstance(token_val, str) else None
                client_job_id = jobid_val if isinstance(jobid_val, str) else None

            # Ziel-URL gemäß neuer Spezifikation: jobId im Pfad
            def _build_endpoint(base: str, job_id_client: Optional[str]) -> str:
                if not job_id_client:
                    return base
                b = base.rstrip('/')
                if b.endswith(job_id_client):
                    return b
                if '{jobId}' in b:
                    return b.replace('{jobId}', job_id_client)
                return f"{b}/{job_id_client}"

            endpoint_url: Optional[str] = None
            if callback_url:
                endpoint_url = _build_endpoint(str(callback_url), client_job_id)

            # Observer zum Weiterleiten von Prozessor-Logs registrieren
            observer_ref: Optional[Callable[[str, str, Dict[str, Any]], None]] = None
            if endpoint_url:
                def _observer(level: str, message: str, kwargs: Dict[str, Any]) -> None:
                    try:
                        # Nur info/error weiterleiten, debug ignorieren
                        if level not in ("info", "error"):
                            return
                        phase = "running" if level == "info" else "failed"
                        progress_val: Optional[int] = None
                        # einfache Progress-Erkennung (kwargs ist Dict[str, Any])
                        progress_raw = kwargs.get('progress')
                        percent_raw = kwargs.get('percent')
                        if isinstance(progress_raw, (int, float)):
                            progress_val = int(progress_raw)
                        elif isinstance(percent_raw, (int, float)):
                            progress_val = int(percent_raw)
                        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
                        if callback_token:
                            headers["Authorization"] = f"Bearer {callback_token}"
                            headers["X-Callback-Token"] = str(callback_token)
                        payload: Dict[str, Any] = {
                            "phase": phase,
                            "message": message,
                            "process": {"id": job.job_id},
                        }
                        if progress_val is not None:
                            payload["progress"] = progress_val
                        requests.post(url=str(endpoint_url), json=payload, headers=headers, timeout=10)
                    except Exception:
                        # Log-Weiterleitung darf Job nicht stören
                        pass

                observer_ref = _observer
                register_log_observer(job.job_id, observer_ref)

            try:
                await handler(job, self.job_repo, self.resource_calculator)
            finally:
                # Observer deregistrieren
                if observer_ref is not None:
                    try:
                        unregister_log_observer(job.job_id, observer_ref)
                    except Exception:
                        pass

            # Vor Persistenz: Größe und größte Felder messen
            try:
                update_doc: Dict[str, Any] = {
                    "status": JobStatus.COMPLETED,
                    "progress": JobProgress(step="completed", percent=100, message="Verarbeitung abgeschlossen"),
                }
                # Heuristik: Hole aktuelles Resultat aus Repo, wenn vorhanden, um Feldergrößen abzuschätzen
                current_doc = self.job_repo.get_job(job.job_id)  # type: ignore[attr-defined]
                field_sizes: list[tuple[str, int]] = []
                def _measure_field(path: str, val: Any) -> None:
                    try:
                        if val is None:
                            size = 0
                        elif isinstance(val, (str, bytes)):
                            size = len(val)
                        else:
                            size = len(json.dumps(val))
                        field_sizes.append((path, size))
                    except Exception:
                        pass
                if isinstance(current_doc, dict):
                    # Potentiell große Felder
                    for key in ["data", "data.extracted_text", "data.images_archive_data", "data.metadata.text_contents"]:
                        parts = key.split(".")
                        ref: Any = current_doc
                        for p in parts:
                            if isinstance(ref, dict) and p in ref:
                                ref = ref[p]
                            else:
                                ref = None
                                break
                        _measure_field(key, ref)
                bson_size: Optional[int] = None
                if BSON is not None:
                    try:
                        # Simuliertes $set für Schätzung
                        bson_size = len(BSON.encode({"$set": update_doc}))
                    except Exception:
                        bson_size = None
                largest = sorted(field_sizes, key=lambda x: x[1], reverse=True)[:5]
                logger.info(
                    f"Job {job.job_id} Persistenz-Check: bson_size={bson_size} largest_fields={largest}"
                )
            except Exception:
                # Messfehler sollen Persistenz nicht verhindern
                pass

            self.job_repo.update_job_status(
                job_id=job.job_id,
                status=JobStatus.COMPLETED,
                progress=JobProgress(step="completed", percent=100, message="Verarbeitung abgeschlossen"),
            )
            logger.info(f"Job {job.job_id} erfolgreich abgeschlossen")
            if job.batch_id:
                self.job_repo.update_batch_progress(job.batch_id)
        except Exception as e:
            logger.error(f"Fehler in Job {job.job_id}: {e}")
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
            # Fehler-Webhook senden, falls konfiguriert
            try:
                extra_any: Any = getattr(job.parameters, "extra", {}) or {}
                params_extra: Dict[str, Any] = cast(Dict[str, Any], extra_any) if isinstance(extra_any, dict) else {}
                webhook_any_cfg: Any = params_extra.get("webhook")
                webhook_cfg: Optional[Dict[str, Any]] = cast(Optional[Dict[str, Any]], webhook_any_cfg) if isinstance(webhook_any_cfg, dict) else None
                if webhook_cfg is not None:
                    callback_url = cast(Optional[str], webhook_cfg.get("url"))
                    callback_token = cast(Optional[str], webhook_cfg.get("token"))
                    if callback_url:
                        payload: Dict[str, object] = {
                            "status": "error",
                            "worker": "secretary",
                            "jobId": job.job_id,
                            "process": {
                                "id": job.job_id,
                                "main_processor": job.job_type or "pdf",
                                "started": start_time.isoformat(),
                            },
                            "data": None,
                            "error": {
                                "code": error_info.code,
                                "message": error_info.message,
                                "details": error_info.details,
                            },
                        }
                        if callback_token:
                            payload["callback_token"] = callback_token
                        headers: Dict[str, str] = {"Content-Type": "application/json"}
                        if callback_token:
                            headers["Authorization"] = f"Bearer {callback_token}"
                            headers["X-Callback-Token"] = str(callback_token)
                        try:
                            self.job_repo.add_log_entry(job.job_id, "info", f"Sende Error-Webhook an {callback_url}")
                            resp = requests.post(url=str(callback_url), json=payload, headers=headers, timeout=30)
                            self.job_repo.add_log_entry(job.job_id, "info", f"Error-Webhook Antwort: {getattr(resp, 'status_code', None)} ok={getattr(resp, 'ok', None)}")
                        except Exception as post_err:
                            self.job_repo.add_log_entry(job.job_id, "error", f"Error-Webhook-POST fehlgeschlagen: {str(post_err)}")
            except Exception:
                # Webhook-Fehler nicht weiter eskalieren
                pass


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


