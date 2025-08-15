---
status: draft
last_verified: 2025-08-15
---

# Sicherheit

## Grundsätze
- API‑Keys in `.env`, nie im Repo
- HTTPS, HSTS, sichere Headers (CSP, X-Content-Type-Options, X-Frame-Options)
- Rate‑Limiting auf API‑Layer
- Eingabevalidierung in API und Prozessoren

## Zugriff & Berechtigungen
- `X-User-ID` für Jobs/Batches (Lesen/Schreiben prüfen)
- Download‑Endpunkte prüfen Pfade (z. B. `samples`, `files`)

## Logging & Monitoring
- Fehler/Tracebacks in Logs, sensible Inhalte vermeiden
- LLM‑Tracking ohne PII in `process.llm_info`

## Betrieb
- Secrets Rotation, least privilege, Firewall/CORS passend konfigurieren
