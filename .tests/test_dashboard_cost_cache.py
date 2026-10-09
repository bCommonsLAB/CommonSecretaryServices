"""
Tests für die Dashboard-Anzeige von Kosten, Cache-Treffern und Zeit.

Hintergrund: Das Dashboard zeigte "$0.000" auch dann, wenn der Provider gar
keinen Preis liefert (OpenAI, Voyage), ein Cache-Treffer sah aus wie eine
Anfrage ohne erfasstes Modell, und Kacheln und Übersicht blieben auf dem Stand
des Seitenaufrufs stehen.

Geprüft wird:
- Tracker zählt Aufrufe mit und ohne Preis und merkt sich Cache-Treffer
- Kostenstatus je Anfrage: bekannt, teilweise, unbekannt ("?"), Cache ($0)
- Alte Dokumente ohne Zählung: Betrag > 0 bekannt, sonst "?"
- Kosten/Anfrage je Prozessor mittelt nur über Anfragen mit Preis
- Kompakte Zeitangabe
- Teilvorlagen und /api/dashboard-stats liefern die ganze Ansicht

Ausführen:
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_dashboard_cost_cache.py -q
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from flask import Flask

from src.core.models.llm import LLMRequest
from src.core.mongodb.metrics_repository import (
    COST_CACHE,
    COST_KNOWN,
    COST_PARTIAL,
    COST_UNKNOWN,
    compute_stats,
    cost_status,
    format_compact_time,
    format_cost,
    map_recent_entry,
)
from src.utils.performance_tracker import PerformanceTracker

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "dashboard" / "templates"
NOW = datetime(2026, 10, 9, 14, 0, 0)


def _req(cost: float, model: str = "gpt-transcribe") -> LLMRequest:
    return LLMRequest(
        model=model,
        purpose="transcription",
        tokens=10,
        duration=100.0,
        processor="Test",
        cost=cost,
        timestamp="2026-10-09T12:00:00",
    )


def _doc(
    processor: str = "audio",
    cost: float = 0.0,
    models: Optional[List[str]] = None,
    priced: Optional[int] = None,
    unpriced: Optional[int] = None,
    from_cache: Optional[bool] = None,
    timestamp: str = "2026-10-09T12:45:07.614614",
) -> Dict[str, Any]:
    resources: Dict[str, Any] = {
        "total_tokens": 10,
        "total_cost": cost,
        "models_used": models or [],
    }
    if priced is not None:
        resources["priced_requests"] = priced
    if unpriced is not None:
        resources["unpriced_requests"] = unpriced
    doc: Dict[str, Any] = {
        "processor": processor,
        "status": "success",
        "total_duration": 2.0,
        "timestamp": timestamp,
        "measurements": {"operations": [], "processors": {}, "resources": resources},
    }
    if from_cache is not None:
        doc["from_cache"] = from_cache
    return doc


# --- Tracker -----------------------------------------------------------------


def test_tracker_counts_priced_and_unpriced_requests() -> None:
    tracker = PerformanceTracker("p-1")
    tracker.add_llm_request_list([_req(0.0), _req(0.012, model="google/gemini"), _req(0.0)])
    resources = tracker.measurements["resources"]
    assert resources["priced_requests"] == 1
    assert resources["unpriced_requests"] == 2
    assert resources["total_cost"] == 0.012


def test_tracker_persists_from_cache_flag() -> None:
    tracker = PerformanceTracker("p-2")
    tracker.set_processor_name("audio")
    tracker.set_from_cache(True)
    recorded: List[Dict[str, Any]] = []

    class _Repo:
        def record(self, doc: Dict[str, Any]) -> None:
            recorded.append(doc)

    with patch("src.core.mongodb.get_metrics_repository", return_value=_Repo()):
        tracker.complete_tracking()

    assert recorded[0]["from_cache"] is True
    assert recorded[0]["measurements"]["resources"]["unpriced_requests"] == 0


def test_tracker_without_cache_report_stores_none() -> None:
    tracker = PerformanceTracker("p-3")
    recorded: List[Dict[str, Any]] = []

    class _Repo:
        def record(self, doc: Dict[str, Any]) -> None:
            recorded.append(doc)

    with patch("src.core.mongodb.get_metrics_repository", return_value=_Repo()):
        tracker.complete_tracking()

    assert recorded[0]["from_cache"] is None


# --- Kostenstatus je Anfrage -------------------------------------------------


def test_cost_status_cases() -> None:
    assert cost_status(_doc(cost=0.02, models=["gemini"], priced=2, unpriced=0)) == COST_KNOWN
    assert cost_status(_doc(cost=0.02, models=["gemini", "voyage"], priced=1, unpriced=1)) == COST_PARTIAL
    assert cost_status(_doc(cost=0.0, models=["gpt-transcribe"], priced=0, unpriced=1)) == COST_UNKNOWN
    assert cost_status(_doc(cost=0.0, priced=0, unpriced=0, from_cache=True)) == COST_CACHE
    # Keine Modellaufrufe erfasst und kein Cache-Treffer: Preis nicht bekannt.
    assert cost_status(_doc(cost=0.0, priced=0, unpriced=0, from_cache=False)) == COST_UNKNOWN


def test_old_documents_without_counts() -> None:
    assert cost_status(_doc(cost=0.017, models=["gemini"])) == COST_KNOWN
    assert cost_status(_doc(cost=0.0, models=["gpt-transcribe"])) == COST_UNKNOWN
    assert cost_status(_doc(cost=0.0)) == COST_UNKNOWN


def test_recent_entry_shows_question_mark_instead_of_zero() -> None:
    entry = map_recent_entry(_doc(cost=0.0, models=["gpt-transcribe"], priced=0, unpriced=1), now=NOW)
    assert entry["cost_text"] == "?"
    assert entry["cost_status"] == COST_UNKNOWN
    assert "unbekannt" in entry["cost_hint"]


def test_recent_entry_for_cache_hit() -> None:
    entry = map_recent_entry(_doc(cost=0.0, priced=0, unpriced=0, from_cache=True), now=NOW)
    assert entry["from_cache"] is True
    assert entry["cost_text"] == "$0"
    assert entry["model"] == ""


def test_recent_entry_partial_and_small_amounts() -> None:
    partial = map_recent_entry(_doc(cost=0.0004, models=["a", "b"], priced=1, unpriced=1), now=NOW)
    assert partial["cost_text"] == "$0.0004 + ?"
    known = map_recent_entry(_doc(cost=0.017059, models=["a"], priced=1, unpriced=0), now=NOW)
    assert known["cost_text"] == "$0.017"


def test_format_cost() -> None:
    assert format_cost(0.0) == "$0"
    assert format_cost(0.00025) == "$0.0003"
    assert format_cost(0.12345) == "$0.123"


# --- Zeit --------------------------------------------------------------------


def test_compact_time() -> None:
    assert format_compact_time("2026-10-09T12:45:07.614614", NOW) == "12:45:07"
    assert format_compact_time("2026-10-08T00:59:12.1", NOW) == "08.10. 00:59"
    assert format_compact_time("2025-12-31T23:10:00", NOW) == "31.12.25 23:10"
    assert format_compact_time("kaputt", NOW) == "kaputt"


def test_recent_entry_keeps_full_timestamp_for_tooltip() -> None:
    entry = map_recent_entry(_doc(), now=NOW)
    assert entry["timestamp"] == "2026-10-09T12:45:07.614614"
    assert entry["time_text"] == "12:45:07"


# --- Performance-Übersicht ---------------------------------------------------


def test_processor_avg_cost_uses_only_priced_requests() -> None:
    stats = compute_stats([
        _doc("transformer", cost=0.02, models=["gemini"], priced=1, unpriced=0),
        _doc("transformer", cost=0.04, models=["gemini"], priced=1, unpriced=0),
        _doc("transformer", cost=0.0, models=["gpt"], priced=0, unpriced=1),
    ])
    transformer = stats["processor_stats"]["transformer"]
    assert abs(transformer["avg_cost"] - 0.03) < 1e-9
    assert transformer["avg_cost_text"] == "$0.030"
    assert transformer["unknown_cost_count"] == 1
    assert transformer["cost_note"] == "1 von 3 ohne Preis"


def test_processor_without_any_price_is_question_mark() -> None:
    stats = compute_stats([_doc("audio", cost=0.0, models=["gpt-transcribe"], priced=0, unpriced=1)])
    audio = stats["processor_stats"]["audio"]
    assert audio["avg_cost"] is None
    assert audio["avg_cost_text"] == "?"
    assert audio["cost_note"] == ""


def test_cache_hits_count_as_known_zero() -> None:
    stats = compute_stats([
        _doc("audio", cost=0.0, priced=0, unpriced=0, from_cache=True),
        _doc("audio", cost=0.0, models=["gpt-transcribe"], priced=0, unpriced=1),
    ])
    audio = stats["processor_stats"]["audio"]
    assert audio["avg_cost"] == 0.0
    assert audio["cost_note"] == "1 von 2 ohne Preis"


# --- Vorlagen und Route ------------------------------------------------------


def _app() -> Flask:
    return Flask(__name__, template_folder=str(TEMPLATES))


def _stats() -> Dict[str, Any]:
    docs = [
        _doc("audio", cost=0.0, models=["gpt-transcribe"], priced=0, unpriced=1),
        _doc("audio", cost=0.0, priced=0, unpriced=0, from_cache=True, timestamp="2026-10-09T12:44:49.1"),
    ]
    stats = compute_stats(docs)
    stats["recent_requests"] = [map_recent_entry(d, now=NOW) for d in docs]
    stats["generated_at"] = "14:00:00"
    return stats


def test_recent_requests_partial_renders_cache_badge_and_question_mark() -> None:
    from flask import render_template

    with _app().app_context():
        html = render_template("_recent_requests.html", recent_requests=_stats()["recent_requests"])
    assert "Cache" in html
    assert ">?<" in html
    assert "$0.000" not in html
    assert "12:45:07" in html
    assert "2026-10-09T12:45:07" in html  # vollständig im Tooltip


def test_dashboard_stats_endpoint_returns_whole_view() -> None:
    from src.dashboard.routes import main_routes

    app = _app()
    with patch.object(main_routes, "_load_dashboard_stats", return_value=_stats()):
        with app.test_request_context("/api/dashboard-stats"):
            response = main_routes.get_dashboard_stats()
    data = response.get_json()
    assert data["generated_at"] == "14:00:00"
    assert "Gesamtanfragen (24h)" in data["tiles_html"]
    assert ">2<" in data["tiles_html"]
    assert "Kosten/Anfrage" in data["processors_html"]
    assert "Cache" in data["recent_html"]
    assert data["charts"]["operations"] == {"labels": ["audio"], "data": [2]}
    assert data["charts"]["hourly"]["data"] == [2]
