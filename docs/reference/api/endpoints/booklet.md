# Booklet API Endpoints

Endpoints for the b*coop **Projektheft**: a 120 × 120 mm booklet generated from
a list of pages. Stage 1 (available) prepares the photos: crop around a focus
point, duotone in the theme colours, watermark when the photo is too small for
print. Stage 2 (planned) renders the PDF with WeasyPrint from the same job.

The work runs asynchronously in the Secretary Job Worker as job type `booklet`.
Status and results are read through the generic [Jobs API](jobs.md).

**Base URL (production)**: `https://secretaryservices.bcommonslab.org/api`
**Swagger UI**: `https://secretaryservices.bcommonslab.org/api/doc`, namespace `booklet`

All endpoints need the service API key:

```
Authorization: Bearer <SECRETARY_SERVICE_API_KEY>
```

## POST /api/booklet/jobs

Validates the page list against the booklet schema and enqueues a job.

### Request

**Content-Type**: `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template` | String | No | Template set, default `bcoop-heft-120` |
| `title` | String | No | Booklet title |
| `pages` | Array | Yes | Pages in reading order, at least one. The job never reorders |
| `webhook` | Object | No | `{url, token, jobId}`; POST callback after completion |
| `user_id` | String | No | Owner of the job for access control |

### Page

| Field | Type | Used by | Description |
|-------|------|---------|-------------|
| `type` | String | all | `cover`, `text`, `divider`, `project`, `blank`, `back` |
| `id` | String | all | Unique id, becomes the image file name. Generated as `page-001` when missing |
| `title` | String | cover, project | Title |
| `subtitle` | String | cover | Subtitle |
| `heading` | String | text, divider | Heading |
| `theme` | String | divider, project, cover | `arbeiten`, `natur`, `lernen`, `leben`, `zusammenhalt`, `marke`. bwiki values such as `Natur` are accepted; unknown or empty falls back to `marke` |
| `text` | String | project | Short text, 400 characters recommended |
| `markdown` | String | text, back | Body text, Markdown |
| `image_url` | String | cover, project | Photo, http(s) URL (e.g. Azure SAS URL) or a path readable by the service. Send the print variant when available |
| `focus` | Object | cover, project | `{x, y}` in percent, where the motif sits. Default 50/50 |
| `qr_url` | String | project, text, back | Target of the QR code |
| `organization` | Object | project | `{name, logo_url}`, brand on the bar |
| `template` | String | text | Sub-template: `intro`, `outro`, `impressum`, `default` |

### Example

```bash
curl -X POST "https://secretaryservices.bcommonslab.org/api/booklet/jobs" \
  -H "Authorization: Bearer $SECRETARY_SERVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "b*coop Projektheft 2026",
    "pages": [
      { "type": "cover", "id": "cover", "title": "b*coop Projektheft", "subtitle": "Projekte 2026",
        "image_url": "https://.../Titelbild.jpg?sv=...", "focus": { "x": 50, "y": 40 } },
      { "type": "text", "id": "vorwort", "template": "intro", "heading": "Vorwort",
        "markdown": "Wir sind eine Genossenschaft ..." },
      { "type": "project", "id": "abc123", "title": "b*garden", "theme": "natur",
        "text": "Ein Stück Garten für alle ...",
        "image_url": "https://.../1712345_print.jpg?sv=...", "focus": { "x": 50, "y": 3 },
        "qr_url": "https://wiki.bcommonslab.org/projekte?id=abc123",
        "organization": { "name": "b*coop" } },
      { "type": "back", "id": "back", "markdown": "wiki.bcommonslab.org",
        "qr_url": "https://wiki.bcommonslab.org" }
    ]
  }'
```

### Response

**Status Code**: `202 Accepted`

```json
{
  "status": "success",
  "data": {
    "job_id": "job-3f0c...",
    "status_url": "/api/jobs/job-3f0c...",
    "assets_url": "/api/booklet/jobs/job-3f0c.../assets/",
    "page_count": 4,
    "image_pages": 2
  }
}
```

**Status Code**: `400 Bad Request` with `error.code = VALIDATION_ERROR` when the
page list does not match the schema (unknown page type, duplicate id, focus out
of range).

