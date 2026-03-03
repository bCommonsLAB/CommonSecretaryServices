# Job Management API Endpoints

Endpoints for managing asynchronous jobs (Secretary Job Worker).

## POST /api/jobs/

Create a new job for asynchronous processing.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "job_type": "pdf",
  "parameters": {
    "filename": "/path/to/file.pdf",
    "extraction_method": "combined",
    "template": "MeetingMinutes",
    "use_cache": true
  },
  "user_id": "optional-user-id"
}
```

### Supported Job Types

- `pdf`: PDF processing (see [PDF Handler documentation](../../../explanations/async-events/handlers.md))
- `session`: Session processing
- `transformer`: Template transformation

### Request Example

```bash
curl -X POST "http://localhost:5001/api/jobs/" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "pdf",
    "parameters": {
      "filename": "/path/to/file.pdf",
      "extraction_method": "combined"
    }
  }'
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "job": {
      "job_id": "job-id-123",
      "job_type": "pdf",
      "status": "pending",
      "created_at": "2024-01-01T00:00:00Z",
      "parameters": {...}
    }
  }
}
```

## POST /api/jobs/batch

Create a batch of jobs for parallel processing.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "batch_name": "My Batch",
  "jobs": [
    {
      "job_type": "pdf",
      "parameters": {
        "filename": "/path/to/file1.pdf"
      }
    },
    {
      "job_type": "pdf",
      "parameters": {
        "filename": "/path/to/file2.pdf"
      }
    }
  ]
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "batch_id": "batch-id-123",
    "batch": {
      "batch_id": "batch-id-123",
      "batch_name": "My Batch",
      "status": "pending",
      "job_count": 2,
      "jobs": [...]
    }
  }
}
```

## GET /api/jobs/{job_id}

Get job status and results.

### Request

**URL Parameters**:
- `job_id`: Job identifier

### Request Example

```bash
curl -X GET "http://localhost:5001/api/jobs/job-id-123" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "job_type": "pdf",
    "status": "completed",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:05:00Z",
    "progress": {
      "step": "completed",
      "percent": 100,
      "message": "Processing completed"
    },
    "results": {
      "structured_data": {
        "extracted_text": "...",
        "metadata": {...}
      },
      "assets": ["/path/to/image1.jpg"],
      "target_dir": "/path/to/results"
    },
    "logs": [
      {
        "timestamp": "2024-01-01T00:00:00Z",
        "level": "info",
        "message": "Job started"
      }
    ]
  }
}
```

### Job Status Values

- `pending`: Job is waiting to be processed
- `processing`: Job is currently being processed
- `completed`: Job completed successfully
- `failed`: Job failed with an error

## GET /api/jobs/batch/{batch_id}

Get batch status and all jobs in the batch.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/jobs/batch/batch-id-123" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "batch_id": "batch-id-123",
    "batch_name": "My Batch",
    "status": "completed",
    "job_count": 2,
    "completed_count": 2,
    "failed_count": 0,
    "jobs": [
      {
        "job_id": "job-1",
        "status": "completed"
      },
      {
        "job_id": "job-2",
        "status": "completed"
      }
    ]
  }
}
```

## GET /api/jobs/{job_id}/download-archive

Download job archive (ZIP file) if available.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/jobs/job-id-123/download-archive" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o archive.zip
```

### Response

Returns ZIP file as binary download.

## Webhook Integration

Jobs can be configured with webhooks for completion notifications.

### Webhook Configuration

Include `webhook` in job parameters:

```json
{
  "job_type": "pdf",
  "parameters": {
    "filename": "/path/to/file.pdf",
    "webhook": {
      "url": "https://example.com/webhook",
      "token": "webhook_auth_token",
      "jobId": "client_job_id"
    }
  }
}
```

### Webhook Payload

When job completes, a POST request is sent to the webhook URL:

**Standard PDF Processing**:
```json
{
  "phase": "completed",
  "message": "Processing completed",
  "data": {
    "extracted_text": "...",
    "metadata": {...}
  }
}
```

**Mistral OCR Processing** (with `extraction_method="mistral_ocr_with_pages"`):
```json
{
  "phase": "completed",
  "message": "Extraktion abgeschlossen",
  "data": {
    "extracted_text": "...",
    "metadata": {
      "text_contents": [...]
    },
    "mistral_ocr_raw_url": "/api/pdf/jobs/{job_id}/mistral-ocr-raw",
    "mistral_ocr_raw_metadata": {
      "model": "mistral-ocr-latest",
      "pages_count": 235,
      "usage_info": {...}
    },
    "pages_archive_url": "/api/pdf/jobs/{job_id}/download-pages-archive"
  }
}
```

**Note**: For large documents, `mistral_ocr_raw` is stored as a separate JSON file due to MongoDB size limits. Use `mistral_ocr_raw_url` to download the complete data including all images.

### Progress Webhooks

Progress updates are sent during processing:

```json
{
  "phase": "processing",
  "progress": 50,
  "message": "Extracting text from PDF...",
  "process": {
    "id": "job-id-123"
  }
}
```

## GET /api/jobs/{job_id}/stream

Echtzeit-Updates fuer einen Job via Server-Sent Events (SSE). Ideal fuer Offline-Clients, die keinen Webhook-Endpunkt bereitstellen koennen (z.B. hinter NAT/Firewall).

### Konzept

Der Client oeffnet eine langlebige HTTP-Verbindung zum Server. Der Server pollt intern MongoDB und pusht Events bei Statusaenderungen. Die Verbindung wird automatisch geschlossen, wenn der Job abgeschlossen oder fehlgeschlagen ist.

