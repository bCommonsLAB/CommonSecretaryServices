---
status: draft
last_verified: 2025-08-15
---

# PDF Processor

## Endpunkte
- POST `/api/pdf/process`
- POST `/api/pdf/process-url`
- GET `/api/pdf/text-content/<path:file_path>`

## Funktionen (Kurz)
- Native Textextraktion, Tesseract-OCR, LLM-gestützte OCR
- Vorschaubilder und optional ZIP-Archiv
- Cache-Unterstützung (MD5-Hash)

```mermaid
flowchart TD
  S[PDF/Image] --> A{OCR-Mode}
  A -->|Native| N[Text-Extraction]
  A -->|Tesseract| T[Tesseract OCR]
  A -->|LLM| L[Vision LLM]
  N --> X[Postprocess -> Markdown]
  T --> X
  L --> X
  X --> R[Optional: Transformer]
```

## Weiterführend
- OCR-Refactoring: [ocr-refactoring.md](ocr-refactoring.md)
- PDF/ImageOCR Endpoints: [endpoints.md](endpoints.md)
