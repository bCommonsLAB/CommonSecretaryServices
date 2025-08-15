### Secretary Job Worker – Konzept (Input/Output, Flows, Speicherung)

Ziel: Generischer, nebenläufiger Worker für unterschiedliche `job_type`s (z. B. `pdf`, `session`, `audio`, `imageocr`, `transformer`), mit einheitlichem Job‑Lebenszyklus, konsistenter Speicherung (MongoDB), optionalen Webhooks und klaren I/O‑Schemata.

#### Collections und Namenskonvention

- Collections (neu): `jobs`, `batches`
- Job‑Felder (Kern): `job_id`, `job_type`, `status`, `parameters`, `progress`, `results`, `error`, `created_at`, `updated_at`, `processing_started_at`, `completed_at`, `batch_id`, `user_id`, `access_control`, `logs`
- Batch‑Felder (Kern): `batch_id`, `status`, `total_jobs`, `completed_jobs`, `failed_jobs`, `pending_jobs`, `processing_jobs`, Timestamps

#### Lebenszyklus und Progress (Standard)

- Status: `pending → processing → completed/failed`
- Progress‑Schritte (Beispiel `pdf`):
  - `initializing` (0 %)
  - `downloading_or_opening` (5 %)
  - `converting_pptx_to_pdf` (optional)
  - `processing_pages:<i>/<n>` (10–90 %)
  - `postprocessing` (90–98 %)
  - `completed` (100 %)

#### Enqueue: Beispiel für PDF‑Transformation (Job‑Dokument)

```json
{
  "job_type": "pdf",
  "parameters": {
    "file_path": "C:/data/docs/report.pdf",  
    "url": null,                                 
    "extraction_method": "llm_and_native",     
    "include_images": true,                      
    "template": "Session",                     
    "context": {"document_type": "report", "language": "de"},
    "use_cache": true,
    "force_overwrite": false
  },
  "webhook": {
    "url": "https://example.local/webhook/jobs",
    "headers": {"Authorization": "Bearer <token>"},
    "include_markdown": true,
    "include_metadata": true
  },
  "user_id": "u-123"
}
```

Hinweise:
- Lokaldatei via `file_path` oder Remote‑Download via `url` (eines von beiden ausreichend).
- `extraction_method`: `native | ocr | both | preview | llm | llm_and_native | llm_and_ocr | preview_and_native`.
- `template` und `context` optional für nachgelagerte Transformationen.

#### Batch‑Enqueue (Beispiel)

```json
{
  "batch": {
    "batch_name": "pdf_import_2025_03",
    "jobs": [
      { "job_type": "pdf", "parameters": { "url": "https://example/doc1.pdf", "extraction_method": "native" } },
      { "job_type": "pdf", "parameters": { "file_path": "C:/docs/scan.pdf", "extraction_method": "llm_and_ocr", "include_images": true } }
    ]
  }
}
```

#### Response‑Muster (API)

- Enqueue (synchron): Sofortige Bestätigung mit IDs.

```json
{
  "status": "success",
  "request": {"processor": "job-enqueue", "timestamp": "...", "parameters": {"job_count": 2}},
  "process": {"id": "...", "main_processor": "SecretaryJobWorker", "llm_info": {"requests": []}},
  "data": {"job_ids": ["job-...", "job-..."], "batch_id": "batch-..."}
}
```

- Polling (Status/Ergebnis): `GET /api/jobs/{job_id}` liefert Job‑Dokument (inkl. `results`, `error`, `progress`).

#### Webhook‑Callback (Beispiel `completed`)

