# Job Models

Dataclasses for asynchronous job processing and batch management.

## JobStatus

Enum for job status values.

### Values

- `PENDING` - Job is waiting to be processed
- `PROCESSING` - Job is currently being processed
- `COMPLETED` - Job completed successfully
- `FAILED` - Job failed with an error

## SecretaryJob

Main job model for asynchronous processing.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `job_id` | `str` | Unique job identifier |
| `job_type` | `str` | Type of job (e.g., "pdf", "session", "transformer") |
| `status` | `JobStatus` | Current status of the job |
| `parameters` | `Dict[str, Any]` | Job parameters |
| `created_at` | `datetime` | Creation timestamp |
| `updated_at` | `datetime` | Last update timestamp |
| `progress` | `Optional[JobProgress]` | Progress information |
| `results` | `Optional[Dict[str, Any]]` | Processing results |
| `error` | `Optional[Dict[str, Any]]` | Error information |
| `logs` | `List[LogEntry]` | Log entries |
| `access_control` | `AccessControl` | Access control settings |

### Example

```python
from src.core.models.job_models import SecretaryJob, JobStatus, JobProgress

job = SecretaryJob(
    job_id="job-123",
    job_type="pdf",
    status=JobStatus.PROCESSING,
    parameters={
        "filename": "/path/to/file.pdf",
        "extraction_method": "combined"
    },
    progress=JobProgress(
        step="extracting_text",
        percent=50,
        message="Extracting text from PDF..."
    )
)
```

## BatchJob

Batch job model for batch processing.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `batch_id` | `str` | Unique batch identifier |
| `batch_name` | `str` | Name of the batch |
| `status` | `JobStatus` | Current status of the batch |
| `jobs` | `List[SecretaryJob]` | Jobs in the batch |
| `created_at` | `datetime` | Creation timestamp |
| `updated_at` | `datetime` | Last update timestamp |
| `active` | `bool` | Whether batch is active |

## JobProgress

Progress information for a job.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `step` | `str` | Current processing step |
| `percent` | `int` | Progress percentage (0-100) |
| `message` | `Optional[str]` | Progress message |

## LogEntry

A log entry for a job.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | `datetime` | Log timestamp |
| `level` | `Literal["debug", "info", "warning", "error", "critical"]` | Log level |
| `message` | `str` | Log message |

## AccessControl

Access control for an object.

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `visibility` | `AccessVisibility` | Visibility (PRIVATE, PUBLIC) |
| `read_access` | `List[str]` | List of user IDs with read access |
| `write_access` | `List[str]` | List of user IDs with write access |
| `admin_access` | `List[str]` | List of user IDs with admin access |

