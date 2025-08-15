---
status: draft
last_verified: 2025-08-15
---

# Caching (Übersicht)

- Zweck: Ergebnisse wiederverwenden, LLM‑Kosten senken, Latenz reduzieren.
- Ebenen:
  - Dateibasiert (Temp/Cache‑Dirs je Prozessor)
  - MongoDB‑basierte Caches (Jobs/Batches, Transformer‑Zwischenstände)
- Schlüsselideen:
  - deterministische Cache‑Keys (z. B. MD5 über Datei/URL + Parameter)
  - klare Invalidierungsregeln (force_refresh, use_cache)
  - Tracing: `process.llm_info`, `process.duration_ms`

## Dateibasierter Cache (Prozessoren)
- PDF/Image‑OCR: Hash aus Dateiinhalt bzw. URL (`file_hash`/`url_hash`) + Extraktionsmethode + Template/Context.
- Audio/Video: Upload wird in temp‑Pfad geschrieben, Verarbeitungsergebnis kann anhand Quell‑Fingerprint wiederverwendet werden.
- Flags in API:
  - `useCache`/`use_cache` (bool)
  - `force_refresh` (Video)

## MongoDB‑Cache (Jobs & Batches)
- Komponenten:
  - `src/core/mongodb/repository.py` (SessionJobRepository)
  - Endpunkte unter `/api/event-job/*` für Jobs, Batches, Files
- Datenmodell (vereinfacht):
  - Job: `parameters`, `results` (Markdown, Assets, Archive), `progress`, `error`, `batch_id`, `user_id`
  - Batch: `status`, `isActive`, `archived`, Zähler (completed/failed)
- Steuerung:
  - Archivieren: `/api/event-job/batches/{id}/archive`
  - Aktiv/Passiv: `/api/event-job/batches/{id}/toggle-active`
  - Neustart Job: `/api/event-job/{job_id}/restart`

## Transformer‑Caching (Kurz)
- Prozessor erzeugt `process_info.cache_key` aus Inputs (Text/URL, Template, Parameter, Ziel‑Format, Sprache, Context).
- Ergebniswiederverwendung, wenn Key identisch.

## Cache‑Key Strategie (Empfehlung)
- Quelle: `md5(file)` oder `md5(url)` bzw. `md5(text)` für kleine Inputs
- Parameter: Methode (`native|ocr|llm|...`), `template`, `target_format`, `languages`, relevante `context`‑Felder
- Key: `sha1( source_fingerprint + '|' + method + '|' + template + '|' + param_hash )`

## Invalidation
- Automatisch: jeder Input‑/Parameterwechsel → neuer Key
- Manuell: `force_refresh=true` (Video) oder `useCache=false`
- Organisatorisch: Batches können archiviert werden; Archivieren löscht Cache nicht, sondern markiert Lebenszyklus.

Weiterführende Details wurden ins Archiv verschoben (historische Ausarbeitung).
