# Image Analyzer API Endpoints

Endpoints for template-based image analysis and classification. Extracts structured data (features, classifications, properties) from images using a Vision-capable LLM and a template schema.

**Difference to ImageOCR**: ImageOCR reads *text* from images. Image Analyzer extracts *features and classifications* based on a template.

## POST /api/image-analyzer/process

Analyze an uploaded image using a template and return structured data.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Image file (JPG, PNG, WebP, GIF) |
| `template` | String | No* | - | Template name from `templates/` (e.g. `"image_classify"`) |
| `template_content` | String | No* | - | Direct template content as string |
| `context` | String (JSON) | No | - | Additional context as JSON (e.g. `{"domain": "nature"}`) |
| `additional_field_descriptions` | String (JSON) | No | - | Extra field descriptions as JSON |
| `target_language` | String | No | `"de"` | Target language (ISO 639-1) |
| `model` | String | No | - | Model override (e.g. `"google/gemini-2.5-flash"`) |
| `provider` | String | No | - | Provider override (e.g. `"openrouter"`) |
| `useCache` | Boolean | No | `true` | Whether to use cache |

*Exactly one of `template` or `template_content` must be provided.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/image-analyzer/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@photo.jpg" \
  -F "template=image_classify" \
  -F "target_language=de"
```

### Request Example (with inline template)

```bash
curl -X POST "http://localhost:5001/api/image-analyzer/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@photo.jpg" \
  -F "template_content=---
title: {{title|Short title of the image}}
category: {{category|Main category}}
---
{{description|Detailed description}}" \
  -F "target_language=en"
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "request": {
    "processor": "image_analyzer",
    "timestamp": "2026-04-15T10:00:00Z",
    "parameters": {
      "file_path": "temp_abc123.jpg",
      "template": "image_classify",
      "context": null
    }
  },
  "process": {
    "id": "process-id-456",
    "main_processor": "image_analyzer",
    "started": "2026-04-15T10:00:00Z",
    "completed": "2026-04-15T10:00:03Z",
    "duration": 3000.0,
    "sub_processors": [],
    "llm_info": {
      "total_tokens": 850,
      "total_cost": 0.005,
      "requests": [
        {
          "model": "google/gemini-2.5-flash",
          "purpose": "vision",
          "tokens": 850,
          "duration_ms": 2800,
          "processor": "OpenRouterProvider"
        }
      ]
    },
    "is_from_cache": false,
    "cache_key": null
  },
  "data": {
    "text": "---\ntitle: \"Mountain Landscape\"\ncategory: \"Nature\"\ntags: \"mountains, lake, forest\"\n---\n\n## Bildanalyse\n\nA serene mountain landscape...",
    "language": "de",
    "format": "text",
    "structured_data": {
      "title": "Mountain Landscape",
      "category": "Nature",
      "tags": "mountains, lake, forest",
      "description": "A serene mountain landscape with a crystal-clear lake in the foreground...",
      "objects": "mountains, lake, forest, clouds, sky",
      "mood": "peaceful and serene",
      "quality": "Sharp focus, natural lighting, well-balanced composition"
    }
  },
  "error": null
}
```

## POST /api/image-analyzer/process-url

Analyze an image from a URL using a template.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | String | Yes | - | URL to the image file |
| `template` | String | No* | - | Template name from `templates/` |
| `template_content` | String | No* | - | Direct template content |
| `context` | String (JSON) | No | - | Additional context as JSON |
| `additional_field_descriptions` | String (JSON) | No | - | Extra field descriptions as JSON |
| `target_language` | String | No | `"de"` | Target language (ISO 639-1) |
| `model` | String | No | - | Model override |
| `provider` | String | No | - | Provider override |
| `useCache` | Boolean | No | `true` | Whether to use cache |

*Exactly one of `template` or `template_content` must be provided.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/image-analyzer/process-url" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://example.com/photo.jpg" \
  -F "template=image_classify" \
  -F "target_language=de"
```

### Response (Success)

Same format as `/api/image-analyzer/process`.

## Response (Error)

**Status Code**: `400 Bad Request`

```json
{
  "status": "error",
  "error": {
    "code": "ProcessingError",
    "message": "Kein Provider für IMAGE_ANALYSIS konfiguriert.",
    "details": {
      "error_type": "ProcessingError"
    }
  }
}
```

### Error Codes

| Code | Description |
|------|-------------|
| `ProcessingError` | General processing error (missing config, invalid image, etc.) |
| `ValueError` | Invalid parameters (both template and template_content, etc.) |

## Template Format

Templates use the `{{name|description}}` syntax to define extractable fields. The LLM analyzes the image and fills each field based on the description.

### Example Template (`image_classify.md`)

```markdown
---
title: {{title|Short title or description of the image}}
category: {{category|Main category (e.g. Nature, Architecture, Person, Document)}}
tags: {{tags|Relevant tags as comma-separated list}}
---

## Image Analysis

{{description|Detailed description of the image content in 2-3 sentences}}

## Detected Objects
{{objects|List of detected objects as comma-separated list}}

## Mood and Atmosphere
{{mood|The overall mood or atmosphere of the image}}

--- systemprompt
You are an expert image analyst. Analyze the provided image and extract structured information.
Return all values as a valid JSON object. Be precise and factual - only describe what is actually visible.
Provide all answers in the target language ISO 639-1 code: {target_language}.
```

### Template Features

- **YAML Frontmatter** (`---` blocks): Fields are serialized as YAML-safe strings
- **Body fields** (`{{name|desc}}`): Fields are inserted as plain text
- **System prompt** (`--- systemprompt`): Custom instructions for the LLM
- **Context variables** (`{{key}}`): Replaced with values from the `context` parameter before LLM processing

## Configuration

The image-analyzer endpoint requires configuration in `config.yaml`:

```yaml
llm_config:
  use_cases:
    image_analysis:
      provider: openrouter
      model: google/gemini-2.5-flash

llm_providers:
  openrouter:
    available_models:
      image_analysis:
        - google/gemini-2.5-flash
        - google/gemini-2.5-pro
        - openai/gpt-4o
```

The provider and model can also be configured via the Dashboard under "Image Analysis (Bildklassifizierung)".

### Notes

- The response uses the same `TransformerResponse` structure as the `/api/transformer/template` endpoint
- `data.structured_data` contains the extracted fields as a JSON object
- `data.text` contains the filled template with all placeholders replaced
- The `model` and `provider` parameters allow per-request overrides of the configured defaults
- Caching is based on a hash of the image content, template, context, and target language
- Supported image formats: JPG, PNG, WebP, GIF
- Maximum file size and resolution are controlled by the `processors.imageocr` config section
