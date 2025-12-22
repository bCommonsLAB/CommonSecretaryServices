# Transformer API Endpoints

Endpoints for text transformation, translation, and template processing.

## POST /api/transformer/text

Translate text between languages.

### Request

**Content-Type**: `application/x-www-form-urlencoded`

**Body Parameters**:

- `text` (required): Text to translate
- `source_language` (required): Source language (ISO 639-1 code, e.g., "en", "de")
- `target_language` (required): Target language (ISO 639-1 code, e.g., "en", "de")
- `summarize` (optional): Whether to summarize the text (true/false, default: false)
- `target_format` (optional): Target format (TEXT, HTML, MARKDOWN, JSON)
- `context` (optional): JSON string with context for transformation
- `use_cache` (optional): Whether to use cache (true/false, default: true)

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/text" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "text=Hello, world!" \
  -d "source_language=en" \
  -d "target_language=de" \
  -d "use_cache=true"
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

### Authentication

**Required Headers** (one of the following):

- `Authorization: Bearer <YOUR_API_KEY>` (recommended)
- `X-Secretary-Api-Key: <YOUR_API_KEY>` (alternative)

### Request

**Content-Type**: `application/x-www-form-urlencoded`

**Body Parameters**:

- `text` (optional): Input text to transform (required if `url` not provided)
- `url` (optional): URL of the webpage (required if `text` not provided)
- `template` (optional): Template name (without .md extension, required if `template_content` not provided)
- `template_content` (optional): Direct template content (Markdown, required if `template` not provided)
- `source_language` (optional): Source language (ISO 639-1 code, default: "de")
- `target_language` (optional): Target language (ISO 639-1 code, default: "de")
- `context` (optional): JSON string with context for template processing
- `additional_field_descriptions` (optional): JSON string with additional field descriptions
- `use_cache` (optional): Whether to use cache (true/false, default: true)
- `container_selector` (optional): CSS selector for event container (e.g., "li.single-element")
- `callback_url` (optional): Absolute HTTPS URL for webhook callback
- `callback_token` (optional): Per-job secret for webhook callback
- `jobId` (optional): Unique job ID for callback
- `wait_ms` (optional): Wait time in milliseconds for completion (only without callback_url, default: 0)

### Alternative: Template Content

Instead of template name, provide template content directly:

```bash
curl -X POST "http://localhost:5001/api/transformer/template" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "text=Input text" \
  -d "template_content=Extract: {summary}\nParticipants: {participants}" \
  -d 'additional_field_descriptions={"summary":"Brief summary","participants":"List of participants"}'
```

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/template" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "text=Meeting notes..." \
  -d "template=MeetingMinutes" \
  -d "source_language=en" \
  -d 'context={"meeting_date":"2024-01-01","participants":["Alice","Bob"]}'
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

## POST /api/transformer/html-table

Extract tables from HTML webpage.

### Request

**Content-Type**: `application/x-www-form-urlencoded`

**Body Parameters**:

