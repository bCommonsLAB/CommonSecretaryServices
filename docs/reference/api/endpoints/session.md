# Session API Endpoints

Endpoints for processing session information and associated media.

## POST /api/session/process

Process a session with URL and associated media.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "event": "Event Name",
  "session": "Session Name",
  "url": "https://example.com/session-page",
  "filename": "session_output.md",
  "track": "Track Name",
  "day": "2024-01-01",
  "starttime": "10:00",
  "endtime": "11:30",
  "speakers": ["Speaker 1", "Speaker 2"],
  "speakers_url": ["https://example.com/speaker1", "https://example.com/speaker2"],
  "speakers_image_url": ["https://example.com/speaker1.jpg"],
  "video_url": "https://example.com/video.mp4",
  "attachments_url": "https://example.com/attachments.zip",
  "source_language": "en",
  "target_language": "de",
  "template": "Session",
  "create_archive": true,
  "use_cache": true
}
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/session/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event": "Conference 2024",
    "session": "Keynote",
    "url": "https://example.com/session",
    "filename": "keynote.md",
    "track": "Main Track"
  }'
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "output": {
      "markdown_file": "/path/to/keynote.md",
      "markdown_content": "# Session Content...",
      "attachments": ["/path/to/video.mp4", "/path/to/slides.pdf"],
      "video_transcript": "Transcribed video content...",
      "attachments_text": "Extracted text from attachments...",
      "target_dir": "/path/to/session/output"
    }
  }
}
```

## POST /api/session/process-async

Process session asynchronously with webhook callback.

### Request

Same as `/api/session/process`, but processing happens in background.

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "status": "pending",
    "message": "Session processing started"
  }
}
```

### Webhook Callback

When processing completes, a POST request is sent to the configured webhook URL:

```json
{
  "phase": "completed",
  "message": "Session processing completed",
  "data": {
    "markdown_file": "/path/to/output.md",
    "attachments": [...]
  }
}
```

## GET /api/session/cached

Retrieve all cached sessions.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/session/cached" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "sessions": [
      {
        "event": "Conference 2024",
        "session": "Keynote",
        "url": "https://example.com/session",
        "cached_at": "2024-01-01T00:00:00Z"
      }
    ]
  }
}
```

