---
status: draft
last_verified: 2025-08-15
---

# Systemarchitektur (Überblick)

- API Layer (Flask-RESTX): Namespaces unter `/api/*`, Swagger unter `/api/doc`
- Processor Layer: Audio, Video, YouTube, Transformer, Metadata
- Storage: Cache/Temp, Logs, Konfiguration, Templates
- Externe Dienste: OpenAI (Whisper/GPT), YouTube API, FFmpeg

## Prozessorbeziehungen (vereinfacht)

- YouTube → Audio → Transformer
- Audio → Metadata → Transformer

```mermaid
graph TD
  A[BaseProcessor] --> B[CacheableProcessor]
  B --> C[AudioProcessor]
  B --> D[PDFProcessor]
  B --> E[ImageOCRProcessor]
  B --> F[TransformerProcessor]
  A --> G[MetadataProcessor]
  B --> H[SessionProcessor]
  B --> I[VideoProcessor]
  B --> J[TrackProcessor]
  B --> K[StoryProcessor]
  B --> L[YoutubeProcessor]
```

## Konfiguration

- `config/config.yaml`
- `.env`
