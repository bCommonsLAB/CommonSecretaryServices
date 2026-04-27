# Image Analyzer API Endpoints

Endpoints for template-based image analysis and classification. Extracts structured data (features, classifications, properties) from images using a Vision-capable LLM and a template schema.

**Difference to ImageOCR**: ImageOCR reads *text* from images. Image Analyzer extracts *features and classifications* based on a template.

**Single- and Multi-Image**: A single request can carry one *or* multiple images. With multiple images, the analyzer sends **all images in a single LLM call**, allowing the model to correlate information across them (e.g. table on page 1, dimensions on page 2). See [docs/multi_image_analyzer.md](../../../multi_image_analyzer.md) for design details.

**In-Memory only**: Uploads are streamed directly to RAM; nothing is written to disk by this code. Werkzeug may spool very large uploads into a `SpooledTemporaryFile`, which is the default Flask behavior and outside this code's control.

## POST /api/image-analyzer/process

Analyze one or more uploaded images using a template and return structured data.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | No*** | - | Single image file (JPG, PNG, WebP, GIF). Backwards-compatible with the legacy single-image API. |
| `files` | File (repeatable) | No*** | - | One or more image files. Send the parameter once per image (`-F "files=@a.jpg" -F "files=@b.jpg"`). Up to **10** images per request. |
| `template` | String | No* | - | Template name from `templates/` (e.g. `"image_classify"`) |
| `template_content` | String | No* | - | Direct template content as string |
| `context` | String (JSON) | No | - | Additional context as JSON (e.g. `{"domain": "nature"}`) |
| `additional_field_descriptions` | String (JSON) | No | - | Extra field descriptions as JSON |
| `target_language` | String | No | `"de"` | Target language (ISO 639-1) |
| `model` | String | No | - | Model override (e.g. `"google/gemini-2.5-flash"`) |
| `provider` | String | No | - | Provider override (e.g. `"openrouter"`) |
| `useCache` | Boolean | No | `true` | Whether to use cache |

*Exactly one of `template` or `template_content` must be provided.

***At least one image must be provided via `file` and/or `files` (they can be combined; both contribute to the merged image list).

**Multi-Image notes**:

- Order matters. The first uploaded image is treated as image 1, the second as image 2, etc. The same images in a different order will produce a different cache entry, because the order gives the LLM context.
- Multi-image is fully supported by the `openrouter` provider. The other providers currently accept only single-image calls and will reject multi-image requests with a `ProcessingError`.
- The Swagger UI shows only a single file picker for the `files` parameter — this is a known limitation. Use `curl`/Postman or a custom frontend (`FormData.append('files', blob)` per image) to test multiple images.

### Request Example (single image, backwards-compatible)

```bash
curl -X POST "http://localhost:5001/api/image-analyzer/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@photo.jpg" \
  -F "template=image_classify" \
  -F "target_language=de"
```

### Request Example (multiple images)

```bash
curl -X POST "http://localhost:5001/api/image-analyzer/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "files=@page_009.jpeg" \
  -F "files=@page_010.jpeg" \
  -F "files=@page_011.jpeg" \
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
      "file_names": ["photo.jpg"],
      "image_urls": null,
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

Analyze an image from a URL using a template. The image is downloaded into RAM and not written to disk.

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

This endpoint accepts only a single URL. For multi-image analysis, use `/process` and upload the files via the `files` parameter.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/image-analyzer/process-url" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://example.com/photo.jpg" \
  -F "template=image_classify" \
  -F "target_language=de"
```

### Response (Success)

Same format as `/api/image-analyzer/process`. The `request.parameters` block contains `image_urls: ["https://example.com/photo.jpg"]` and `file_names: null`.

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
| `ProcessingError` | General processing error (missing config, invalid image, no images uploaded, more than 10 images, empty upload, multi-image not supported by selected provider, etc.) |
| `ValueError` | Invalid parameters (both `template` and `template_content`, etc.) |

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
- Caching is based on a combined key built from: ordered list of MD5 hashes of the image bytes, template name and/or content, sorted JSON of `context`, `target_language`, resolved provider, and resolved model. Different image order ⇒ different cache entry.
- Hardcoded LLM parameters (`max_tokens=4000`, `temperature=0.1`, `detail="high"`) are **not** part of the cache key — changing them in code requires manual cache invalidation.
- Supported image formats: JPG, PNG, WebP, GIF
- Maximum file size and resolution per image are controlled by the `processors.imageanalyzer` config section (`max_file_size`, `max_resolution`). These limits apply to *each* uploaded image individually.
- Maximum number of images per request is `ImageAnalyzerProcessor.MAX_IMAGES_PER_REQUEST` (currently `10`).
