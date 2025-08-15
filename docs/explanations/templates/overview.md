---
status: draft
last_verified: 2025-08-15
---

# Templates (Übersicht)

- Zweck: Unstrukturierte Eingaben (Text/URL) in strukturierte Ausgaben (Markdown/JSON/HTML) überführen.
- Ort: `templates/` im Projekt (Markdown‑basierte Templates)
- Hauptendpoint: `POST /api/transformer/template`
  - Eingaben: `text` oder `url`, `template` oder `template_content`, optional `context`, `additional_field_descriptions`, `use_cache`
- Erweiterungen:
  - `template_content`: Template direkt im Request übergeben
  - `additional_field_descriptions`: Felder/Validierung präzisieren
  - Caching via `use_cache`

Minimalbeispiel (curl):
```bash
curl -X POST http://localhost:5000/api/transformer/template \
  -F "text=Beispieltext" \
  -F "template=Besprechung"
```

Hinweis: Ausführliche historische Beschreibungen wurden ins Archiv verschoben. Die aktuelle Referenz steht in „Processors → Transformer“ und „Reference → API“.
