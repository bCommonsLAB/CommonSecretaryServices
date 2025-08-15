---
status: draft
last_verified: 2025-08-15
---

# Image OCR Processor

## Endpunkte
- POST `/api/imageocr/process`
- POST `/api/imageocr/process-url`

## Funktionen (Kurz)
- Tesseract-OCR, optional LLM-OCR
- Templates/Formatting
- Cache-Unterstützung (MD5-Hash)

## Konfiguration (Kurz)
- `config/config.yaml`:
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o"
    max_image_size: 2048
    image_quality: 85
```
- `.env`: `OPENAI_API_KEY=...`
- Varianten: `gpt-4o` (Qualität), `gpt-4o-mini` (Kosten/Geschwindigkeit)

## Extraktionsmethoden
- `ocr` (Tesseract), `llm`, `llm_and_ocr`

## Beispiele (curl)
```bash
# LLM-OCR Bild
curl -X POST http://localhost:5000/api/imageocr/process \
  -F "file=@tests/samples/diagramm.jpg" \
  -F "extraction_method=llm"
```

## Best Practices
- Dokumenttyp im `context` angeben (z. B. scientific, presentation)
- `max_image_size`/`image_quality` feinjustieren
- Cache aktivieren, kombinierte Methoden für schwierige Dokumente

## Weiterführend
- Historische Details im Archiv (`_archive/HowToUseimageocr.md`, `_archive/swagger_llm_ocr_integration.md`).
