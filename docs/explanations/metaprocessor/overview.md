---
status: draft
last_verified: 2025-08-15
---

# Metaprocessor (Überblick)

Ziel: Höherstufige Orchestrierung mehrerer Prozessoren (Audio, Transformer, Metadata, PDF/Image‑OCR) für komplexe Pipelines.

## Aufgaben (typisch)
- Eingaben normalisieren (Datei/URL/Text)
- Reihenfolge festlegen (z. B. Download → Transkription → Transformation → Metadaten)
- Kontext/Template‑Weitergabe
- Zwischenergebnisse cachen (Schlüssel aus Quelle + Parametern)
- Einheitliche Response (status/request/process/data/error)

## Designprinzipien
- Dünne Orchestrierung, Fachlogik bleibt in einzelnen Prozessoren
- Dataclasses mit `frozen=True`, `slots=True`, klare `to_dict()`
- Messpunkte: `process.duration_ms`, LLM‑Tracking

## BaseProcessor (Hinweise)
- Verantwortlich für Prozess‑ID, Temp‑Verzeichnisse, Performance‑Tracking, LLM‑Tracking
- Ort: `src/processors/base_processor.py`
- Erweiterungen: klare Hooks pro Verarbeitungsschritt statt verschachtelter Logik

Hinweis: Ausführliche historische Notizen sind im Archiv abgelegt. Diese Seite dient als aktuelle Referenz der Rolle und Prinzipien.
