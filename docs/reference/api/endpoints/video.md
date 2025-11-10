# Video API Endpoints

Endpoints for video file processing, YouTube video processing, and frame extraction.

## POST /api/video/process

Process a video file with audio extraction and transcription.

### Request

**Content-Type**: `multipart/form-data` or `application/json`

**Parameters** (Form Data):

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | No* | - | Video file (MP4, MOV, WebM, etc.) |
| `url` | String | No* | - | Video URL (alternative to file upload) |
| `source_language` | String | No | `de` | Source language for transcription |
| `target_language` | String | No | `de` | Target language for translation |
| `template` | String | No | `""` | Optional template name |
| `useCache` | Boolean | No | `true` | Whether to use cache |

*Either `file` or `url` must be provided.

### Request Example (File Upload)

```bash
curl -X POST "http://localhost:5001/api/video/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@video.mp4" \
  -F "source_language=en" \
  -F "target_language=de"
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

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "duration": 300.0,
    "transcription": "Transcribed text from video audio...",
    "metadata": {
      "resolution": "1920x1080",
      "codec": "h264",
      "fps": 30
    }
  }
}
```

## POST /api/video/youtube

Process a YouTube video with download and transcription.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | String | Yes | - | YouTube video URL |
| `source_language` | String | No | `de` | Source language |
| `target_language` | String | No | `de` | Target language |
| `template` | String | No | `""` | Optional template |

### Request Example

```bash
curl -X POST "http://localhost:5001/api/video/youtube" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://www.youtube.com/watch?v=VIDEO_ID" \
  -F "source_language=en"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "video_id": "VIDEO_ID",
    "title": "Video Title",
    "duration": 600.0,
    "transcription": "Transcribed text...",
    "metadata": {
      "uploader": "Channel Name",
      "views": 10000,
      "description": "Video description..."
    }
  }
}
```

## POST /api/video/frames

Extract frames from a video at specific timestamps.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Video file |
| `timestamps` | String | Yes | - | Comma-separated timestamps (e.g., "10,30,60") |
| `interval` | Integer | No | - | Extract frame every N seconds |

### Request Example

```bash
curl -X POST "http://localhost:5001/api/video/frames" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@video.mp4" \
  -F "timestamps=10,30,60"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "frames": [
      {
        "timestamp": 10.0,
        "path": "/path/to/frame_10.jpg"
      },
      {
        "timestamp": 30.0,
        "path": "/path/to/frame_30.jpg"
      }
    ]
  }
}
```