- `source_url` (required): URL of the webpage containing HTML tables
- `output_format` (optional): Output format (currently only "json" supported, default: "json")
- `table_index` (optional): Index of the desired table (0-based)
- `start_row` (optional): Start row for paging (0-based)
- `row_count` (optional): Number of rows to return

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/html-table" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "source_url=https://example.com/table-page" \
  -d "output_format=json" \
  -d "table_index=0" \
  -d "start_row=0" \
  -d "row_count=10"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "input": {
      "text": "https://example.com/table-page",
      "language": "",
      "format": "URL"
    },
    "output": {
      "text": "JSON representation of tables",
      "language": "",
      "format": "JSON",
      "structured_data": {
        "url": "https://example.com/table-page",
        "table_count": 1,
        "tables": [
          {
            "table_index": 0,
            "headers": ["Column 1", "Column 2"],
            "rows": [
              {"Column 1": "Value 1", "Column 2": "Value 2"}
            ],
            "metadata": {
              "total_rows": 1,
              "column_count": 2,
              "has_group_info": false,
              "paging": {
                "start_row": 0,
                "row_count": 1,
                "has_more": false
              }
            }
          }
        ]
      }
    }
  }
}
```

## POST /api/transformer/chat

LLM Broker endpoint for chat completions. This endpoint is the **single integration point** for all LLM usage in the app.
Clients are **LLM consumers**: they send `messages` and optionally request **structured output** (with a schema).
The Transformer is the **broker**: it chooses the provider, enforces output contracts, validates structured output, and returns a stable response format.

### Authentication

**Required Headers** (one of the following):

- `Authorization: Bearer <YOUR_API_KEY>` (recommended)
- `X-Secretary-Api-Key: <YOUR_API_KEY>` (alternative)

Both headers are accepted. The API key must match the `SECRETARY_SERVICE_API_KEY` environment variable.

### Request

**Content-Type**: `application/x-www-form-urlencoded`

**Body Parameters**:

- `messages` (required): JSON string with list of messages in format `[{"role": "system|user|assistant", "content": "..."}]`
- `model` (optional): Model name (uses default from config if not provided)
- `provider` (optional): Provider name (uses default from config if not provided)
- `temperature` (optional): Temperature for response (0.0-2.0, default: 0.7)
- `max_tokens` (optional): Maximum number of tokens
- `stream` (optional): Whether to enable streaming (default: false, currently not supported)
- `use_cache` (optional): Whether to use cache (true/false, default: true)
  - **Note**: Cache applies to structured requests as well. Cached responses maintain their `structured_data` format.
- `timeout_ms` (optional): Request timeout in milliseconds
  - **Note**: Server may clamp timeout to a maximum value (implementation-dependent)
  - If not provided, uses provider default timeout

#### Structured Output (optional, recommended for app features)

- `response_format` (optional): `text` | `json_object` (default: `text`)
  - `text`: normal text response
  - `json_object`: broker guarantees that `data.structured_data` is a JSON object (never null when `status=success`)
- `schema_json` (optional): JSON Schema as string (recommended when `response_format=json_object`)
  - **Format**: JSON Schema Draft 7 (draft-07)
  - **Example**: `'{"$schema":"http://json-schema.org/draft-07/schema#","type":"object","properties":{"name":{"type":"string"}}}'`
- `schema_id` (optional): Server-known schema identifier (alternative to `schema_json`)
  - Predefined schemas: `metadata`, `meeting_minutes` (see schema registry)
- `strict` (optional): true/false (default: true when `response_format=json_object`)
  - If `true`: broker validates output against the schema and returns `status=error` on mismatch
  - If `false`: broker logs validation warnings but returns `status=success` even on schema mismatch

**Schema Validation Behavior**:

- **Invalid `schema_json`**: Returns `status=error` with `code="InvalidSchema"` (400)
- **Unknown `schema_id`**: Returns `status=error` with `code="SchemaNotFound"` (400)
- **Valid JSON but schema mismatch**:
  - If `strict=true`: Returns `status=error` with `code="SchemaValidationError"` (400)
  - If `strict=false`: Returns `status=success` with `data.structured_data` containing the (invalid) JSON, validation warning logged

### Chat History Support

The endpoint supports full chat history by passing multiple messages:

- `system`: System prompt (optional, should be at the beginning)
- `user`: User messages
- `assistant`: Previous assistant responses (for context)

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/chat" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "messages=[{\"role\":\"system\",\"content\":\"You are a helpful assistant.\"},{\"role\":\"user\",\"content\":\"What is 2+2?\"}]" \
  -d "model=openai/gpt-4" \
  -d "provider=openrouter" \
  -d "temperature=0.7"
```

**Alternative Authentication**:

```bash
curl -X POST "http://localhost:5001/api/transformer/chat" \
  -H "X-Secretary-Api-Key: YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "messages=[{\"role\":\"user\",\"content\":\"Hello\"}]"
```

### Request Example with Chat History

```bash
curl -X POST "http://localhost:5001/api/transformer/chat" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'messages=[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":"Hello!"},{"role":"assistant","content":"Hello! How can I help you?"},{"role":"user","content":"What is 2+2?"}]' \
  -d "model=openai/gpt-4" \
  -d "provider=openrouter"
```

### Request Example with Structured Output

