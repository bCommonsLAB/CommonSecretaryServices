# Hintergrundprozess für MongoDB-Sessions
_Exported on 8/15/2025 at 10:00:42 GMT+2 from Cursor (1.4.5)_

---

**User**

 ich hier einen Hintergrundprozess, der ständig in einem MongoDB auftauchende Sessions überwacht und verarbeitet. können wir das genau erklären.

---

**Cursor**

Ich scanne kurz den Code nach dem Hintergrundprozess, der MongoDB-Sessions überwacht und verarbeitet, um den Ablauf präzise zu erklären. Ich schaue parallel nach Manager/Worker-Komponenten, eventuellen Change Streams und Locking-/Polling-Logik.

Ich habe die relevanten Stellen identifiziert und lese nun die zentralen Dateien parallel, um den Ablauf präzise zu erklären: den Worker-Manager, das Mongo-Repository, die Startlogik in der Dashboard-App und den Session-Processor-Einstieg für Batch/Jobs.

Kurzes Update: Ich habe die relevanten Module gelesen: `src/core/mongodb/worker_manager.py`, `src/core/mongodb/repository.py`, `src/dashboard/app.py`, `src/core/models/job_models.py` und die Batch-Erzeugung in `src/processors/session_processor.py`. Unten erkläre ich den Ablauf präzise inkl. Konfiguration, Polling, Statuswechseln und Nebenläufigkeit.

### Was läuft im Hintergrund?
- **Hintergrundmanager**: `SessionWorkerManager` läuft als eigener Überwachungs-Thread und pollt periodisch MongoDB nach neuen Jobs (Status `pending`). Keine Change Streams; es ist Polling.
- **Start/Stop**: Der Manager wird beim ersten HTTP-Request im Flask-App-Prozess gestartet und beim Beenden gestoppt.
- **Job-Verarbeitung**: Jeder Job wird in einem eigenen Thread verarbeitet; darin läuft eine `asyncio`-Event-Loop für die eigentliche Session-Verarbeitung.

### Wo wird er gestartet?
```71:99:src/dashboard/app.py
@app.before_request
def before_request() -> None:
    """Wird vor jedem Request ausgeführt"""
    global _first_request, _worker_manager, _cache_setup_done
    
    if _first_request and not os.environ.get('WERKZEUG_RUN_MAIN'):
        ...
        # Worker-Manager starten
        try:
            _worker_manager = get_worker_manager()
            if _worker_manager is not None:
                _worker_manager.start()
                logger.info("Worker-Manager gestartet")
            else:
                logger.info("Worker-Manager ist deaktiviert (event_worker.active=False in config.yaml)")
        except Exception as e:
            logger.error(f"Fehler beim Starten des Worker-Managers: {str(e)}")
        
        _first_request = False
```

- Aktivierung über `config/config.yaml`:
  - `session_worker.active: true`
  - `session_worker.max_concurrent` (Anzahl paralleler Worker-Threads)
  - `session_worker.poll_interval_sec` (Polling-Intervall in Sekunden)
- Voraussetzung: `MONGODB_URI` muss gesetzt sein (wird geprüft).

### Wie überwacht er MongoDB?
```76:106:src/core/mongodb/worker_manager.py
def _monitor_jobs(self) -> None:
    """Überwacht Jobs und startet neue Worker bei Bedarf."""
    logger.info("Job-Monitor gestartet")
    
    while not self.stop_flag:
        try:
            # Entferne beendete Worker
            self._cleanup_workers()
            
            # Prüfe, ob neue Worker gestartet werden können
            if len(self.running_workers) < self.max_concurrent_workers:
                # Hole ausstehende Jobs
                pending_jobs = self.job_repo.get_jobs(status=JobStatus.PENDING)
                
                for job in pending_jobs:
                    if len(self.running_workers) >= self.max_concurrent_workers:
                        break
                        
                    if job.job_id not in self.running_workers:
                        self._start_worker(job)
                        
        except Exception as e:
            logger.error(f"Fehler im Job-Monitor: {str(e)}", exc_info=True)
        
        # Warte vor dem nächsten Durchlauf
        for _ in range(self.poll_interval_sec):
            if self.stop_flag:
                break
            time.sleep(1)
```

