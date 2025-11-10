# PDF API Endpoints

Endpoints for PDF file processing with text extraction and OCR.

## POST /api/pdf/process

Process a PDF file with text extraction and optional OCR.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | PDF file |
| `extraction_method` | String | No | `native` | Extraction method: `native`, `ocr`, `mistral_ocr`, `openai_vision`, `combined` |
| `template` | String | No | `""` | Optional template for text transformation |
| `context` | JSON | No | `{}` | Additional context for template |
| `useCache` | Boolean | No | `true` | Whether to use cache |
| `include_images` | Boolean | No | `false` | Include page images in response |
| `page_start` | Integer | No | - | Start page (1-indexed) |
| `page_end` | Integer | No | - | End page (1-indexed) |

### Extraction Methods

- **native**: Extract text directly from PDF structure (fastest)
- **ocr**: Use Tesseract OCR for text extraction
- **mistral_ocr**: Use Mistral API for OCR
- **openai_vision**: Use OpenAI Vision API for OCR
- **combined**: Try multiple methods and combine results

### Request Example

```bash
curl -X POST "http://localhost:5001/api/pdf/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.pdf" \
  -F "extraction_method=combined" \
  -F "template=MeetingMinutes" \
  -F "include_images=true"
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "extracted_text": "Full extracted text from PDF...",
    "metadata": {
      "page_count": 10,
      "author": "Author Name",
      "title": "Document Title",
      "text_contents": [
        {
          "page": 1,
          "text": "Page 1 text...",
          "method": "native"
        }
      ],
      "image_paths": [
        "/path/to/page_1.jpg",
        "/path/to/page_2.jpg"
      ]
    },
    "images_archive_filename": "document_images.zip",
    "images_archive_data": "base64_encoded_zip_data"
  }
}
```

## POST /api/pdf/job

Process PDF asynchronously as a job.

### Request

**Content-Type**: `application/json`

**Body**:

```json
{
  "filename": "/path/to/file.pdf",
  "extraction_method": "combined",
  "template": "MeetingMinutes",
  "use_cache": true,
  "webhook": {
    "url": "https://example.com/webhook",
    "token": "webhook_token",
    "jobId": "client_job_id"
  }
}
```

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "status": "pending"
  }
}
```

### Job Status

Query job status via `/api/jobs/{job_id}`:

```json
{
  "status": "success",
  "data": {
    "job_id": "job-id-123",
    "status": "completed",
    "progress": {
      "step": "completed",
      "percent": 100,
      "message": "Processing completed"
    },
    "results": {
      "structured_data": {
        "extracted_text": "...",
        "metadata": {...}
      }
    }
  }
}
```

