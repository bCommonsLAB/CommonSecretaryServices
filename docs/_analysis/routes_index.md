# Routes-Index (aus Code extrahiert)

Quelle: Flask-RESTX Namespaces in src/api/routes/** und Registrierung in src/api/routes/__init__.py

Basis-Pfad: /api

## Namespaces

- audio → /api/audio
- video → /api/video
- session → /api/session
- common → /api/common
- transformer → /api/transformer
- event-job → /api/event-job
- tracks → /api/tracks
- events → /api/events
- pdf → /api/pdf
- imageocr → /api/imageocr
- story → /api/story

## Endpunkte (Ausschnitt)

- pdf
  - POST /api/pdf/process
  - POST /api/pdf/process-url
  - GET /api/pdf/text-content/<path:file_path>
- imageocr
  - POST /api/imageocr/process
  - POST /api/imageocr/process-url
- common
  - GET /api/common/
  - POST /api/common/notion
  - GET /api/common/samples
  - GET /api/common/samples/<string:filename>
  - Zusätzlich auch direkt unter Root registriert: /api/samples, /api/samples/<filename>
- transformer
  - POST /api/transformer/text
  - POST /api/transformer/template
  - POST /api/transformer/html-table
  - POST /api/transformer/text/file
  - POST /api/transformer/metadata
- session
  - POST /api/session/process
  - POST /api/session/process-async
  - GET  /api/session/cached
- event-job
  - POST /api/event-job/jobs
  - GET  /api/event-job/jobs
  - GET  /api/event-job/jobs/<string:job_id>
  - DELETE /api/event-job/jobs/<string:job_id>
  - POST /api/event-job/batches
  - GET  /api/event-job/batches
  - GET  /api/event-job/batches/<string:batch_id>
  - DELETE /api/event-job/batches/<string:batch_id>
  - GET  /api/event-job/files/<path:file_path>
  - POST /api/event-job/<string:job_id>/restart
  - POST /api/event-job/batches/<string:batch_id>/archive
  - POST /api/event-job/batches/<string:batch_id>/toggle-active
  - POST /api/event-job/jobs/<string:job_id>/download-archive
- tracks
  - POST /api/tracks/<string:track_name>/summary
  - GET  /api/tracks/available
  - POST /api/tracks/<string:track_name>/summarize_all
- story
  - POST /api/story/generate
  - GET  /api/story/topics
  - GET  /api/story/target-groups
- events
  - POST /api/events/<string:event_name>/summary

Hinweis: HTTP-Methoden wurden aus den Klassendefinitionen übernommen (def get/post/...).

## Swagger-UI und OpenAPI

- Swagger-UI: /api/doc
- OpenAPI-JSON (RESTX): üblicherweise /api/swagger.json

Diese können in die Doku eingebunden werden, um die Referenz in docs/reference/api/ automatisch aktuell zu halten.
