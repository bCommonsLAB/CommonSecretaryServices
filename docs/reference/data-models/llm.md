# LLM Models

Dataclasses for Language Model interactions and tracking.

## LLMInfo

Central tracking class that collects all LLM requests.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `requests` | `List[LLMRequest]` | List of all LLM requests |

### Properties

- `requests_count: int` - Number of requests
- `total_tokens: int` - Total number of tokens used
- `total_duration: float` - Total duration in milliseconds

### Methods

- `merge(other: LLMInfo) -> LLMInfo` - Merge two LLMInfo objects
- `add_request(request: Union[LLMRequest, List[LLMRequest]]) -> LLMInfo` - Add request(s)
- `to_dict() -> Dict[str, Any]` - Convert to dictionary

### Example

```python
from src.core.models.llm import LLMInfo, LLMRequest

llm_info = LLMInfo(requests=[
    LLMRequest(
        model="whisper-1",
        purpose="transcription",
        tokens=1500,
        duration=4500.0,
        processor="audio"
    ),
    LLMRequest(
        model="gpt-4",
        purpose="translation",
        tokens=2000,
        duration=3000.0,
        processor="transformer"
    )
])

print(llm_info.total_tokens)  # 3500
print(llm_info.total_duration)  # 7500.0
```

## LLMRequest

Detailed information about a single LLM request.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `model` | `str` | Name of the model (e.g., "whisper-1", "gpt-4") |
| `purpose` | `str` | Purpose of the request (e.g., "transcription", "translation") |
| `tokens` | `int` | Number of tokens used |
| `duration` | `float` | Processing duration in milliseconds |
| `processor` | `str` | Name of the calling processor |
| `timestamp` | `str` | ISO 8601 timestamp of the request |

### Example

```python
from src.core.models.llm import LLMRequest

request = LLMRequest(
    model="gpt-4",
    purpose="template_transformation",
    tokens=2500,
    duration=5000.0,
    processor="transformer"
)
```

## LLModel

Basic information about LLM usage.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `model` | `str` | Name of the model |
| `duration` | `float` | Processing duration in milliseconds |
| `tokens` | `int` | Number of tokens processed |
| `timestamp` | `str` | ISO 8601 timestamp |

