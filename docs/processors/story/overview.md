---
status: draft
last_verified: 2025-08-15
---

# Story Processor

## Endpunkte
- POST `/api/story/generate`
- GET  `/api/story/topics`
- GET  `/api/story/target-groups`

## Nutzung (Kurz)
- `generate`: erzeugt Story‑Inhalte aus Eingaben/Kontexten (Thema, Zielgruppe, Event/Session‑Daten)
- `topics`, `target-groups`: unterstützen UI/Dropdowns

## Hinweise
- Einheitliche Response‑Struktur (`status/request/process/data/error`)
- LLM‑Tracking in `process.llm_info`
