### Webhooks für langlaufende Verarbeitung in Secretary-Services

Diese Analyse beschreibt das Webhook-Verfahren für asynchrone Verarbeitungen (PDF, perspektivisch auch Image, Audio, Video). Ziel: einheitliche Schnittstelle, minimale Datenweitergabe, robuste Sicherheit, klare Logs, einfache Wiederverwendung.

#### 1) Zielbild und Prinzipien
- **Data Minimization**: Client übergibt nur das Nötigste (Datei + minimale Steuerfelder + jobId + callback). Interne IDs/Strukturen bleiben beim Client.
- **Asynchrones Muster**: HTTP-Request liefert sofort ein „accepted“-Ack; Ergebnis kommt per Webhook.
- **Sicherheit**: Secret pro Job; optional HMAC-Signatur und Zeitstempel; Token bevorzugt im Header.
- **Konsistenz**: Gleiches Muster für PDF, Image, Audio, Video; nur `data`-Teil ist pro Prozessor unterschiedlich.

---

#### 2) API-Interface: Request (multipart/form-data)
Pflichtfelder (Domäne):
- `file`: Binärdaten
- `target_language`: z. B. `de`
- `extraction_method`: z. B. `native`
- `useCache`: `true|false`
- `includeImages`: `true|false`

Optionale Domänenfelder:
- `template`: String
- `context`: JSON-String (falls benötigt)

Neu/minimal für Webhook:
- `jobId`: string (vom Client vergeben; wird 1:1 zurückgesendet)
- `callback_url`: absolute HTTPS/HTTP-URL zum Webhook des Clients
- `callback_token`: opakes per‑Job Secret (authentisiert den Callback)

Optional für synchrones Warten (nur wenn KEIN `callback_url` gesetzt ist):
- `wait_ms`: Millisekunden, die der Server nach dem Enqueue des Jobs auf Abschluss wartet. Wenn der Job rechtzeitig fertig ist → direkte Ergebnis‑Response (200). Sonst → 202 mit `job_id`.

Abgekündigt/entfernt:
- `correlation` und sämtliche darin enthaltenen Felder (`libraryId`, `parentId`, `itemId`, `name`, `options`, …)

Validierung/Fehler:
- Wenn `callback_url` gesetzt ist, ist `jobId` Pflicht. Fehlt sie, antwortet der API-Endpunkt mit HTTP 400 und einem klaren Fehlerobjekt (`code: MISSING_JOB_ID`).

Beispiel (Request):
```bash
curl -X POST http://localhost:5001/api/pdf/process \
  -H "Accept: application/json" \
  -F "file=@./sample.pdf" \
  -F "target_language=de" \
  -F "extraction_method=native" \
  -F "useCache=false" \
  -F "includeImages=true" \
  -F "jobId=78dfcb48-a02b-4fe3-9a33e-e130b984ea09" \
  -F "callback_url=https://app.example.com/api/external/webhook" \
  -F "callback_token=opaque-job-secret"
```

---

#### 3) Antworten des Endpunkts

3.1 Bei gesetzter `callback_url`: Sofortiges Ack (202)
Der Endpunkt antwortet sofort mit einem Ack. Beispiel:
```json
{
  "status": "accepted",
  "worker": "secretary",
  "process": {
    "id": "<proc-id>",
    "main_processor": "pdf",
    "started": "2025-08-21T10:15:00Z",
    "is_from_cache": false
  },
  "job": { "id": "78dfcb48-a02b-4fe3-9a33e-e130b984ea09" },
  "webhook": { "delivered_to": "https://app.example.com/api/external/webhook" },
  "error": null
}
```

Hinweise:
- `job.id` entspricht exakt der übergebenen `jobId`.
- Daten (`data`) sind im Ack nicht enthalten; sie kommen ausschließlich per Webhook.

3.2 Ohne `callback_url`: Optionales Warten mit `wait_ms`
- Der Endpunkt legt immer einen Job an (Worker‑basiert). Wenn `wait_ms > 0`, wird bis zu dieser Dauer auf Abschluss gepollt:
  - Erfolgreich innerhalb des Fensters: 200 mit vollständiger Ergebnisstruktur (siehe Abschnitt 5 `data`).
  - Timeout oder noch in Bearbeitung: 202 mit `job_id` (Ack wie oben, aber ohne `webhook`).

---

- #### 4) Hintergrundverarbeitung
- Der Job wird immer in die Queue eingereiht und durch den `SecretaryWorkerManager` verarbeitet (konfigurierbare Parallelität).
- Temporäre Dateien werden erst nach Abschluss des Webhook-Versands gelöscht (kein vorzeitiges Cleanup).
- Cache-Handling bleibt unverändert; `is_from_cache`/`cache_key` werden wie gewohnt in `process` geführt.

---

#### 5) Webhook-Callback (Ergebnis)
Header (empfohlen):
- `Content-Type: application/json`
- `X-Worker: secretary`
- `X-Callback-Token: <jobSecret>` (empfohlen)
- `X-Signature: <hmac>` (optional, HMAC_SHA256(jobSecret, rawBodyJSON))
- `X-Timestamp: <ISO-8601>` (optional, Replayschutz)

Body (JSON):
```json
{
  "jobId": "78dfcb48-a02b-4fe3-9a33e-e130b984ea09",
  "process": {
    "id": "<proc-id>",
    "main_processor": "pdf",
    "started": "2025-08-21T10:15:00Z",
    "completed": "2025-08-21T10:16:12Z",
    "sub_processors": ["native-text"],
    "is_from_cache": false,
    "cache_key": "pdf:sha256:...",
    "llm_info": { "total_tokens": 0, "total_duration": 0 }
  },
  "data": {
    "extracted_text": "…vollständiger Text…",
    "images_archive_data": null,
    "images_archive_filename": null,
    "metadata": {
      "text_contents": [{ "page": 1, "content": "…" }],
      "extraction_method": "native"
    }
  },
  "error": null
}
```

