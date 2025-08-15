# Doku-Triage (automatisch generiert)

Legende:
- keep: Bereits Teil der neuen Struktur
- curate: Relevante Inhalte vorhanden, aber konsolidieren/aktualisieren
- archive: Historisch oder redundant; in Archiv verschieben

Heuristiken:
- Pfad beginnt mit `historie/` → archive
- Enthält `/api/v1/` → curate (auf `/api` aktualisieren) oder archive, wenn vollständig ersetzt
- Liegt unter `guide/`, `processors/`, `reference/`, `explanations/` → keep

## Ergebnisse (Auszug)

- keep: `guide/getting-started/installation.md`, `guide/getting-started/development.md`, `guide/ui/dashboard.md`
- keep: `explanations/architecture/overview.md`
- keep: `processors/audio/overview.md`, `processors/video/overview.md`, `processors/pdf/overview.md`, `processors/image-ocr/overview.md`, `processors/transformer/overview.md`, `processors/session/overview.md`, `processors/event-job/overview.md`
- keep: `reference/api/overview.md`, `reference/api/openapi.md`

- archive: `historie/cursor_25.07.14_1_aufgaben_im_pdf_und_image_prozes.md`
- archive: `historie/cursor_25.07.14_2_unterschied_zwischen_pdf_verarbe.md`

- curate: `pdf_processor_ocr_refactoring.md` (verlinkt), `processors_pdf_imageocr.md` (verlinkt)
- curate: `llm_ocr_configuration.md`, `llm_ocr_integration.md`, `swagger_llm_ocr_integration.md` → in Image‑OCR/Reference integrieren
- curate: `08_templates.md`, `template_content_feature.md` → in Transformer integrieren
- curate: `CommonSecretaryServicesAPI.md` → zerteilen in Guide/Reference
- curate: `ProcessorArchitecture.md`, `localbrain_architecture.md` → nach Explanations migrieren
- curate: `session_archive_usage.md` → Event‑Job Seite erweitern
- curate: `vimeo_support.md` → Video-Seite (optional)

- archive (veraltet `/api/v1/`): `13_api_reference.md`, `07_youtube.md`, `07_async_event_processing.md`
- curate: `07_async_event_processing_implementation.md` → Explanations übernehmen

- curate: Typen/Dataclasses: `05_types.md`, `dataclasses-types.md`, `audioprocessor_typisierung.md`, `videoprocessor_typisierung.md`, `youtubeprocessor_typisierung.md`, `metaprocessor_typisierung.md`, `generic_typing_improvements.md`, `type-migration.md` → konsolidierte Seite unter Explanations/Types

- curate: Caching/MongoDB: `caching_implementation_plan.md`, `mongodb_caching_implementation.md`, `transformer_mongodb_caching.md`, `process-events-mongo-db.md` → Explanations/Caching

- curate: Metaprocessor: `metaprocessor-concept.md`, `metaprocessor-integration.md`, `refact-metaprocessor.md`, `metaprocessor_typisierung.md` → eigener Explanations‑Cluster oder Archive, falls nicht mehr relevant

- curate: Security/Deployment/Troubleshooting: `09_security.md`, `11_security.md`, `11_deployment.md`, `12_troubleshooting.md` → Ops‑Bereich

- curate: Story/Track/Events: `storytelling.md`, `concept_storytelling_processor.md`, `track_processor.md`, `track-processor-api.md`, `events.md` → Processors/Story/Track/Events oder Archive

- curate: Sonstiges: `linting_strategy.md`, `optimizeProzessWithBaseprocess.md`, `process_events.md`, `n8nEventsProcessing.md`, `scrape-notion.md`, `api-responses-concept.md` → je nach Relevanz konsolidieren/archivieren

Hinweis: Dies ist eine erste automatische Einordnung. Im nächsten Schritt verschiebe ich alle als „archive“ markierten Dateien nach `docs/_archive/` und lege TODO‑Listen für die „curate“-Gruppen an.
