---
status: draft
last_verified: 2025-08-15
---

# Troubleshooting

## Häufige Probleme
- 400 INVALID_CONTENT_TYPE: multipart/form-data fehlt (Audio/Image)
- 404 Datei nicht gefunden: Pfad außerhalb erlaubter Verzeichnisse
- 403 Permission denied: `X-User-ID` stimmt nicht
- 500 ProcessingError: Stacktrace in Logs prüfen

## Checks
```bash
# API erreichbar?
curl -sSf http://localhost:5000/api/doc > /dev/null
# Swagger JSON
curl -sSf http://localhost:5000/api/swagger.json > /dev/null
# Tests
pytest -q
```

## Logs
- `logs/` Dateien sichten
- DEBUG einschalten (temporär) in `config.yaml`
