## Office-Endpunkte (A/B Vergleich): Python-only vs. LibreOffice→PDF→PDFProcessor

### Ziel
Wir wollen Office-Dateien (DOCX/XLSX/PPTX) **asynchron** verarbeiten – mit **Jobs**, **Webhooks**, **Artefakten** (Markdown + Bilder) und **Download-URLs** – analog zur bestehenden PDF-Verarbeitung.

Dabei implementieren wir **zwei Pipelines**, um die Ergebnisqualität zu vergleichen:

- **Pipeline A (python-only)**: Native Parsing-Libraries → Markdown + extrahierte Embedded-Images + **Thumbnail-Previews**.
- **Pipeline B (via PDF)**: LibreOffice headless konvertiert Office → PDF, danach nutzt der Job **denselben** `PDFProcessor.process(...)` und damit die bestehende PDF-Logik (inkl. Mistral OCR, Preview-Generierung, Template-Transformation).

Die Plan-Idee ist: **Vergleichbarkeit vor Optimierung**. Danach kann entschieden werden, welche Pipeline standardmäßig aktiv sein soll.

---

### Begriffe / Definitionen
- **Embedded-Images**: Bilder, die im Dokument eingebettet sind (DOCX: inline drawings; PPTX: pictures; XLSX: worksheet images).
- **Previews**: In diesem Projekt bedeutet das **Thumbnails** der extrahierten Bilder (keine Seiten-/Slide-Renderings).
- **Job/Webhook**: Wir nutzen das bestehende Secretary-Job-System (`SecretaryJobRepository` + `SecretaryWorkerManager`). Webhooks folgen dem etablierten Muster (progress + completed/error).

---

### Pipeline A: Python-only (native Office → Markdown)

#### Erwartete Qualität (Trade-offs)
**Stärken**:
- Gute **Semantik**: Überschriften, Absätze, Tabellen (XLSX/Tabellen in DOCX) lassen sich strukturiert nach Markdown abbilden.
- Embedded-Images sind als Dateien verfügbar; Thumbnails sind deterministisch erzeugbar.

**Schwächen** (bewusste Einschränkungen):
- **Layout-Treue** ist begrenzt (Seitenumbrüche, Spalten, Textfluss um Objekte).
- **Charts/SmartArt/Shapes** sind je nach Library nur begrenzt abbildbar (oft nicht oder nur als Bild/vereinfachte Darstellung).
- **PPTX**: Kein echtes Slide-Rendering → keine „Slide Preview“-Bilder (nur Thumbnails der extrahierten Embedded-Images).

#### Artefakte
Im `process_dir` (Job-spezifisches Arbeitsverzeichnis):
- `output.md`
- `images/` (Originalbilder)
- `previews/` (Thumbnails)

Markdown referenziert Bilder relativ:
- `![image-1](images/image-1.png)`

---

### Pipeline B: LibreOffice→PDF→PDFProcessor (Parameter-Pass-through)

#### Motivation
Maximale **visuelle Konsistenz** (Office wird gerendert) und Wiederverwendung der bestehenden PDF-Pipeline. Das ist besonders nützlich für:
- Layout-intensives DOCX
- Excel mit komplexem Drucklayout/Charts (oft als Render-Ergebnis sinnvoller als „Tabellenwerte“)
- PPTX, wenn eine „PDF-Ansicht“ als Quelle genügt

#### Risiken / Anforderungen
- Deployment benötigt **LibreOffice** (`soffice`) + passende Fonts.
- Konvertierung ist „Blackbox“; Ergebnisse können je nach Umgebung leicht variieren.
- Danach ist das Dokument **PDF** – d.h. Office-Semantik (z.B. echte Tabellenstruktur) kann verloren gehen.

#### Parametrisierung: identisch zu `POST /api/pdf/process`
Der Endpoint `POST /api/office/process-via-pdf` akzeptiert **denselben** FormData-Parameter-Satz wie `POST /api/pdf/process` (plus `file` im Office-Format).

Parameter (Pass-through):
- `extraction_method` (Default: `mistral_ocr`)
- `page_start`, `page_end`
- `template`, `context` (JSON String)
- `useCache`
- `includeImages`
- `target_language` (wird akzeptiert; `PDFProcessor` nutzt es aktuell nicht direkt)
- `callback_url`, `callback_token`, `jobId`
- `force_refresh`
- `wait_ms` (nur wenn kein `callback_url`)

Mapping-Logik:
1) Office-Datei → PDF via `soffice --headless --convert-to pdf --outdir <process_dir>`
2) PDF-Verarbeitung über `PDFProcessor.process(...)` mit den Parameterwerten.

---

### Job/Webhook Verhalten (gemeinsam)

#### Job-Typen
Zur sauberen Trennung und Vergleichbarkeit:
- `job_type="office"`: Pipeline A (python-only)
- `job_type="office_via_pdf"`: Pipeline B (LibreOffice→PDF→PDFProcessor)

#### Webhook Events
Wir bleiben bei der bestehenden Konvention:
- **Progress**: `{phase, progress, message, process: {id}}`
- **Completed**: `{phase:"completed", message, data:{...urls...}}`
- **Error**: `{phase:"error", message, error:{code,message,details}, data?:{...}}`

**Wichtig**: Große Payloads (z.B. Base64 ZIP) werden nicht im Webhook gesendet; stattdessen URLs.

---

### Größenlimits / Persistenz
Analog zur PDF-Implementierung vermeiden wir große Base64-Felder in MongoDB.
- Große Dateien werden im `process_dir` als Datei gespeichert.
- MongoDB speichert Referenzen/URLs in `JobResults.structured_data` und `JobResults.asset_dir`.

---

### Test-Strategie
- **Unit-Tests** (schnell, deterministisch) für Pipeline A unter `.tests/`.
- **Integration-Tests** für Pipeline B (LibreOffice vorhanden) unter `.tests/` mit `@pytest.mark.integration`.

Da `pytest.ini` aktuell `testpaths=tests` setzt (Ordner existiert nicht), wird `pytest.ini` auf `.tests` umgestellt.






