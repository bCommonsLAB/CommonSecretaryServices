---
status: draft
last_verified: 2025-08-15
---

# Response‑Struktur

Alle Endpunkte liefern Antworten im standardisierten Format. Ziel ist Einheitlichkeit, Nachvollziehbarkeit (inkl. LLM‑Tracking) und einfache Fehlerbehandlung.

## Schema
- **status**: `success` | `error`
- **request**: Kontext der Anfrage (Pfad, Parameter)
- **process**: Prozessinformationen (ID, Dauer in Millisekunden, Sub‑Prozessoren, LLM‑Tracking)
- **data**: Ergebnisdaten (prozessor‑spezifisch)
- **error**: Fehlerobjekt bei `status = error`

## Beispiel (success)
```json
{
  "status": "success",
  "request": {"path": "/api/transformer/text", "parameters": {"template": "summary"}},
  "process": {
    "id": "6a2...",
    "main_processor": "TransformerProcessor",
    "started": "2025-08-15T10:00:00Z",
    "duration_ms": 245,
    "sub_processors": [],
    "llm_info": {"total_requests": 1, "total_input_tokens": 900, "total_output_tokens": 120}
  },
  "data": {"text": "Kurzfassung ..."},
  "error": null
}
```

## Beispiel (error)
```json
{
  "status": "error",
  "request": {"path": "/api/pdf/process"},
  "process": {"id": "e19...", "main_processor": "PDFProcessor", "duration_ms": 12, "sub_processors": [], "llm_info": {}},
  "data": null,
  "error": {"code": "FILE_NOT_FOUND", "message": "Quelle nicht gefunden", "details": {"path": " /tmp/x.pdf"}}
}
```

## Hinweise
- Zeitangaben sind in Millisekunden
- `process.llm_info` aggregiert Anfragen/Tokens aller beteiligten Teilschritte
- Einheitliche Struktur erleichtert Logging, Monitoring und Tests


