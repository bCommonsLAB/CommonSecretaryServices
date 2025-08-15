---
status: draft
last_verified: 2025-08-15
---

# Async Events (Überblick)

Ziel: Sessions in Jobs/Batches asynchron verarbeiten, Ergebnisse persistieren (MongoDB), optional Webhooks.

## Bausteine
- API: `/api/event-job/*` (Jobs, Batches, Files)
- Storage: MongoDB (Jobs/Batches/Results)
- Worker: verarbeitet Queue/Jobs (siehe Repository/Worker‑Manager)

## Kernablauf
1) Client erstellt Job oder Batch (`POST /api/event-job/jobs|batches`)
2) Worker nimmt Jobs auf, verarbeitet (Scrape → Audio/Video/PDF → Transformer)
3) Ergebnisse landen im Job (`results`, Markdown/Assets/Archive)
4) Optionaler Webhook erhält Callback

```mermaid
flowchart LR
  A[Client] --> B[/POST /api/event-job/submit/]
  B --> C[Queue/DB]
  C -->|Worker| D[EventProcessor]
  D --> E[(Cache/Mongo)]
  D --> F[Prozessoren: Video/Audio/PDF/...]
  F --> D
  D --> G[/GET /api/event-job/status/{id}/]
  G --> H[Result JSON/ZIP]
```

## Endpunkte (Auszug)
- Jobs: `POST/GET /api/event-job/jobs`, `GET/DELETE /api/event-job/jobs/{job_id}`
- Batch: `POST/GET /api/event-job/batches`, `GET/DELETE /api/event-job/batches/{batch_id}`
- Steuerung: `POST /api/event-job/batches/{id}/archive`, `POST /api/event-job/batches/{id}/toggle-active`, `POST /api/event-job/{job_id}/restart`
- Download: `GET /api/event-job/jobs/{job_id}/download-archive`

## Beispiel: Batch anlegen
```bash
curl -X POST http://localhost:5000/api/event-job/batches \
  -H 'Content-Type: application/json' \
  -d '{
    "batch_name": "FOSDEM ecosocial",
    "jobs": [
      {"parameters": {"event":"FOSDEM","session":"T1","url":"https://...","filename":"t1.md","track":"ecosocial"}},
      {"parameters": {"event":"FOSDEM","session":"T2","url":"https://...","filename":"t2.md","track":"ecosocial"}}
    ],
    "webhook": {"url": "https://example.org/hook"}
  }'
```

## Status/Verwaltung
- Job: `status`, `progress`, `results`, `error`, `batch_id`, `user_id`
- Batch: `status`, `completed_jobs/failed_jobs`, `isActive`, `archived`
- Zugriff: optional via `X-User-ID` (Lesen/Schreiben)

## Hinweise
- `use_cache` steuert Wiederverwendung; Neustart per `POST /api/event-job/{job_id}/restart`
- Archivieren ändert den Lebenszyklus, löscht keine Ergebnisse
