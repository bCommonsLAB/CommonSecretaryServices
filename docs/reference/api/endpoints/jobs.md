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

## Related Documentation

- [Secretary Job Worker](../../../explanations/async-events/secretary-job-worker-detailed.md) - Detailed worker documentation
- [Handlers](../../../explanations/async-events/handlers.md) - Handler documentation

