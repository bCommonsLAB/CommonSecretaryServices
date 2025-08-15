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

### Anwendungsbeispiele (API)

- Aktivierung: In `config/config.yaml` `generic_worker.active: true` setzen. Der Worker startet dann mit der App.

- PDF einreihen (Einzeljob):

```json
POST /api/jobs
{
  "job_type": "pdf",
  "parameters": {
    "url": "https://example.com/document.pdf",
    "extraction_method": "native",
    "use_cache": true,
    "extra": { "include_images": true }
  }
}
```

- Session einreihen (Einzeljob):

```json
POST /api/jobs
{
  "job_type": "session",
  "parameters": {
    "event": "FOSDEM 2025",
    "session": "Forked Communities: Project Re-licensing and Community Impact",
    "url": "https://fosdem.org/2025/schedule/event/...",
    "filename": "Forked-Communities-Project-Relicensing-and-Community-Impact.md",
    "track": "Main-Track-Janson-7",
    "day": "Saturday",
    "starttime": "17:00",
    "endtime": "17:50",
    "speakers": ["Dawn M Foster", "Brian Proffitt", "Stephen  Walli", "Ben Ford"],
    "attachments_url": "https://fosdem.org/.../slides/.../FOSDEM_Fo_HyZR9km.pdf",
    "source_language": "en",
    "target_language": "de",
    "use_cache": true,
    "extra": { "create_archive": true, "template": "Session" }
  }
}
```

- Batch einreihen:

```json
POST /api/jobs/batch
{
  "batch_name": "import_batch",
  "jobs": [
    { "job_type": "pdf", "parameters": { "url": "https://example.com/a.pdf", "extraction_method": "native" } },
    { "job_type": "session", "parameters": { "event": "FOSDEM 2025", "session": "...", "url": "https://fosdem.org/...", "target_language": "de" } }
  ]
}
```

- Status/Ergebnis abrufen:
  - `GET /api/jobs/{job_id}` (liefert den Job, inkl. `status`, `progress`, `results`)
  - `GET /api/batch/{batch_id}`
  - Archiv‑Download (wenn vorhanden): `GET /api/jobs/{job_id}/download-archive`

- Hinweise zu Ergebnissen:
  - PDF: `results.page_texts` enthält API‑URLs (`/api/pdf/text-content/<path>`) auf die extrahierten Seiten‑Texte; `results.asset_dir` enthält das Arbeitsverzeichnis.
  - Session: `results.markdown_file` verweist auf erzeugte Markdown‑Datei im `sessions/`‑Baum; optionales ZIP im Archiv‑Download.