Hinweise:
- `jobId` stammt 1:1 aus dem Eingangs-Request.
- `callback_token` kann zusätzlich im Body toleriert werden (Fallback), bevorzugt ist jedoch der Header `X-Callback-Token`.
- `correlation` und sonstige internen IDs entfallen vollständig.

---

#### 6) Sicherheitsempfehlungen
- **Token-Transport**: Bevorzugt per Header `X-Callback-Token`; Body-Fallback zulässig, aber nicht empfohlen.
- **HMAC**: Optional Signatur `X-Signature = HMAC_SHA256(jobSecret, rawBodyJSON)` und `X-Timestamp` prüfen.
- **HTTPS**: Für produktive Webhooks nur HTTPS verwenden.
- **Replay**: `X-Timestamp` und begrenztes Zeitfenster (z. B. ±5 Minuten) prüfen.

---

#### 7) Logging und Testbarkeit
- Eingehende Requests (multipart) werden mit Header-/Form‑Snapshot geloggt (Token maskiert).
- Ack mit Job-ID wird geloggt.
- Webhook-Dispatch: Ziel-URL, Statuscode und (gekürzter) Response‑Body werden geloggt.
- Optional: Beispiel `curl` und vollständige JSON‑Payload können zur Reproduktion gespeichert werden.

---

#### 8) Übertrag auf andere Endpoints (Image, Audio, Video)
Gleiches Muster – Unterschiede nur im `data`-Bereich:
- Image‑OCR
  - Request: `file`, `target_language?`, `extraction_method` (z. B. `ocr`), Cache‑Felder + Webhook‑Felder wie oben
  - Webhook `data`: erkannte Texte pro Bild, ggf. Bounding Boxes/Metadaten
- Audio
  - Request: `file`, `target_language`, `extraction_method` (z. B. `transcribe`), Cache + Webhook‑Felder
  - Webhook `data`: `transcript`, `segments`, optionale `metadata`
- Video
  - Request: `file`, `target_language`, `extraction_method` (z. B. `frames|asr`), Cache + Webhook‑Felder
  - Webhook `data`: `transcript`, `keyframes`/`thumbnails`, optionale `metadata`

Für alle: `jobId`, `callback_url`, `callback_token` identisch als Webhook‑Mechanik, Ack-Struktur identisch, Security/Logging identisch.

---

#### 9) Implementierungs-Checkliste (für jeden Endpoint)
1. Parser erweitern:
   - `jobId`, `callback_url`, `callback_token` (multipart/form-data)
   - Prüfen: Wenn `callback_url` gesetzt → `jobId` Pflicht (400 sonst)
2. Hintergrundverarbeitung:
   - Dateiablage im Prozessor‑Temp, Hash/Cache wie gewohnt
   - Cleanup erst nach Versand des Webhooks
3. Ack‑Antwort (HTTP 202):
   - `status=accepted`, `job.id = jobId`, `process.*` minimal
4. Webhook‑Sender:
   - Header: `Content-Type: application/json`, `X-Worker: secretary`, optional `X-Callback-Token`, Signatur/Timestamp
   - Body: `{ jobId, process, data, error? }`
   - Fehlerfall: `{ status=error, jobId, process{id, …}, data=null, error{code,message,details} }`
   - Robust Logging von Versand und Antwort (Statuscode)
5. Tests:
   - Request ohne `jobId` bei gesetzter `callback_url` → 400
   - End‑to‑End: 202‑Ack → Webhook mit korrekter `jobId`
   - Header‑Token wird akzeptiert; Body‑Fallback (optional) funktioniert
6. Sicherheit (empfohlen):
   - HMAC‑Signatur und Timestamp implementieren und verifizieren
7. Dokumentation:
   - Beispiel‑Requests, Beispiel‑Callbacks, Feldbeschreibungen aktualisieren

---

#### 10) Beispiele (Copy‑&‑Paste)

Ack‑Prüfung (Server‑Response):
```bash
curl -X POST http://localhost:5001/api/pdf/process \
  -H "Accept: application/json" \
  -F "file=@./sample.pdf" \
  -F "target_language=de" \
  -F "extraction_method=native" \
  -F "useCache=false" \
  -F "includeImages=true" \
  -F "jobId=78dfcb48-a02b-4fe3-9a33e-e130b984ea09" \
  -F "callback_url=http://localhost:3000/api/external/webhook" \
  -F "callback_token=opaque-job-secret"
```

Webhook‑Verifikation (Client‑Seite – Beispiel, wie es aussehen wird):
```bash
curl -X POST "http://localhost:3000/api/external/webhook" \
  -H "Content-Type: application/json" \
  -H "X-Worker: secretary" \
  -H "X-Callback-Token: opaque-job-secret" \
  -d '{
    "jobId": "78dfcb48-a02b-4fe3-9a33e-e130b984ea09",
    "process": { "id": "proc_123", "main_processor": "pdf", "started": "2025-08-21T10:15:00Z" },
    "data": {
      "extracted_text": "Hello World",
      "metadata": { "text_contents": [{ "page": 1, "content": "..." }], "extraction_method": "native" }
    },
    "error": null
  }'
```

---

Diese Vorlage kann 1‑zu‑1 für Image-, Audio‑ und Video‑Routen übernommen werden. Nur der `data`‑Block ist pro Prozessor anzupassen.


