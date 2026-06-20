# Analyse: Dashboard erfasst nur PDF, nicht Transformer/Embeddings

## Beobachtung

Nach dem Neustart erscheint im Dashboard nur der PDF-Job (1 Anfrage, ~24s,
100%). Transformer und Embeddings (RAG) tauchen nicht auf, obwohl sie laut
Server-Log liefen.

## Ursache (aus dem Code belegt)

Die Erfassung ist über die Code-Pfade hinweg **inkonsistent**:

1. **PDF (asynchroner Job)** wird erfasst, weil der `SecretaryWorkerManager`
   in `_process_job` jetzt explizit einen Tracker anlegt und
   `set_processor_name(job.job_type)` ("pdf") setzt. → erscheint als "pdf".

2. **Embeddings** laufen synchron über `POST /api/rag/embed-text`. Die Route
   `src/api/routes/rag_routes.py` legt **gar keinen** `PerformanceTracker` an.
   `teardown_request` findet daher nichts zum Finalisieren → nichts wird
   gespeichert.

3. **Transformer** lief im beobachteten Lauf nur als **Sub-Prozessor innerhalb**
   des PDF-Jobs (kein eigener `/api/transformer`-Request). Außerdem: Die
   synchronen Routen, die zwar einen Tracker anlegen (transformer, imageocr,
   session, image_analyzer, video), rufen **kein** `set_processor_name(...)` auf.
   Default ist `processor_name = None` → in `compute_stats` wird daraus
   "unknown". Ein Standalone-Transformer-Call würde also als "unknown"
   erscheinen, nicht als "transformer".

### Kernproblem
- Tracker-Erstellung ist pro Route optional und uneinheitlich.
- Processor-Name wird in synchronen Routen praktisch nie gesetzt.
- Async-Jobs werden auf Worker-Ebene erfasst; synchrone Calls uneinheitlich.

## Lösungsvarianten

### Variante 1 — Minimal, pro Route (geringstes Risiko)
- In `rag_routes.py` einen Tracker anlegen + `set_processor_name("rag")`.
- In den bereits "getrackten" Routen `set_processor_name(...)` ergänzen.
- **Pro:** kleine, lokale Änderungen; keine Doppelzählung.
- **Contra:** bleibt opt-in pro Route; leicht wieder zu vergessen; verschachtelter
  Transformer (innerhalb PDF) wird weiterhin nicht separat angezeigt.

### Variante 2 — Zentral pro Prozessor (BaseProcessor)
- Jede Prozessor-Ausführung in `BaseProcessor` zentral erfassen.
- **Pro:** pdf, transformer, imageocr, rag erscheinen je einzeln, automatisch.
- **Contra:** verschachtelte Prozessoren erzeugen mehrere Einträge pro Job
  (pdf + transformer + imageocr); zusätzlich Doppelzählung mit dem Job-Eintrag
  des Workers. Bedeutung von "Anfragen" ändert sich von pro-Request zu
  pro-Prozessor-Lauf. Höheres Risiko, größere Umstellung.

### Variante 3 — Zentral im Request-Lifecycle (empfohlen)
- In `src/dashboard/app.py` (`before_request`) für synchrone API-Verarbeitungs-
  Endpunkte einen Tracker anlegen und den Processor-Namen aus dem Namespace
  ableiten (z. B. `/api/rag/...` → "rag", `/api/transformer/...` → "transformer").
- Asynchrone Job-Submission-Endpunkte (pdf, jobs) und reine Status-/Download-/
  Polling-GETs werden per Allowlist/Denylist ausgenommen (Worker-Ebene erfasst
  die Jobs bereits → keine Doppelzählung, kein Rauschen).
- `teardown_request` finalisiert wie bisher.
- **Pro:** einheitlich, eine zentrale Stelle, kein per-Route-Aufwand;
  synchrone Calls erscheinen korrekt benannt.
- **Contra:** kleine kuratierte Allow-/Denylist nötig; verschachtelte
  Sub-Prozessoren bleiben Teil ihres Haupt-Requests (i. d. R. gewünscht).

## Empfehlung
Variante 3: einheitliche, wartungsarme Erfassung mit geringem Rauschen.
Variante 1 als schneller Zwischenschritt möglich, falls nur Embeddings dringend
sichtbar sein müssen.

## Nachtrag (umgesetzt + neuer Befund)

### Schritt A (umgesetzt, verifiziert)
Variante 3 implementiert in `src/dashboard/app.py`:
- `before_request` legt für synchrone API-POSTs einen Tracker an und leitet den
  Processor-Namen aus dem Namespace ab (z. B. `rag`, `transformer`).
- `after_request` verwirft den Tracker bei HTTP 202 (Async-Submission → wird auf
  Worker-Ebene erfasst, keine Doppelzählung).
- Verifiziert: `rag` (Embeddings) erscheint jetzt als eigene Zeile.

### Schritt B (verschachtelte Sub-Prozessoren) — Blockierender Befund
Ziel war, Sub-Prozessoren (Transformer/ImageOCR im PDF-Job) als eigene Zeilen zu
zeigen, gespeist aus `measurements.processors`.

