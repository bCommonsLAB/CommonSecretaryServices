"""
Unit-Tests: LLM-Requests landen mit Token und Kosten im PerformanceTracker.

Ausführen:
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_tracker_llm_requests.py -q
"""

from src.core.models.llm import LLMRequest
from src.utils.performance_tracker import (
    PerformanceTracker,
    clear_performance_tracker,
    get_performance_tracker,
)


def test_add_llm_request_list_sums_tokens_and_cost() -> None:
    tracker = PerformanceTracker("test-proc")
    tracker.add_llm_request_list([
        LLMRequest(
            model="openrouter/google/gemini-2.5-flash",
            purpose="chat_completion",
            tokens=100,
            duration=10.0,
            processor="OpenRouterProvider",
            cost=0.01,
            timestamp="2026-08-21T12:00:00",
        ),
        LLMRequest(
            model="openrouter/google/gemini-2.5-flash",
            purpose="chat_completion",
            tokens=50,
            duration=5.0,
            processor="OpenRouterProvider",
            cost=0.005,
            timestamp="2026-08-21T12:00:01",
        ),
    ])
    resources = tracker.measurements["resources"]
    assert resources["total_tokens"] == 150
    assert abs(resources["total_cost"] - 0.015) < 1e-9
    # Derselbe Modellname nur einmal (keine Wiederholung in der Spalte).
    assert resources["models_used"] == ["openrouter/google/gemini-2.5-flash"]


def test_thread_local_tracker_receives_requests() -> None:
    clear_performance_tracker()
    tracker = get_performance_tracker("thread-1")
    assert tracker is not None
    tracker.add_llm_request_list([
        LLMRequest(
            model="voyage-3-large",
            purpose="embedding",
            tokens=80,
            duration=0.0,
            processor="RAGProcessor",
            cost=0.0,
            timestamp="2026-08-21T12:00:00",
        )
    ])
    assert tracker.measurements["resources"]["total_tokens"] == 80
    clear_performance_tracker()
    assert get_performance_tracker() is None
