"""Tests für den Booklet-Job-Handler mit Fake-Repository."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image

from src.core.exceptions import ValidationError
from src.core.models.job_models import Job, JobParameters
from src.core.processing import available_job_types
from src.core.processing.handlers.booklet_handler import handle_booklet_job
from src.core.resource_tracking import ResourceCalculator
from src.processors.booklet_processor import BookletProcessor


class _FakeRepo:
    def __init__(self) -> None:
        self.status_updates: List[Dict[str, Any]] = []
        self.logs: List[Dict[str, Any]] = []

    def update_job_status(self, *, job_id: str, status: str, progress: Any = None, results: Any = None, error: Any = None) -> bool:
        self.status_updates.append({"job_id": job_id, "status": status, "progress": progress, "results": results, "error": error})
        return True

    def add_log_entry(self, job_id: str, level: str, message: str) -> bool:
        self.logs.append({"job_id": job_id, "level": level, "message": message})
        return True


def _weasyprint_available() -> bool:
    try:
        from weasyprint import HTML  # type: ignore
        HTML(string="<p>x</p>").write_pdf()
        return True
    except Exception:
        return False


@unittest.skipUnless(_weasyprint_available(), "WeasyPrint/Pango nicht verfügbar")
class TestBookletHandler(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        BookletProcessor.work_root = self.tmp / "work"
        photo = self.tmp / "foto.jpg"
        Image.new("RGB", (3000, 2000), (90, 120, 80)).save(photo, "JPEG")
        self.photo = str(photo)

    def tearDown(self) -> None:
        BookletProcessor.work_root = None
        self._tmp.cleanup()

    def test_registered_as_job_type(self) -> None:
        self.assertIn("booklet", available_job_types())

    def test_handler_stores_assets_and_report(self) -> None:
        parameters = JobParameters.from_dict({
            "template": "bcoop-heft-120",
            "title": "Heft",
            "pages": [
                {"type": "project", "id": "p1", "theme": "Zusammenhalt", "image_url": self.photo, "text": "Text"},
                {"type": "back", "id": "back", "markdown": "Ende"},
            ],
        })
        # Round-Trip wie beim Laden aus MongoDB
        parameters = JobParameters.from_dict(parameters.to_dict())
        job = Job(job_id="job-booklet-test", job_type="booklet", parameters=parameters)
        repo = _FakeRepo()

        asyncio.run(handle_booklet_job(job, repo, ResourceCalculator()))

        final = [u for u in repo.status_updates if u["results"]]
        self.assertEqual(len(final), 1)
        results = final[0]["results"]
        self.assertIn("images/p1.jpg", results["assets"])
        self.assertIn("report.json", results["assets"])
        self.assertTrue(Path(results["asset_dir"]).is_dir())
        structured = results["structured_data"]
        self.assertEqual(structured["stage"], "pdf")
        self.assertIn("heft.pdf", results["assets"])
        self.assertTrue((Path(results["asset_dir"]) / "heft.pdf").is_file())
        self.assertEqual(structured["pdf"]["page_count"], 4)
        self.assertTrue(structured["pdf"]["page_count_ok"])
        self.assertEqual(structured["page_count"], 2)
        self.assertEqual(structured["images"][0]["status"], "ready")
        self.assertEqual(structured["images"][0]["theme"], "zusammenhalt")
        self.assertTrue(any(u["progress"] and u["progress"].step == "images" for u in repo.status_updates))

    def test_handler_rejects_invalid_parameters(self) -> None:
        job = Job(job_id="job-invalid", job_type="booklet", parameters=JobParameters.from_dict({"title": "ohne Seiten"}))
        with self.assertRaises(ValidationError):
            asyncio.run(handle_booklet_job(job, _FakeRepo(), ResourceCalculator()))


if __name__ == "__main__":
    unittest.main()
