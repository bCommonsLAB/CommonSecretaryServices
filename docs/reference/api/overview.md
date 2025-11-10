# API Reference Overview

Complete API reference for Common Secretary Services. All endpoints require authentication via API key unless otherwise noted.

## Authentication

All API requests require authentication via one of the following methods:

- **Header**: `Authorization: Bearer <token>`
- **Alternative Header**: `X-Secretary-Api-Key: <token>`

The API key is configured via the `SECRETARY_SERVICE_API_KEY` environment variable.

### Exempt Paths

The following paths do not require authentication:
- `/api/doc` - Swagger UI documentation
- `/api/swagger.json` - OpenAPI specification
- `/api/health` - Health check endpoints

## Base URL

All endpoints are prefixed with `/api`. For example:
- Production: `https://commonsecretaryservices.bcommonslab.org/api`
- Local: `http://localhost:5001/api`

## Interactive Documentation

The complete interactive API documentation is available via **Swagger UI** at:
- `/api/doc` - Interactive API explorer

## API Endpoints by Category

### Audio Processing

**Namespace**: `/api/audio`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/audio/process` | Process audio file with transcription and optional translation |

**See**: [Audio Endpoints](endpoints/audio.md) for detailed documentation.

### Video Processing

**Namespace**: `/api/video`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/video/process` | Process video file with audio extraction and transcription |
| POST | `/api/video/youtube` | Process YouTube video with download and transcription |
| POST | `/api/video/frames` | Extract frames from video at specific timestamps |

**See**: [Video Endpoints](endpoints/video.md) for detailed documentation.

### PDF Processing

**Namespace**: `/api/pdf`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/pdf/process` | Process PDF file with text extraction and OCR |
| POST | `/api/pdf/job` | Process PDF asynchronously as a job |

**See**: [PDF Endpoints](endpoints/pdf.md) for detailed documentation.

### Image OCR

**Namespace**: `/api/imageocr`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/imageocr/process` | Process image file with OCR |
| POST | `/api/imageocr/process-url` | Process image from URL with OCR |

**See**: [ImageOCR Endpoints](endpoints/imageocr.md) for detailed documentation.

### Text Transformation

**Namespace**: `/api/transformer`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/transformer/text` | Translate text between languages |
| POST | `/api/transformer/template` | Transform text using template |
| POST | `/api/transformer/summarize` | Summarize text |
| POST | `/api/transformer/html-to-markdown` | Convert HTML to Markdown |
| POST | `/api/transformer/extract-tables` | Extract tables from HTML |

**See**: [Transformer Endpoints](endpoints/transformer.md) for detailed documentation.

### Session Processing

**Namespace**: `/api/session`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/session/process` | Process session with URL and associated media |
| POST | `/api/session/process-async` | Process session asynchronously with webhook |
| GET | `/api/session/cached` | Retrieve cached sessions |

**See**: [Session Endpoints](endpoints/session.md) for detailed documentation.

### Event Processing

**Namespace**: `/api/events`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/events/<event_name>/summary` | Generate event summary |

**See**: [Event Endpoints](endpoints/event.md) for detailed documentation.

### Track Processing

**Namespace**: `/api/tracks`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/tracks/<track_name>/summary` | Generate track summary |
| GET | `/api/tracks/available` | List all available tracks |
| POST | `/api/tracks/<track_name>/summarize_all` | Summarize all tracks |

**See**: [Track Endpoints](endpoints/track.md) for detailed documentation.

### Story Generation

**Namespace**: `/api/story`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/story/generate` | Generate story from topic |
| GET | `/api/story/topics` | List all available topics |
| GET | `/api/story/target-groups` | List all available target groups |

**See**: [Story Endpoints](endpoints/story.md) for detailed documentation.

### Job Management (Secretary Jobs)

**Namespace**: `/api/jobs`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/jobs/` | Create new job |
| POST | `/api/jobs/batch` | Create batch of jobs |
| GET | `/api/jobs/<job_id>` | Get job status and results |
| GET | `/api/jobs/batch/<batch_id>` | Get batch status |
| GET | `/api/jobs/<job_id>/download-archive` | Download job archive (ZIP) |

**See**: [Job Endpoints](endpoints/jobs.md) for detailed documentation.

### Event Job Management (Legacy)

**Namespace**: `/api/event-job`

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/event-job/jobs` | Create session job |
| GET | `/api/event-job/jobs/<job_id>` | Get job details |
| POST | `/api/event-job/batches` | Create batch |
| GET | `/api/event-job/batches/<batch_id>` | Get batch details |
| GET | `/api/event-job/files/<path>` | Download job file |
| POST | `/api/event-job/<job_id>/restart` | Restart failed job |
| GET | `/api/event-job/batches/<batch_id>/archive` | Download batch archive |
| POST | `/api/event-job/batches/<batch_id>/toggle-active` | Toggle batch active status |
| POST | `/api/event-job/batches/fail-all` | Fail all jobs in batch |
| GET | `/api/event-job/jobs/<job_id>/download-archive` | Download job archive |

**See**: [Event Job Endpoints](endpoints/event-job.md) for detailed documentation.

### Common Endpoints

**Namespace**: `/api/common`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/common/` | API home endpoint |
| POST | `/api/common/notion` | Process Notion blocks |
| GET | `/api/common/samples` | List sample files |
| GET | `/api/common/samples/<filename>` | Download sample file |

**See**: [Common Endpoints](endpoints/common.md) for detailed documentation.

### Root Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/` | API welcome message |

## Response Format

All API responses follow a standardized format:

```json
{
  "status": "success" | "error",
  "request": {
    "id": "process-id",
    "timestamp": "2024-01-01T00:00:00Z"
  },
  "process": {
    "duration_ms": 1234,
    "llm_info": {
      "total_tokens": 1000,
      "total_cost": 0.01,
      "requests": [...]
    }
  },
  "data": {
    // Processor-specific data
  },
  "error": {
    "code": "ERROR_CODE",
    "message": "Error message",
    "details": {}
  }
}
```

## Error Handling

Errors are returned with HTTP status codes:

- `400` - Bad Request (validation errors)
- `401` - Unauthorized (authentication required)
- `403` - Forbidden (authentication failed)
- `404` - Not Found (resource not found)
- `500` - Internal Server Error (processing errors)

Error responses include:
- `code`: Error code identifier
- `message`: Human-readable error message
- `details`: Additional error information

## Rate Limiting

Rate limiting is configured via `config.yaml`:
- Default: 60 requests per minute per IP
- Configurable via `rate_limiting.requests_per_minute`

## Caching

Most processors support caching:
- Results are cached in MongoDB
- Cache TTL is configurable per processor
- Use `useCache=false` parameter to bypass cache

## Asynchronous Processing

Some endpoints support asynchronous processing:
- Jobs are created and processed in the background
- Status can be queried via job endpoints
- Webhooks can be configured for completion notifications

## Related Documentation

- [OpenAPI / Swagger](openapi.md) - Interactive API documentation
- [Data Models](../data-models/index.md) - Response data structures
- [Configuration](../configuration.md) - Configuration options

