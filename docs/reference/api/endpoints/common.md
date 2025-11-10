# Common API Endpoints

General endpoints for common operations.

## GET /api/common/

API home endpoint.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/common/" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response

```json
{
  "message": "Welcome to Common Secretary Services API"
}
```

## POST /api/common/notion

Process Notion blocks and create multilingual newsfeed entry.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "blocks": [
    {
      "type": "paragraph",
      "content": "Block content"
    }
  ],
  "source_language": "en",
  "target_language": "de"
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "processed_blocks": [...],
    "newsfeed_entry": "Multilingual newsfeed content..."
  }
}
```

## GET /api/common/samples

List all available sample files.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/common/samples" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "samples": [
      {
        "filename": "sample_audio.mp3",
        "size": 1024000,
        "type": "audio"
      },
      {
        "filename": "sample_video.mp4",
        "size": 5120000,
        "type": "video"
      }
    ]
  }
}
```

## GET /api/common/samples/{filename}

Download a specific sample file.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/common/samples/sample_audio.mp3" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o sample_audio.mp3
```

### Response

Returns file as binary download.

