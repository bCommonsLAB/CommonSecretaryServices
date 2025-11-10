# Base Models

Fundamental dataclasses used by all processors and API routes.

## BaseResponse

Base class for all API responses with standardized format.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ProcessingStatus` | Status of the processing (SUCCESS, ERROR, PENDING) |
| `request` | `RequestInfo` | Information about the request |
| `process` | `Optional[ProcessInfo]` | Information about the processing process |
| `error` | `Optional[ErrorInfo]` | Error information (if status is ERROR) |
| `data` | `Any` | Processor-specific data |

### Example

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

## ErrorInfo

Structured error information for API responses.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `code` | `str` | Error code identifier |
| `message` | `str` | Human-readable error message |
| `details` | `Dict[str, Any]` | Additional error details |

### Example

```python
from src.core.models.base import ErrorInfo

error = ErrorInfo(
    code="INVALID_FORMAT",
    message="The format 'xyz' is not supported",
    details={"supported_formats": ["mp3", "wav"]}
)
```

## RequestInfo

Information about a processing request.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `processor` | `str` | Name of the processor |
| `timestamp` | `str` | ISO 8601 timestamp of the request |
| `parameters` | `Dict[str, Any]` | Request parameters |

## ProcessInfo

Information about a processing process, including LLM tracking.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique process identifier |
| `main_processor` | `str` | Name of the main processor |
| `started` | `str` | ISO 8601 timestamp when processing started |
| `sub_processors` | `List[str]` | List of sub-processors used |
| `completed` | `Optional[str]` | ISO 8601 timestamp when processing completed |
| `duration` | `Optional[float]` | Processing duration in milliseconds |
| `llm_info` | `Optional[LLMInfo]` | LLM usage tracking information |
| `is_from_cache` | `bool` | Whether result was loaded from cache |
| `cache_key` | `Optional[str]` | Cache key used |

### Example

```python
from src.core.models.base import ProcessInfo
from src.core.models.llm import LLMInfo, LLMRequest

process_info = ProcessInfo(
    id="process-123",
    main_processor="audio",
    started="2024-01-01T00:00:00Z",
    completed="2024-01-01T00:05:00Z",
    duration=300000.0,
    llm_info=LLMInfo(requests=[
        LLMRequest(
            model="whisper-1",
            purpose="transcription",
            tokens=1500,
            duration=4500.0,
            processor="audio"
        )
    ]),
    is_from_cache=False
)
```

## ProcessingLogger

Protocol for logger interface.

### Methods

- `debug(message: str, **kwargs: Any) -> None`
- `info(message: str, **kwargs: Any) -> None`
- `warning(message: str, **kwargs: Any) -> None`
- `error(message: str, **kwargs: Any) -> None`

