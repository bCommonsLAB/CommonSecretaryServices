## Ziel

Ein generischer Hintergrund-Worker soll nicht nur Sessions/Events, sondern auch PDF-, Audio-, Bild-/OCR-, Video- und Transformationsaufgaben asynchron verarbeiten. Ein einziges, erweiterbares System soll beliebige Prozessoren bedienen (Batch-fähig), Status/Progress/Errors konsistent tracken und Webhooks optional unterstützen.

## Ist-Zustand (kurz)

- `SessionWorkerManager` pollt `event_jobs` (MongoDB) zyklisch nach `pending` und startet Threads, die pro Job `SessionProcessor.process_session(...)` ausführen.
- Statuswechsel: `pending → processing → completed/failed`, Logs und Batch-Fortschritt via `SessionJobRepository`.
- `Job` Dataclass hat bereits `job_type` (String), aber `parameters` ist auf session-spezifische Felder limitiert (`JobParameters`).

## Anforderungen an die Generalisierung

- Einheitlicher Job-Lebenszyklus für verschiedene Typen (`session`, `pdf`, `audio`, ...).
- Dispatching: `job_type → Handler/Processor` mit klarer Signatur und Fehler-/Progress-Reporting.
- Batch-Verarbeitung über dieselben Batch-Modelle (minimale Änderungen), per-Type Einstellungen für Parallelität sinnvoll.
- Rückwärtskompatibilität: Bestehende Session-Jobs funktionieren weiter.

## Varianten

1) Separater Prozess/Manager je Domäne (z. B. `DocumentWorkerManager` für PDFs)
- Vorteile: Isolation, per-Domäne eigene Skalierung/Abhängigkeiten; geringes Risiko für Regressionen.
- Nachteile: Code-Duplizierung (Polling, Status, Logging), mehr Betriebsaufwand, mehrere Queues/Collections.

2) Ein generischer Worker mit Registry/Dispatch (empfohlen)
- Idee: Eine `ProcessorRegistry` mappt `job_type` → `JobHandler`. Der bestehende Manager pollt weiterhin, nimmt aber alle `pending` Jobs und ruft den passenden Handler auf.
- Vorteile: Einfache Erweiterbarkeit, einheitliches Monitoring/Batching, minimale Infrastrukturänderung.
- Nachteile: Kleiner Refactor nötig (Parameter/Job-Modell), per-Type QoS muss bedacht werden.

3) Supervisor + per-Type Sub-Worker (hybrid)
- Ein Supervisor spawnt Sub-Worker pro Typ mit eigener Parallelität (Work-Stealing möglich).
- Vorteile: Gute Kontrolle/Isolation, trotzdem einheitliche Steuerung.
- Nachteile: Komplexer als (2), eher für hohe Last nötig.

## Empfohlene Abstraktion (Variante 2)

1) Job-Modell erweitern (minimal-invasiv):
- `JobParameters` um `extra: Dict[str, Any]` erweitern, das unbekannte Felder aus `parameters` aufnimmt (in `from_dict`) und in `to_dict` wieder ausgibt. So können PDF-spezifische Parameter (z. B. `file_path`, `extraction_method`, `include_images`, `template`, `context`) ohne Schema-Bruch transportiert werden.
- Optional später: per-`job_type`-spezifische Parameter-Dataclasses.

2) Processor-Registry einführen:
- Ort: `src/core/processing/registry.py` (neu).
- API: `register(job_type: str, handler: Callable[[Job, SessionJobRepository, ResourceCalculator], Awaitable[None]]))` und `get(job_type) → handler`.
- Handlers implementieren Status-/Progress-Updates per `SessionJobRepository` wie heute in `SessionWorkerManager._process_session`.

3) `SessionWorkerManager` → `GenericWorkerManager` umbauen (schrittweise):
- Behalte Polling, Thread-Start und Cleanup.
- Im Worker-Thread: Statt fest `SessionProcessor` zu nutzen, `job.job_type` lesen, Handler aus Registry holen, aufrufen.
- Fallback: unbekannter `job_type` → `FAILED` mit Fehlercode `UNKNOWN_JOB_TYPE`.
- Optional: per-Type Parallelitäts-Limits (z. B. `max_concurrent_per_type` in Config).

4) PDF-Handler (Beispiel):
- Liest `file_path`, `extraction_method`, `template`, `context`, `include_images` aus `job.parameters.extra` (bzw. generisch `parameters`).
- Nutzt `PDFProcessor.process(...)` und schreibt Ergebnis nach `results`.

5) Batchs beibehalten:
- Batches funktionieren unverändert; optional `batch.job_type` setzen, aber nicht zwingend.

## Pseudocode-Entwurf (vereinfachter Kern)

```python
# registry.py
REGISTRY: dict[str, Callable[..., Awaitable[None]]] = {}

def register(job_type: str, handler: Callable[[Job, SessionJobRepository, ResourceCalculator], Awaitable[None]]):
    REGISTRY[job_type] = handler

def get_handler(job_type: str):
    return REGISTRY.get(job_type)

# worker_manager (Worker-Thread)
async def _process_job(self, job: Job):
    handler = registry.get_handler(job.job_type or "session")
    if not handler:
        self.job_repo.update_job_status(job.job_id, JobStatus.FAILED, error=JobError(code="UNKNOWN_JOB_TYPE", message=f"{job.job_type}"))
        return
    await handler(job, self.job_repo, self.resource_calculator)

# registrierung
register("session", handle_session_job)
register("pdf", handle_pdf_job)
```

## Inkrementeller Migrationsplan

1) Minimal-Refactor (keine API-Änderungen):
- Registry hinzufügen, `SessionWorkerManager` intern auf `job_type`-Dispatch umbauen.
- `session`-Handler implementieren und als Default registrieren.

2) PDF-Unterstützung:
- `pdf`-Handler implementieren (ruft `PDFProcessor.process(...)`).
- Endpunkt/Use-Case zum Enqueue von PDF-Jobs oder Batch (analog `process_sessions_async`).

3) Parameter-Generalität:
- `JobParameters` um `extra: Dict[str, Any]` erweitern und `from_dict` so anpassen, dass unbekannte Keys dort landen.
- Später optional per-Type Parameter-Dataclasses + Validierung.

4) Konfiguration/Skalierung:
- `session_worker` → `generic_worker` benennen (optional) und `max_concurrent_per_type` unterstützen.
- Optional: Webhooks pro Job vereinheitlichen (Dataclass im Job-Modell aufnehmen).

## Risiken und Tests

- Risiko: Verlust unbekannter Parameter im aktuellen `JobParameters`. → Mit `extra` abfangen.
- Tests: 
  - Enqueue + Verarbeitung `session` und `pdf` Jobs in einem Batch; 
  - Parallelitätsgrenzen; 
  - Fehlerpfade (unbekannter `job_type`, fehlende Parameter), 
  - Batch-Fortschritt und Status-Updates.

## Empfehlung

Variante (2) mit Registry/Dispatch zuerst implementieren. Sie ist die kleinste, saubere Generalisierung und lässt sich später zu (3) ausbauen, falls per-Type Supervisor nötig wird.


