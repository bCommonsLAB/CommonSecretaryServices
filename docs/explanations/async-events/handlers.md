# Handler Documentation

Complete documentation of all available handlers for the Secretary Job Worker.

## Overview

Handlers are async functions that process specific job types. They are registered in the processor registry and executed by the SecretaryWorkerManager.

## Handler Signature

All handlers follow this signature:

```python
async def handle_job(
    job: Job,
    repo: SecretaryJobRepository,
    resource_calculator: ResourceCalculator
) -> None:
    # Process job
    pass
```

### Parameters

- **job**: Job object with `job_id`, `job_type`, `status`, `parameters`
- **repo**: Repository for updating job status, progress, and results
- **resource_calculator**: Resource tracking calculator

## PDF Handler

**Job Type**: `pdf`

Processes PDF files with text extraction and OCR.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `filename` | String | Yes* | Local file path |
| `url` | String | Yes* | PDF URL (alternative to filename) |
| `extraction_method` | String | No | `native`, `ocr`, `mistral_ocr`, `openai_vision`, `combined` (default: `native`) |
| `template` | String | No | Template name for text transformation |
| `context` | Dict | No | Additional context for template |
| `use_cache` | Boolean | No | Whether to use cache (default: `true`) |
| `include_images` | Boolean | No | Include page images in response (default: `false`) |
| `page_start` | Integer | No | Start page (1-indexed) |
| `page_end` | Integer | No | End page (1-indexed) |
| `webhook` | Dict | No | Webhook configuration |

*Either `filename` or `url` must be provided.

### Example

```json
{
  "job_type": "pdf",
  "parameters": {
    "filename": "/path/to/document.pdf",
    "extraction_method": "combined",
    "template": "MeetingMinutes",
    "include_images": true
  }
}
```

### Progress Steps

1. `initializing` (0%) - Initializing PDF processor
2. `reading_file` (10%) - Reading PDF file
3. `extracting_text` (30%) - Extracting text
4. `processing_images` (60%) - Processing images (if enabled)
5. `applying_template` (80%) - Applying template transformation
6. `finalizing` (90%) - Finalizing results
7. `completed` (100%) - Processing completed

### Results

```json
{
  "structured_data": {
    "extracted_text": "Full extracted text...",
    "metadata": {
      "page_count": 10,
      "author": "Author Name",
      "text_contents": [...]
    },
    "images_archive_filename": "document_images.zip",
    "images_archive_data": "base64_encoded_zip_data"
  }
}
```

## Session Handler

**Job Type**: `session`

Processes session information with associated media.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `event` | String | Yes | Event name |
| `session` | String | Yes | Session name |
| `url` | String | Yes | Session URL |
| `filename` | String | Yes | Output filename |
| `track` | String | Yes | Track name |
| `day` | String | No | Event day (YYYY-MM-DD) |
| `starttime` | String | No | Start time (HH:MM) |
| `endtime` | String | No | End time (HH:MM) |
| `speakers` | List[String] | No | List of speakers |
| `video_url` | String | No | Video URL |
| `attachments_url` | String | No | Attachments URL |
| `source_language` | String | No | Source language (default: `en`) |
| `target_language` | String | No | Target language (default: `de`) |
| `template` | String | No | Template name (default: `Session`) |

### Example

```json
{
  "job_type": "session",
  "parameters": {
    "event": "Conference 2024",
    "session": "Keynote",
    "url": "https://example.com/session",
    "filename": "keynote.md",
    "track": "Main Track"
  }
}
```

### Progress Steps

1. `initializing` (0%) - Initializing session processor
2. `fetching_page` (10%) - Fetching session page
3. `downloading_media` (30%) - Downloading videos and attachments
4. `processing_video` (50%) - Processing video
5. `processing_attachments` (70%) - Processing PDF attachments
6. `generating_markdown` (90%) - Generating Markdown
7. `completed` (100%) - Processing completed

### Results

```json
{
  "markdown_file": "/path/to/keynote.md",
  "markdown_content": "# Session Content...",
  "attachments": ["/path/to/video.mp4", "/path/to/slides.pdf"],
  "video_transcript": "Transcribed video content...",
  "target_dir": "/path/to/session/output"
}
```

## Transformer Handler

**Job Type**: `transformer`

Processes text transformation with templates.

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `text` | String | Yes* | Text to transform |
| `url` | String | Yes* | URL to fetch text from (alternative to text) |
| `template` | String | Yes | Template name |
| `context` | Dict | No | Additional context for template |
| `source_language` | String | No | Source language |
| `target_language` | String | No | Target language |
| `use_cache` | Boolean | No | Whether to use cache (default: `true`) |

*Either `text` or `url` must be provided.

### Example

```json
{
  "job_type": "transformer",
  "parameters": {
    "text": "Meeting notes...",
    "template": "MeetingMinutes",
    "context": {
      "meeting_date": "2024-01-01",
      "participants": ["Alice", "Bob"]
    }
  }
}
```

### Progress Steps

1. `initializing` (0%) - Initializing transformer processor
2. `loading_template` (20%) - Loading template
3. `transforming_text` (50%) - Transforming text with LLM
4. `finalizing` (90%) - Finalizing results
5. `completed` (100%) - Processing completed

### Results

