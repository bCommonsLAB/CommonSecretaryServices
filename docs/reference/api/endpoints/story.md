# Story API Endpoints

Endpoints for story generation from sessions.

## POST /api/story/generate

Generate a story from a topic.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "topic": "Topic Name",
  "target_group": "General Public",
  "target_language": "de",
  "template": "StoryTemplate"
}
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/story/generate" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "topic": "Climate Change",
    "target_group": "General Public",
    "target_language": "de"
  }'
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "topic": "Climate Change",
    "target_group": "General Public",
    "story": "Generated story text...",
    "sessions_used": [
      {
        "name": "Session 1",
        "contribution": "Contributed information about..."
      }
    ]
  }
}
```

## GET /api/story/topics

List all available topics.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/story/topics" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "topics": [
      {
        "name": "Climate Change",
        "session_count": 5
      },
      {
        "name": "Technology",
        "session_count": 3
      }
    ]
  }
}
```

## GET /api/story/target-groups

List all available target groups.

### Request Example

```bash
curl -X GET "http://localhost:5001/api/story/target-groups" \
  -H "Authorization: Bearer YOUR_API_KEY"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "target_groups": [
      "General Public",
      "Experts",
      "Students",
      "Policy Makers"
    ]
  }
}
```

