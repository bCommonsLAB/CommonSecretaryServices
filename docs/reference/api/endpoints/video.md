# Video API Endpoints

Endpoints for video file processing, YouTube video processing, and frame extraction.
Analog zu Audio: Mit `callback_url` wird die Verarbeitung **asynchron** per Webhook ausgeliefert.

## POST /api/video/process

Process a video file with audio extraction and transcription.
Unterstützt Datei-Upload, Video-URL und asynchrone Verarbeitung per Webhook.

### Request

**Content-Type**: `multipart/form-data` oder `application/json`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | No* | - | Video file (MP4, MOV, WebM, etc.) |
| `url` | String | No* | - | Video URL (alternative to file upload) |
| `source_language` | String | No | `auto` | Source language for transcription |
| `target_language` | String | No | `de` | Target language for translation |
| `template` | String | No | - | Optional template name |
| `useCache` | Boolean | No | `true` | Whether to use cache |
| `force_refresh` | Boolean | No | `false` | Cache ignorieren |
| `callback_url` | String | No | - | If set: **asynchronous** processing, results via webhook (HTTP 202) |
| `callback_token` | String | No | - | Optional token for webhook auth |
| `jobId` | String | No | - | Optional external job id (returned in 202 ACK) |

*Either `file` or `url` must be provided.

**Upload-Limit**: Standard 100 MB. Über Umgebungsvariable `MAX_UPLOAD_SIZE_MB` (z.B. `500`) erhöhen. Bei 413 Request Entity Too Large: Limit erhöhen oder `url` statt Datei-Upload nutzen.

### Request Example (File Upload, Sync)

```bash
curl -X POST "http://localhost:5001/api/video/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@video.mp4" \
  -F "source_language=en" \
  -F "target_language=de"
```

### Request Example (Async via Webhook)

```bash
curl -X POST "http://localhost:5001/api/video/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@video.mp4" \
  -F "source_language=en" \
  -F "target_language=de" \
  -F "callback_url=https://your-client.example.com/webhook/video" \
  -F "callback_token=YOUR_WEBHOOK_TOKEN" \
  -F "jobId=client-job-123"
```

### Request Example (URL)

```bash
curl -X POST "http://localhost:5001/api/video/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/video.mp4",
    "source_language": "en",
    "target_language": "de"
  }'
```

### Response (Success, Sync)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "data": {
    "metadata": { "title": "...", "duration": 300, ... },
    "transcription": { "text": "Transcribed text...", ... }
  }
}
```

### Response (Accepted, Async)

**Status Code**: `202 Accepted`

```json
{
  "status": "accepted",
  "worker": "secretary",
  "process": {
    "id": "process-id-123",
    "main_processor": "video",
    "started": "2026-01-01T00:00:00Z",
    "is_from_cache": false
  },
  "job": { "id": "client-job-123" },
  "webhook": { "delivered_to": "https://your-client.example.com/webhook/video" },
  "error": null
}
```

### Webhook Payload (Async Completion)

```json
{
  "phase": "completed",
  "message": "Video-Verarbeitung abgeschlossen",
  "job": { "id": "client-job-123" },
  "data": {
    "transcription": { "text": "..." },
    "result": { ... }
  }
}
```

### Webhook Payload (Async Error)

Bei Fehlern wird ein Error-Webhook gesendet:

```json
{
  "phase": "error",
  "message": "Video-Verarbeitung fehlgeschlagen",
  "job": { "id": "client-job-123" },
  "error": {
    "code": "RuntimeError",
    "message": "Fehlermeldung",
    "details": { "traceback": "..." }
  },
  "data": null
}
```

### Job Status / Full Results

Für async Jobs: `GET /api/jobs/<job_id>`

---

## POST /api/video/youtube

Process a YouTube video with download and transcription.
Mit `callback_url`: asynchrone Verarbeitung per Webhook.

### Request

**Content-Type**: `multipart/form-data` oder `application/json`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | String | Yes | - | YouTube video URL |
| `source_language` | String | No | `auto` | Source language |
| `target_language` | String | No | `de` | Target language |
| `template` | String | No | `youtube` | Optional template |
| `useCache` | Boolean | No | `true` | Whether to use cache |
| `callback_url` | String | No | - | If set: async, results via webhook (HTTP 202) |
| `callback_token` | String | No | - | Optional token for webhook auth |
| `jobId` | String | No | - | Optional external job id |

### Request Example (Sync)

```bash
curl -X POST "http://localhost:5001/api/video/youtube" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://www.youtube.com/watch?v=VIDEO_ID" \
  -F "source_language=en"
```

### Request Example (Async via Webhook)

```bash
curl -X POST "http://localhost:5001/api/video/youtube" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://www.youtube.com/watch?v=VIDEO_ID" \
  -F "source_language=en" \
  -F "callback_url=https://your-client.example.com/webhook/youtube" \
  -F "callback_token=YOUR_WEBHOOK_TOKEN" \
  -F "jobId=client-job-123"
```

### Response (Success)

```json
{
  "status": "success",
  "request": { ... },
  "process": { ... },
  "data": {
    "metadata": {
      "title": "Video Title",
      "video_id": "VIDEO_ID",
      "duration": 600,
      "uploader": "Channel Name",
      "view_count": 10000,
      "description": "Video description..."
    },
    "transcription": {
      "text": "Transcribed text...",
      "segments": [ { "text": "...", "start": 0.0, "end": 5.0, ... } ],
      "detected_language": "en"
    },
    "process_id": "...",
    "processed_at": "2026-01-01T00:00:00",
    "status": "success"
  },
  "error": null
}
```

### Response (Accepted, Async)

**Status Code**: `202 Accepted` – analog zu `/process` mit `job`, `webhook`, `process`.

### Webhook Payload (YouTube)

Analog zu `/process`: `phase: "completed"` mit `data.transcription.text` und `data.result`; bei Fehler `phase: "error"` mit `error` und `data: null`.

## POST /api/video/frames

Extract frames from a video at fixed interval.
*(Kein Webhook/Async – synchroner Endpoint.)*

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | No* | - | Video file |
| `url` | String | No* | - | Video URL (alternative) |
| `interval_seconds` | Integer | No | `5` | Extract frame every N seconds |
| `width` | Integer | No | - | Target width (optional) |
| `height` | Integer | No | - | Target height (optional) |
| `format` | String | No | `jpg` | Image format (jpg/png) |
| `useCache` | Boolean | No | `true` | Whether to use cache |

*Either `file` or `url` must be provided.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/video/frames" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@video.mp4" \
  -F "interval_seconds=10"
```

### Response (Success)

```json
{
  "status": "success",
  "request": { ... },
  "process": { ... },
  "data": {
    "metadata": { ... },
    "process_id": "...",
    "output_dir": "/path/to/output",
    "interval_seconds": 10,
    "frame_count": 2,
    "frames": [
      {
        "index": 0,
        "timestamp_s": 10.0,
        "file_path": "/path/to/frame_10.jpg",
        "width": null,
        "height": null
      },
      {
        "index": 1,
        "timestamp_s": 20.0,
        "file_path": "/path/to/frame_20.jpg",
        "width": null,
        "height": null
      }
    ]
  },
  "error": null
}
```