```json
{
  "job_id": "job-...",
  "job_type": "pdf",
  "status": "completed",
  "progress": {"step": "completed", "percent": 100, "message": "Verarbeitung abgeschlossen"},
  "results": {
    "markdown_file": "/api/pdf/text-content/cache/pdf/<hash>/.../page_001.txt",
    "markdown_content": null,
    "assets": ["/cache/pdf/<hash>/image_001.jpg"],
    "web_text": null,
    "video_transcript": null,
    "attachments_text": null,
    "attachments_url": null,
    "archive_data": "<base64-zip>",
    "archive_filename": "report_images_20250306_125636.zip",
    "structured_data": null,
    "target_dir": "C:/.../cache/pdf/<hash>/llm_and_native",
    "page_texts": ["/api/pdf/text-content/cache/pdf/<hash>/.../page_001.txt"],
    "asset_dir": "C:/.../cache/pdf/<hash>/llm_and_native"
  }
}
```

Hinweis: Pfade können als URLs aufbereitet werden (z. B. `/api/pdf/text-content/...`).

#### Dateiablage (konzeptionell)

- Arbeitsverzeichnis (temporär): `cache/pdf/<file_key>/<extraction_subdir>`
  - `image_###.jpg` (Hauptbilder)
  - `preview_###.jpg` (Vorschaubilder, optional)
  - `page_###.txt` (extrahierter Text/Markdown pro Seite)
  - `previews.zip` (optional)
- Persistente Verweise
  - URLs in `results.page_texts` zeigen auf API‑Routen, die Inhalte aus dem Dateisystem bereitstellen.

#### Fehler‑Muster

- `status: failed` und `error: { code, message, details }`
- Typische Fehlercodes `PROCESSING_TIMEOUT`, `DOWNLOAD_FAILED`, `UNSUPPORTED_FILE`, `UNKNOWN_JOB_TYPE`.

#### Handler‑Schnittstelle (Registry)

- `handler(job, repo, resource_calculator) -> Awaitable[None]`
- Verantwortlich für: Parameter lesen/validieren, Progress updaten, Processor aufrufen, `results` speichern, Logs schreiben, Fehler abfangen.

#### Session‑(Alt) Kompatibilität

- Alte `event_jobs`/`event_batches` unverändert. Für Migration kann ein `session`‑Handler definiert werden, der die bisherige Logik spiegelt, aber in `jobs`/`batches` läuft.

#### Abruf durch aufrufende Anwendungen (Mongo + Dateisystem)

- MongoDB/Status/Ergebnisse (heute vorhanden, Alt‑System):
  - `GET /api/event-job/jobs` (Filter nach `status`, `batch_id`, `user_id`)
  - `GET /api/event-job/jobs/{job_id}`
  - `GET /api/event-job/batches`
  - `GET /api/event-job/batches/{batch_id}`
  - ZIP‑Archiv: `GET /api/event-job/jobs/{job_id}/download-archive`

- Dateisystem‑Inhalte (heute vorhanden):
  - PDF‑Seiteninhalte (Textdateien aus Cache): `GET /api/pdf/text-content/<path:file_path>`
    - Sicherheit: Zugriff nur innerhalb `cache/`, nur `.txt`
  - In `results` liefern Prozessoren URLs/Verweise: `results.page_texts` (API‑URLs), `results.asset_dir`, `results.target_dir`, `results.images_archive_*`.

- Für den neuen Secretary Job Worker (Zielbild):
  - Neue Endpoints analog zu oben, aber auf `jobs`/`batches` (neue Collections) gemappt:
    - `POST /api/jobs` (einzelner Job), `POST /api/batches` (mehrere Jobs)
    - `GET /api/jobs/{job_id}` (Status/Results), `GET /api/batches/{batch_id}` (Aggregat)
    - `GET /api/jobs/{job_id}/download-archive` (ZIP aus `results.archive_data`)
  - File‑Serving weiter über spezialisierte Endpoints (z. B. `GET /api/pdf/text-content/...`) oder optional generisch `GET /api/files/text/<path>` mit Whitelist (`cache/`) und Typkontrolle.
  - Empfehlung: Results konsequent mit API‑URLs ausliefern (nicht mit Rohpfaden), damit Clients einheitlich abrufen können.


