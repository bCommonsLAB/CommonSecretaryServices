## Office API Endpoints

Endpoints für Office-Dateien (DOCX/XLSX/PPTX). Es gibt **zwei** Pipelines, um die Ergebnisqualität zu vergleichen:

- **A: Python-only**: native Parsing-Libraries → Markdown + extrahierte Bilder + Thumbnail-Previews
- **B: Via PDF**: LibreOffice konvertiert Office → PDF, danach wird der **bestehende PDFProcessor** genutzt (inkl. `extraction_method=mistral_ocr`).

---

## POST /api/office/process

Pipeline A (python-only): Office-Datei zu Markdown + Images + Thumbnails.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Office-Datei (`.docx`, `.xlsx`, `.pptx`) |
| `useCache` | Boolean | No | `true` | Cache verwenden |
| `includeImages` | Boolean | No | `true` | Embedded-Images extrahieren |
| `includePreviews` | Boolean | No | `true` | Thumbnail-Previews der extrahierten Bilder erzeugen |
| `callback_url` | String | No | - | Absolute HTTPS-URL für Webhook |
| `callback_token` | String | No | - | Per-Job Secret für Webhook |
| `jobId` | String | No | - | Client-Job-ID für Webhook |
| `force_refresh` | Boolean | No | `false` | Cache ignorieren/neu berechnen |
| `wait_ms` | Integer | No | `0` | Optional: Wartezeit in ms (nur ohne `callback_url`) |

### Response
- Ohne `callback_url`: `202 accepted` (oder synchrones Resultat, falls `wait_ms>0` und Job rechtzeitig fertig)\n+- Mit `callback_url`: `202 accepted` + Webhook wird später gesendet\n+
---

## POST /api/office/process-via-pdf

Pipeline B: Office → PDF (LibreOffice headless), dann Weiterverarbeitung über `PDFProcessor.process(...)`.

**Wichtig**: Die Parameter sind **analog** zu `POST /api/pdf/process`. Zusätzlich ist `extraction_method=mistral_ocr` erlaubt und ist der Default für diesen Endpoint.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Office-Datei (`.docx`, `.xlsx`, `.pptx`) |
| `extraction_method` | String | No | `mistral_ocr` | Wie PDF: `native`, `tesseract_ocr`, `both`, `preview`, `preview_and_native`, `llm`, `llm_and_native`, `llm_and_ocr` **plus** `mistral_ocr`, `preview_and_mistral_ocr` |
| `page_start` | Integer | No | - | Startseite (1-basiert) |
| `page_end` | Integer | No | - | Endseite (1-basiert, inkl.) |
| `template` | String | No | - | Template-Name |
| `context` | String | No | - | JSON-String für Template-Kontext |
| `useCache` | Boolean | No | `true` | Cache verwenden |
| `includeImages` | Boolean | No | `false` | Bilder-Archiv erzeugen (bei PDF-Flow) |
| `target_language` | String | No | - | Wird akzeptiert, aktuell aber nicht direkt im PDFProcessor genutzt |
| `callback_url` | String | No | - | Absolute HTTPS-URL für Webhook |
| `callback_token` | String | No | - | Per-Job Secret für Webhook |
| `jobId` | String | No | - | Client-Job-ID für Webhook |
| `force_refresh` | Boolean | No | `false` | Cache ignorieren/neu berechnen |
| `wait_ms` | Integer | No | `0` | Optional: Wartezeit in ms (nur ohne `callback_url`) |

### Webhook Payload (completed)

Der Webhook ist absichtlich kompakt und liefert URLs zu großen Artefakten:

```json
{
  "phase": "completed",
  "message": "Office-via-PDF abgeschlossen ...",
  "data": {
    "extracted_text": "...",
    "metadata": {
      "text_contents": [...]
    },
    "markdown_url": "/api/office/jobs/{job_id}/markdown",
    "mistral_ocr_raw_url": "/api/office/jobs/{job_id}/mistral-ocr-raw",
    "images_archive_url": "/api/jobs/{job_id}/download-archive"
  }
}
```

---

## GET /api/office/jobs/{job_id}/markdown

Lädt die erzeugte Markdown-Datei (Attachment) herunter.

Status Codes:
- `200`: Markdown bereit
- `202`: Job läuft noch
- `404`: Job nicht gefunden
- `400`: Kein Markdown verfügbar

---

## GET /api/office/jobs/{job_id}/mistral-ocr-raw

Lädt die gespeicherte Rohantwort der Mistral OCR als JSON herunter (nur wenn im Handler gespeichert).

Status Codes:
- `200`: JSON bereit
- `202`: Job läuft noch
- `404`: Job nicht gefunden
- `400`: Keine Rohdaten verfügbar






