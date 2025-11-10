# Audio API Endpoints

Endpoints for audio file processing with transcription and optional translation.

## POST /api/audio/process

Process an audio file with transcription and optional template-based transformation.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Audio file (MP3, WAV, M4A, FLAC, OGG, etc.) |
| `source_language` | String | No | `de` | Source language (ISO 639-1 code, e.g., "en", "de") |
| `target_language` | String | No | `de` | Target language for translation (ISO 639-1 code) |
| `template` | String | No | `""` | Optional template name for text transformation |
| `useCache` | Boolean | No | `true` | Whether to use cache |

### Supported Formats

- FLAC, M4A, MP3, MP4, MPEG, MPGA, OGA, OGG, WAV, WEBM

### Request Example

```bash
curl -X POST "http://localhost:5001/api/audio/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@audio.mp3" \
  -F "source_language=en" \
  -F "target_language=de" \
  -F "template=MeetingMinutes" \
  -F "useCache=true"
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "request": {
    "id": "process-id-123",
    "timestamp": "2024-01-01T00:00:00Z"
  },
  "process": {
    "duration_ms": 5000,
    "llm_info": {
      "total_tokens": 1500,
      "total_cost": 0.015,
      "requests": [
        {
          "model": "whisper-1",
          "purpose": "transcription",
          "tokens": 1500,
          "duration_ms": 4500
        }
      ]
    }
  },
  "data": {
    "duration": 120.5,
    "detected_language": "en",
    "output_text": "Transcribed and transformed text...",
    "original_text": "Original transcribed text...",
    "translated_text": "Translated text...",
    "llm_model": "whisper-1",
    "translation_model": "gpt-4",
    "token_count": 1500,
    "segments": [
      {
        "id": 0,
        "start": 0.0,
        "end": 10.5,
        "text": "First segment..."
      }
    ],
    "process_id": "process-id-123",
    "process_dir": "/path/to/process/dir",
    "from_cache": false
  }
}
```

### Response (Error)

**Status Code**: `400 Bad Request`

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_FORMAT",
    "message": "The format 'xyz' is not supported. Supported formats: flac, m4a, mp3...",
    "details": {
      "error_type": "INVALID_FORMAT",
      "supported_formats": ["flac", "m4a", "mp3", ...]
    }
  }
}
```

### Processing Flow

1. Audio file is uploaded and validated
2. File is segmented into manageable chunks (if large)
3. Each segment is transcribed using OpenAI Whisper API
4. Optional: Text is transformed using template (via TransformerProcessor)
5. Optional: Text is translated to target language
6. Results are aggregated and returned

### LLM Tracking

The response includes detailed LLM usage information:
- Total tokens used
- Total cost
- Individual requests with model, purpose, tokens, duration

### Caching

Results are cached based on:
- File hash
- Source language
- Target language
- Template name

Use `useCache=false` to bypass cache and force reprocessing.

