# Secretary Job Worker - Detailed Documentation

Complete documentation of the Secretary Job Worker system for asynchronous job processing.

## Overview

The Secretary Job Worker is a generic background worker system that processes jobs asynchronously. It polls MongoDB for pending jobs and routes them to appropriate handlers based on `job_type`.

## Architecture

### Components

1. **SecretaryWorkerManager**: Main worker manager that polls and routes jobs
2. **Processor Registry**: Maps `job_type` strings to handler functions
3. **Handlers**: Async functions that process specific job types
4. **SecretaryJobRepository**: MongoDB repository for job management

### Job Lifecycle

```
PENDING → PROCESSING → COMPLETED/FAILED
```

1. **PENDING**: Job is created and waiting to be processed
2. **PROCESSING**: Job is currently being processed by a handler
3. **COMPLETED**: Job completed successfully with results
4. **FAILED**: Job failed with error information

## Configuration

Configure the worker in `config.yaml`:

```yaml
generic_worker:
  active: true
  max_concurrent: 3
  poll_interval_sec: 5
```

### Parameters

- **active**: Enable/disable the worker
- **max_concurrent**: Maximum concurrent jobs
- **poll_interval_sec**: Polling interval in seconds

## Job Creation

### Via API

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

### Job Structure

```json
{
  "job_id": "job-123",
  "job_type": "pdf",
  "status": "pending",
  "parameters": {
    "filename": "/path/to/file.pdf",
    "extraction_method": "combined",
    "template": "MeetingMinutes"
  },
  "created_at": "2024-01-01T00:00:00Z"
}
```

## Handler Registry

Handlers are registered at module import time:

```python
from src.core.processing.registry import register
from src.core.processing.handlers.pdf_handler import handle_pdf_job

register("pdf", handle_pdf_job)
```

### Handler Signature

```python
async def handle_job(
    job: Job,
    repo: SecretaryJobRepository,
    resource_calculator: ResourceCalculator
) -> None:
    # Process job
    pass
```

## Available Handlers

### PDF Handler (`pdf`)

Processes PDF files with text extraction and OCR.

**Parameters**:
- `filename` or `url`: PDF file path or URL
- `extraction_method`: `native`, `ocr`, `mistral_ocr`, `openai_vision`, `combined`
- `template`: Optional template name
- `context`: Optional context for template
- `use_cache`: Whether to use cache

### Session Handler (`session`)

Processes session information with associated media.

**Parameters**:
- `event`: Event name
- `session`: Session name
- `url`: Session URL
- `filename`: Output filename
- `track`: Track name
- Additional session parameters

### Transformer Handler (`transformer`)

Processes text transformation with templates.

**Parameters**:
- `text`: Text to transform
- `url`: URL to fetch text from (alternative to text)
- `template`: Template name
- `context`: Context for template
- `source_language`: Source language
- `target_language`: Target language

## Progress Tracking

Jobs support progress tracking:

```python
repo.update_job_progress(
    job_id="job-123",
    progress=JobProgress(
        step="extracting_text",
        percent=50,
        message="Extracting text from PDF..."
    )
)
```

### Progress Updates

Progress is updated during processing:
- `0%`: Initialization
- `25%`: Reading file
- `50%`: Processing
- `75%`: Finalizing
- `100%`: Completed

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

When job completes, a POST request is sent:

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

### Progress Webhooks

Progress updates are sent during processing:

```json
{
  "phase": "processing",
  "progress": 50,
  "message": "Extracting text from PDF...",
  "process": {
    "id": "job-123"
  }
}
```

## Error Handling

Jobs track errors:

```python
repo.update_job_error(
    job_id="job-123",
    error=JobError(
        code="PROCESSING_ERROR",
        message="Failed to extract text",
        details={"error_type": "OCR_ERROR"}
    )
)
```

### Error Structure

```json
{
  "code": "PROCESSING_ERROR",
  "message": "Error message",
  "details": {
    "error_type": "OCR_ERROR",
    "traceback": "..."
  }
}
```

## Logging

Jobs maintain log entries:

```python
repo.add_log_entry(
    job_id="job-123",
    level="info",
    message="Processing started"
)
```

### Log Levels

- `debug`: Debug information
- `info`: General information
- `warning`: Warnings
- `error`: Errors
- `critical`: Critical errors

## Job Status Query

Query job status via API:

```bash
curl -X GET "http://localhost:5001/api/jobs/job-123" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response

```json
{
  "status": "success",
  "data": {
    "job_id": "job-123",
    "job_type": "pdf",
    "status": "completed",
    "progress": {
      "step": "completed",
      "percent": 100,
      "message": "Processing completed"
    },
    "results": {
      "extracted_text": "...",
      "metadata": {...}
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

## Creating Custom Handlers

### 1. Create Handler Function

```python
from src.core.models.job_models import Job, JobProgress
from src.core.resource_tracking import ResourceCalculator

async def handle_custom_job(
    job: Job,
    repo: Any,
    resource_calculator: ResourceCalculator
) -> None:
    # Update progress
    repo.update_job_progress(
        job.job_id,
        JobProgress(step="processing", percent=0)
    )
    
    # Process job
    params = job.parameters
    result = process_custom(params)
    
    # Store results
    repo.update_job_results(
        job.job_id,
        {"result": result}
    )
    
    # Mark as completed
    repo.update_job_status(
        job.job_id,
        JobStatus.COMPLETED
    )
```

### 2. Register Handler

```python
from src.core.processing.registry import register

register("custom", handle_custom_job)
```

### 3. Create Job

```bash
curl -X POST "http://localhost:5001/api/jobs/" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "job_type": "custom",
    "parameters": {
      "input": "data"
    }
  }'
```

## Related Documentation

- [Handlers](handlers.md) - Detailed handler documentation
- [Generic Worker](generic-worker.md) - Worker overview
- [Job API Endpoints](../../reference/api/endpoints/jobs.md) - API documentation