**Befund (aus echtem Dokument geprüft):** `measurements.processors = {}` und
`operations = []`. Die Sub-Prozessor-Zeiten werden heute **gar nicht** erfasst,
weil `pdf_processor`/`transformer_processor` **kein** `measure_operation(...)`
aufrufen.

**Zusätzlich:** Im Mistral-OCR-Flow wird der `TransformerProcessor` nur im
Konstruktor initialisiert, leistet aber keine Arbeit (`transformByTemplate` wird
nur bei Template-Extraktion aufgerufen, Zeile ~2062). Echte Transformer-Arbeit
gibt es nur in Template-Flows; ImageOCR nur in bestimmten Bild-Flows
(Zeilen ~1633/1835/1916).

**Konsequenz:** Sub-Prozessor-Zeilen erfordern, die echten Arbeitspunkte in
`pdf_processor` mit `measure_operation(...)` zu instrumentieren (invasiver,
berührt Kern-Verarbeitung) und danach `measurements.processors` in
`compute_stats` als eigene Zeilen auszuweisen. Reine Initialisierung wird bewusst
NICHT erfasst (wäre irreführend).

### Offene Entscheidung
- Option B1: Echte Arbeitspunkte instrumentieren (`transformByTemplate`,
  `imageocr.process`) + `compute_stats` erweitern. Transformer/ImageOCR erscheinen
  als eigene Zeilen, wenn sie tatsächlich laufen.
- Option B2: Bei Request-Granularität bleiben. Transformer erscheint nur bei
  direktem Aufruf von `/api/transformer/...`.

## Präzise Pipeline-Analyse (KORRIGIERT nach Client-Repo-Durchsicht)

Frühere (falsche) Schlussfolgerung war: „transformer ist Client-Arbeit, erreicht
den Server nicht." Das stimmt NICHT. Korrektur:

Die Template-Phase ist ein eigener, dedizierter Secretary-Aufruf
`POST /api/transformer/template` — getrennt von OCR und RAG. In diesem konkreten
Job wurde er nur **vor** dem HTTP-Call legitim übersprungen (Gate/Override
`chapters_already_exist`), deshalb fehlt er im Server-Log.

| Client-Phase           | Aufruf an unseren Server               | Server-Verarbeitung                         | Dashboard-Label |
|------------------------|----------------------------------------|---------------------------------------------|-----------------|
| extract (OCR)          | `POST /api/pdf/process-mistral-ocr`    | pdf-Job (`process_mistral_ocr_with_pages`)  | `pdf` ✓ |
| template (transformer) | `POST /api/transformer/template`       | **async** Job `transformer_template` (Webhook) bzw. **sync** (ohne callback) | `transformer_template` bzw. `transformer` ✓ |
| ingest (rag)           | `POST /api/rag/embed-text`             | synchron, RAGProcessor                      | `rag` ✓ |

**Belege im Server-Repo:**
- `/api/transformer/template` (transformer_routes.py:467ff): mit `callback_url`
  → erzeugt Secretary-Job `job_type="transformer_template"` und gibt **202**
  zurück (Zeile 756); ohne callback → synchron **200**.
- Handler registriert: `register("transformer_template", handle_transformer_template_job)`
  (core/processing/__init__.py:20).
- Damit gilt:
  - Async (Client nutzt Webhook): Worker-Instrumentierung erfasst den Job als
    `transformer_template`. Die 202-Submission wird per `after_request` verworfen
    (keine Doppelzählung).
  - Sync: Schritt A erfasst den Request als `transformer` (Namespace-Ableitung).

**Warum hier nichts erscheint (belegt durch Client-Analyse):** Die Phase wurde vor
`runTemplateTransform` übersprungen (Override `chapters_already_exist` →
`template_override_skip`; bzw. `transform_gate_skip`). Entscheidender Trace-Marker:
`template_request_start` wird nur emittiert, wenn der HTTP-Call wirklich rausgeht.
Fehlt er → übersprungen (unser Fall) → korrekterweise kein Server-Eintrag.

**Konsequenz für die Hebel:**
- H2/H3 sind NICHT nötig und sogar kontraproduktiv: Das Repo schickt dem
  OCR-Endpoint bewusst NIE ein Template-Feld (secretary-request.ts:93–100); die
  Template-Anwendung läuft architektonisch immer über
  `/api/transformer/template`. Inline-Template im OCR-Pfad würde diese Logik
  duplizieren und die Gate-/Repair-Logik umgehen.
- KEIN Server-Code-Change erforderlich. „transformer" erscheint automatisch,
  sobald die Template-Phase tatsächlich läuft (Policy `force` oder Lauf ohne
  vorab existierende chapters).

### Verifikation (offen, noch nicht live beobachtet)
Einen Lauf erzwingen, bei dem `runTemplateTransform` wirklich ausgeführt wird
(z. B. Policy `metadata: 'force'` oder Dokument ohne vorhandene chapters). Dann
sollte im Dashboard eine Zeile `transformer_template` (async) bzw. `transformer`
(sync) erscheinen.
