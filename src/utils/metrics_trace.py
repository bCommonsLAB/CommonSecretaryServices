"""
Diagnose-Logs für Request-Metriken und Webhook-Verschachtelung.

Kein Verhaltenswechsel: nur Logging mit Prefix [METRICS-TRACE], damit sich
HTTP-Eingang, 202-Verwerfen, Worker-Slots und Tracker-Abschluss im Log
filtern lassen. Dient der Klärung, ob Folgeaufrufe Flask erreichen.

Wichtig: Ausgabe über ProcessingLogger (get_logger), nicht über stdlib
logging.getLogger. Die Konsole hängt nur an processing_service.*.
"""

from typing import Any, Dict, List, Optional, TYPE_CHECKING
import threading

if TYPE_CHECKING:
    from src.utils.logger import ProcessingLogger

# Fester Prefix. Damit lassen sich die Zeilen in der Logdatei greppen.
_TRACE_PREFIX = "[METRICS-TRACE]"

# App-Logger (ProcessingLogger), nicht stdlib getLogger: sonst landet die
# Zeile nirgendwo, weil die Konsole nur processing_service.* bedient.
_trace_logger: Optional["ProcessingLogger"] = None


def _get_trace_logger() -> "ProcessingLogger":
    """Lazy: vermeidet Import-Zyklen beim Modulstart."""
    global _trace_logger
    if _trace_logger is None:
        from src.utils.logger import get_logger
        _trace_logger = get_logger(
            process_id="metrics-trace",
            processor_name="MetricsTrace",
        )
    return _trace_logger


def reset_metrics_trace_logger() -> None:
    """Nur für Tests: Lazy-Logger zurücksetzen, damit Mocks greifen."""
    global _trace_logger
    _trace_logger = None


def log_metrics_event(event: str, **fields: Any) -> None:
    """
    Schreibt eine Diagnosezeile. Fehler werden verschluckt, damit Metrik-
    Tracing nie einen Request stört.
    """
    try:
        parts: List[str] = [f"{k}={_fmt(v)}" for k, v in fields.items()]
        extra = " ".join(parts)
        message = f"{_TRACE_PREFIX} {event} {extra}".strip()
        # Eine Message ohne kwargs: Prefix bleibt grep-fähig, kein Args-Suffix.
        _get_trace_logger().info(message)
    except Exception:
        pass


def current_thread_name() -> str:
    """Name des aktuellen Threads (MainThread vs. Worker-Thread)."""
    return threading.current_thread().name


def running_job_ids() -> List[str]:
    """
    Job-IDs der gerade laufenden Worker. Leer, wenn Manager nicht da.

    Nur lesend. Startet keine Worker.
    """
    ids: List[str] = []
    try:
        from src.core.mongodb.secretary_worker_manager import snapshot_running_job_ids as sec_ids
        ids.extend(sec_ids())
    except Exception:
        pass
    try:
        from src.core.mongodb.worker_manager import snapshot_running_job_ids as sess_ids
        ids.extend(sess_ids())
    except Exception:
        pass
    return ids


def _fmt(value: Any) -> str:
    """Kompakte Darstellung ohne Whitespace-Explosion."""
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return _as_text(value)


def _as_text(value: object) -> str:
    """Stringify ohne Unknown-Typen im Aufrufer."""
    text = f"{value}"
    if len(text) > 180:
        return text[:177] + "..."
    return text


def tracker_resource_fields(tracker: Any) -> Dict[str, Any]:
    """Liest Token/Kosten/Modell aus einem PerformanceTracker, falls vorhanden."""
    empty: Dict[str, Any] = {"tokens": 0, "cost": 0.0, "models": []}
    if tracker is None:
        return empty
    try:
        resources: Optional[Dict[str, Any]] = tracker.measurements.get("resources")
        if not resources:
            return empty
        return {
            "tokens": int(resources.get("total_tokens", 0) or 0),
            "cost": float(resources.get("total_cost", 0.0) or 0.0),
            "models": list(resources.get("models_used") or []),
        }
    except Exception:
        return empty


def traced_webhook_post(
    job_id: str,
    url: str,
    *,
    json: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> Any:
    """
    requests.post für Webhooks mit Start/Ende/Fehler-Log.

    Verhalten identisch zu requests.post, plus [METRICS-TRACE] Zeilen.
    Host ohne Query/Token loggen.
    """
    import time
    from urllib.parse import urlparse
    import requests

    host = urlparse(url).netloc or "unknown"
    log_metrics_event(
        "webhook_post_start",
        job_id=job_id,
        host=host,
        timeout=timeout,
        thread=current_thread_name(),
        running_jobs=running_job_ids(),
    )
    started = time.time()
    try:
        resp = requests.post(url=url, json=json, headers=headers, timeout=timeout)
        log_metrics_event(
            "webhook_post_end",
            job_id=job_id,
            host=host,
            status_code=getattr(resp, "status_code", None),
            duration_ms=int((time.time() - started) * 1000),
            thread=current_thread_name(),
        )
        return resp
    except Exception as exc:
        log_metrics_event(
            "webhook_post_error",
            job_id=job_id,
            host=host,
            error=type(exc).__name__,
            duration_ms=int((time.time() - started) * 1000),
            thread=current_thread_name(),
        )
        raise
