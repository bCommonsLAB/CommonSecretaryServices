# ImageOCR API Endpoints

Endpoints for image OCR processing.

## POST /api/imageocr/process

Process an image file with OCR.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Image file (JPG, PNG, WebP, etc.) |
| `template` | String | No | `""` | Optional template for text transformation |
| `use_cache` | Boolean | No | `true` | Whether to use cache |

### Request Example

```bash
curl -X POST "http://localhost:5001/api/imageocr/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@image.jpg" \
  -F "template=DocumentExtraction"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "extracted_text": "Text extracted from image...",
    "metadata": {
      "width": 1920,
      "height": 1080,
      "format": "JPEG",
      "dpi": 300
    }
  }
}
```

## POST /api/imageocr/process-url

Process an image from URL with OCR.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `url` | String | Yes | - | Image URL |
| `template` | String | No | `""` | Optional template |
| `use_cache` | Boolean | No | `true` | Whether to use cache |

### Request Example

```bash
curl -X POST "http://localhost:5001/api/imageocr/process-url" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "url=https://example.com/image.jpg" \
  -F "template=DocumentExtraction"
```

### Response (Success)

Same format as `/api/imageocr/process`.