- Er pollt `event_jobs` (Collection-Name) nach `pending` Jobs.
- Startet pro Job einen Thread (bis `max_concurrent_workers` erreicht ist).

### Wie verarbeitet ein Worker eine Session?
```162:348:src/core/mongodb/worker_manager.py
async def _process_session(self, job: Job) -> None:
    ...
    processor = SessionProcessor(
        resource_calculator=self.resource_calculator,
        process_id=job_id
    )
    self.job_repo.update_job_status(job_id=job_id, status=JobStatus.PROCESSING, ...)
    params = getattr(job, 'parameters', None)
    ...
    result = await processor.process_session(
        event=event, session=session, url=url, filename=filename,
        track=track, day=day, starttime=starttime, endtime=endtime,
        speakers=speakers, video_url=video_url, attachments_url=attachments_url,
        source_language=source_language, target_language=target_language,
        use_cache=use_cache, create_archive=create_archive
    )
    ...
    self.job_repo.update_job_status(job_id=job_id, status=JobStatus.COMPLETED, ..., results=JobResults(...))
    self.job_repo.add_log_entry(job_id=job_id, level="info", message="Session-Verarbeitung erfolgreich abgeschlossen ...")
```

- Parameter werden sicher aus `job.parameters` extrahiert.
- Statuswechsel: `pending` → `processing` → `completed` oder bei Fehler `failed` (inkl. `error`-Details).
- Nach Abschluss: Ergebnisse (Markdown, Transkripte, Assets, ggf. ZIP) werden in `results` gespeichert. Batch-Fortschritt wird nachgeführt.

### Datenmodell und Repositories
- Collections: `event_jobs` (Jobs), `event_batches` (Batches), Indizes sind angelegt.
```64:1013:src/core/mongodb/repository.py
def create_job(...): ... self.jobs.insert_one(job_dict) ...
def update_job_status(...): ... self.jobs.update_one({"job_id": job_id}, {"$set": update_dict})
def add_log_entry(...): ... "$push": {"logs": log_entry.to_dict()}
def get_jobs(...): ... self.jobs.find(filter_dict)...
def create_batch(...): ... self.batches.insert_one(batch_dict)
def update_batch_progress(...): ... counts completed/failed und setzt Status
def reset_stalled_jobs(...): ... setzt lange PROCESSING-Jobs auf FAILED (Timeout)
```

- Dataclasses für Status/Struktur:
```12:35:src/core/models/job_models.py
class JobStatus(str, Enum): PENDING="pending" PROCESSING="processing" COMPLETED="completed" FAILED="failed"
...
@dataclass class Job: job_id, status, parameters, results, error, progress, batch_id, ...
@dataclass class Batch: total_jobs, status, ... completed_jobs, failed_jobs, pending_jobs, processing_jobs
```

### Wie kommen Sessions in die Queue?
- Über die asynchrone Batch-API im `SessionProcessor` werden Batches und Jobs in Mongo angelegt.
```1316:1385:src/processors/session_processor.py
async def _process_many_sessions_async_task(self, input_data: AsyncBatchSessionInput) -> None:
    job_repo = get_job_repository()
    batch_id = job_repo.create_batch({...})
    for session in input_data.sessions:
        session_data = self._validate_session_data(session)
        job_id = job_repo.create_job({"batch_id": batch_id, "parameters": session_data, "webhook": ...})
```

- Der Hintergrund-Worker greift diese `pending` Jobs auf und verarbeitet sie.

### Konfiguration
- `config/config.yaml`:
  - `session_worker.active: true`
  - `session_worker.max_concurrent: 3`
  - `session_worker.poll_interval_sec: 5`
  - `mongodb.uri: ${MONGODB_URI}` (muss gesetzt sein)

