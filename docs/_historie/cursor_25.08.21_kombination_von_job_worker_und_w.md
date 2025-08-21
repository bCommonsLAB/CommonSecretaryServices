# Kombination von Job-Worker und Webhook
_Exported on 8/21/2025 at 18:10:15 GMT+2 from Cursor (1.4.5)_

---

**User**

Ich habe da jetzt, glaube ich, ein architektonisches Problem. Wenn ich... Ich kann jetzt z.B. über die HP PDF-Datei transformieren. Und diese werden... Wenn sie fertig sind, über einen Webhook zum Client gesendet. Aber was passiert, wenn ich jetzt 100 HP-Ernfahrungen gleichzeitig mache? Dann wird der Server wahrscheinlich in die Knie gehen. Parallel dazu habe ich da ja dieses... ...Job-Konzept auch schon implementiert. Mit diesem Generic-Worker, der Jobs entgegennimmt, sie abarbeitet. Und die Frage ist, wie könnte man jetzt beide Logik kombinieren? D.h. reingehende HP-Ernfahrungen werden immer an den Job-Worker weitergeleitet. Und dann halt abgearbeitet. Wenn sie dann kommen. Und... Wäre dann der jetzige Webhook mit der Logik kompatibel, oder sollte der Job-Worker den Webhook absenden? Wie könnte man die beiden Logiken kombinieren?@pdf_routes.py @secretary_worker_manager.py 

---

**Cursor**

Ich prüfe zuerst, wie der PDF-Flow heute funktioniert und welche Hooks/Handler für Jobs bereits vorhanden sind, um eine saubere Kombinationsstrategie und ggf. minimal-invasive Änderungen abzuleiten. Danach dokumentiere ich die Architekturvarianten in docs/_analysis und skizziere eine empfohlene Implementierungsroute.

Ich schaue mir die Job-Modelle, die Registry und das Repository an, um zu prüfen, wie sich PDF-Anfragen als Jobs einreihen lassen und ob Callback-Infos bereits abbildbar sind. Danach kann ich konkrete Integrationsoptionen formulieren.

Ich suche parallel nach der Registrierung des PDF-Handlers in der Registry und nach vorhandener Webhook-Logik im Job-Repository/Worker, um die Integration abschätzen zu können.

Ich schaue mir an, wie der Worker gestartet wird und ob wir Jobs aus den PDF-Routen anlegen können, indem ich die relevante App-Initialisierung lade. Danach skizziere Integrationsoptionen.

Ich erstelle eine kurze Analyse-Datei mit Integrationsvarianten und einer Empfehlung. Danach kannst du entscheiden, ob ich implementieren soll.

Ich verfasse jetzt die Analyse in einer neuen Datei unter docs/_analysis, dann formuliere ich Strategie und Empfehlung.

```markdown
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
```

Ich habe die relevanten Teile gelesen (`pdf_routes.py`, `secretary_worker_manager.py`, Registry/Handler/Repo) und eine kurze Architektur-Analyse erstellt: `docs/_analysis/webhook_vs_job_worker.md`. Jetzt skizziere ich dir die Integrationsoptionen und eine klare Empfehlung.

### Ziel
- Eingehende PDF-Anfragen nicht mehr pro Request im Thread verarbeiten.
- Immer als Jobs in den `SecretaryWorkerManager` einreihen, der die Parallelität begrenzt.
- Webhook-Callback nach Abschluss vom Worker senden, nicht mehr aus der Route.

### Optionen
- Variante A (empfohlen): API legt immer `job_type="pdf"` an, antwortet mit 202/`job_id`. Worker verarbeitet und sendet Webhook (completed/error).
- Variante B: Hybrid (synchron bei Idle, sonst Job). Komplexer, fehleranfälliger, schwerer zu testen.
- Variante C: Job + Webhook trotzdem in Route. Inkonsistent, bricht Entkopplung.

### Empfehlung
- Klar Variante A. Der Worker sendet den Webhook. Die Route ist nur “Ingress → Job anlegen → 202 ACK”.