The same job can be created through the generic endpoint:

```json
POST /api/jobs/
{ "job_type": "booklet", "parameters": { "title": "...", "pages": [ ... ] } }
```

## Reading the result

Poll `GET /api/jobs/{job_id}` until `status` is `completed` or `failed`.
`results` then contains:

| Field | Description |
|-------|-------------|
| `asset_dir` | Work directory of the job on the server |
| `assets` | File names relative to the work directory: `images/<page-id>.jpg` per image page, `report.json` |
| `structured_data.stage` | `images` after stage 1, `pdf` after stage 2 |
| `structured_data.summary` | Counts per status: `ready`, `borderline`, `not-ready`, `missing`, `error` |
| `structured_data.images[]` | Per page: `page_id`, `status`, `dpi`, `source_width/height`, `crop`, `output_width/height`, `file`, `warnings` |

### Image status

| Status | Meaning | What the file shows |
|--------|---------|---------------------|
| `ready` | ≥ 300 dpi in the 126 × 58 mm photo field | toned photo, 1488 × 685 px |
| `borderline` | 220 to 299 dpi | toned photo, smaller than 1488 px, no mark |
| `not-ready` | < 220 dpi | toned photo with the diagonal band **BILD ZU KLEIN · n dpi** |
| `missing` | no `image_url` | plate in the theme's bar colour, **KEIN BILD** |
| `error` | image could not be loaded | plate, **BILD FEHLT**, reason in `warnings` |

A too-small photo never fails the job. The band is meant to be seen on the
proof so that a larger original gets uploaded.

## GET /api/booklet/jobs/{job_id}/assets/{filename}

Downloads one produced file, e.g. `images/abc123.jpg` or `report.json`.

```bash
curl -o abc123.jpg \
  -H "Authorization: Bearer $SECRETARY_SERVICE_API_KEY" \
  "https://secretaryservices.bcommonslab.org/api/booklet/jobs/job-3f0c.../assets/images/abc123.jpg"
```

Returns `409` while the job has not produced files yet, `404` for unknown jobs
or file names. Paths outside the work directory are rejected.

## GET /api/booklet/themes

Theme colours and page geometry, the same values the image pipeline uses.
Clients can use them for previews.

```json
{
  "status": "success",
  "data": {
    "themes": {
      "natur": { "key": "natur", "label": "NATUR", "dark": "#216826", "bar": "#adb151",
                 "shadow": "#2b2b18", "light": "#e0e0cd" }
    },
    "text": { "dark": "#1c2d3a", "default": "#3a4a55" },
    "geometry": {
      "page_mm": { "width": 120, "height": 120 }, "bleed_mm": 3,
      "photo_trim_mm": { "width": 120, "height": 55 },
      "photo_mm": { "width": 126, "height": 58 },
      "photo_px_300dpi": { "width": 1488, "height": 685 },
      "dpi_ready": 300, "dpi_borderline": 220, "jpeg_quality": 92
    }
  }
}
```

## GET /api/booklet/schema

The JSON schema (Draft 7) used to validate `POST /api/booklet/jobs`.

## How the images are prepared

1. Load from `image_url`, apply EXIF orientation, convert to RGB.
2. Crop to 126 : 58 (about 2.17 : 1). Photos narrower than that (4:3, 16:9) keep
   their full width; the height window is placed at `focus.y`. Wider photos keep
   their full height; the width window is placed at `focus.x`.
3. Effective dpi = crop pixels over 126 mm (or 58 mm). The crop is downscaled to
   1488 × 685 px when larger, never upscaled.
4. Greyscale, contrast +10 %, then a per-channel linear ramp from the theme's
   `shadow` to its `light` colour (duotone).
5. Below 220 dpi the red diagonal band is composited on top.
6. Saved as JPEG, quality 92, sRGB.

## Notes for the bwiki client

- Send the print variant (`_print` suffix) of the hero image when it exists; the
  web variant of 1920 px is borderline for 4:3 photos.
- Private blobs need a SAS URL valid long enough for the job (24 h is plenty).
- Sort pages before sending; the job keeps the order.
