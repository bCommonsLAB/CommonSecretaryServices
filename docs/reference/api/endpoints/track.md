# Track API Endpoints

Endpoints for track processing and summarization.

## POST /api/tracks/{track_name}/summary

Generate track summary.

### Request

**URL Parameters**:
- `track_name`: Name of the track

**Content-Type**: `application/json`

**Body** (optional):

```json
{
  "template": "TrackSummary",
  "target_language": "de"
}
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/tracks/MainTrack/summary" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "TrackSummary"
  }'
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "track_name": "MainTrack",
    "summary": "Track summary text...",
    "sessions": [
      {
        "name": "Session 1",
        "summary": "Session summary..."
      }
    ],
    "session_count": 5
  }
}
```

## GET /api/tracks/available

List all available tracks.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/tracks/available" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "tracks": [
      {
        "name": "MainTrack",
        "session_count": 5
      },
      {
        "name": "SideTrack",
        "session_count": 3
      }
    ]
  }
}
```

## POST /api/tracks/{track_name}/summarize_all

Summarize all tracks.

### Request

**URL Parameters**:
- `track_name`: Name of the track

**Content-Type**: `application/json`

**Body** (optional):

```json
{
  "template": "TrackSummary",
  "target_language": "de"
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "track_name": "MainTrack",
    "summaries": [
      {
        "session": "Session 1",
        "summary": "Summary..."
      }
    ]
  }
}
```

