# Drift-Audit (Doku ↔ Code)

Ziel: Abweichungen zwischen dokumentierten Endpunkten/Begriffen und dem tatsächlichen Code sichtbar machen.

## Befund (Stand jetzt)

- API-Präfix
  - Doku: Mehrere Seiten verwenden `/api/v1/...` (z. B. 13_api_reference.md, 06_audio_processing.md, 07_youtube.md, 02_installation.md, 03_development.md)
  - Code: Registrierte Namespaces unter `/api/...` (ohne Version). → Status: outdated

- PDF/ImageOCR
  - Doku: Dokumentiert `/api/pdf/process`, `/api/pdf/process-url`, `/api/imageocr/process`, `/api/imageocr/process-url` mehrfach (z. B. HowToUseimageocr.md, historien-Dateien, swagger_llm_ocr_integration.md)
  - Code: Entspricht den Namespaces `pdf` und `imageocr` und deren Routen. → Status: confirmed

- Transformer
  - Doku: Fokus auf `/api/transformer/template` (u. a. 08_templates.md, template_content_feature.md)
  - Code: Zusätzliche Endpunkte vorhanden (`/text`, `/html-table`, `/text/file`, `/metadata`). → Status: missing (Doku ergänzen)

- Session/Event-Job
  - Doku: Umfangreiche Beispiele unter session_archive_usage.md mit `/api/event-job/...` und `/api/session/process` → Status: confirmed (stichprobenartig)
  - Code: Endpunkte vorhanden (Jobs, Batches, Files, Restart, Archive, Toggle-Active, Download-Archive)

- Events/Tracks/Story
  - Doku: Story-/Track-/Events-Dokumente teils konzeptionell, Endpunkte werden erwähnt; Pfade prüfen und konsolidieren → Status: needs-review

- Common/Samples
  - Doku: Samples in CommonSecretaryServicesAPI.md und testroutine.md verlinkt
  - Code: `/api/common/samples` und zusätzlich `/api/samples` (Root-Registrierung) → Status: confirmed

## Empfehlungen pro Thema

- `/api/v1` Vorkommen systematisch ersetzen durch `/api`, aber: Redirect/Notiz für Alt-Links beibehalten.
- Transformer-Referenzseite erstellen, die alle Endpunkte abdeckt, plus kurze Beispiele.
- In Prozessorseiten (Audio, PDF, ImageOCR, Video, YouTube) am Seitenanfang „Last verified“ mit Datum und Verweis auf Tests angeben.

## Nächste Automatisierungsschritte

- Audit-Skript (Python) einführen, das:
  - aus `src/api/routes/**` alle Routen extrahiert,
  - in `docs/` nach Vorkommen sucht,
  - „missing/outdated/unreferenced“ als Tabelle ausgibt.
- Frontmatter-Konvention in Doku-Seiten: `status`, `last_verified`.
- CI: Build + Linkcheck + Audit als Warnung im PR.