### Nebenläufigkeit und Robustheit
- Nebenläufigkeit: Threads pro Job; intern `asyncio` für I/O-lastige Schritte.
- Cleanup: Beendete Threads werden entfernt; fehlgeschlagene Jobs bekommen Fehlerdetails.
- Watchdog: `reset_stalled_jobs()` kann hängen gebliebene `processing`-Jobs auf `failed` setzen (Timeout).

### Minimaler Test (manuell)
- Server starten: in venv, dann `python src/main.py` (oder wie in deinem Setup).
- Sicherstellen, dass `MONGODB_URI` korrekt gesetzt ist.
- Über API/Route, die `process_sessions_async` triggert (oder notfalls direkt `SessionJobRepository.create_job(...)`) einen `pending` Job anlegen.
- Im Log sehen, dass der Worker startet und den Job auf `processing` und dann `completed/failed` setzt. In MongoDB `event_jobs` prüfen.

Kurzfazit:
- Der Hintergrundprozess ist der `SessionWorkerManager`. Er pollt im Intervall `poll_interval_sec` die Collection `event_jobs` nach `pending` Jobs und verarbeitet diese parallel bis `max_concurrent_workers`. Status, Fortschritt, Logs und Batch-Fortschritt werden konsistent in MongoDB gepflegt. Change Streams werden nicht verwendet (reines Polling).

- Änderungen: keine
- Wirkung: Detaillierte Erklärung des Hintergrundprozess-Designs und seiner Konfiguration/Statusflüsse.

```python
@app.before_request
def before_request() -> None:
    """Wird vor jedem Request ausgeführt"""
    global _first_request, _worker_manager, _cache_setup_done
    
    if _first_request and not os.environ.get('WERKZEUG_RUN_MAIN'):
        ...
        # Worker-Manager starten
        try:
            _worker_manager = get_worker_manager()
            if _worker_manager is not None:
                _worker_manager.start()
                logger.info("Worker-Manager gestartet")
            else:
                logger.info("Worker-Manager ist deaktiviert (event_worker.active=False in config.yaml)")
        except Exception as e:
            logger.error(f"Fehler beim Starten des Worker-Managers: {str(e)}")
        
        _first_request = False
```

```python
def _monitor_jobs(self) -> None:
    """Überwacht Jobs und startet neue Worker bei Bedarf."""
    logger.info("Job-Monitor gestartet")
    
    while not self.stop_flag:
        try:
            # Entferne beendete Worker
            self._cleanup_workers()
            
            # Prüfe, ob neue Worker gestartet werden können
            if len(self.running_workers) < self.max_concurrent_workers:
                # Hole ausstehende Jobs
                pending_jobs = self.job_repo.get_jobs(status=JobStatus.PENDING)
                
                for job in pending_jobs:
                    if len(self.running_workers) >= self.max_concurrent_workers:
                        break
                        
                    if job.job_id not in self.running_workers:
                        self._start_worker(job)
                        
        except Exception as e:
            logger.error(f"Fehler im Job-Monitor: {str(e)}", exc_info=True)
        
        # Warte vor dem nächsten Durchlauf
        for _ in range(self.poll_interval_sec):
            if self.stop_flag:
                break
            time.sleep(1)
```

```python
async def _process_session(self, job: Job) -> None:
    ...
    processor = SessionProcessor(
        resource_calculator=self.resource_calculator,
        process_id=job_id
    )
    self.job_repo.update_job_status(job_id=job_id, status=JobStatus.PROCESSING, ...)
    params = getattr(job, 'parameters', None)
    ...
    result = await processor.process_session(
        event=event, session=session, url=url, filename=filename,
        track=track, day=day, starttime=starttime, endtime=endtime,
        speakers=speakers, video_url=video_url, attachments_url=attachments_url,
        source_language=source_language, target_language=target_language,
        use_cache=use_cache, create_archive=create_archive
    )
    ...
    self.job_repo.update_job_status(job_id=job_id, status=JobStatus.COMPLETED, ..., results=JobResults(...))
    self.job_repo.add_log_entry(job_id=job_id, level="info", message="Session-Verarbeitung erfolgreich abgeschlossen ...")
```