### Request

**Headers**:
- `Authorization: Bearer YOUR_API_KEY` (erforderlich)
- `Accept: text/event-stream` (empfohlen)

**URL Parameters**:
- `job_id`: Job-ID fuer die Updates gestreamt werden sollen

### Request Example

```bash
curl -N -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:5001/api/jobs/job-id-123/stream"
```

**Hinweis**: `-N` deaktiviert Buffering bei curl, damit Events sofort angezeigt werden.

### Response

**Content-Type**: `text/event-stream`

**Status Code**: `200 OK`

Der Stream sendet SSE-Events im Standard-Format:

### SSE Event Types

#### `pending` - Job wartet auf Verarbeitung

```
event: pending
data: {"phase":"pending","message":"Job wartet auf Verarbeitung","job":{"id":"job-id-123"},"process":{"id":"job-id-123","main_processor":"pdf"},"data":{"progress":0}}
```

#### `progress` - Job wird verarbeitet

```
event: progress
data: {"phase":"running","message":"Transkription laeuft (45%)","job":{"id":"job-id-123"},"process":{"id":"job-id-123","main_processor":"audio"},"data":{"progress":45}}
```

#### `completed` - Job abgeschlossen

```
event: completed
data: {"phase":"completed","message":"Verarbeitung abgeschlossen","job":{"id":"job-id-123"},"process":{"id":"job-id-123","main_processor":"pdf"},"data":{"results":{"markdown_content":"...","structured_data":{...}}}}
```

#### `error` - Job fehlgeschlagen

```
event: error
data: {"phase":"error","message":"Verarbeitung fehlgeschlagen","job":{"id":"job-id-123"},"process":{"id":"job-id-123","main_processor":"pdf"},"error":{"code":"RuntimeError","message":"..."}}
```

#### `timeout` - Stream-Timeout

```
event: timeout
data: {"phase":"timeout","message":"Stream-Timeout nach 300s","job":{"id":"job-id-123"}}
```

Wird gesendet, wenn der Job innerhalb von 5 Minuten nicht abgeschlossen wird. Der Client sollte dann auf Polling (`GET /api/jobs/{job_id}`) umsteigen oder den Stream neu oeffnen.

### Heartbeats

Der Server sendet regelmaessig Heartbeat-Kommentare, um Proxy-/Firewall-Timeouts zu vermeiden:

```
: heartbeat
```

Diese Zeilen sind SSE-Kommentare und werden von SSE-Clients automatisch ignoriert.

### Vergleich: SSE vs. Webhook vs. Polling

| Eigenschaft | Webhook | SSE | Polling |
|---|---|---|---|
| Client muss erreichbar sein | Ja | Nein | Nein |
| Echtzeit-Updates | Ja | Ja | Nein (Intervall) |
| Firewall-freundlich | Nein | Ja | Ja |
| Verbindung | Keine | Langlebig | Kurzlebig |
| Ideal fuer | Server-zu-Server | Offline-Clients | Einfache Clients |

### Typischer Workflow fuer Offline-Clients

SSE ist relevant fuer Endpoints, die immer die Job-Queue nutzen (PDF, Office). Audio, Video und Transformer verarbeiten ohne `callback_url` synchron – dort ist kein SSE noetig.

**Schritt 1**: Datei an den direkten Endpoint senden (ohne `callback_url`):

```bash
curl -X POST "http://localhost:5001/api/pdf/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.pdf" \
  -F "extraction_method=combined"
```

Response (202): `{"status":"accepted","job":{"id":"job-abc-123"},...}`

**Schritt 2**: SSE-Stream mit der `job_id` oeffnen:

```bash
curl -N -H "Authorization: Bearer YOUR_API_KEY" \
  "http://localhost:5001/api/jobs/job-abc-123/stream"
```

**Schritt 3**: Events empfangen bis `completed` oder `error`.

### Endpoint-Verhalten ohne `callback_url`

| Endpoint | Ohne `callback_url` | SSE noetig? |
|---|---|---|
| Audio, Video, Transformer | Synchron (200 + Ergebnis) | Nein |
| PDF, Office | Asynchron (202 + `job_id`) | Ja, oder Polling |

### Client-Implementierung

Siehe [Offline-Client Integration Guide](../../../guide/offline-clients.md) fuer ausfuehrliche Beispiele in Python, JavaScript und C#.

### Hinweise

- **Proxy-Timeouts**: Manche Proxies schliessen langlebige Verbindungen nach 60-120s. Die Heartbeats verhindern dies in den meisten Faellen. Bei Problemen: Reconnect-Logik im Client implementieren.
- **Nginx**: Der Header `X-Accel-Buffering: no` ist gesetzt, um Nginx-Buffering zu deaktivieren.
- **Maximale Dauer**: Der Stream schliesst automatisch nach 5 Minuten. Fuer laenger laufende Jobs: Polling verwenden oder Stream neu oeffnen.
- **Kein Breaking Change**: Dieser Endpoint ist additiv. Bestehende Webhook-Integrationen sind nicht betroffen.

## Related Documentation

- [Secretary Job Worker](../../../explanations/async-events/secretary-job-worker-detailed.md) - Detailed worker documentation
- [Handlers](../../../explanations/async-events/handlers.md) - Handler documentation
- [Offline-Client Integration Guide](../../../guide/offline-clients.md) - SSE/Polling Client-Beispiele

