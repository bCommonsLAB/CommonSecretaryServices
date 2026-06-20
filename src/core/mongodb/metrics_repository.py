"""
@fileoverview Request Metrics Repository - MongoDB persistence for request performance metrics

@description
Speichert Performance-Metriken pro API-/Verarbeitungs-Request in MongoDB und
liefert aggregierte Kennzahlen für das Dashboard. Ersetzt die frühere
JSON-Datei (logs/performance.json), die nie zuverlässig befüllt wurde.

Die eigentliche Aggregation (compute_stats) ist eine reine Funktion ohne
DB-Zugriff und damit isoliert testbar (siehe .tests/test_metrics_stats.py).

@module core.mongodb.metrics_repository

@exports
- RequestMetricsRepository: Class - Repository für Request-Metriken
- compute_stats(): Dict - Reine Aggregation einer Dokumentliste zu Kennzahlen
- map_recent_entry(): Dict - Bringt ein Dokument in die vom Template erwartete Form
"""

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from typing import Any, Dict, List, cast
from datetime import datetime, timedelta, timezone
import logging

from .connection import get_mongodb_database

logger = logging.getLogger(__name__)

# Aufbewahrungsdauer der Metriken (TTL-Index). 30 Tage analog zu den Caches.
METRICS_TTL_SECONDS: int = 30 * 24 * 60 * 60


def _parse_timestamp(value: str) -> datetime:
    """Parst einen ISO-Zeitstempel defensiv; bei Fehler -> Unix-Epoch."""
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return datetime.fromtimestamp(0)


