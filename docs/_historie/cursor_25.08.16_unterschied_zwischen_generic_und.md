# Unterschied zwischen generic und secretary worker
_Exported on 8/21/2025 at 18:13:28 GMT+2 from Cursor (1.4.5)_

---

**User**

@generic-worker.md @secretary-job-worker-concept.md was ist der Unterschied dieser beiden worker?

---

**Cursor**

### Kurzantwort
- **generic-worker.md**: Praxisnahe Übersicht/How‑to für den generischen Worker im aktuellen System. Zeigt Architektur, Registry/Dispatch, Konfiguration und API‑Beispiele zum Einreihen und Abfragen.
- **secretary-job-worker-concept.md**: Ausführliches Zielbild/Design‑Spezifikation für ein vereinheitlichtes Job‑System (Datenmodell, Collections, Webhooks, Response‑Schema, Migrationspfad).

### Gegenüberstellung

| Aspekt | generic-worker.md | secretary-job-worker-concept.md |
|---|---|---|
| **Fokus** | Überblick + schnelle Nutzung | Vollständige Spezifikation/Zielarchitektur |
| **Reifegrad** | Implementierungsnah, pragmatisch | Konzeptionell, normierend |
| **Collections** | Verweist auf bestehende `event_jobs`/`event_batches` | Neue `jobs`/`batches` mit klaren Feldern |
| **Registry/Handler** | Beispiel für `register/get_handler`, Thread/async Mix | Einheitliche Handler‑Schnittstelle, Verantwortlichkeiten klar definiert |
| **Progress/Status** | Allgemeine Statuswechsel, Beispiele | Standardisierte Schritte und Prozent‑Logik |
| **API‑Beispiele** | `POST /api/jobs`, `GET /api/jobs/{id}`, Batch | Endpunkt‑Set vollständig inkl. Archiv‑Download, Polling |
| **Response‑Struktur** | Hinweise zu Ergebnissen (z. B. `page_texts`, `asset_dir`) | Striktes Schema inkl. `status/request/process/llm_info/data`, Fehlercodes |
| **Ergebnis‑Objekte** | URLs für Seiten‑Texte, Asset‑Verweise | Zusätzlich `archive_data` (Base64), konsistente API‑URLs statt Rohpfaden |
| **Webhooks** | Nicht zentral | Optionaler Webhook mit Payload‑Beispielen |
| **Sicherheit/ACL** | Nicht vertieft | `user_id`, `access_control` vorgesehen |
| **Migration** | Implizit kompatibel zur heutigen Nutzung | Expliziter Migrationspfad von Alt (`event_*`) → Neu (`jobs/batches`) |
| **Konfiguration** | `generic_worker.active`, `MONGODB_URI`, Concurrency | Zielbild; greift Standardisierung von Endpoints/Storage auf |

### Empfehlung
- **Schnell starten/integrieren**: Nutze die Leitplanken aus `generic-worker.md`.
- **System konsolidieren/erweitern** (Webhooks, Responses, neue Collections, Governance): Implementiere nach `secretary-job-worker-concept.md`.

- Kurz: `generic-worker.md` ist die kompakte Betriebsanleitung; `secretary-job-worker-concept.md` ist die normative Spezifikation, die das Zielsystem (inkl. API/Storage/Webhook) vollständig beschreibt.

