---
status: draft
last_verified: 2025-08-15
---

# Audio Processor

## Endpunkte
- POST `/api/audio/process`

## Parameter (Form)
- `file`: Audiodatei (multipart/form-data)
- `source_language` (ISO 639-1, default: de)
- `target_language` (ISO 639-1, default: de)
- `template` (optional)
- `useCache` (bool, default: true)

## Unterstützte Formate
`flac`, `m4a`, `mp3`, `mp4`, `mpeg`, `mpga`, `oga`, `ogg`, `wav`, `webm`

## Beispiel (cURL)
```bash
curl -X POST \
  -H "Content-Type: multipart/form-data" \
  -F "file=@tests/samples/sample_audio.m4a" \
  -F "source_language=de" \
  -F "target_language=de" \
  http://localhost:5000/api/audio/process
```

## Hinweise
- Content-Type muss `multipart/form-data` sein.
- Bei ungültigem Format oder fehlender Datei erfolgen valide Fehlerantworten.

## Mögliche Fehlercodes (Auszug)
- `INVALID_CONTENT_TYPE`
- `MISSING_FILE`
- `INVALID_FORMAT`

## Funktionen (Kurz)
- Transkription, Übersetzung, Segmentierung
- Optionale Template-Ausgabe
- Cache-Unterstützung
