"""
@fileoverview Booklet API Routes - Flask-RESTX endpoints for the b*coop Projektheft

@description
Endpoints to enqueue a booklet job, read the theme tokens and download produced
files. The job itself runs in the Secretary Job Worker (job_type `booklet`);
status and results are read via the generic jobs API (GET /api/jobs/<job_id>).

Main endpoints:
- POST /api/booklet/jobs: Validate the page list and enqueue a booklet job
- GET /api/booklet/jobs/<job_id>/assets/<filename>: Download a produced file
- GET /api/booklet/themes: Theme colours and page geometry
- GET /api/booklet/schema: JSON schema of the job parameters

@module api.routes.booklet_routes

@exports
- booklet_ns: Namespace - Flask-RESTX namespace for booklet endpoints

@usedIn
- src.api.routes.__init__: Registers booklet_ns namespace under /booklet

@dependencies
- External: flask_restx - REST API framework with Swagger UI
- Internal: src.core.models.booklet - BookletRequest, BOOKLET_PARAMETERS_SCHEMA
- Internal: src.core.mongodb.secretary_repository - SecretaryJobRepository
- Internal: src.processors.booklet.tokens - THEMES and geometry
"""
# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# type: ignore
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

from flask import request, send_file
from flask_restx import Namespace, Resource, fields

from src.api.routes.secretary_job_routes import get_repo
from src.core.exceptions import ValidationError
from src.core.models.booklet import BOOKLET_PARAMETERS_SCHEMA, BookletRequest, PAGE_TYPES
from src.processors.booklet.tokens import (
    BLEED_MM,
    DPI_BORDERLINE,
    DPI_READY,
    JPEG_QUALITY,
    PAGE_MM,
    PHOTO_MM,
    PHOTO_PX,
    PHOTO_TRIM_MM,
    TEXT,
    TEXT_DARK,
    THEMES,
)
from src.utils.logger import get_logger

logger = get_logger(process_id="booklet-api")

booklet_ns = Namespace(
    "booklet",
    description="Projektheft: Bildaufbereitung und PDF-Erzeugung als asynchroner Job (job_type booklet)",
)

# ---------------------------------------------------------------- Swagger-Modelle
focus_model = booklet_ns.model("BookletFocus", {
    "x": fields.Float(description="Fokuspunkt horizontal in Prozent (0..100), Standard 50", example=50),
    "y": fields.Float(description="Fokuspunkt vertikal in Prozent (0..100), Standard 50", example=30),
})

organization_model = booklet_ns.model("BookletOrganization", {
    "name": fields.String(description="Name der Organisation, Marke rechts auf dem Balken", example="b*coop"),
    "logo_url": fields.String(description="Optionales Logo (URL)", required=False),
})

page_model = booklet_ns.model("BookletPage", {
    "type": fields.String(required=True, enum=list(PAGE_TYPES),
                          description="Seitentyp: cover, text, divider, project, blank, back"),
    "id": fields.String(description="Eindeutige Seiten-ID, Dateiname des Bildes. Fehlt sie, wird page-<n> vergeben",
                        example="abc123"),
    "title": fields.String(description="Titel (cover, project)", example="b*garden"),
    "subtitle": fields.String(description="Untertitel (cover)"),
    "heading": fields.String(description="Überschrift (text, divider)"),
    "theme": fields.String(description="Thema: arbeiten, natur, lernen, leben, zusammenhalt oder marke. "
                                       "bwiki-Werte wie 'Natur' werden erkannt", example="natur"),
    "text": fields.String(description="Kurztext der Projektseite, max. 400 Zeichen empfohlen"),
    "markdown": fields.String(description="Fließtext für text- und back-Seiten, Markdown"),
    "image_url": fields.String(description="Foto (http(s)-URL, z. B. Azure SAS-URL). Möglichst die Druckvariante"),
    "focus": fields.Nested(focus_model, description="Fokuspunkt für den Bildausschnitt"),
    "qr_url": fields.String(description="Ziel des QR-Codes, z. B. die Projektseite im bwiki"),
    "organization": fields.Nested(organization_model, description="Marke auf dem Balken"),
    "template": fields.String(description="Untertyp für text-Seiten: intro, outro, impressum, default"),
})

