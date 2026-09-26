"""Tests: Fehler-Webhook des Secretary-Workers liest die Webhook-Konfiguration korrekt."""

from typing import Any, Dict, Optional

from src.core.models.job_models import Job, JobParameters, JobStatus
from src.core.mongodb.secretary_worker_manager import (
    _build_callback_endpoint,
    _read_webhook_config,
)


def _job(params: Dict[str, Any]) -> Job:
    return Job(
        job_id="job-1",
        job_type="pdf",
        status=JobStatus.PENDING,
        parameters=JobParameters.from_dict(params),
    )


def test_webhook_is_flat_field_after_from_dict() -> None:
    # Genau so kommt es aus pdf_routes: webhook als Top-Level-Key.
    job = _job({"webhook": {"url": "https://c/api/jobs", "token": "t", "jobId": "cj"}})
    assert job.parameters.webhook is not None
    assert "webhook" not in job.parameters.extra
    assert _read_webhook_config(job) == ("https://c/api/jobs", "t", "cj")


def test_webhook_in_extra_still_supported() -> None:
    job = _job({})
    job.parameters.webhook = None
    job.parameters.extra["webhook"] = {"url": "https://c/x", "token": None, "jobId": None}
    assert _read_webhook_config(job) == ("https://c/x", None, None)


def test_no_webhook() -> None:
    assert _read_webhook_config(_job({})) == (None, None, None)


def test_build_endpoint() -> None:
    assert _build_callback_endpoint("https://c/api/jobs", "cj") == "https://c/api/jobs/cj"
    assert _build_callback_endpoint("https://c/api/jobs/cj", "cj") == "https://c/api/jobs/cj"
    assert _build_callback_endpoint("https://c/api/{jobId}/cb", "cj") == "https://c/api/cj/cb"
    assert _build_callback_endpoint("https://c/api/jobs", None) == "https://c/api/jobs"
