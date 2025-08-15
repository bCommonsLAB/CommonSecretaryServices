---
status: draft
last_verified: 2025-08-15
---

# Session Processor

## Endpunkte
- POST `/api/session/process`
- POST `/api/session/process-async` (Platzhalter)
- GET  `/api/session/cached`

## POST /api/session/process (JSON)
Pflichtfelder: `event`, `session`, `url`, `filename`, `track`
Optionale Felder: `day`, `starttime`, `endtime`, `speakers`, `video_url`, `attachments_url`, `source_language`, `target_language`, `target`, `template`, `use_cache`, `create_archive`

Beispiel (Kurz):
```bash
curl -X POST http://localhost:5000/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{"event":"FOSDEM","session":"Talk","url":"https://...","filename":"talk.md","track":"ecosocial"}'
```

## GET /api/session/cached
Gibt eine flache Liste gecachter Sessions zurück.