```json
{
  "transformed_text": "Structured meeting minutes...",
  "template_fields": {
    "summary": "Meeting summary",
    "participants": ["Alice", "Bob"],
    "action_items": [...]
  }
}
```

## Booklet Handler

**Job Type**: `booklet`

Produces the b*coop Projektheft (120 × 120 mm booklet). Stage 1 crops every
photo to the 126 × 58 mm photo field around a focus point, tones it in the
theme's duotone and marks it when it is too small for print. Stage 2 fills the
Jinja2 template and renders `heft.pdf` with WeasyPrint, then checks the PDF with
PyMuPDF. Full endpoint documentation: [Booklet API](../../reference/api/endpoints/booklet.md).

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `pages` | Array | Yes | Pages in reading order, each with `type` (`cover`, `text`, `divider`, `project`, `blank`, `back`) |
| `template` | String | No | Template set (default: `bcoop-heft-120`) |
| `title` | String | No | Booklet title |
| `webhook` | Dict | No | `{url, token, jobId}`, called after completion |

Pages of type `cover` and `project` carry `image_url`, `focus {x, y}` and `theme`.
The parameters are validated against `BOOKLET_PARAMETERS_SCHEMA`
(`src/core/models/booklet.py`); invalid input fails the job with a `ValidationError`.

### Example

```json
{
  "job_type": "booklet",
  "parameters": {
    "title": "b*coop Projektheft 2026",
    "pages": [
      { "type": "cover", "id": "cover", "title": "b*coop Projektheft", "image_url": "https://.../titel.jpg" },
      { "type": "project", "id": "abc123", "title": "b*garden", "theme": "natur",
        "text": "Ein Stück Garten für alle ...", "image_url": "https://.../abc123_print.jpg?sv=...",
        "focus": { "x": 50, "y": 3 }, "qr_url": "https://wiki.bcommonslab.org/projekte?id=abc123" }
    ]
  }
}
```

### Progress Steps

1. `initializing` (5%) - Parameters validated
2. `images` (10-90%) - One step per image page, message names the page and its status
3. `images` (92%) - "PDF wird gesetzt"
4. `postprocessing` (95%) - Results stored
5. `completed` (100%) - Set by the worker

### Results

```json
{
  "asset_dir": "cache/booklet/temp/job-3f0c...",
  "assets": ["images/cover.jpg", "images/abc123.jpg", "report.json", "heft.pdf"],
  "structured_data": {
    "stage": "pdf",
    "pdf_file": "heft.pdf",
    "pdf": { "page_count": 4, "page_count_ok": true, "media_mm": { "width": 126, "height": 126 },
             "trim_mm": { "width": 120, "height": 120 }, "fonts_embedded": ["ABCDEF+Jost-Regular"],
             "fonts_not_embedded": [], "min_image_ppi": 300 },
    "page_count": 2,
    "summary": { "ready": 2, "borderline": 0, "not-ready": 0, "missing": 0, "error": 0 },
    "images": [
      { "page_id": "abc123", "page_type": "project", "status": "ready", "theme": "natur",
        "dpi": 806, "source_width": 4000, "source_height": 3000,
        "crop": { "x": 0, "y": 0, "width": 4000, "height": 1841 },
        "output_width": 1488, "output_height": 685, "file": "abc123.jpg", "warnings": [] }
    ]
  }
}
```

Files are downloaded via `GET /api/booklet/jobs/<job_id>/assets/<file>`.

## Creating Custom Handlers

### 1. Implement Handler Function

```python
from src.core.models.job_models import Job, JobStatus, JobProgress
from src.core.resource_tracking import ResourceCalculator

async def handle_custom_job(
    job: Job,
    repo: Any,
    resource_calculator: ResourceCalculator
) -> None:
    # Update status to processing
    repo.update_job_status(
        job.job_id,
        JobStatus.PROCESSING,
        progress=JobProgress(step="initializing", percent=0)
    )
    
    try:
        # Extract parameters
        params = job.parameters
        input_data = params.get("input")
        
        # Update progress
        repo.update_job_progress(
            job.job_id,
            JobProgress(step="processing", percent=50, message="Processing...")
        )
        
        # Process job
        result = process_custom(input_data)
        
        # Store results
        repo.update_job_results(
            job.job_id,
            {"result": result}
        )
        
        # Mark as completed
        repo.update_job_status(
            job.job_id,
            JobStatus.COMPLETED,
            progress=JobProgress(step="completed", percent=100)
        )
        
    except Exception as e:
        # Handle errors
        repo.update_job_error(
            job.job_id,
            JobError(
                code="PROCESSING_ERROR",
                message=str(e),
                details={"error_type": type(e).__name__}
            )
        )
        repo.update_job_status(job.job_id, JobStatus.FAILED)
```

### 2. Register Handler

In your handler module:

```python
from src.core.processing.registry import register

register("custom", handle_custom_job)
```

### 3. Import Handler Module

Ensure the handler module is imported so registration happens:

```python
# In src/core/processing/__init__.py or similar
from .handlers import custom_handler  # This triggers registration
```

## Related Documentation

- [Secretary Job Worker](secretary-job-worker-detailed.md) - Complete worker documentation
- [Job API Endpoints](../../reference/api/endpoints/jobs.md) - API documentation