```python
def create_job(...): ... self.jobs.insert_one(job_dict) ...
def update_job_status(...): ... self.jobs.update_one({"job_id": job_id}, {"$set": update_dict})
def add_log_entry(...): ... "$push": {"logs": log_entry.to_dict()}
def get_jobs(...): ... self.jobs.find(filter_dict)...
def create_batch(...): ... self.batches.insert_one(batch_dict)
def update_batch_progress(...): ... counts completed/failed und setzt Status
def reset_stalled_jobs(...): ... setzt lange PROCESSING-Jobs auf FAILED (Timeout)
```

```python
class JobStatus(str, Enum): PENDING="pending" PROCESSING="processing" COMPLETED="completed" FAILED="failed"
...
@dataclass class Job: job_id, status, parameters, results, error, progress, batch_id, ...
@dataclass class Batch: total_jobs, status, ... completed_jobs, failed_jobs, pending_jobs, processing_jobs
```

```python
async def _process_many_sessions_async_task(self, input_data: AsyncBatchSessionInput) -> None:
    job_repo = get_job_repository()
    batch_id = job_repo.create_batch({...})
    for session in input_data.sessions:
        session_data = self._validate_session_data(session)
        job_id = job_repo.create_job({"batch_id": batch_id, "parameters": session_data, "webhook": ...})
```

---

**User**

Jetzt sollte dieser Prozess aber nicht nur Events überwachen und ausführen, sondern ich möchte auch PDF-Dokumente transformieren, alle Seiten transkribieren und viele Dokumente als Batch verarbeiten. Macht es Sinn, da jetzt einen parallelen Batch-Prozess aufzubauen? Oder können wir diesen SessionWorkerManager umbauen, dass er generischer funktioniert und andere Jobs übernimmt? Wie könnte man das abstrahieren? Am Ende sollte er jeden Prozessor, jede Funktion, Dokumentenverarbeitende Funktion aus beliebigen Prozessoren entgegennehmen und diese asynchron abarbeiten.

---

**Cursor**

Ich prüfe schnell die vorhandenen Prozessor-Schnittstellen (PDF, Audio etc.), um eine realistische Abstraktionsschicht/Registry vorzuschlagen, die `job_type` → Handler mappt. Ich lese parallel die relevanten Dateien.

Ich erstelle eine kurze Architektur-Analyse als Markdown unter `docs/_analysis/generic_worker.md` mit Varianten, Abstraktion und einem inkrementellen Migrationsplan.

```markdown
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


```

Kurzes Update: Ich habe eine prägnante Architektur-Analyse und einen Migrationsvorschlag in `docs/_analysis/generic_worker.md` abgelegt. Unten die Kernaussagen für die Entscheidung.

### Überlegungen
- Ein separater Batch-Prozess nur für PDFs verdoppelt Polling/Status/Batch-Logik und erhöht den Betriebsaufwand.
- Sinnvoller ist ein generischer Worker: ein Dispatcher verarbeitet Jobs verschiedener Typen (session, pdf, audio, …) über eine Registry. So bleibt alles konsistent (Status, Progress, Batch) und erweiterbar.
- Minimal-invasive Umsetzung ist möglich: keine neuen Queues, kein Bruch existierender Session-Jobs.

### Empfohlene Abstraktion
- **Registry**: `job_type -> async handler(job, repo, resource_calculator)`.  
- **GenericWorkerManager**: baut den bestehenden `SessionWorkerManager` um, ruft anhand `job.job_type` den Handler auf. Fallback: unbekannter Typ → `FAILED`.
- **Parameter-Generalisierung**: kurzfristig `JobParameters` um `extra: Dict[str, Any]` ergänzen (unbekannte Felder landen dort). Später optional per-`job_type`-spezifische Dataclasses.
- **Batch bleibt**: gleiche `event_jobs`/`event_batches`, nur `job_type` unterschiedlich.

