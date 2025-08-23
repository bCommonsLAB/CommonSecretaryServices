# Integration von PDF-HTTP-Endpunkten mit dem Secretary-Job-Worker

Ziel: Eingehende PDF-Verarbeitungen (Upload/URL) sollen nicht direkt in Threads/Async-Tasks pro Request laufen, sondern als Jobs in den `SecretaryWorkerManager` eingereiht werden. So wird Parallelität begrenzt (Konfiguration), Last geglättet, und Backpressure erreicht.

## IST-Zustand (Kurz)
- `src/api/routes/pdf_routes.py` verarbeitet Requests synchron oder startet pro Request einen Hintergrund-Thread und sendet direkt Webhooks.
- `src/core/mongodb/secretary_worker_manager.py` pollt `jobs` (Mongo), startet begrenzt Threads und delegiert an `registry`-Handler.
- `src/core/processing/__init__.py` registriert `"pdf"` → `handle_pdf_job` in `handlers/pdf_handler.py`.
- Jobs/Progress/Results-Strukturen existieren (`Job`, `JobProgress`, `JobResults`).

## Integrationsvarianten

### Variante A: Vollständige Entkopplung per Job-Queue (empfohlen)
- API-Endpunkt legt immer einen Job `job_type="pdf"` an; Payload enthält Dateiquelle (Upload-Tempfile/URL), Optionen, Callback-Infos.
- Endpunkt antwortet sofort mit `202 Accepted` und `job_id`. Keine unmittelbare Verarbeitung im Request-Prozess.
- `SecretaryWorkerManager` verarbeitet den Job und sendet den Webhook nach Abschluss/Fehler.
- Vorteile:
  - Gekapselte Parallelitätssteuerung über `max_concurrent_workers`.
  - Einheitlicher Pfad für Webhooks und Fehler.
  - Backpressure: viele Requests → Jobs steigen in `pending`.
- Nachteile:
  - Leichte Latenzerhöhung auch für kleine Last (bewusst akzeptiert).

### Variante B: Hybrid (Synchron wenn idle, sonst Job)
- Endpunkt prüft aktive Worker; wenn genug Kapazität frei, synchron verarbeiten (heutiger Weg), sonst als Job enqueuen.
- Vorteile: Geringe Latenz bei leichter Last.
- Nachteile: Mehr Pfadvarianten, komplexer, schwerer zu testen; Race-Conditions bzgl. Kapazitätsprüfung.

### Variante C: Webhook im Endpunkt belassen, Worker schreibt nur DB
- Endpunkt legt Job an, aber weiterhin sendet der Endpunkt den Webhook; Worker persistiert nur Ergebnisse.
- Nachteile: Bricht Entkopplung; Endpunkt muss trotzdem Ergebnisse/Fehler kennen, obwohl Worker rechnet → unlogisch.

## Empfehlung
- Variante A. Webhook-Senden in den Worker verlagern. API-Endpunkte erstellen nur Jobs und geben `202` mit `job_id` zurück. Einheitliches Payload-Format für `completed|error`.

## Design-Details

- Job-Parameters (Erweiterung von `JobParameters.extra`):
  - `file_source`: `{"type": "upload", "path": "..."}` oder `{"type": "url", "value": "..."}`
  - `extraction_method`, `template`, `context`, `use_cache`, `include_images`, `force_refresh` (optional)
  - `webhook`: `{"url": "...", "token": "...", "jobId": "..."}`
- Upload-Handling:
  - Datei wird in ein persistentes Arbeitsverzeichnis gespeichert (z. B. `cache/uploads`) und Pfad im Job referenziert. Cleanup durch Processor/Worker nach Verarbeitung.
- Worker-Seite (`handle_pdf_job`):
  - Liest `file_source`: bei `upload` → Pfad; bei `url` → direkte URL.
  - Führt `PDFProcessor.process` aus.
  - Persistiert `results` in Job.
  - Wenn `webhook` gesetzt → sendet Callback (success/error) und loggt Antwortstatus.
- Webhook-Payload (konsolidiert an `pdf_routes.py` angelehnt):
  - success: `{status: "completed", worker: "secretary", jobId, process, data, error: null}`
  - error: `{status: "error", worker: "secretary", jobId, process: {id, main_processor: "pdf", started}, data: null, error: {code, message}}`
  - Token-Handling: Header `Authorization: Bearer <token>` und `X-Callback-Token`; optional Kompatibilität: Token zusätzlich im Body.

## Minimal-invasive Änderungen (Schrittfolge)
1) `pdf_routes.py`:
   - Upload-/URL-Endpoints ändern: statt eigener Threads → Job anlegen via `SecretaryJobRepository().create_job(...)`.
   - Antwort sofort: `202`, `job_id`, echo der Webhook-Ziele.
2) `handlers/pdf_handler.py`:
   - Webhook-Senden ergänzen (success/error), Payload-Format an heutige Routen angleichen.
   - Pfad-Handling für Uploads vs. URLs vereinheitlichen.
3) `secretary_worker_manager.py` bleibt unverändert (Konkurrenz justierbar über config).
4) Config-Dokumentation: `generic_worker.active`, `max_concurrent`, `poll_interval_sec`.
5) Tests:
   - Route erstellt Job und liefert `202` mit `job_id`.
   - Worker verarbeitet Job und ruft Mock-Webhook auf (HTTP-Server/Requests-Mock).

## Migrationshinweis
- Bestehende Clients, die synchronen Response-Inhalt erwarten, müssen auf `job_id`-basiertes Polling/Callback umstellen.
- Übergangsphase: Optionaler Query-Parameter `sync=true` könnte vorübergehend den alten Pfad aktivieren, wird aber nicht empfohlen.

