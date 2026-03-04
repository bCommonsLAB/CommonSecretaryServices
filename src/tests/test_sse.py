"""
Tests fuer SSE (Server-Sent Events) Modul.

Testet die SSE-Formatierung und den Event-Stream-Generator
ohne MongoDB-Verbindung (Mocks).
"""
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, UTC

from src.api.sse import format_sse, build_event_from_job, event_type_for_status
from src.core.models.job_models import (
    Job, JobStatus, JobProgress, JobResults, JobError, JobParameters
)


class TestFormatSSE(unittest.TestCase):
    """Tests fuer die SSE-Formatierungsfunktion."""

    def test_format_sse_with_event(self) -> None:
        """SSE-Event mit Event-Typ wird korrekt formatiert."""
        result = format_sse({"phase": "completed"}, event="completed")
        lines = result.split("\n")
        self.assertEqual(lines[0], "event: completed")
        self.assertTrue(lines[1].startswith("data: "))
        data = json.loads(lines[1][6:])
        self.assertEqual(data["phase"], "completed")

    def test_format_sse_without_event(self) -> None:
        """SSE-Event ohne Event-Typ wird korrekt formatiert."""
        result = format_sse({"message": "test"})
        self.assertFalse(result.startswith("event:"))
        self.assertTrue(result.startswith("data: "))

    def test_format_sse_ends_with_double_newline(self) -> None:
        """SSE-Events muessen mit doppeltem Newline enden (SSE-Spezifikation)."""
        result = format_sse({"test": True}, event="test")
        self.assertTrue(result.endswith("\n\n"))

    def test_format_sse_datetime_serialization(self) -> None:
        """datetime-Objekte werden korrekt zu ISO-Format serialisiert."""
        dt = datetime(2026, 3, 3, 12, 0, 0, tzinfo=UTC)
        result = format_sse({"timestamp": dt})
        data = json.loads(result.split("data: ")[1].split("\n")[0])
        self.assertIn("2026-03-03", data["timestamp"])

    def test_format_sse_unicode(self) -> None:
        """Unicode-Zeichen (Umlaute etc.) werden korrekt serialisiert."""
        result = format_sse({"message": "Verarbeitung laeuft fuer Aerzte"})
        data = json.loads(result.split("data: ")[1].split("\n")[0])
        self.assertIn("Aerzte", data["message"])


class TestBuildEventFromJob(unittest.TestCase):
    """Tests fuer die Event-Payload-Erstellung aus Job-Objekten."""

    def test_pending_job(self) -> None:
        """PENDING-Job erzeugt korrektes Event."""
        job = Job()
        job.job_id = "test-job-123"
        job.job_type = "pdf"
        job.status = JobStatus.PENDING
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "pending")
        self.assertEqual(event["job"]["id"], "test-job-123")
        self.assertEqual(event["data"]["progress"], 0)

    def test_processing_job_with_progress(self) -> None:
        """PROCESSING-Job mit Fortschritt erzeugt korrektes Event."""
        job = Job()
        job.job_id = "test-job-123"
        job.job_type = "pdf"
        job.status = JobStatus.PROCESSING
        job.progress = JobProgress(step="transcription", percent=45, message="Transkription laeuft")
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "running")
        self.assertEqual(event["data"]["progress"], 45)
        self.assertIn("Transkription", event["message"])

    def test_processing_job_without_progress(self) -> None:
        """PROCESSING-Job ohne Fortschritt erzeugt Fallback-Event."""
        job = Job()
        job.job_id = "test-job-123"
        job.job_type = "pdf"
        job.status = JobStatus.PROCESSING
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "running")
        self.assertEqual(event["data"]["progress"], 0)

    def test_completed_pdf_job_webhook_format(self) -> None:
        """COMPLETED PDF-Job erzeugt Event mit Webhook-kompatibler data-Struktur."""
        job = Job()
        job.job_id = "test-job-123"
        job.job_type = "pdf"
        job.status = JobStatus.COMPLETED
        job.parameters = JobParameters(extraction_method="mistral_ocr_with_pages")
        job.results = JobResults(
            structured_data={
                "data": {
                    "extracted_text": "--- Seite 1 ---\nTest-Text",
                    "metadata": {"page_count": 3, "text_contents": ["Seite 1"]},
                }
            },
            assets=["/path/to/image.png"],
        )
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "completed")
        # Webhook-kompatible flache Struktur (kein data.results Wrapper)
        self.assertEqual(event["data"]["extracted_text"], "--- Seite 1 ---\nTest-Text")
        self.assertEqual(event["data"]["metadata"]["page_count"], 3)
        # Mistral OCR URLs muessen vorhanden sein
        self.assertIn("mistral_ocr_raw_url", event["data"])
        self.assertIn("pages_archive_url", event["data"])
        self.assertIn(job.job_id, event["data"]["mistral_ocr_raw_url"])

    def test_completed_audio_job_webhook_format(self) -> None:
        """COMPLETED Audio-Job erzeugt Event mit transcription.text."""
        job = Job()
        job.job_id = "test-job-456"
        job.job_type = "audio"
        job.status = JobStatus.COMPLETED
        job.results = JobResults(markdown_content="Transkribierter Text hier")
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "completed")
        self.assertEqual(event["data"]["transcription"]["text"], "Transkribierter Text hier")

    def test_completed_video_job_webhook_format(self) -> None:
        """COMPLETED Video-Job erzeugt Event mit transcription.text und result."""
        job = Job()
        job.job_id = "test-job-789"
        job.job_type = "video"
        job.status = JobStatus.COMPLETED
        job.results = JobResults(
            video_transcript="Video-Transkript",
            structured_data={"some": "data"},
        )
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "completed")
        self.assertEqual(event["data"]["transcription"]["text"], "Video-Transkript")
        self.assertEqual(event["data"]["result"]["some"], "data")

    def test_completed_generic_job_fallback(self) -> None:
        """COMPLETED Job mit unbekanntem Typ nutzt structured_data direkt."""
        job = Job()
        job.job_id = "test-job-gen"
        job.job_type = "transformer_template"
        job.status = JobStatus.COMPLETED
        job.results = JobResults(structured_data={"transformed": "text"})
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "completed")
        self.assertEqual(event["data"]["transformed"], "text")

    def test_failed_job(self) -> None:
        """FAILED-Job erzeugt Error-Event."""
        job = Job()
        job.job_id = "test-job-123"
        job.job_type = "pdf"
        job.status = JobStatus.FAILED
        job.error = JobError(code="RuntimeError", message="Datei nicht gefunden")
        event = build_event_from_job(job)
        self.assertEqual(event["phase"], "error")
        self.assertEqual(event["error"]["code"], "RuntimeError")
        self.assertIsNone(event["data"])

    def test_event_contains_process_info(self) -> None:
        """Alle Events enthalten process-Informationen."""
        job = Job()
        job.job_id = "test-job-123"
        job.job_type = "pdf"
        job.status = JobStatus.PENDING
        event = build_event_from_job(job)
        self.assertEqual(event["process"]["id"], "test-job-123")
        self.assertEqual(event["process"]["main_processor"], "pdf")


