# Data Models Reference

Complete documentation of all dataclasses and Pydantic models used throughout Common Secretary Services.

## Overview

All data models follow a consistent structure:
- **Type Safety**: Strict type annotations with Python `typing` module
- **Validation**: Field validation in `__post_init__` methods
- **Serialization**: `to_dict()` and `from_dict()` methods for JSON conversion
- **Immutability**: Many models use `frozen=True` for immutability
- **Slots**: Performance optimization with `slots=True` where applicable

## Model Categories

### Base Models

Fundamental models used by all processors:

- **[Base Models](base.md)** - BaseResponse, ErrorInfo, RequestInfo, ProcessInfo

### Processor-Specific Models

Models for specific processors:

- **[Audio Models](audio.md)** - AudioResponse, TranscriptionResult, TranscriptionSegment
- **[Video Models](video.md)** - VideoResponse, VideoProcessingResult, VideoSource
- **[PDF Models](pdf.md)** - PDFResponse, PDFMetadata, PDFProcessingResult
- **[ImageOCR Models](imageocr.md)** - ImageOCRResponse, ImageOCRMetadata
- **[Transformer Models](transformer.md)** - TransformerResponse, TemplateField, TemplateFields
- **[Session Models](session.md)** - SessionResponse, SessionInput, SessionOutput, SessionData
- **[Event Models](event.md)** - EventResponse, EventInput, EventOutput, EventData
- **[Track Models](track.md)** - TrackResponse, TrackInput, TrackOutput, TrackData
- **[Story Models](story.md)** - StoryResponse, StoryProcessorInput, StoryProcessorOutput
- **[YouTube Models](youtube.md)** - YoutubeResponse, YoutubeMetadata, YoutubeProcessingResult

### System Models

Models for system functionality:

- **[Job Models](job.md)** - Job, Batch, JobStatus, JobProgress, JobResults
- **[LLM Models](llm.md)** - LLMInfo, LLMRequest, LLModel
- **[Metadata Models](metadata.md)** - MetadataResponse, ContentMetadata, TechnicalMetadata
- **[Translation Models](translation.md)** - Translation
- **[Notion Models](notion.md)** - NotionBlock, NotionPage, NotionResponse

### Enums and Types

- **[Enums](enums.md)** - ProcessorType, ProcessingStatus, OutputFormat, EventFormat, PublicationStatus, LanguageCode

## Common Patterns

### Response Format

All API responses follow this structure:

```python
@dataclass(frozen=True)
class BaseResponse:
    status: ProcessingStatus
    request: RequestInfo
    process: Optional[ProcessInfo]
    error: Optional[ErrorInfo]
    data: Any  # Processor-specific data
```

### Error Handling

Errors are structured as:

```python
@dataclass
class ErrorInfo:
    code: str
    message: str
    details: Dict[str, Any]
```

### Process Tracking

Process information includes LLM tracking:

```python
@dataclass
class ProcessInfo:
    id: str
    main_processor: str
    started: str
    completed: Optional[str]
    duration: Optional[float]
    llm_info: Optional[LLMInfo]  # LLM usage tracking
    is_from_cache: bool
    cache_key: Optional[str]
```

## Usage Examples

### Creating a Response

```python
from src.core.models.base import BaseResponse, RequestInfo, ProcessInfo
from src.core.models.enums import ProcessingStatus

response = BaseResponse(
    status=ProcessingStatus.SUCCESS,
    request=RequestInfo(
        processor="audio",
        timestamp="2024-01-01T00:00:00Z"
    ),
    process=ProcessInfo(
        id="process-123",
        main_processor="audio",
        started="2024-01-01T00:00:00Z"
    ),
    data={"transcription": "..."}
)
```

### Serialization

```python
# Convert to dictionary
response_dict = response.to_dict()

# Convert to JSON
import json
json_str = json.dumps(response_dict)
```

### Deserialization

```python
# From dictionary
response = BaseResponse.from_dict(response_dict)

# From JSON
response_dict = json.loads(json_str)
response = BaseResponse.from_dict(response_dict)
```

## Related Documentation

- [API Reference](../api/overview.md) - API endpoints using these models
- [Configuration Reference](../configuration.md) - Configuration options
- [Code Index](../code-index.md) - All documented modules