```bash
curl -X POST "http://localhost:5001/api/transformer/chat" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d 'messages=[{"role":"system","content":"You are a helpful assistant."},{"role":"user","content":"Extract metadata from this text: ..."}]' \
  -d "model=openai/gpt-4" \
  -d "provider=openrouter" \
  -d "response_format=json_object" \
  -d "schema_id=metadata" \
  -d "strict=true"
```

### Response (Success, Text)

Stable TransformerResponse contract:

```json
{
  "status": "success",
  "request": {
    "processor": "transformer",
    "timestamp": "2025-12-22T18:00:00",
    "parameters": {
      "messages_count": 2,
      "model": "openai/gpt-4",
      "provider": "openrouter",
      "temperature": 0.7,
      "max_tokens": null,
      "response_format": "text",
      "duration_ms": 1234
    }
  },
  "process": {
    "id": "uuid-here",
    "main_processor": "transformer",
    "started": "2025-12-22T18:00:00",
    "completed": "2025-12-22T18:00:00.234",
    "duration": 1234.0,
    "llm_info": {
      "requests": [
        {
          "model": "openai/gpt-4",
          "purpose": "chat_completion",
          "tokens": 150,
          "duration": 1234.0,
          "processor": "transformer",
          "timestamp": "2025-12-22T18:00:00"
        }
      ],
      "requests_count": 1,
      "total_tokens": 150,
      "total_duration": 1234.0
    }
  },
  "data": {
    "text": "2+2 equals 4.",
    "language": "",
    "format": "TEXT",
    "summarized": false,
    "structured_data": null
  }
}
```

### Response (Success, Structured)

When `response_format=json_object`:

```json
{
  "status": "success",
  "request": {
    "processor": "transformer",
    "timestamp": "2025-12-22T18:00:00",
    "parameters": {
      "messages_count": 2,
      "model": "openai/gpt-4",
      "provider": "openrouter",
      "temperature": 0.7,
      "response_format": "json_object",
      "schema_id": "metadata",
      "strict": true,
      "duration_ms": 1234
    }
  },
  "process": {
    "id": "uuid-here",
    "main_processor": "transformer",
    "started": "2025-12-22T18:00:00",
    "completed": "2025-12-22T18:00:00.234",
    "duration": 1234.0,
    "llm_info": {
      "requests": [
        {
          "model": "openai/gpt-4",
          "purpose": "chat_completion",
          "tokens": 150,
          "duration": 1234.0,
          "processor": "transformer",
          "timestamp": "2025-12-22T18:00:00"
        }
      ],
      "requests_count": 1,
      "total_tokens": 150,
      "total_duration": 1234.0
    }
  },
  "data": {
    "text": "",
    "language": "",
    "format": "TEXT",
    "summarized": false,
    "structured_data": {
      "recommendation": "chunk",
      "confidence": "high",
      "reasoning": "..."
    }
  }
}
```

**Guarantees**:
- `status="success"` implies `data.text` exists (string, can be empty).
- **Structured Output Guarantee**: If `response_format=json_object` AND `status=success`, then `data.structured_data` is **never null** and is always a JSON object (dict).
- If `strict=true` and schema validation fails, the response is `status="error"`.
- If `strict=false` and schema validation fails, the response is `status="success"` but validation warnings are logged.

### Erkennung von Structured Output

Um zu erkennen, ob eine Response Structured Output enthält, gibt es zwei Möglichkeiten:

1. **Prüfe `data.structured_data`**:
   ```javascript
   if (response.data && response.data.structured_data !== null && typeof response.data.structured_data === 'object') {
       // Structured Output vorhanden
       const structuredData = response.data.structured_data;
   }
   ```

2. **Prüfe `request.parameters.response_format`**:
   ```javascript
   if (response.request && response.request.parameters && response.request.parameters.response_format === 'json_object') {
       // Structured Output wurde angefordert
       // Prüfe zusätzlich ob structured_data vorhanden ist
   }
   ```

**Empfehlung**: Prüfe primär `data.structured_data !== null`, da dies die tatsächlichen Daten widerspiegelt. `request.parameters.response_format` zeigt nur an, was angefordert wurde, nicht was tatsächlich zurückgegeben wurde.

### Response (Error)

```json
{
  "status": "error",
  "error": {
    "code": "InvalidMessages",
    "message": "messages muss eine Liste sein",
    "details": {}
  }
}
```

