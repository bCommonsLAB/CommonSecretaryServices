# Doku-Inventur (H1/H2 Übersicht)

Hinweis: Historisch gewachsene Inhalte, erste Konsolidierung. Diese Übersicht dient als Ausgangspunkt für IA/Navigation und Drift-Prüfung. Statusfelder werden nach und nach ergänzt.

## Hauptdokumente (Root von `docs/`)

- 01_architecture.md — Architekturüberblick
- 02_installation.md — Installation
- 03_development.md — Entwicklung
- 04_api.md — API Überblick (historisch)
- 05_types.md — Typen/Typisierung (historisch)
- 05_webinterface.md — Webinterface/Dashboard
- 06_audio_processing.md — Audioverarbeitung
- 07_async_event_processing.md — Async Event Processing (Konzept)
- 07_async_event_processing_implementation.md — Async Event Processing (Implementierung)
- 07_youtube.md — YouTube-Processor
- 08_templates.md — Templates/Transformer
- 09_security.md — Sicherheit (alt)
- 10_development_guidelines.md — Entwicklungsrichtlinien
- 11_deployment.md — Deployment
- 11_security.md — Sicherheit (neu)
- 12_troubleshooting.md — Troubleshooting
- 13_api_reference.md — API Referenz (historisch, /api/v1)
- 14_changelog.md — Changelog 2024/2025
- 15_faq.md — FAQ
- 15_support.md — Support
- CommonSecretaryServicesAPI.md — Einstieg/Swagger/Beispiele
- HowToUseimageocr.md — Image-OCR API Doku
- llm_ocr_configuration.md — LLM-OCR Konfiguration
- swagger_llm_ocr_integration.md — Swagger-Integration (LLM-OCR)
- processors_pdf_imageocr.md — PDF/ImageOCR Notizen
- pdf_processor_ocr_refactoring.md — PDF/OCR Refactoring
- transformer_mongodb_caching.md — Transformer/MongoDB Caching und Typisierung
- metaprocessor-*.md — Metaprocessor Konzepte/Integration/Typisierung
- mongodb_caching_implementation.md — MongoDB Caching Plan
- caching_implementation_plan.md — Caching Konzept
- metadata-concept.md — Metadata Konzept
- processor/processors related docs — mehrere (YouTube/Video/Track/Story etc.)

## Wichtige Unterordner

- historie/ — Arbeitsprotokolle, lange Schrittfolgen, implementierte Änderungen (nicht als Referenz nutzen)
- screens/ — UI-Screenshots
- powerpoint/ — Präsentationsfolien

## Beobachtungen (kurz)

- Zahlreiche Seiten referenzieren alte Pfade im Format `/api/v1/...`. Der aktuelle Code registriert Namespaces unter `/api/...` (ohne `v1`). Diese Seiten sind voraussichtlich „outdated“ und werden im Drift-Audit markiert.
- Mehrere Referenzen zu PDF/ImageOCR sind aktuell und stimmen mit den Namespaces `pdf` und `imageocr` überein.
- Transformer hat mehrere Endpunkte (text, template, html-table, text/file, metadata), von denen nur ein Teil prominent dokumentiert ist (template). Ergänzungsbedarf.

## Nächste Schritte

- Seiten systematisch in Guide/Explanations/Processors/Reference/Ops gliedern.
- Pro Seite Frontmatter `status: confirmed|outdated|draft` und `last_verified: YYYY-MM-DD` ergänzen.


