---
status: draft
last_verified: 2025-08-15
---

# LLM‑Optimierung

## Kosten/Leistung
- Modelle: `gpt-4o` (Qualität), `gpt-4o-mini` (Schnell/Kosten)
- Bildgrößen/Qualität (Image‑OCR): 1024/75 (günstig), 2048/85 (Standard), 4096/95 (Qualität)

## Prompts/Kontext
- Dokumenttyp im Kontext setzen (scientific/technical/presentation)
- Zusätzliche Feldbeschreibungen (`additional_field_descriptions`) nutzen

## Tracking
- `src/core/resource_tracking.py` (Token/Kosten)
- Responses: `process.llm_info`

Verweise: `processors/image-ocr/overview.md`, `processors/transformer/overview.md`.
