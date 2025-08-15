# API-Referenz

## Überblick

Die Common Secretary Services API bietet RESTful Endpunkte für die Verarbeitung von Audio-, Video- und anderen Mediendateien. Diese Dokumentation beschreibt alle verfügbaren Endpunkte, deren Parameter und Responses.

## Authentifizierung

### API-Schlüssel
```http
POST /api/v1/audio/process
Authorization: Bearer your-api-key
```

### Rate Limiting
```yaml
limits:
  requests_per_minute: 60
  burst: 5
  reset_interval: 60
```

## Audio-Verarbeitung

### Audio-Datei verarbeiten
```http
POST /api/v1/audio/process
Content-Type: multipart/form-data

Parameters:
- file: Audio-Datei (required)
- template: Template-Name (optional)
- language: Zielsprache (optional)
```

#### Erfolgreiche Response
```json
{
  "status": "success",
  "process_id": "a62c1513f83a98f7b50075000964537b",
  "result": {
    "duration": 300.5,
    "detected_language": "de",
    "output_text": "Transkribierter Text...",
    "segments": [
      {
        "text": "Segment 1",
        "segment_id": 1,
        "start_time": 0.0,
        "end_time": 10.5
      }
    ]
  }
}
```

#### Fehler-Response
```json
{
  "status": "error",
  "error": {
    "code": "INVALID_FILE",
    "message": "Ungültiges Audioformat",
    "details": {
      "allowed_formats": ["mp3", "wav", "m4a"]
    }
  }
}
```

### Audio-Status abrufen
```http
GET /api/v1/audio/status/{process_id}

Response:
{
  "status": "processing",
  "progress": 45,
  "eta_seconds": 120
}
```

## YouTube-Integration

### Video verarbeiten
```http
POST /api/v1/youtube/process
Content-Type: application/json

{
  "url": "https://youtube.com/watch?v=...",
  "template": "Youtube",
  "language": "de"
}
```

#### Erfolgreiche Response
```json
{
  "status": "success",
  "process_id": "7994422446609c0d615bc2010d379e38",
  "result": {
    "title": "Video Titel",
    "duration": 600,
    "url": "https://youtube.com/watch?v=...",
    "video_id": "video123",
    "transcription": {
      "text": "Transkribierter Text...",
      "detected_language": "de",
      "segments": []
    },
    "metadata": {
      "upload_date": "20240122",
      "uploader": "Kanal Name",
      "view_count": 1000
    }
  }
}
```

### Video-Status abrufen
```http
GET /api/v1/youtube/status/{process_id}

Response:
{
  "status": "downloading",
  "progress": 75,
  "downloaded_bytes": 15000000,
  "total_bytes": 20000000
}
```

## Template-Verarbeitung

### Template rendern
```http
POST /api/v1/template/render
Content-Type: application/json

{
  "template": "Besprechung",
  "data": {
    "title": "Meeting Protokoll",
    "date": "2024-01-22T10:00:00",
    "content": "..."
  }
}
```

#### Erfolgreiche Response
```json
{
  "status": "success",
  "result": {
    "rendered_content": "# Meeting Protokoll\n\n...",
    "format": "markdown"
  }
}
```

## Job-Management

### Job-Status abrufen
```http
GET /api/v1/jobs/{job_id}

Response:
{
  "job_id": "a62c1513f83a98f7b50075000964537b",
  "status": "completed",
  "progress": 100,
  "result": {},
  "created_at": "2024-01-22T10:00:00Z",
  "updated_at": "2024-01-22T10:05:00Z"
}
```

### Job abbrechen
```http
POST /api/v1/jobs/{job_id}/cancel

Response:
{
  "status": "cancelled",
  "message": "Job erfolgreich abgebrochen"
}
```

## System-Status

### Health Check
```http
GET /health

Response:
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime": 3600,
  "components": {
    "api": "healthy",
    "processors": "healthy",
    "storage": "healthy"
  }
}
```

### Metriken
```http
GET /metrics

Response:
{
  "processing_jobs": {
    "active": 5,
    "queued": 10,
    "completed_last_hour": 45
  },
  "system_resources": {
    "cpu_usage": 45.2,
    "memory_usage": 2048,
    "disk_usage": 15000
  }
}
```

## Fehler-Codes

### HTTP-Status-Codes
- 200: Erfolgreiche Anfrage
- 201: Ressource erstellt
- 400: Ungültige Anfrage
- 401: Nicht authentifiziert
- 403: Nicht autorisiert
- 404: Ressource nicht gefunden
- 429: Rate-Limit überschritten
- 500: Server-Fehler

### Anwendungsspezifische Fehler
```json
{
  "INVALID_FILE": {
    "code": 4001,
    "message": "Ungültiges Dateiformat"
  },
  "PROCESSING_ERROR": {
    "code": 4002,
    "message": "Fehler bei der Verarbeitung"
  },
  "RATE_LIMIT_EXCEEDED": {
    "code": 4003,
    "message": "Rate-Limit überschritten"
  }
}
```

## Webhook-Integration

### Webhook konfigurieren
```http
POST /api/v1/webhooks
Content-Type: application/json

{
  "url": "https://your-domain.com/webhook",
  "events": ["job.completed", "job.failed"],
  "secret": "your-webhook-secret"
}
```

### Webhook-Payload
```json
{
  "event": "job.completed",
  "timestamp": "2024-01-22T10:05:00Z",
  "data": {
    "job_id": "a62c1513f83a98f7b50075000964537b",
    "status": "completed",
    "result": {}
  }
}
```

## API-Versioning

### Version Header
```http
GET /api/v1/audio/process
API-Version: 2024-01-22
```

### Changelog
```yaml
versions:
  - version: "2024-01-22"
    changes:
      - "Neue Audio-Formate hinzugefügt"
      - "Verbesserte Fehlerbehandlung"
  
  - version: "2023-12-15"
    changes:
      - "YouTube-Integration hinzugefügt"
      - "Template-System erweitert"
```

## Beispiel-Implementierungen

### Python-Client
```python
from secretary_client import SecretaryAPI

api = SecretaryAPI(api_key="your-api-key")

# Audio verarbeiten
result = api.process_audio(
    file_path="audio.mp3",
    template="Besprechung",
    language="de"
)

# Status abrufen
status = api.get_status(result.process_id)
```

### cURL-Beispiele
```bash
# Audio verarbeiten
curl -X POST \
  -H "Authorization: Bearer your-api-key" \
  -F "file=@audio.mp3" \
  http://localhost:5000/api/v1/audio/process

# YouTube-Video verarbeiten
curl -X POST \
  -H "Authorization: Bearer your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://youtube.com/watch?v=..."}' \
  http://localhost:5000/api/v1/youtube/process
``` 