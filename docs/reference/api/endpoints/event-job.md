# Event Job API Endpoints (Legacy)

Legacy endpoints for event job management. Consider using `/api/jobs/` endpoints instead.

## POST /api/event-job/jobs

Create a session job.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "event": "Event Name",
  "session": "Session Name",
  "url": "https://example.com/session",
  "filename": "session.md",
  "track": "Track Name",
  "source_language": "en",
  "target_language": "de"
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "status": "pending"
  }
}
```

## GET /api/event-job/jobs/{job_id}

Get job details.

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "status": "completed",
    "progress": {
      "step": "completed",
      "percent": 100
    },
    "results": {
      "markdown_file": "/path/to/output.md",
      "assets": [...]
    }
  }
}
```

## POST /api/event-job/batches

Create a batch of jobs.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "batch_name": "My Batch",
  "jobs": [
    {
      "event": "Event 1",
      "session": "Session 1",
      "url": "https://example.com/session1"
    },
    {
      "event": "Event 2",
      "session": "Session 2",
      "url": "https://example.com/session2"
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
    "batch_name": "My Batch",
    "status": "pending",
    "job_count": 2
  }
}
```

## GET /api/event-job/batches/{batch_id}

Get batch details.

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
    "jobs": [...]
  }
}
```

## GET /api/event-job/files/{path}

Download a job file.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/event-job/files/path/to/file.md" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o file.md
```

### Response

Returns file as binary download.

## POST /api/event-job/{job_id}/restart

Restart a failed job.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/event-job/job-id-123/restart" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "status": "pending",
    "message": "Job restarted"
  }
}
```

## GET /api/event-job/batches/{batch_id}/archive

Download batch archive (ZIP).

### Request Example

```bash
curl -X GET "http://localhost:5001/api/event-job/batches/batch-id-123/archive" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o batch.zip
```

### Response

Returns ZIP file as binary download.

## POST /api/event-job/batches/{batch_id}/toggle-active

Toggle batch active status.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/event-job/batches/batch-id-123/toggle-active" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "batch_id": "batch-id-123",
    "active": false,
    "message": "Batch status toggled"
  }
}
```

## POST /api/event-job/batches/fail-all

Fail all jobs in a batch.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "batch_id": "batch-id-123",
  "reason": "Manual failure"
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "batch_id": "batch-id-123",
    "failed_count": 2,
    "message": "All jobs failed"
  }
}
```

## GET /api/event-job/jobs/{job_id}/download-archive

Download job archive (ZIP).

### Request Example

```bash
curl -X GET "http://localhost:5001/api/event-job/jobs/job-id-123/download-archive" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o archive.zip
```

### Response

Returns ZIP file as binary download.

