# Transformer API Endpoints

Endpoints for text transformation, translation, and template processing.

## POST /api/transformer/text

Translate text between languages.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "text": "Text to translate",
  "source_language": "en",
  "target_language": "de",
  "use_cache": true
}
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/text" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hello, world!",
    "source_language": "en",
    "target_language": "de"
  }'
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "original_text": "Hello, world!",
    "translated_text": "Hallo, Welt!",
    "source_language": "en",
    "target_language": "de"
  }
}
```

## POST /api/transformer/template

Transform text using a template.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "text": "Input text to transform",
  "template": "MeetingMinutes",
  "source_language": "en",
  "target_language": "de",
  "context": {
    "meeting_date": "2024-01-01",
    "participants": ["Alice", "Bob"]
  },
  "use_cache": true
}
```

### Alternative: Template Content

Instead of template name, provide template content directly:

```json
{
  "text": "Input text",
  "template_content": "Extract: {summary}\nParticipants: {participants}",
  "additional_field_descriptions": {
    "summary": "Brief summary of the meeting",
    "participants": "List of participants"
  }
}
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/template" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Meeting notes...",
    "template": "MeetingMinutes",
    "source_language": "en"
  }'
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "original_text": "Meeting notes...",
    "transformed_text": "Structured meeting minutes...",
    "template_fields": {
      "summary": "Meeting summary",
      "participants": ["Alice", "Bob"],
      "action_items": [...]
    }
  }
}
```

## POST /api/transformer/summarize

Summarize text.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "text": "Long text to summarize...",
  "max_length": 200,
  "use_cache": true
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "original_text": "Long text...",
    "summary": "Brief summary..."
  }
}
```

## POST /api/transformer/html-to-markdown

Convert HTML to Markdown.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "html": "<h1>Title</h1><p>Content</p>",
  "use_cache": true
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "html": "<h1>Title</h1>...",
    "markdown": "# Title\n\nContent"
  }
}
```

## POST /api/transformer/extract-tables

Extract tables from HTML.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "html": "<table>...</table>",
  "use_cache": true
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "tables": [
      {
        "headers": ["Column 1", "Column 2"],
        "rows": [
          ["Value 1", "Value 2"]
        ]
      }
    ]
  }
}
```

