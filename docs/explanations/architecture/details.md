---
status: draft
last_verified: 2025-08-15
---

# Architektur (Details)

## Komponenten und Codepfade
- API Routing: `src/api/routes/__init__.py` (Registrierung aller Namespaces unter `/api/*`)
- Prozessoren: `src/processors/*` (Audio, Video, PDF, Image‑OCR, Transformer, Metadata, Session)
- Modelle/Typen: `src/core/models/*`
- MongoDB/Jobs: `src/core/mongodb/*`

## Flows (vereinfacht)
- Video: URL/Upload → `VideoProcessor` → Audio → `TransformerProcessor` → Ergebnis
- PDF/Image‑OCR: Datei/URL → (Native/Tesseract/LLM) → Markdown/Text → optional Transformer
- Async: Client → `/api/event-job/*` → Worker → Ergebnisse (Markdown/ZIP) in MongoDB

## Prinzipien
- Standardisierte Responses (`status/request/process/data/error`)
- LLM‑Tracking in `process.llm_info`
- Caching (Datei/MongoDB) mit deterministischen Keys

Weitere Übersichten: siehe `explanations/architecture/overview.md`.
