# Configuration Reference

Complete documentation of all `config.yaml` options.

## Overview

The application configuration is stored in `config/config.yaml` and supports environment variable substitution using `${VAR_NAME}` syntax.

## Cache Configuration

### `cache.base_dir`

- **Type**: String (path)
- **Default**: `./cache`
- **Description**: Base directory for cache files

### `cache.cleanup_interval`

- **Type**: Integer (hours)
- **Default**: `24`
- **Description**: Interval for cache cleanup in hours

### `cache.max_age_days`

- **Type**: Integer (days)
- **Default**: `7`
- **Description**: Maximum age of cache entries in days before cleanup

### `cache.mongodb.enabled`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable MongoDB-based caching

### `cache.mongodb.ttl_days`

- **Type**: Integer (days)
- **Default**: `30`
- **Description**: Time-to-live for MongoDB cache entries

### `cache.mongodb.create_indexes`

- **Type**: Boolean
- **Default**: `false`
- **Description**: Whether to create indexes on cache collections

## Worker Configuration

### `session_worker.active`

- **Type**: Boolean
- **Default**: `false`
- **Description**: Enable session worker for asynchronous session processing

### `session_worker.max_concurrent`

- **Type**: Integer
- **Default**: `3`
- **Description**: Maximum concurrent session jobs

### `session_worker.poll_interval_sec`

- **Type**: Integer (seconds)
- **Default**: `5`
- **Description**: Polling interval for session jobs

### `generic_worker.active`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable generic secretary job worker

### `generic_worker.max_concurrent`

- **Type**: Integer
- **Default**: `3`
- **Description**: Maximum concurrent generic jobs

### `generic_worker.poll_interval_sec`

- **Type**: Integer (seconds)
- **Default**: `5`
- **Description**: Polling interval for generic jobs

## Logging Configuration

### `logging.file`

- **Type**: String (path)
- **Default**: `logs/dev_detailed.log`
- **Description**: Path to log file

### `logging.level`

