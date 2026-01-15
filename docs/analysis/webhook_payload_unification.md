# Analyse: Einheitliches Webhook-Format (ohne Sync-API zu destabilisieren)

## Ausgangslage
In der Codebasis existieren aktuell mehrere „Antwortformen“:

- **Synchroner HTTP-Response** (z.B. `/api/audio/process`, `/api/pdf/process`): liefert eine vollständige API-Response.
- **Webhook-Callbacks** (Async): liefern typischerweise ein reduziertes Payload wie `{ phase, message, data }` bzw. `{ phase, message, error, data }`.

Zusätzlich existieren **Progress-Events** (Log-Observer) und vereinzelte Error-Callbacks aus dem Worker-Manager, die nicht überall identisch strukturiert sind.

Ziel: **Webhooks sollen einheitlich** sein, ohne bestehende Sync-Nutzer (Audio wird von mehreren Prozessoren genutzt) zu brechen.

## Anforderungen / Leitplanken
- **Backward compatible**: Bestehende Webhook-Consumer dürfen nicht brechen.
  - Praktisch: Nur **zusätzliche** Felder hinzufügen, keine entfernen/umbenennen.
- **Sync-Responses unverändert lassen**, um Abhängigkeiten nicht zu destabilisieren.
- **Webhook-Envelope** soll für alle Job-Handler gleich aussehen.
- Payload klein halten (keine großen Base64-Felder).

## 3 Varianten

### Variante A (empfohlen): Additiver Webhook-Envelope (Schema v1)
Wir standardisieren Webhooks über ein gemeinsames Envelope und fügen die Felder **additiv** hinzu:

```json
{
  "schema_version": 1,
  "worker": "secretary",
  "phase": "initializing|running|postprocessing|completed|error",
  "message": "...",
  "process": { "id": "internal_job_id", "main_processor": "pdf|audio|..." },
  "job": { "id": "external_job_id_or_internal_job_id" },
  "data": { ... },
  "error": { "code": "...", "message": "...", "details": {...} }
}
```

**Pro**
- Minimaler Eingriff.
- Sehr geringe Gefahr, bestehende Clients zu brechen (zusätzliche JSON-Keys werden meist ignoriert).
- Sync bleibt unverändert.

**Contra**
- Webhook ist weiterhin nicht „identisch“ zum Sync-Response (aber konsistent/standardisiert).

### Variante B: Webhook = vollständiger Sync-Response
Webhook sendet exakt dieselbe Struktur wie der sync Response (inkl. `status/request/process/data/error`).

**Pro**
- 100% identisches Contract zwischen Sync und Webhook.

**Contra**
- Größere Payloads, potenziell große Felder (Mongo/ZIP/Base64) → Risiko.
- Clients, die heute `{phase,message,data}` erwarten, müssten angepasst werden (breaking change).

### Variante C: Versionierte Webhooks (v1/v2 Opt-in)
Wir führen einen Request-Parameter ein (z.B. `webhook_version=v2`), der das Payload-Format umschaltet.

**Pro**
- Saubere Migration: bestehende Clients bleiben auf v1.
- Neue Clients können v2 erzwingen.

**Contra**
- Mehr Komplexität (Doku, Tests, Code-Pfade).

## Entscheidung
Für Stabilität der bestehenden Anwendung: **Variante A**.

- Sync-Responses bleiben unverändert.
- Webhook-Payload wird standardisiert durch **zusätzliche** Felder (`schema_version`, `worker`, `process`, `job`).
- Bestehende Felder `phase`, `message`, `data`, `error` bleiben erhalten.
- **Standardfeld für Audio/Video**: `data.transcription.text`
- **Standardfeld für PDF**: `data.extracted_text` (optional zusätzlich Alias `data.transcription.text` für Unified Parsing)

Optionaler Folge-Schritt (später): Variante C, falls wir harte Guarantees oder breaking changes brauchen.