webhook_model = booklet_ns.model("BookletWebhook", {
    "url": fields.String(description="Callback-URL, wird nach Abschluss per POST aufgerufen"),
    "token": fields.String(description="Bearer-Token für den Callback"),
    "jobId": fields.String(description="Job-ID des Auftraggebers, wird im Callback zurückgegeben"),
})

booklet_request_model = booklet_ns.model("BookletJobRequest", {
    "template": fields.String(description="Template-Satz", default="bcoop-heft-120", example="bcoop-heft-120"),
    "title": fields.String(description="Titel des Hefts", example="b*coop Projektheft 2026"),
    "pages": fields.List(fields.Nested(page_model), required=True,
                         description="Seiten in Lesereihenfolge; der Job ordnet nicht um"),
    "webhook": fields.Nested(webhook_model, required=False),
    "user_id": fields.String(description="Optionale Benutzer-ID für die Zugriffssteuerung des Jobs", required=False),
})

error_model = booklet_ns.model("BookletError", {
    "status": fields.String(description="error"),
    "error": fields.Nested(booklet_ns.model("BookletErrorDetails", {
        "code": fields.String(),
        "message": fields.String(),
        "details": fields.Raw(),
    })),
})

job_created_model = booklet_ns.model("BookletJobCreated", {
    "status": fields.String(description="success"),
    "data": fields.Nested(booklet_ns.model("BookletJobCreatedData", {
        "job_id": fields.String(description="ID des angelegten Jobs"),
        "status_url": fields.String(description="Statusabfrage: GET /api/jobs/<job_id>"),
        "assets_url": fields.String(description="Download-Basis: GET /api/booklet/jobs/<job_id>/assets/<datei>"),
        "pdf_url": fields.String(description="Download des fertigen Hefts, sobald der Job abgeschlossen ist"),
        "page_count": fields.Integer(),
        "image_pages": fields.Integer(description="Seiten mit Bildplatz (cover, project)"),
    })),
})


