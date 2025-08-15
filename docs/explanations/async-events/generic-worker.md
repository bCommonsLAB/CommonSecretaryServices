### Generischer Async-Worker (Übersicht)

Dieser Worker verarbeitet unterschiedliche Job-Typen (z. B. `session`, `pdf`) asynchron, nutzt MongoDB als Queue (`event_jobs`, `event_batches`) und liefert konsistente Status‑, Progress‑ und Fehlerdaten.

- **Ziel**: Ein System für alle Prozessoren (PDF, Audio, Video, OCR, Transformer, …)
- **Mechanik**: Polling, Threads für Nebenläufigkeit, `asyncio` im Worker, Batch‑Tracking
- **Erweiterbarkeit**: `job_type → handler` via Registry

#### Architektur auf einen Blick

- Ein `GenericWorkerManager` pollt `pending` Jobs und startet Worker‑Threads (bis `max_concurrent_workers`).
- Pro Job sucht er den passenden Handler anhand `job_type` und führt ihn aus (Statuswechsel: `pending → processing → completed/failed`).
- Ergebnisse und Logs werden im `SessionJobRepository` gepflegt, Batches aggregieren Fortschritt.

#### Registry/Dispatch (Beispiel)

```python
# registry.py
REGISTRY: dict[str, Callable[[Job, SessionJobRepository, ResourceCalculator], Awaitable[None]]] = {}

def register(job_type: str, handler: Callable[..., Awaitable[None]]) -> None:
    REGISTRY[job_type] = handler

def get_handler(job_type: str):
    return REGISTRY.get(job_type)

# im Worker-Thread
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

#### PDF als Job‑Typ

- Parameter (z. B. `file_path`, `extraction_method`, `include_images`, `template`, `context`) werden im Job abgelegt und vom PDF‑Handler an `PDFProcessor.process(...)` übergeben.

#### Konfiguration

- `session_worker.*` wird zu `generic_worker.*` erweitert (optional pro Typ: `max_concurrent_per_type`).
- `MONGODB_URI` muss gesetzt sein.

#### Weiterführend

- Detaillierte Analyse und Migrationsplan: siehe `docs/_analysis/generic_worker.md`.