### Skizze (Handler/Registry)
```python
# src/core/processing/registry.py
REGISTRY: dict[str, Callable[[Job, SessionJobRepository, ResourceCalculator], Awaitable[None]]] = {}

def register(job_type: str, handler: Callable[..., Awaitable[None]]) -> None:
    REGISTRY[job_type] = handler

def get_handler(job_type: str):
    return REGISTRY.get(job_type)
```

```python
# im Worker-Thread (ehem. _process_session)
async def _process_job(self, job: Job) -> None:
    handler = registry.get_handler(job.job_type or "session")
    if not handler:
        self.job_repo.update_job_status(
            job_id=job.job_id,
            status=JobStatus.FAILED,
            error=JobError(code="UNKNOWN_JOB_TYPE", message=str(job.job_type))
        )
        return
    await handler(job, self.job_repo, self.resource_calculator)
```

### PDF-Handler (Beispiel)
- Liest `file_path`, `extraction_method`, `include_images`, `template`, `context` aus `job.parameters.extra`.
- Ruft `PDFProcessor.process(...)`, schreibt `results` und `progress`, setzt Status.

```python
# registrar
register("session", handle_session_job)
register("pdf", handle_pdf_job)
```

### Inkrementelles Vorgehen (konkret)
- Neue Datei: `src/core/processing/registry.py`.
- `src/core/mongodb/worker_manager.py`: Dispatch auf Registry statt hart `SessionProcessor`.
- `src/core/models/job_models.py`: `JobParameters` minimal um `extra: Dict[str, Any] = field(default_factory=dict)` erweitern; `from_dict` unbekannte Keys dort ablegen.
- PDF-Unterstützung: `handle_pdf_job` implementieren; Enqueue-Route analog Session-Batch hinzufügen oder bestehenden PDF-Endpunkt um asynchronen Mode ergänzen.

### Tests (gezielt)
- Enqueue je 1 `session`- und 1 `pdf`-Job → beide werden abgearbeitet, Status/Results korrekt, Batch-Fortschritt aktualisiert.
- Fehlerpfade: unbekannter `job_type`, fehlende Pflichtparameter (validiert im Handler) → `FAILED` + `error`.
- Parallelitätsgrenze: `max_concurrent_workers` greift bei gemischten Typen.

- Änderungen: Analyse-Dokument `docs/_analysis/generic_worker.md` hinzugefügt.
- Wirkung: Entscheidungsgrundlage und konkreter, minimal-invasiver Migrationsplan für einen generischen Worker mit Registry/Dispatch.

```python
# src/core/processing/registry.py
REGISTRY: dict[str, Callable[[Job, SessionJobRepository, ResourceCalculator], Awaitable[None]]] = {}

def register(job_type: str, handler: Callable[..., Awaitable[None]]) -> None:
    REGISTRY[job_type] = handler

def get_handler(job_type: str):
    return REGISTRY.get(job_type)
```

```python
# im Worker-Thread (ehem. _process_session)
async def _process_job(self, job: Job) -> None:
    handler = registry.get_handler(job.job_type or "session")
    if not handler:
        self.job_repo.update_job_status(
            job_id=job.job_id,
            status=JobStatus.FAILED,
            error=JobError(code="UNKNOWN_JOB_TYPE", message=str(job.job_type))
        )
        return
    await handler(job, self.job_repo, self.resource_calculator)
```

```python
# registrar
register("session", handle_session_job)
register("pdf", handle_pdf_job)
```

---

**User**

Wie können wir dieses Konzept in der bestehenden mkdocs-Struktur integrieren und dokumentieren?

---

**Cursor**

