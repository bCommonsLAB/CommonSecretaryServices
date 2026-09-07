"""
Unit-Tests für das Diagnose-Logging (kein I/O gegen Webhooks).

Ausführen:
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_metrics_trace.py -q
"""

from typing import Optional

from pytest import MonkeyPatch

from src.utils.metrics_trace import (
    current_thread_name,
    log_metrics_event,
    reset_metrics_trace_logger,
    running_job_ids,
    tracker_resource_fields,
)


def test_log_metrics_event_does_not_raise() -> None:
    log_metrics_event("unit_test", path="/api/rag/embed-text", tokens=0)


def test_log_metrics_event_uses_app_logger(monkeypatch: MonkeyPatch) -> None:
    """Trace muss über ProcessingLogger gehen, sonst fehlt die Konsole."""
    recorded: list[str] = []

    class FakeLogger:
        def info(self, message: str, **_kwargs: object) -> None:
            recorded.append(message)

    def _fake_get_logger(
        process_id: str,
        processor_name: Optional[str] = None,
    ) -> FakeLogger:
        return FakeLogger()

    reset_metrics_trace_logger()
    monkeypatch.setattr("src.utils.logger.get_logger", _fake_get_logger)
    log_metrics_event("http_in", path="/api/rag/embed-text")
    assert recorded, "keine Log-Zeile geschrieben"
    assert "[METRICS-TRACE]" in recorded[0]
    assert "http_in" in recorded[0]
    assert "/api/rag/embed-text" in recorded[0]
    reset_metrics_trace_logger()


def test_running_job_ids_is_a_list() -> None:
    ids = running_job_ids()
    assert isinstance(ids, list)


def test_current_thread_name_is_nonempty() -> None:
    assert len(current_thread_name()) > 0


def test_tracker_resource_fields_none() -> None:
    fields = tracker_resource_fields(None)
    assert fields["tokens"] == 0
    assert fields["cost"] == 0.0
    assert fields["models"] == []
