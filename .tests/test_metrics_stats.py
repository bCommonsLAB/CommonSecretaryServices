"""
Unit-Tests für die reine Aggregationslogik der Request-Metriken
(src/core/mongodb/metrics_repository.py).

Diese Tests laufen ohne MongoDB, da compute_stats() und map_recent_entry()
reine Funktionen über Dokumentlisten sind.

Ausführen (aus dem Projektroot, in der venv):
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_metrics_stats.py -q
"""

from typing import Any, Dict, List, Optional

from src.core.mongodb.metrics_repository import compute_stats, map_recent_entry


def _doc(
    processor: str,
    status: str,
    duration: float,
    tokens: int,
    cost: float,
    timestamp: str,
    models: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Hilfsfunktion: erzeugt ein Metrik-Dokument in der gespeicherten Form."""
    return {
        "processor": processor,
        "status": status,
        "total_duration": duration,
        "timestamp": timestamp,
        "measurements": {
            "operations": [],
            "processors": {},
            "resources": {
                "total_tokens": tokens,
                "total_cost": cost,
                "models_used": models or [],
            },
        },
    }


def test_empty_docs_returns_zero_stats() -> None:
    """Ohne Dokumente müssen alle Kennzahlen 0/leer sein."""
    stats = compute_stats([])
    assert stats["total_requests"] == 0
    assert stats["avg_duration"] == 0.0
    assert stats["success_rate"] == 0.0
    assert stats["operations"] == {}
    assert stats["processor_stats"] == {}
    assert stats["hourly_stats"] == {}


def test_basic_aggregation() -> None:
    """Prüft Gesamtzahl, Durchschnittsdauer, Erfolgsrate und Token-Summe."""
    docs: List[Dict[str, Any]] = [
        _doc("audio", "success", 2.0, 100, 0.01, "2026-06-19T09:00:00"),
        _doc("audio", "error", 4.0, 0, 0.0, "2026-06-19T09:30:00"),
        _doc("pdf", "success", 6.0, 200, 0.02, "2026-06-19T10:00:00"),
    ]
    stats = compute_stats(docs)

    assert stats["total_requests"] == 3
    assert stats["avg_duration"] == 4.0  # (2+4+6)/3
    assert round(stats["success_rate"], 2) == round((2 / 3) * 100, 2)
    assert stats["total_tokens"] == 300
    # Operationen werden nach Hauptprozessor gezählt.
    assert stats["operations"] == {"audio": 2, "pdf": 1}


def test_processor_stats_averages() -> None:
    """Prüft die abgeleiteten Kennzahlen je Prozessor."""
    docs: List[Dict[str, Any]] = [
        _doc("audio", "success", 2.0, 100, 0.01, "2026-06-19T09:00:00"),
        _doc("audio", "error", 4.0, 50, 0.00, "2026-06-19T09:30:00"),
    ]
    stats = compute_stats(docs)
    audio = stats["processor_stats"]["audio"]

    assert audio["request_count"] == 2
    assert audio["avg_duration"] == 3.0       # (2+4)/2
    assert audio["success_rate"] == 50.0      # 1 von 2 erfolgreich
    assert audio["avg_tokens"] == 75          # (100+50)//2


def test_hourly_buckets() -> None:
    """Mehrere Requests in derselben Stunde werden zusammengefasst."""
    docs: List[Dict[str, Any]] = [
        _doc("audio", "success", 1.0, 0, 0.0, "2026-06-19T09:05:00"),
        _doc("pdf", "success", 1.0, 0, 0.0, "2026-06-19T09:45:00"),
        _doc("pdf", "success", 1.0, 0, 0.0, "2026-06-19T11:10:00"),
    ]
    stats = compute_stats(docs)
    assert stats["hourly_stats"] == {"09:00": 2, "11:00": 1}


def test_map_recent_entry_shape() -> None:
    """map_recent_entry liefert die vom Template erwartete flache Struktur."""
    doc = _doc("video", "success", 3.5, 120, 0.05, "2026-06-19T09:00:00")
    entry = map_recent_entry(doc)

    assert entry["status"] == "success"
    assert entry["operation"] == "video"
    assert entry["total_duration"] == 3.5
    assert entry["resources"]["total_tokens"] == 120
    assert entry["resources"]["total_cost"] == 0.05
    assert entry["timestamp"] == "2026-06-19T09:00:00"
    # Ohne erfasstes Modell bleibt die Spalte leer.
    assert entry["model"] == ""


def test_map_recent_entry_model() -> None:
    """Erfasste Modelle werden als kommaseparierter String zusammengefasst."""
    doc = _doc(
        "transformer", "success", 1.0, 0, 0.0, "2026-06-19T09:00:00",
        models=["mistral-ocr-2512", "voyage-3-large"],
    )
    entry = map_recent_entry(doc)
    assert entry["model"] == "mistral-ocr-2512, voyage-3-large"


def test_missing_fields_are_robust() -> None:
    """Dokumente mit fehlenden Feldern dürfen nicht zum Absturz führen."""
    stats = compute_stats([{"status": "success"}])
    assert stats["total_requests"] == 1
    assert stats["avg_duration"] == 0.0
    # Kein 'processor' -> als 'unknown' gezählt.
    assert stats["operations"] == {"unknown": 1}
