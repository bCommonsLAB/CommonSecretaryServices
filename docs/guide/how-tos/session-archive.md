---
status: draft
last_verified: 2025-08-15
---

# How‑To: Session‑Archive herunterladen

1) Job anlegen (`POST /api/event-job/jobs`) oder Batch (`POST /api/event-job/batches`).
2) Verarbeiten lassen; `job_id` merken.
3) ZIP herunterladen: `GET /api/event-job/jobs/{job_id}/download-archive`.

Beispiel (curl):
```bash
curl -L -o result.zip http://localhost:5000/api/event-job/jobs/<JOB_ID>/download-archive
```
