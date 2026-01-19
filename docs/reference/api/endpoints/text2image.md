# Text2Image API Endpoints

Endpoints for text-to-image generation using configured LLM providers (e.g., OpenRouter with DALL-E models).

## POST /api/text2image/generate

Generate an image from a text prompt.

### Request

**Content-Type**: `application/json` oder `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `prompt` | String | Yes | - | Text prompt for image generation |
| `size` | String | No | `1024x1024` | Image size (e.g., "1024x1024", "1792x1024", "1024x1792") |
| `quality` | String | No | `standard` | Image quality ("standard" or "hd") |
| `n` | Integer | No | `1` | Number of images (most models support only n=1) |
| `seed` | Integer | No | - | Optional seed for reproducibility |
| `seeds` | Array/String | No | - | Optional list of seeds (JSON array or comma-separated string) |
| `useCache` | Boolean | No | `true` | Whether to use cache |

### Supported Sizes

- `1024x1024` - Square image (default)
- `1792x1024` - Landscape image
- `1024x1792` - Portrait image

### Request Example (JSON)

```bash
curl -X POST "http://localhost:5001/api/text2image/generate" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A serene mountain lake at sunset with snow-capped peaks in the background",
    "size": "1024x1024",
    "quality": "standard",
    "useCache": true
  }'
```

### Request Example (JSON, 4 Vorschauen mit Seeds)

```bash
curl -X POST "http://localhost:5001/api/text2image/generate" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "A serene mountain lake at sunset with snow-capped peaks in the background",
    "size": "256x256",
    "quality": "standard",
    "n": 4,
    "seeds": [101, 102, 103, 104],
    "useCache": false
  }'
```

### Request Example (Form Data)

```bash
curl -X POST "http://localhost:5001/api/text2image/generate" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "prompt=A serene mountain lake at sunset with snow-capped peaks in the background" \
  -F "size=1024x1024" \
  -F "quality=standard" \
  -F "useCache=true"
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "request": {
    "processor": "text2image",
    "timestamp": "2024-01-01T00:00:00Z",
    "parameters": {
      "prompt": "A serene mountain lake at sunset...",
      "size": "1024x1024",
      "quality": "standard",
      "n": 1
    }
  },
  "process": {
    "id": "process-id-123",
    "main_processor": "text2image",
    "started": "2024-01-01T00:00:00Z",
    "completed": "2024-01-01T00:00:05Z",
    "duration": 5000.0,
    "sub_processors": [],
    "llm_info": {
      "total_tokens": 150,
      "total_cost": 0.02,
      "requests": [
        {
          "model": "openai/dall-e-3",
          "purpose": "text2image",
          "tokens": 150,
          "duration_ms": 4500,
          "processor": "OpenRouterProvider"
        }
      ]
    },
    "is_from_cache": false,
    "cache_key": null
  },
  "data": {
    "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
    "image_format": "png",
    "size": "1024x1024",
    "model": "openai/dall-e-3",
    "prompt": "A serene mountain lake at sunset with snow-capped peaks in the background",
    "seed": null,
    "images": [
      {
        "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "image_format": "png",
        "size": "1024x1024",
        "seed": 101
      }
    ]
  },
  "error": null
}
```

### Response (Error)

**Status Code**: `400 Bad Request` or `500 Internal Server Error`

```json
{
  "status": "error",
  "request": {
    "processor": "text2image",
    "timestamp": "2024-01-01T00:00:00Z",
    "parameters": {}
  },
  "process": {
    "id": "process-id-123",
    "main_processor": "text2image",
    "started": "2024-01-01T00:00:00Z",
    "completed": null,
    "duration": null,
    "sub_processors": [],
    "llm_info": null,
    "is_from_cache": false,
    "cache_key": null
  },
  "data": null,
  "error": {
    "code": "MISSING_PROMPT",
    "message": "Prompt darf nicht leer sein",
    "details": {}
  }
}
```

### Error Codes

| Code | Description |
|------|-------------|
| `MISSING_PROMPT` | Prompt parameter is missing or empty |
| `INVALID_SIZE` | Invalid size format (must be WIDTHxHEIGHT) |
| `INVALID_QUALITY` | Invalid quality (must be "standard" or "hd") |
| `PROVIDER_NOT_CONFIGURED` | No provider configured for text2image use case |
| `MODEL_NOT_CONFIGURED` | No model configured for text2image use case |
| `TEXT2IMAGE_ERROR` | Error during image generation |
| `INTERNAL_ERROR` | Unexpected internal error |

### Configuration

The text2image endpoint requires configuration in `config.yaml`:

```yaml
llm_config:
  use_cases:
    text2image:
      provider: openrouter
      model: openai/dall-e-3

llm_providers:
  openrouter:
    available_models:
      text2image:
        - openai/dall-e-3
        - stability-ai/stable-diffusion-xl-base-1.0
        - black-forest-labs/flux-pro
        - black-forest-labs/flux-schnell
```

### Notes

- The generated image is returned as base64-encoded data in the `data.image_base64` field
- For multiple images, the first image is mirrored in `data.image_base64` for backward compatibility
- Use `data.images[*].seed` to re-generate a selected preview in higher resolution
- To display the image in a client, build a data URL with the reported format:
  `data:image/{image_format};base64,{image_base64}`
- Example (Browser):
  ```js
  const imageDataUrl = `data:image/${response.data.image_format};base64,${response.data.image_base64}`;
  document.querySelector("img").src = imageDataUrl;
  ```
- Caching is enabled by default and uses a hash of the prompt, size, quality, model, and n parameters
- Most image generation models support only `n=1` (single image generation)
- The `seed` parameter can be used for reproducible image generation (if supported by the model)