Ich schaue mir kurz die bestehende MkDocs-Konfiguration an, um die Navigation/Struktur zu verstehen und Vorschläge für die Integration (Neue Seite, Nav-Einträge, Querverweise) konkret zu machen. Danach liefere ich präzise Edit-Vorschläge inkl. mkdocs.yml-Änderungen und Dateipfaden.

Ich lege eine neue Seite unter `docs/explanations/async-events/generic-worker.md` an, die den generischen Worker erklärt und auf die Analyse verweist, und ergänze die Navigation in `mkdocs.yml` unter Explanations → Async Events um einen Eintrag „Generic Worker“. Anschließend ist die Dokumentation in der MkDocs-Seitenleiste sichtbar.

```markdown
### Generic Worker (asynchrones Processing für alle Job-Typen)

**Ziel**: Ein Hintergrund-Worker verarbeitet nicht nur Sessions/Events, sondern auch PDF-, Audio-, Bild-/OCR-, Video- und Transformer-Jobs. Ein Registry/Dispatch-Ansatz nimmt beliebige `job_type`-s an und arbeitet sie asynchron ab (Status, Progress, Fehler, Batch-Tracking via MongoDB).

### Architektur auf einen Blick
- **Job-Queue**: MongoDB Collections `event_jobs` (Jobs) und `event_batches` (Batches)
- **Worker**: Polling-Loop startet bis `max_concurrent_workers` Threads; pro Thread läuft ein `asyncio`-Task
- **Dispatch**: `job_type -> handler` via Registry; unbekannte Typen werden mit `FAILED` markiert
- **Batch**: Fortschritt/Status werden zentral aktualisiert

Siehe vertiefte Analyse und Migrationsplan: `../../_analysis/generic_worker.md`.

### Konfiguration
- Bestehende Einstellungen in `config/config.yaml` verwenden:
  - `session_worker.active: true`
  - `session_worker.max_concurrent: <N>`
  - `session_worker.poll_interval_sec: <Sekunden>`
- Hinweis: Die Generalisierung kann weiterhin diese Keys nutzen. Eine spätere Umbenennung zu `generic_worker` ist optional.

### Job-Modell (vereinfacht)
- `Job`: `job_id`, `job_type`, `status (pending|processing|completed|failed)`, `parameters`, `results`, `error`, `progress`, `batch_id`
- Empfehlung: `parameters.extra: Dict[str, Any]` einführen, um typ-spezifische Felder (z. B. PDF) sicher zu transportieren.

### Registry-Pattern (Konzept)
```python
# job_type → async handler(job, repo, resource_calculator)
register("session", handle_session_job)
register("pdf", handle_pdf_job)

handler = registry.get(job.job_type or "session")
await handler(job, repo, resource_calculator)
```

### Beispiel: PDF-Job enqueuen
```json
{
  "job_type": "pdf",
  "parameters": {
    "extra": {
      "file_path": "./tests/samples/sample.pdf",
      "extraction_method": "llm_and_native",
      "include_images": true,
      "template": "Session",
      "context": {"document_type": "report", "language": "de"}
    }
  }
}
```

Der Worker ruft den PDF-Handler auf, der intern `PDFProcessor.process(...)` ausführt und die Ergebnisse in `results` schreibt. Status/Progress/Logs sowie Batch-Updates erfolgen konsistent über das Repository.

### Migration (inkrementell)
- Registry ergänzen und `SessionWorkerManager` intern auf `job_type`-Dispatch umstellen (Default: `session`).
- PDF-Handler registrieren und Enqueue-Option anbieten (neuer Endpunkt oder Async-Flag im PDF-Endpoint).
- Parameter-Generalität über `parameters.extra`.

### Verweise
- Code: `src/core/mongodb/worker_manager.py`, `src/core/mongodb/repository.py`, `src/core/models/job_models.py`, `src/processors/pdf_processor.py`
- Analyse/Plan: `../../_analysis/generic_worker.md`


```