### Error Codes

- `InvalidMessages`: Invalid message format
- `InvalidJSON`: Invalid JSON in messages parameter
- `InvalidRequest`: Invalid request parameters (e.g., invalid response_format)
- `InvalidSchema`: Invalid JSON Schema
- `SchemaNotFound`: Schema ID not found
- `SchemaValidationError`: JSON does not match schema (only when strict=true)
- `JSONParseError`: JSON could not be parsed from LLM response
- `StreamingNotSupported`: Streaming requested but not supported
- `NoDefaultModel`: No default model configured
- `NoProvider`: No provider configured
- `ProviderNotFound`: Provider not found
- `ChatCompletionError`: Error during chat completion

### Usage/Tokens

Token-Informationen sind in `process.llm_info` verfügbar:

**Stabile Usage-Ableitung**:
```javascript
// Aggregierte Token-Informationen
const llmInfo = response.process?.llm_info;
const usage = {
  total_tokens: llmInfo?.total_tokens || 0,
  requests_count: llmInfo?.requests_count || 0,
  total_duration: llmInfo?.total_duration || 0
};

// Einzelne Request-Details
const requests = llmInfo?.requests || [];
requests.forEach(req => {
  console.log(`Model: ${req.model}, Tokens: ${req.tokens}, Duration: ${req.duration}ms`);
});
```

**Hinweis**: `prompt_tokens` und `completion_tokens` sind aktuell nicht separat verfügbar. Nur `total_tokens` wird getrackt. Dies kann in zukünftigen Versionen erweitert werden, wenn Provider diese Informationen liefern.

### Notes

- This endpoint is the preferred integration point for LLM usage in the app.
- The broker may apply provider/model policies, retries, caching and safety checks.
- Streaming is currently not supported (will return error if `stream=true`)
- The endpoint uses the standard TransformerResponse format for consistency
- LLM usage is tracked in `process.llm_info` with aggregated `total_tokens`, `requests_count`, and `total_duration`
- Chat history is fully supported - pass all previous messages in the conversation
- Do not return secrets/tokens in `data` or logs
- **Cache Semantik**: `use_cache=true` (default) gilt auch für structured requests. Cached responses behalten ihr `structured_data` Format bei.
- **Timeout**: `timeout_ms` wird serverseitig auf einen maximalen Wert begrenzt (implementation-dependent). Wenn nicht angegeben, wird der Provider-Default verwendet.

## POST /api/transformer/text/file

Transform a text file (TXT, MD) from one language to another.

### Request

**Content-Type**: `multipart/form-data`

**Body Parameters**:

- `file` (required): Text file to transform (.txt or .md)
- `source_language` (required): Source language (ISO 639-1 code, e.g., "de", "en")
- `target_language` (required): Target language (ISO 639-1 code, e.g., "de", "en")
- `summarize` (optional): Whether to summarize the text (true/false, default: false)
- `target_format` (optional): Target format (TEXT, HTML, MARKDOWN, JSON)
- `context` (optional): JSON string with context for transformation
- `use_cache` (optional): Whether to use cache (true/false, default: true)

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/text/file" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.txt" \
  -F "source_language=en" \
  -F "target_language=de" \
  -F "use_cache=true"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "text": "Transformed text content...",
    "language": "de",
    "format": "TEXT",
    "summarized": false,
    "structured_data": null
  }
}
```

## POST /api/transformer/metadata

Extract metadata from files (images, videos, PDFs, and other documents).

### Request

**Content-Type**: `multipart/form-data`

**Body Parameters**:

- `file` (optional): File to extract metadata from
- `content` (optional): Text content to extract metadata from (required if `file` not provided)
- `context` (optional): JSON string with context for metadata extraction
- `use_cache` (optional): Whether to use cache (true/false, default: true)

### Request Example

```bash
curl -X POST "http://localhost:5001/api/transformer/metadata" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.pdf" \
  -F "use_cache=true"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "technical_metadata": {
      "file_size": 12345,
      "format": "pdf",
      "mime_type": "application/pdf"
    },
    "content_metadata": {
      "title": "Document Title",
      "author": "Author Name",
      "description": "Document description"
    }
  }
}
```

