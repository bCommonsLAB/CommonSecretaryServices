---
status: draft
last_verified: 2025-08-15
---

# Metadata Processor

Der Metadata‑Prozessor extrahiert technische und inhaltliche Metadaten aus Inhalten und wird häufig von anderen Prozessoren (z. B. Audio, Video, Session, PDF/Image‑OCR) intern genutzt.

## Endpunkte
- Keine direkten öffentlichen Endpunkte. Metadaten werden im Rahmen anderer Verarbeitungen erzeugt oder über Transformationsendpunkte (siehe Transformer/Metadata) angereichert.

## Typische Aufgaben
- Technische Metadaten (z. B. Dauer, Formate, Größen)
- Inhaltliche Metadaten via LLM (z. B. Titel, Tags, Zusammenfassungen, Sprachinformationen)
- Normalisierung und Strukturierung für die Ausgabe

## Eingaben (Beispiele)
- Referenz auf Quellinhalt (Dateipfad/URL/Text)
- Optionale Parameter: Ziel‑Sprache, gewünschte Kategorien, Qualitätsprofil

## Ausgaben (Beispiele)
- Strukturierte Metadaten (z. B. `title`, `language`, `keywords`, `summary`, `duration_ms`)
- Einbettung in den standardisierten API‑Response‑Wrapper

## Response‑Beispiel (success)
```json
{
  "status": "success",
  "request": {"path": "/api/...", "parameters": {"source": "file"}},
  "process": {
    "id": "b1f...",
    "main_processor": "MetadataProcessor",
    "started": "2025-08-15T10:00:00Z",
    "duration_ms": 1234,
    "sub_processors": [],
    "llm_info": {"total_requests": 1, "total_input_tokens": 800, "total_output_tokens": 120}
  },
  "data": {
    "title": "Beispieltitel",
    "language": "de",
    "keywords": ["konferenz", "ki"],
    "summary": "Kurze inhaltliche Zusammenfassung.",
    "duration_ms": 3600000
  },
  "error": null
}
```

## Fehlerfälle
- Quellen nicht erreichbar oder leer → `status: error`, Fehlercode und Details
- LLM‑Limit überschritten → Parameter/Qualitätsprofil anpassen

## Hinweise
- Konsistente Parameterübergabe erhöht Cache‑Trefferquoten
- Für LLM‑basierte Anreicherungen: Kontext knapp und präzise halten
- Siehe auch: `Processors → Transformer (Metadata)` und `Explanations → Types`


