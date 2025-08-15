---
status: draft
last_verified: 2025-08-15
---

# Video Processor

## Endpunkte
- POST `/api/video/process` (Datei-Upload oder URL)
- POST `/api/video/youtube` (YouTube-URL)

## Parameter (Kurz)
- Datei-/URL-basierte Verarbeitung
- `source_language` (auto)
- `target_language` (de)
- `template` (optional)
- `useCache` (bool)
- `force_refresh` (bool, für `/process`)

## Funktionen (Kurz)
- Video → Audio-Extraktion → Transkription → Transformation
- Direkte YouTube-Unterstützung
- Cache-Unterstützung

## YouTube / Plattformen
- Unterstützt YouTube‑URLs (Download → Audio‑Extraktion → Transkription)
- Parameter: `youtube_include_dash_manifest`, `best_audio_format`
- Hinweise: Raten‑Limits und Formatverfügbarkeit können variieren

```mermaid
sequenceDiagram
  participant Client
  participant API as /api/video/youtube
  participant VP as VideoProcessor
  participant YT as YouTube
  participant TP as Transformer

  Client->>API: POST { url }
  API->>VP: process(url)
  VP->>YT: Download + Audio‑Extraktion
  VP->>TP: Transkription/Transformation
  TP-->>VP: Text/MD
  VP-->>API: BaseResponse{...}
  API-->>Client: JSON
```