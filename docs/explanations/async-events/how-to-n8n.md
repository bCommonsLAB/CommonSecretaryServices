---
status: draft
last_verified: 2025-08-15
---

# How‑To: Async Batches mit n8n

1) HTTP Node: `POST /api/event-job/batches`
2) Webhook (optional): URL in `webhook.url` setzen
3) Polling/Status: `GET /api/event-job/batches/{id}` oder `GET /api/event-job/jobs?batch_id=...`

Beispiel‑Payload:
```json
{
  "batch_name": "FOSDEM ecosocial",
  "jobs": [
    {"parameters": {"event":"FOSDEM","session":"T1","url":"https://...","filename":"t1.md","track":"ecosocial"}},
    {"parameters": {"event":"FOSDEM","session":"T2","url":"https://...","filename":"t2.md","track":"ecosocial"}}
  ],
  "webhook": {"url": "https://example.org/hook"}
}
```

Relevanter Code: `src/api/routes/event_job_routes.py`.
