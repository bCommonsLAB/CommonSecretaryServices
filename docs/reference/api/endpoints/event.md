# Event API Endpoints

Endpoints for event processing and summarization.

## POST /api/events/{event_name}/summary

Generate event summary.

### Request

**URL Parameters**:
- `event_name`: Name of the event

**Content-Type**: `application/json`

**Body** (optional):

```json
{
  "template": "EventSummary",
  "target_language": "de"
}
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/events/Conference2024/summary" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "template": "EventSummary",
    "target_language": "de"
  }'
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "event_name": "Conference2024",
    "summary": "Event summary text...",
    "tracks": [
      {
        "name": "Track 1",
        "session_count": 5,
        "summary": "Track summary..."
      }
    ],
    "total_sessions": 20
  }
}
```