class TestEventTypeForStatus(unittest.TestCase):
    """Tests fuer das Status-zu-EventType-Mapping."""

    def test_all_statuses_mapped(self) -> None:
        """Alle JobStatus-Werte haben ein Event-Type-Mapping."""
        for status in JobStatus:
            evt_type = event_type_for_status(status)
            self.assertIsInstance(evt_type, str)
            self.assertTrue(len(evt_type) > 0)

    def test_mapping_values(self) -> None:
        """Korrekte Event-Typen fuer jeden Status."""
        self.assertEqual(event_type_for_status(JobStatus.PENDING), "pending")
        self.assertEqual(event_type_for_status(JobStatus.PROCESSING), "progress")
        self.assertEqual(event_type_for_status(JobStatus.COMPLETED), "completed")
        self.assertEqual(event_type_for_status(JobStatus.FAILED), "error")


class TestJobEventStream(unittest.TestCase):
    """Tests fuer den SSE-Event-Stream-Generator (mit Mock-Repository)."""

    @patch("src.api.sse.SecretaryJobRepository")
    def test_stream_job_not_found(self, mock_repo_cls: MagicMock) -> None:
        """Stream sendet Error-Event wenn Job nicht existiert."""
        from src.api.sse import job_event_stream

        mock_repo = mock_repo_cls.return_value
        mock_repo.get_job.return_value = None

        events = list(job_event_stream("nonexistent-job"))
        self.assertEqual(len(events), 1)
        self.assertIn("error", events[0])
        self.assertIn("nicht gefunden", events[0])

    @patch("src.api.sse.SecretaryJobRepository")
    def test_stream_completed_job_sends_one_event(self, mock_repo_cls: MagicMock) -> None:
        """Bereits abgeschlossener Job: Stream sendet 1 Event und schliesst."""
        from src.api.sse import job_event_stream

        mock_repo = mock_repo_cls.return_value
        completed_job = Job()
        completed_job.job_id = "job-done"
        completed_job.job_type = "pdf"
        completed_job.status = JobStatus.COMPLETED
        completed_job.results = JobResults(
            structured_data={"data": {"extracted_text": "# Ergebnis"}}
        )
        mock_repo.get_job.return_value = completed_job

        events = list(job_event_stream("job-done"))
        self.assertEqual(len(events), 1)
        self.assertIn("completed", events[0])
        self.assertIn("Ergebnis", events[0])

    @patch("src.api.sse.time")
    @patch("src.api.sse.SecretaryJobRepository")
    def test_stream_pending_to_completed(self, mock_repo_cls: MagicMock, mock_time: MagicMock) -> None:
        """Stream sendet Updates bei Statuswechsel pending -> processing -> completed."""
        from src.api.sse import job_event_stream

        # Genuegend monotonic()-Aufrufe fuer: start_time, heartbeat_init,
        # initialer check, loop-elapsed, heartbeat-check, loop-elapsed, heartbeat-check, finale Dauer
        mock_time.monotonic.return_value = 5.0
        mock_time.sleep = MagicMock()

        pending_job = Job()
        pending_job.job_id = "job-1"
        pending_job.job_type = "pdf"
        pending_job.status = JobStatus.PENDING

        processing_job = Job()
        processing_job.job_id = "job-1"
        processing_job.job_type = "pdf"
        processing_job.status = JobStatus.PROCESSING
        processing_job.progress = JobProgress(step="extraction", percent=50)

        completed_job = Job()
        completed_job.job_id = "job-1"
        completed_job.job_type = "pdf"
        completed_job.status = JobStatus.COMPLETED
        completed_job.results = JobResults(
            structured_data={"data": {"extracted_text": "Fertig"}}
        )

        mock_repo = mock_repo_cls.return_value
        mock_repo.get_job.side_effect = [pending_job, processing_job, completed_job]

        events = list(job_event_stream("job-1"))

        # 3 Events: pending (initial), processing, completed
        self.assertEqual(len(events), 3)
        self.assertIn("pending", events[0])
        self.assertIn("running", events[1])
        self.assertIn("completed", events[2])


if __name__ == "__main__":
    unittest.main()