def map_recent_entry(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Bringt ein gespeichertes Metrik-Dokument in die flache Form, die die
    Templates (dashboard.html / _recent_requests.html) erwarten.

    Args:
        doc: Das gespeicherte Metrik-Dokument.

    Returns:
        Dict mit status, operation, total_duration, resources, timestamp.
    """
    measurements: Dict[str, Any] = doc.get("measurements") or {}
    resources: Dict[str, Any] = measurements.get("resources") or {}
    # Verwendete Modelle (dedupliziert) für die Anzeige zusammenfassen.
    raw_models: List[Any] = cast(List[Any], resources.get("models_used") or [])
    models_used: List[str] = [str(m) for m in raw_models if m]
    return {
        "status": doc.get("status", "unknown"),
        # 'operation' = Hauptprozessor; reicht für Anzeige und Pie-Chart.
        "operation": doc.get("processor") or "unknown",
        "total_duration": float(doc.get("total_duration", 0) or 0),
        # 'model' = real verwendetes Modell (leer, wenn nicht erfasst).
        "model": ", ".join(models_used),
        "resources": {
            "total_tokens": int(resources.get("total_tokens", 0) or 0),
            "total_cost": float(resources.get("total_cost", 0.0) or 0.0),
        },
        "timestamp": str(doc.get("timestamp", "")),
    }


def compute_stats(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Aggregiert eine Liste von Metrik-Dokumenten zu Dashboard-Kennzahlen.

    Reine Funktion ohne DB-Zugriff -> isoliert testbar.

    Args:
        docs: Liste gespeicherter Metrik-Dokumente.

    Returns:
        Dict mit total_requests, avg_duration, success_rate, hourly_tokens,
        operations, processor_stats und hourly_stats.
    """
    stats: Dict[str, Any] = {
        "total_requests": 0,
        "avg_duration": 0.0,
        "success_rate": 0.0,
        "total_tokens": 0,
        "hourly_tokens": 0,
        "operations": {},
        "processor_stats": {},
        "hourly_stats": {},
        "recent_requests": [],
    }
    if not docs:
        return stats

    count = len(docs)
    total_duration = 0.0
    success_count = 0
    total_tokens = 0
    operations: Dict[str, int] = {}
    processors: Dict[str, Dict[str, float]] = {}
    hour_counts: Dict[str, int] = {}

    for doc in docs:
        duration = float(doc.get("total_duration", 0) or 0)
        total_duration += duration
        is_success = doc.get("status") == "success"
        if is_success:
            success_count += 1

        measurements: Dict[str, Any] = doc.get("measurements") or {}
        resources: Dict[str, Any] = measurements.get("resources") or {}
        tokens = int(resources.get("total_tokens", 0) or 0)
        cost = float(resources.get("total_cost", 0.0) or 0.0)
        total_tokens += tokens

        # Operationen/Prozessor-Statistik nach Hauptprozessor gruppieren.
        proc = doc.get("processor") or "unknown"
        operations[proc] = operations.get(proc, 0) + 1
        ps = processors.setdefault(
            proc,
            {"request_count": 0, "total_duration": 0.0, "success_count": 0,
             "total_tokens": 0, "total_cost": 0.0},
        )
        ps["request_count"] += 1
        ps["total_duration"] += duration
        ps["success_count"] += 1 if is_success else 0
        ps["total_tokens"] += tokens
        ps["total_cost"] += cost

        # Stündliche Verteilung.
        hour = _parse_timestamp(str(doc.get("timestamp", ""))).strftime("%H:00")
        hour_counts[hour] = hour_counts.get(hour, 0) + 1

    # Abgeleitete Kennzahlen je Prozessor berechnen.
    processor_stats: Dict[str, Dict[str, float]] = {}
    for proc, ps in processors.items():
        rc = ps["request_count"] or 1
        processor_stats[proc] = {
            "request_count": ps["request_count"],
            "avg_duration": ps["total_duration"] / rc,
            "success_rate": (ps["success_count"] / rc) * 100,
            "avg_tokens": ps["total_tokens"] // rc,
            "avg_cost": ps["total_cost"] / rc,
        }

    stats["total_requests"] = count
    stats["avg_duration"] = total_duration / count
    stats["success_rate"] = (success_count / count) * 100
    stats["total_tokens"] = total_tokens
    stats["hourly_tokens"] = total_tokens // 24 if total_tokens > 0 else 0
    stats["operations"] = operations
    stats["processor_stats"] = processor_stats
    stats["hourly_stats"] = {h: hour_counts[h] for h in sorted(hour_counts.keys())}
    return stats


class RequestMetricsRepository:
    """
    Repository für die Persistenz von Request-Performance-Metriken in MongoDB.
    """

    def __init__(self) -> None:
        """Initialisiert das Repository und stellt die Indizes sicher."""
        self.db: Database[Any] = get_mongodb_database()
        self.metrics: Collection[Any] = self.db.request_metrics
        self._create_indexes()
        logger.info("RequestMetricsRepository initialisiert")

    def _create_indexes(self) -> None:
        """Erstellt Indizes inkl. TTL für automatische Aufbewahrungsbegrenzung."""
        try:
            # TTL: alte Metriken automatisch nach METRICS_TTL_SECONDS entfernen.
            self.metrics.create_index(
                [("created_at", ASCENDING)], expireAfterSeconds=METRICS_TTL_SECONDS
            )
            self.metrics.create_index([("processor", ASCENDING)])
            self.metrics.create_index([("status", ASCENDING)])
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Metrik-Indizes: {str(e)}")

    def record(self, doc: Dict[str, Any]) -> None:
        """
        Speichert ein Metrik-Dokument. Fügt created_at (UTC) für den TTL-Index
        hinzu. Fehler werden geloggt, aber nie geworfen (darf Requests nie stören).
        """
        try:
            entry = dict(doc)
            entry["created_at"] = datetime.now(timezone.utc)
            self.metrics.insert_one(entry)
        except Exception as e:
            logger.error(f"Fehler beim Speichern der Metrik: {str(e)}")

    def get_documents(self, hours: int = 24) -> List[Dict[str, Any]]:
        """Lädt alle Metrik-Dokumente der letzten `hours` Stunden."""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            cursor = self.metrics.find({"created_at": {"$gte": cutoff}})
            return list(cursor)
        except Exception as e:
            logger.error(f"Fehler beim Laden der Metriken: {str(e)}")
            return []

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Liefert die letzten `limit` Requests in der vom Template erwarteten Form."""
        try:
            cursor = self.metrics.find().sort("created_at", DESCENDING).limit(limit)
            return [map_recent_entry(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Fehler beim Laden der letzten Requests: {str(e)}")
            return []

    def get_stats(self, hours: int = 24, recent_limit: int = 10) -> Dict[str, Any]:
        """Lädt Dokumente und berechnet die aggregierten Dashboard-Kennzahlen."""
        stats = compute_stats(self.get_documents(hours=hours))
        stats["recent_requests"] = self.get_recent(limit=recent_limit)
        return stats