def _error(code: str, message: str, status: int, details: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    return {"status": "error", "error": {"code": code, "message": message, "details": details or {}}}, status


# ---------------------------------------------------------------- Endpunkte
@booklet_ns.route("/jobs")
class BookletJobsEndpoint(Resource):
    """Legt einen Booklet-Job an."""

    @booklet_ns.expect(booklet_request_model)
    @booklet_ns.response(202, "Job angelegt", job_created_model)
    @booklet_ns.response(400, "Ungültige Parameter", error_model)
    @booklet_ns.doc(description=(
        "Validiert die Seitenliste gegen das Booklet-Schema und legt einen Job vom Typ `booklet` an. "
        "Der Worker bereitet die Fotos auf (Ausschnitt nach Fokuspunkt, Duoton je Thema, Wasserzeichen "
        "unter 220 dpi), füllt das Template und setzt heft.pdf (120 × 120 mm, 3 mm Beschnitt, sRGB, "
        "Schriften eingebettet, Seitenzahl auf ein Vielfaches von 4 aufgefüllt). "
        "Status und Ergebnis: GET /api/jobs/{job_id}. Dateien: GET /api/booklet/jobs/{job_id}/assets/{datei}."
))
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        """Booklet-Job anlegen"""
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _error("INVALID_JSON", "Request-Body muss ein JSON-Objekt sein", 400)

        user_id: Optional[str] = data.pop("user_id", None) if isinstance(data.get("user_id"), str) else None

        try:
            booklet = BookletRequest.from_dict(data)
        except ValidationError as e:
            return _error("VALIDATION_ERROR", str(e), 400)

        repo = get_repo()
        job_id = repo.create_job({"job_type": "booklet", "parameters": data}, user_id=user_id)
        logger.info("Booklet-Job angelegt", job_id=job_id, pages=len(booklet.pages))

        return {
            "status": "success",
            "data": {
                "job_id": job_id,
                "status_url": f"/api/jobs/{job_id}",
                "assets_url": f"/api/booklet/jobs/{job_id}/assets/",
                "pdf_url": f"/api/booklet/jobs/{job_id}/assets/heft.pdf",
                "page_count": len(booklet.pages),
                "image_pages": sum(1 for p in booklet.pages if p.has_image_slot),
            },
        }, 202


@booklet_ns.route("/jobs/<string:job_id>/assets/<path:filename>")
class BookletAssetEndpoint(Resource):
    """Liefert eine vom Job erzeugte Datei."""

    @booklet_ns.response(200, "Datei")
    @booklet_ns.response(404, "Job oder Datei nicht gefunden", error_model)
    @booklet_ns.response(409, "Job noch nicht fertig", error_model)
    @booklet_ns.doc(description=(
        "Lädt eine Datei aus dem Arbeitsordner des Jobs, z. B. `images/abc123.jpg` oder `report.json`. "
        "Die verfügbaren Namen stehen in `results.assets` des Jobs."
    ))
    def get(self, job_id: str, filename: str):
        """Erzeugte Datei herunterladen"""
        repo = get_repo()
        job = repo.get_job(job_id)
        if job is None:
            return _error("JOB_NOT_FOUND", "Job nicht gefunden", 404)

        results = getattr(job, "results", None)
        asset_dir = getattr(results, "asset_dir", None) if results else None
        if not asset_dir:
            return _error("NOT_READY", "Job hat noch keine Dateien erzeugt", 409)

        base = Path(asset_dir).resolve()
        target = (base / filename).resolve()
        if base not in target.parents and target != base:
            return _error("INVALID_PATH", "Dateiname außerhalb des Arbeitsordners", 404)
        if not target.is_file():
            return _error("FILE_NOT_FOUND", f"Datei nicht gefunden: {filename}", 404)

        return send_file(str(target), as_attachment=False, download_name=target.name)


@booklet_ns.route("/themes")
class BookletThemesEndpoint(Resource):
    """Themenfarben und Seitengeometrie."""

    @booklet_ns.doc(description="Farbwerte je Thema (dunkel, Balken, Duoton) und die Maße des Hefts.")
    def get(self) -> Dict[str, Any]:
        """Themen und Maße"""
        return {
            "status": "success",
            "data": {
                "themes": {key: theme.to_dict() for key, theme in THEMES.items()},
                "text": {"dark": TEXT_DARK, "default": TEXT},
                "geometry": {
                    "page_mm": {"width": PAGE_MM[0], "height": PAGE_MM[1]},
                    "bleed_mm": BLEED_MM,
                    "photo_trim_mm": {"width": PHOTO_TRIM_MM[0], "height": PHOTO_TRIM_MM[1]},
                    "photo_mm": {"width": PHOTO_MM[0], "height": PHOTO_MM[1]},
                    "photo_px_300dpi": {"width": PHOTO_PX[0], "height": PHOTO_PX[1]},
                    "dpi_ready": DPI_READY,
                    "dpi_borderline": DPI_BORDERLINE,
                    "jpeg_quality": JPEG_QUALITY,
                },
            },
        }


@booklet_ns.route("/schema")
class BookletSchemaEndpoint(Resource):
    """JSON-Schema der Job-Parameter."""

    @booklet_ns.doc(description="JSON-Schema (Draft 7) der Parameter für POST /api/booklet/jobs und POST /api/jobs/.")
    def get(self) -> Dict[str, Any]:
        """Parameter-Schema"""
        return {"status": "success", "data": BOOKLET_PARAMETERS_SCHEMA}
