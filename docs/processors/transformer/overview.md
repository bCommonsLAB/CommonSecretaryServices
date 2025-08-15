---
status: draft
last_verified: 2025-08-15
---

# Transformer Processor

## Endpunkte
- POST `/api/transformer/text`
- POST `/api/transformer/template`
- POST `/api/transformer/html-table`
- POST `/api/transformer/text/file`
- POST `/api/transformer/metadata`

## Kurzbeschreibung
- `text`: Freitext-Transformation (Übersetzen, Zusammenfassen, Formatwechsel)
- `template`: Text oder URL anhand eines Templates in Struktur bringen
- `html-table`: HTML-Tabellen von Webseiten als JSON extrahieren
- `text/file`: Textdatei-Upload (.txt, .md) transformieren
- `metadata`: Metadaten-Extraktion für verschiedene Dateitypen

## Templates (kurz)
- Templates liegen im Verzeichnis `templates/` (Markdown)
- Entspricht `POST /api/transformer/template`
- Details siehe: [Templates Übersicht](../../explanations/templates/overview.md)
