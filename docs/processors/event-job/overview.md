---
status: draft
last_verified: 2025-08-15
---

# Event-Job API

## Endpunkte (Auszug)
- Jobs
  - POST `/api/event-job/jobs` (Job erstellen)
  - GET  `/api/event-job/jobs` (Jobs auflisten, Filter: status, batch_id, user_id, limit, skip)
  - GET  `/api/event-job/jobs/{job_id}` (Details)
  - DELETE `/api/event-job/jobs/{job_id}` (löschen)
  - GET  `/api/event-job/jobs/{job_id}/download-archive` (ZIP)
- Batches
  - POST `/api/event-job/batches` (Batch erstellen)
  - GET  `/api/event-job/batches` (Batches auflisten)
  - GET  `/api/event-job/batches/{batch_id}` (Details)
  - DELETE `/api/event-job/batches/{batch_id}` (löschen)
  - POST `/api/event-job/batches/{batch_id}/archive` (archivieren)
  - POST `/api/event-job/batches/{batch_id}/toggle-active` (aktiv/inaktiv)
  - POST `/api/event-job/batches/fail-all` (alle auf failed setzen)
- Dateien
  - GET  `/api/event-job/files/{path}` (Dateien bereitstellen)

## Beispiele (cURL)

Job erstellen:
```bash
curl -X POST http://localhost:5000/api/event-job/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "parameters": {
      "event": "FOSDEM 2025",
      "session": "Talk 01",
      "url": "https://example.org/session",
      "filename": "Talk_01.md",
      "track": "ecosocial",
      "use_cache": true
    },
    "job_name": "FOSDEM - ecosocial - Talk 01"
  }'
```

Batch erstellen:
```bash
curl -X POST http://localhost:5000/api/event-job/batches \
  -H 'Content-Type: application/json' \
  -d '{
    "batch_name": "FOSDEM ecosocial",
    "jobs": [
      {"parameters": {"event":"FOSDEM","session":"T1","url":"https://...","filename":"t1.md","track":"ecosocial"}},
      {"parameters": {"event":"FOSDEM","session":"T2","url":"https://...","filename":"t2.md","track":"ecosocial"}}
    ]
  }'
```

ZIP herunterladen:
```bash
curl -L -o result.zip http://localhost:5000/api/event-job/jobs/<JOB_ID>/download-archive
```

## Hinweise
- Zugriffskontrolle per `X-User-ID` Header berücksichtigt.
- Rückgaben enthalten Status und Daten; Fehler liefern `status: error` mit Details.

## Troubleshooting (Kurz)
- 404 beim ZIP-Download: Prüfe, ob der Job Ergebnisse und ein Archiv enthält.
- 403 bei Details/Löschen: `X-User-ID` stimmt nicht mit `job.user_id` überein oder fehlt Schreib-/Leserechte.
