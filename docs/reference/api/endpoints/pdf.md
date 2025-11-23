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
| `extraction_method` | String | No | `native` | Extraction method: `native`, `tesseract_ocr`, `openai_vision`, `combined` |
| `template` | String | No | `""` | Optional template for text transformation |
| `context` | JSON | No | `{}` | Additional context for template |
| `useCache` | Boolean | No | `true` | Whether to use cache |
| `includeImages` | Boolean | No | `false` | Base64-kodiertes ZIP-Archiv mit generierten Bildern erstellen |
| `page_start` | Integer | No | - | Start page (1-indexed) |
| `page_end` | Integer | No | - | End page (1-indexed) |

### Extraction Methods

- **native**: Extract text directly from PDF structure (fastest)
- **tesseract_ocr**: Use Tesseract OCR for text extraction
- **openai_vision**: Use OpenAI Vision API for OCR
- **combined**: Try multiple methods and combine results

**Note**: For Mistral OCR transformation with integrated images, use the dedicated endpoint [`POST /api/pdf/process-mistral-ocr`](#post-apipdfprocess-mistral-ocr) instead.

### Request Example

```bash
curl -X POST "http://localhost:5001/api/pdf/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.pdf" \
  -F "extraction_method=combined" \
  -F "template=MeetingMinutes" \
  -F "includeImages=true"
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

## POST /api/pdf/process-mistral-ocr

Process a PDF file with Mistral OCR transformation and parallel page image extraction.

This endpoint is specifically designed for Mistral OCR transformation with integrated images. It runs two processes in parallel:
1. **Mistral OCR Transformation**: Converts PDF to Markdown with embedded images (recognized by Mistral OCR)
2. **Page Image Extraction**: Extracts PDF pages as images and returns them as a ZIP archive

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | PDF file |
| `page_start` | Integer | No | - | Start page (1-indexed) |
| `page_end` | Integer | No | - | End page (1-indexed, inclusive) |
| `includeOCRImages` | Boolean | No | `true` | **Deprecated**: This parameter is ignored. Mistral OCR images are ALWAYS extracted and stored separately. They are NEVER embedded in `mistral_ocr_raw`. Use `mistral_ocr_images_url` in the webhook callback or download endpoint to retrieve images. This parameter maps to the `include_image_base64` field in the Mistral API payload, but images are always extracted and stored separately. |
| `includePageImages` | Boolean | No | `true` | Extract PDF pages as images and return as ZIP archive. Runs in parallel to Mistral OCR transformation. |
| `useCache` | Boolean | No | `true` | Whether to use cache |
| `callback_url` | String | No | - | Absolute HTTPS URL for webhook callback |
| `callback_token` | String | No | - | Per-job secret for webhook callback |
| `jobId` | String | No | - | Unique job ID for callback |
| `wait_ms` | Integer | No | `0` | Optional: Wait time in milliseconds for completion (only without callback_url) |

### Request Example

```bash
curl -X POST "http://localhost:5001/api/pdf/process-mistral-ocr" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.pdf" \
  -F "includeOCRImages=true" \
  -F "includePageImages=true" \
  -F "page_start=1" \
  -F "page_end=10"
```

### Response (Success)

**Important**: Images are **NEVER** embedded in `mistral_ocr_raw`. They are always extracted and stored separately. Use `mistral_ocr_images_url` to download images.

```json
{
  "status": "success",
  "data": {
    "extracted_text": "--- Seite 1 ---\n![img-0.jpeg](img-0.jpeg)\n\nText content...",
    "metadata": {
      "page_count": 10,
      "file_name": "document.pdf",
      "file_size": 753504,
      "extraction_method": "mistral_ocr_with_pages"
    },
    "mistral_ocr_raw": {
      "pages": [
        {
          "index": 0,
          "markdown": "![img-0.jpeg](img-0.jpeg)\n\nText content...",
          "images": [
            {
              "id": "img-0.jpeg",
              "top_left_x": 93,
              "top_left_y": 221,
              "bottom_right_x": 1577,
              "bottom_right_y": 508
            }
          ]
        }
      ],
      "model": "mistral-ocr-latest",
      "usage_info": {
        "pages_processed": 10,
        "doc_size_bytes": 753504
      }
    },
    "mistral_ocr_images_url": "/api/pdf/jobs/{job_id}/mistral-ocr-images",
    "pages_archive_filename": "pages.zip",
    "pages_archive_data": "base64_encoded_zip_data",
    "images_archive_data": null,
    "images_archive_filename": null
  }
}
```

**For async jobs (with `callback_url` or `wait_ms=0`)**, the webhook callback structure differs:

```json
{
  "phase": "completed",
  "message": "Extraktion abgeschlossen",
  "data": {
    "extracted_text": "--- Seite 1 ---\n![img-0.jpeg](img-0.jpeg)\n\nText content...",
    "metadata": {
      "text_contents": [...]
    },
    "mistral_ocr_raw_url": "/api/pdf/jobs/{job_id}/mistral-ocr-raw",
    "mistral_ocr_raw_metadata": {
      "model": "mistral-ocr-latest",
      "pages_count": 235,
      "usage_info": {
        "pages_processed": 235,
        "doc_size_bytes": 7094411
      }
    },
    "pages_archive_url": "/api/pdf/jobs/{job_id}/download-pages-archive"
  }
}
```

### Response Structure

The response contains two types of images:

1. **Mistral OCR Images**:
   - **IMPORTANT**: Images are NEVER embedded in `mistral_ocr_raw`. They are ALWAYS extracted and stored separately.
   - Images recognized and extracted by Mistral OCR
   - Embedded in the Markdown text as references (e.g., `![img-0.jpeg](img-0.jpeg)`)
   - Available as separate files in a ZIP archive
   - Include coordinates and annotations in `mistral_ocr_raw` (without image data)
   - **Download**: Use `mistral_ocr_images_url` in webhook callback or `GET /api/pdf/jobs/{job_id}/mistral-ocr-images` endpoint
   - **Note**: `mistral_ocr_raw` contains image metadata (IDs, coordinates, etc.) but NO image data

2. **Page Images** (`data.pages_archive_data`):
   - All PDF pages converted to images
   - Packaged as a Base64-encoded ZIP archive
   - Filename available in `data.pages_archive_filename`
   - Extracted in parallel to Mistral OCR processing
   - For async jobs, use `data.pages_archive_url` to download

### Differences to `/api/pdf/process`

- **Dedicated endpoint**: Simplified interface specifically for Mistral OCR workflows
- **Parallel processing**: Page image extraction runs in parallel to OCR transformation
- **Two image types**: Returns both Mistral OCR images and page images
- **No template support**: Focused on OCR transformation only
- **Simplified parameters**: Fewer options, clearer purpose

### Use Cases

- Document digitization with full page images and OCR results
- Archival systems requiring both searchable text and page images
- Quality assurance workflows comparing OCR results with original pages
- Multi-format export (Markdown with embedded images + page images)

### Downloading Page Images Archive

There are two ways to download the ZIP archive with PDF pages as images:

#### Option 1: Direct from Response (Base64)

The `pages_archive_data` field in the response contains the ZIP file as a Base64-encoded string. You can decode it directly:

```javascript
// Extract from response
const response = await fetch('/api/pdf/process-mistral-ocr', {...});
const data = await response.json();

if (data.data.pages_archive_data) {
  // Decode Base64 to binary
  const binaryString = atob(data.data.pages_archive_data);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  
  // Create blob and download
  const blob = new Blob([bytes], { type: 'application/zip' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = data.data.pages_archive_filename || 'pages.zip';
  a.click();
  URL.revokeObjectURL(url);
}
```

```python
import base64

# Extract from response
response_data = {...}  # Your API response

if response_data.get('data', {}).get('pages_archive_data'):
    # Decode Base64
    archive_data = base64.b64decode(response_data['data']['pages_archive_data'])
    filename = response_data['data'].get('pages_archive_filename', 'pages.zip')
    
    # Save to file
    with open(filename, 'wb') as f:
        f.write(archive_data)
```

#### Option 2: Download Endpoint (for Async Jobs)

If you're using async job processing (with `callback_url` or `wait_ms=0`), you can download the archive via a dedicated endpoint:

**Endpoint**: `GET /api/pdf/jobs/{job_id}/download-pages-archive`

**Example**:
```bash
curl -X GET "http://localhost:5001/api/pdf/jobs/{job_id}/download-pages-archive" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o pages.zip
```

**Response**: Binary ZIP file with `Content-Type: application/zip` and `Content-Disposition: attachment`

**Status Codes**:
- `200`: Success - ZIP file returned
- `202`: Processing - Job still running, try again later
- `400`: No archive available (check if `includePageImages=true` was set)
- `404`: Job not found
- `500`: Server error

**Note**: The download endpoint only works for jobs that were processed with `includePageImages=true`. The archive is stored in the job results and can be downloaded even after the initial response.

### Downloading Mistral OCR Raw Data

For large documents, `mistral_ocr_raw` is stored as a separate JSON file instead of being included in the response or MongoDB. You can download it via a dedicated endpoint:

**Endpoint**: `GET /api/pdf/jobs/{job_id}/mistral-ocr-raw`

**Example**:
```bash
curl -X GET "http://localhost:5001/api/pdf/jobs/{job_id}/mistral-ocr-raw" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o mistral_ocr_raw.json
```

**Response**: JSON file with `Content-Type: application/json` and `Content-Disposition: attachment`

**Status Codes**:
- `200`: Success - JSON file returned
- `202`: Processing - Job still running, try again later
- `400`: No Mistral OCR data available
- `404`: Job not found
- `500`: Server error

**Note**: This endpoint is only available for jobs processed with the Mistral OCR endpoint (`/api/pdf/process-mistral-ocr`). The file contains the complete Mistral OCR response **WITHOUT** image data. Images are stored separately and must be downloaded via the `mistral_ocr_images_url` endpoint.

### Downloading Mistral OCR Images

Mistral OCR images are **always** stored separately and never embedded in `mistral_ocr_raw`. Download them via a dedicated endpoint:

**Endpoint**: `GET /api/pdf/jobs/{job_id}/mistral-ocr-images`

**Example**:
```bash
curl -X GET "http://localhost:5001/api/pdf/jobs/{job_id}/mistral-ocr-images" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -o mistral_ocr_images.zip
```

**Response**: Binary ZIP file with `Content-Type: application/zip` and `Content-Disposition: attachment`

**Status Codes**:
- `200`: Success - ZIP file returned
- `202`: Processing - Job still running, try again later
- `400`: No Mistral OCR images available
- `404`: Job not found
- `500`: Server error

**Note**: This endpoint is only available for jobs processed with the Mistral OCR endpoint (`/api/pdf/process-mistral-ocr`). The ZIP file contains all images extracted from the Mistral OCR response. Image references in the Markdown text (e.g., `![img-0.jpeg](img-0.jpeg)`) correspond to files in this ZIP archive.

### Error Handling

If MongoDB document size limits are exceeded (e.g., for very large documents with many images), an error webhook is sent:

```json
{
  "phase": "error",
  "message": "Fehler beim Speichern der Ergebnisse",
  "error": {
    "code": "DocumentTooLarge",
    "message": "'update' command document too large",
    "details": {
      "error_type": "mongodb_document_too_large",
      "suggestion": "mistral_ocr_raw wurde als separate Datei gespeichert und kann über die API abgerufen werden"
    }
  },
  "data": {
    "extracted_text": "...",
    "mistral_ocr_raw_url": "/api/pdf/jobs/{job_id}/mistral-ocr-raw"
  }
}
```

In this case, the processing completed successfully, but the results were too large to store in MongoDB. The `mistral_ocr_raw` data is still available via the download endpoint.

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