- **Type**: String (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- **Default**: `DEBUG`
- **Description**: Logging level

### `logging.max_size`

- **Type**: Integer (bytes)
- **Default**: `120000000` (120 MB)
- **Description**: Maximum log file size before rotation

### `logging.backup_count`

- **Type**: Integer
- **Default**: `5`
- **Description**: Number of backup log files to keep

### `logging.max_log_entries`

- **Type**: Integer
- **Default**: `1000`
- **Description**: Maximum log entries to keep in memory

## MongoDB Configuration

### `mongodb.uri`

- **Type**: String (MongoDB URI)
- **Default**: `${MONGODB_URI}` (from environment)
- **Description**: MongoDB connection URI

### `mongodb.connect_timeout_ms`

- **Type**: Integer (milliseconds)
- **Default**: `5000`
- **Description**: Connection timeout

### `mongodb.max_pool_size`

- **Type**: Integer
- **Default**: `50`
- **Description**: Maximum connection pool size

## Processor Configurations

### PDF Processor (`processors.pdf`)

#### `max_file_size`

- **Type**: Integer (bytes)
- **Default**: `150000000` (150 MB)
- **Description**: Maximum PDF file size

#### `max_pages`

- **Type**: Integer
- **Default**: `500`
- **Description**: Maximum number of pages to process

#### `cache_dir`

- **Type**: String (path)
- **Default**: `cache/pdf`
- **Description**: Cache directory for PDF processing

#### `cache.enabled`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable caching for PDF processing

#### `cache.ttl_days`

- **Type**: Integer (days)
- **Default**: `30`
- **Description**: Cache TTL for PDF results

#### `images.main.max_size`

- **Type**: Integer (pixels)
- **Default**: `1280`
- **Description**: Maximum size for main images

#### `images.main.format`

- **Type**: String (jpg, png)
- **Default**: `jpg`
- **Description**: Image format for main images

#### `images.main.quality`

- **Type**: Integer (0-100)
- **Default**: `80`
- **Description**: JPEG quality for main images

#### `images.preview.max_size`

- **Type**: Integer (pixels)
- **Default**: `360`
- **Description**: Maximum size for preview images

### Audio Processor (`processors.audio`)

#### `batch_size`

- **Type**: Integer
- **Default**: `5`
- **Description**: Number of audio segments to process in parallel

#### `export_format`

- **Type**: String (mp3, wav, etc.)
- **Default**: `mp3`
- **Description**: Export format for audio segments

#### `max_file_size`

- **Type**: Integer (bytes)
- **Default**: `200000000` (200 MB)
- **Description**: Maximum audio file size

#### `max_segments`

- **Type**: Integer
- **Default**: `100`
- **Description**: Maximum number of segments

#### `segment_duration`

- **Type**: Integer (seconds)
- **Default**: `300` (5 minutes)
- **Description**: Duration of each audio segment

### Video Processor (`processors.video`)

#### `cache_dir`

- **Type**: String (path)
- **Default**: `cache/video`
- **Description**: Cache directory for video processing

### YouTube Processor (`processors.youtube`)

#### `max_duration`

- **Type**: Integer (seconds)
- **Default**: `15000` (4.17 hours)
- **Description**: Maximum video duration

#### `max_file_size`

- **Type**: Integer (bytes)
- **Default**: `120000000` (120 MB)
- **Description**: Maximum downloaded file size

#### `ydl_opts.format`

- **Type**: String
- **Default**: `bestaudio/best`
- **Description**: yt-dlp format selection

#### `ydl_opts.nocheckcertificate`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Disable SSL certificate checking (Windows workaround)

### Transformer Processor (`processors.transformer`)

#### `model`

- **Type**: String
- **Default**: `gpt-4.1-mini`
- **Description**: LLM model for text transformation

#### `temperature`

- **Type**: Float (0.0-1.0)
- **Default**: `0.1`
- **Description**: Temperature for LLM generation

#### `max_tokens`

- **Type**: Integer
- **Default**: `4000`
- **Description**: Maximum tokens per request

#### `max_concurrent_requests`

- **Type**: Integer
- **Default**: `10`
- **Description**: Maximum concurrent LLM requests

#### `timeout_seconds`

- **Type**: Integer (seconds)
- **Default**: `120`
- **Description**: Request timeout

#### `templates_dir`

- **Type**: String (path)
- **Default**: `resources/templates`
- **Description**: Directory containing templates

### ImageOCR Processor (`processors.imageocr`)

#### `max_file_size`

- **Type**: Integer (bytes)
- **Default**: `10485760` (10 MB)
- **Description**: Maximum image file size

#### `max_resolution`

- **Type**: Integer (pixels)
- **Default**: `4096`
- **Description**: Maximum image resolution

### Metadata Processor (`processors.metadata`)

#### `max_file_size`

- **Type**: Integer (bytes)
- **Default**: `50000000` (50 MB)
- **Description**: Maximum file size for metadata extraction

#### `timeout_seconds`

- **Type**: Integer (seconds)
- **Default**: `30`
- **Description**: Timeout for metadata extraction

#### `extract_advanced_metadata`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Extract advanced metadata with LLM analysis

### Event Processor (`processors.event`)

#### `max_video_size`

- **Type**: Integer (MB)
- **Default**: `1000`
- **Description**: Maximum video size for downloads

#### `max_attachment_size`

- **Type**: Integer (MB)
- **Default**: `100`
- **Description**: Maximum attachment size

#### `request_timeout`

- **Type**: Integer (seconds)
- **Default**: `30`
- **Description**: HTTP request timeout

## Rate Limiting

### `rate_limiting.enabled`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable rate limiting

### `rate_limiting.requests_per_minute`

- **Type**: Integer
- **Default**: `60`
- **Description**: Maximum requests per minute per IP

## Server Configuration

### `server.host`

- **Type**: String (IP address)
- **Default**: `127.0.0.1`
- **Description**: Server host address

### `server.port`

- **Type**: Integer
- **Default**: `5000`
- **Description**: Server port

### `server.debug`

- **Type**: Boolean
- **Default**: `true`
- **Description**: Enable debug mode

### `server.api_base_url`

- **Type**: String (URL)
- **Default**: `http://localhost:5001`
- **Description**: Base URL for API

## Environment Variable Substitution

Configuration values can reference environment variables using `${VAR_NAME}` syntax:

```yaml
mongodb:
  uri: ${MONGODB_URI}  # Loaded from environment

processors:
  openai:
    api_key: ${OPENAI_API_KEY}  # Loaded from environment
```

## Related Documentation

- [Environment Variables](environment-variables.md) - All environment variables
- [Configuration Utilities](../../explanations/configuration.md) - Configuration management