### Minimal-invasive Änderungen
- `src/api/routes/pdf_routes.py`
  - Beim Upload: Datei in ein persistentes Upload-Verzeichnis (z. B. `cache/uploads`) speichern und Pfad in den Job packen.
  - Beim URL-Case: URL in den Job packen.
  - Alle Verarbeitungsparameter in `JobParameters.extra` ablegen:
    - `file_source`: `{ "type": "upload", "path": "..." }` oder `{ "type": "url", "value": "..." }`
    - `extraction_method`, `template`, `context`, `use_cache`, `include_images`, `force_refresh`
    - `webhook`: `{ "url": "...", "token": "...", "jobId": "..." }`
  - Sofortiges `202` mit `job_id`, `webhook.delivered_to` zurückgeben. Keine threads/async runs in der Route mehr.

- `src/core/processing/handlers/pdf_handler.py`
  - `file_source` lesen (Upload-Pfad vs. URL).
  - `PDFProcessor.process(...)` wie heute.
  - Success: Job `COMPLETED` + `results` persistieren, danach Webhook absenden.
  - Error: Job `FAILED` + Fehler persistieren, danach Error-Webhook absenden.
  - Payload kompatibel zum bisherigen Schema halten:
    - completed: `{status: "completed", worker: "secretary", jobId, process, data, error: null}`
    - error: `{status: "error", worker: "secretary", jobId, process, data: null, error: {code, message}}`
  - Token-Handling wie bisher: Header `Authorization: Bearer <token>` und `X-Callback-Token`, optional zusätzlich im Body, damit bestehende Clients weiter funktionieren.

- `src/core/mongodb/secretary_worker_manager.py`
  - Unverändert nutzen; Parallelität per `config.yaml` (generic_worker.active/max_concurrent/poll_interval_sec).

- Konfiguration/Doku
  - Sicherstellen, dass `generic_worker.active=True` gesetzt ist.
  - `max_concurrent_workers` auf vernünftigen Wert (z. B. 3–5) setzen.
  - In `docs/_analysis/webhook_vs_job_worker.md` sind Details festgehalten.

### Kompatibilität des bestehenden Webhooks
- Ja, kompatibel, wenn der Worker den Payload exakt wie in `pdf_routes.py` formt (Keys, Struktur, Token-Verwendung). Empfohlen: Payload 1:1 übernehmen, damit kein Client angepasst werden muss.

### Testplan (prägnant)
- Route smoke-test: POST → `202` und `job_id` zurück.
- Worker-flow: Mit Test-Repo/Mock-Server prüfen, dass bei `COMPLETED`/`FAILED` Webhook mit korrektem Payload gesendet wird (Header + Body).
- Lasttest: 100 Jobs einreihen → nur `max_concurrent` parallel verarbeiten, Rest in `pending`, keine Thread-Explosion.
- mypy/Typen: `JobParameters.extra`-Struktur dokumentieren; Handler robust gegen fehlende Felder.

### Risiken/Details
- Upload-Datei-Lebenszyklus: Route speichert persistent (z. B. `cache/uploads`), Worker löscht nach Verarbeitung.
- Sicherheit Webhook: Nur HTTPS; Token per Header senden; Timeout/Retry-Strategie festlegen (heute: 30s Timeout, kein Retry).
- Linter-Hinweis: Im bestehenden `pdf_routes.py` gibt es einen kleineren Typ-Hinweis bei `args.get(...)` (Unknown). Das ließe sich beim Umbau gleich mit bereinigen.

Wenn du willst, implementiere ich Variante A jetzt: Route umbauen → Job anlegen → Handler um Webhook-Versand erweitern → kurze Tests. Sag mir, ob ein Fallback-Parameter `sync=true` für eine Übergangszeit gewünscht ist.

- Ich habe eine Analyse mit Varianten und Empfehlung erstellt und abgelegt (`docs/_analysis/webhook_vs_job_worker.md`).
- Nächster praktikabler Schritt: `pdf_routes.py` entkoppeln (Job anlegen statt Thread), `pdf_handler` um Webhook ergänzen, Konfig prüfen.

