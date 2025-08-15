> Zur Anwendung zurück: [/](\/)

---
status: draft
last_verified: 2025-08-15
---

# Common Secretary Services

Willkommen zur Dokumentation. Dieses Projekt verarbeitet Medien (Audio, Video, PDF/Bilder) und erzeugt strukturierte Ergebnisse (Markdown/JSON) über eine REST‑API mit Flask‑RESTX.

## Schnellstart
```powershell
# Windows
venv\Scripts\activate
$env:PYTHONPATH = "."
python src/main.py
```
- Swagger UI: `http://127.0.0.1:5000/api/doc`
- OpenAPI JSON: `http://127.0.0.1:5000/api/swagger.json`

## Bereiche
- Guide
  - Getting Started → [Installation](guide/getting-started/installation.md), [Development](guide/getting-started/development.md)
  - How‑Tos → [Session‑Archive](guide/how-tos/session-archive.md)
  - UI → [Dashboard](guide/ui/dashboard.md)
- Explanations
  - Architektur → [Überblick](explanations/architecture/overview.md), [Details](explanations/architecture/details.md)
  - Async Events → [Überblick](explanations/async-events/overview.md), [n8n How‑To](explanations/async-events/how-to-n8n.md)
  - Caching → [Übersicht](explanations/caching/overview.md)
  - Templates → [Übersicht](explanations/templates/overview.md)
  - Typen → [Übersicht](explanations/types/overview.md)
  - Metaprocessor → [Überblick](explanations/metaprocessor/overview.md)
  - Metadaten → [Überblick](explanations/metadata/overview.md)
  - LLM → [Optimierung](explanations/llm/optimization.md)
- Processors
  - Audio → [Overview](processors/audio/overview.md)
  - Video → [Overview](processors/video/overview.md)
  - PDF → [Overview](processors/pdf/overview.md), [OCR‑Refactoring](processors/pdf/ocr-refactoring.md), [Endpoints](processors/pdf/endpoints.md)
  - Image‑OCR → [Overview](processors/image-ocr/overview.md)
  - Transformer → [Overview](processors/transformer/overview.md)
  - Session → [Overview](processors/session/overview.md)
  - Event‑Job → [Overview](processors/event-job/overview.md)
  - Story → [Overview](processors/story/overview.md)
  - Track → [Overview](processors/track/overview.md)
- Reference
  - API → [Überblick](reference/api/overview.md), [OpenAPI](reference/api/openapi.md)
- Ops → [Deployment](ops/deployment.md), [Sicherheit](ops/security.md), [Troubleshooting](ops/troubleshooting.md)
- Analysis → [Inventur](
  _analysis/docs_inventory.md), [Routes‑Index](_analysis/routes_index.md), [Drift‑Audit](_analysis/drift_audit.md)

## Response‑Standard (Kurz)
- `status` (success/error), `request`, `process`, `data`, `error`
- LLM‑Tracking: `process.llm_info`, Zeit in Millisekunden

Viel Erfolg!
