"""
@fileoverview Booklet Models - Dataclasses and JSON schema for booklet (Projektheft) jobs

@description
Models for the booklet job type. A client (e.g. the bwiki) sends a list of
pages in reading order; each page has a type and, for cover and project pages,
an image with a focus point. The Secretary prepares the images (crop, duotone,
watermark) and, in a later stage, renders the PDF.

Main classes:
- BookletPage: One page of the booklet (cover, text, divider, project, blank, back)
- BookletRequest: Validated job parameters (template, title, pages, webhook)
- BookletImageReport: Result of the image preparation for one page
- BookletResult: Result of a booklet job (stage, work dir, reports, pdf)

Features:
- JSON schema validation (jsonschema) in BookletRequest.from_dict
- Serialization to dictionary (to_dict) for job results
- Page ids are generated when missing (page-<index>)

@module core.models.booklet

@exports
- PAGE_TYPES: Tuple - Allowed page types
- BOOKLET_PARAMETERS_SCHEMA: Dict - JSON schema of the job parameters
- BookletFocus, BookletOrganization, BookletPage, BookletRequest: Dataclasses
- BookletImageReport, BookletResult: Dataclasses

@usedIn
- src.processors.booklet_processor: Uses BookletRequest and produces BookletResult
- src.core.processing.handlers.booklet_handler: Builds BookletRequest from job parameters
- src.api.routes.booklet_routes: Validates requests and documents the schema

@dependencies
- External: jsonschema - Parameter validation
- Internal: src.core.exceptions - ValidationError
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple, cast

import jsonschema

from src.core.exceptions import ValidationError


PAGE_TYPES: Tuple[str, ...] = ("cover", "text", "divider", "project", "blank", "back")

DEFAULT_TEMPLATE = "bcoop-heft-120"

BOOKLET_PARAMETERS_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "BookletParameters",
    "type": "object",
    "required": ["pages"],
    "additionalProperties": True,
    "properties": {
        "template": {"type": "string", "minLength": 1, "default": DEFAULT_TEMPLATE},
        "title": {"type": "string"},
        "pages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": True,
                "properties": {
                    "type": {"type": "string", "enum": list(PAGE_TYPES)},
                    "id": {"type": "string", "minLength": 1, "pattern": r"^[A-Za-z0-9_.\-]+$"},
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "heading": {"type": "string"},
                    "theme": {"type": "string"},
                    "text": {"type": "string"},
                    "markdown": {"type": "string"},
                    "image_url": {"type": ["string", "null"]},
                    "focus": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number", "minimum": 0, "maximum": 100},
                            "y": {"type": "number", "minimum": 0, "maximum": 100},
                        },
                    },
                    "qr_url": {"type": ["string", "null"]},
                    "organization": {
                        "type": ["object", "null"],
                        "properties": {
                            "name": {"type": ["string", "null"]},
                            "logo_url": {"type": ["string", "null"]},
                        },
                    },
                    "template": {"type": "string"},
                },
            },
        },
        "webhook": {
            "type": ["object", "null"],
            "properties": {
                "url": {"type": "string"},
                "token": {"type": "string"},
                "jobId": {"type": "string"},
            },
        },
    },
}


def validate_booklet_parameters(data: Dict[str, Any]) -> None:
    """Validiert rohe Job-Parameter gegen das Schema. Wirft ValidationError."""
    try:
        jsonschema.validate(instance=data, schema=BOOKLET_PARAMETERS_SCHEMA)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        raise ValidationError(f"Ungültige Booklet-Parameter bei '{path}': {e.message}") from e


@dataclass
class BookletFocus:
    """Fokuspunkt in Prozent, 50/50 ist die Bildmitte."""
    x: float = 50.0
    y: float = 50.0

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "BookletFocus":
        if not isinstance(data, dict):
            return cls()
        return cls(x=float(data.get("x", 50.0)), y=float(data.get("y", 50.0)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BookletOrganization:
    """Organisation, deren Marke auf der Seite erscheint."""
    name: Optional[str] = None
    logo_url: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["BookletOrganization"]:
        if not isinstance(data, dict):
            return None
        return cls(name=data.get("name"), logo_url=data.get("logo_url"))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BookletPage:
    """Eine Seite des Hefts. Welche Felder gelten, hängt vom Typ ab."""
    type: str
    id: str
    title: Optional[str] = None
    subtitle: Optional[str] = None
    heading: Optional[str] = None
    theme: Optional[str] = None
    text: Optional[str] = None
    markdown: Optional[str] = None
    image_url: Optional[str] = None
    focus: BookletFocus = field(default_factory=BookletFocus)
    qr_url: Optional[str] = None
    organization: Optional[BookletOrganization] = None
    template: Optional[str] = None

    @property
    def has_image_slot(self) -> bool:
        """Umschlag und Projektseite tragen ein Foto."""
        return self.type in ("cover", "project")

    @classmethod
    def from_dict(cls, data: Dict[str, Any], index: int) -> "BookletPage":
        page_id = data.get("id") or f"page-{index + 1:03d}"
        return cls(
            type=str(data["type"]),
            id=str(page_id),
            title=data.get("title"),
            subtitle=data.get("subtitle"),
            heading=data.get("heading"),
            theme=data.get("theme"),
            text=data.get("text"),
            markdown=data.get("markdown"),
            image_url=data.get("image_url") or None,
            focus=BookletFocus.from_dict(data.get("focus")),
            qr_url=data.get("qr_url") or None,
            organization=BookletOrganization.from_dict(data.get("organization")),
            template=data.get("template"),
        )

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "type": self.type,
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "heading": self.heading,
            "theme": self.theme,
            "text": self.text,
            "markdown": self.markdown,
            "image_url": self.image_url,
            "focus": self.focus.to_dict(),
            "qr_url": self.qr_url,
            "organization": self.organization.to_dict() if self.organization else None,
            "template": self.template,
        }
        return result


@dataclass
class BookletRequest:
    """Validierte Job-Parameter eines Booklet-Jobs."""
    pages: List[BookletPage]
    template: str = DEFAULT_TEMPLATE
    title: Optional[str] = None
    webhook: Optional[Dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BookletRequest":
        validate_booklet_parameters(data)
        raw_pages = cast(List[Dict[str, Any]], data.get("pages", []))
        pages = [BookletPage.from_dict(p, i) for i, p in enumerate(raw_pages)]
        seen: set[str] = set()
        for page in pages:
            if page.id in seen:
                raise ValidationError(f"Seiten-ID '{page.id}' ist mehrfach vergeben")
            seen.add(page.id)
        webhook_raw = data.get("webhook")
        webhook = cast(Dict[str, Any], webhook_raw) if isinstance(webhook_raw, dict) else None
        return cls(
            pages=pages,
            template=str(data.get("template") or DEFAULT_TEMPLATE),
            title=data.get("title"),
            webhook=webhook,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template": self.template,
            "title": self.title,
            "pages": [p.to_dict() for p in self.pages],
            "webhook": self.webhook,
        }


@dataclass
class BookletImageReport:
    """Ergebnis der Bildaufbereitung für eine Seite."""
    page_id: str
    page_type: str
    status: str  # ready | borderline | not-ready | missing | error
    theme: str = "marke"
    dpi: int = 0
    source_width: int = 0
    source_height: int = 0
    crop: Optional[Dict[str, int]] = None
    output_width: int = 0
    output_height: int = 0
    file: Optional[str] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BookletResult:
    """Ergebnis eines Booklet-Jobs. Stufe `images` nach der Bildaufbereitung, `pdf` nach dem Rendern."""
    stage: str
    work_dir: str
    template: str
    title: Optional[str]
    page_count: int
    images: List[BookletImageReport] = field(default_factory=list)
    pdf_file: Optional[str] = None
    assets: List[str] = field(default_factory=list)
    # Prüfbericht des PDF (Seitenzahl, Maße, Schriften, Bild-ppi), gesetzt in Stufe pdf
    pdf: Optional[Dict[str, Any]] = None

    @property
    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {"ready": 0, "borderline": 0, "not-ready": 0, "missing": 0, "error": 0}
        for report in self.images:
            counts[report.status] = counts.get(report.status, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "work_dir": self.work_dir,
            "template": self.template,
            "title": self.title,
            "page_count": self.page_count,
            "images": [r.to_dict() for r in self.images],
            "summary": self.summary,
            "pdf_file": self.pdf_file,
            "pdf": self.pdf,
            "assets": list(self.assets),
        }
