"""
@fileoverview Booklet Render - Fills the Jinja2 template and writes the PDF with WeasyPrint

@description
Stage "pdf" of the booklet job. Takes the validated request and the image
reports of stage "images", builds one HTML document with one <section> per
page, pads the page count to a multiple of four with blank pages (inserted
before the back matter), renders it with WeasyPrint and finishes the PDF with
PyMuPDF: metadata plus a check report with page size, trim box, embedded fonts
and the effective ppi of every image.

WeasyPrint is imported lazily inside render(), so the module (and the API)
loads even where Pango is missing; the job then fails with a clear message.

@module processors.booklet.render

@exports
- BookletRenderer: Class - template rendering and PDF finishing
- pad_to_multiple_of_four(): List - inserts blank pages before the back matter
- TEMPLATES_ROOT: Path - templates/booklet in the repository

@usedIn
- src.processors.booklet_processor: BookletProcessor.render_pdf

@dependencies
- External: jinja2, markdown, segno, weasyprint (lazy), PyMuPDF (fitz)
- Internal: src.core.models.booklet - BookletRequest, BookletResult
- Internal: src.processors.booklet.tokens - THEMES, resolve_theme, hex_to_rgb
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
import markdown as markdown_lib
import segno
from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from src.core.exceptions import ProcessingError
from src.core.models.booklet import DEFAULT_TEMPLATE, BookletPage, BookletRequest, BookletResult
from src.processors.booklet.tokens import THEMES, hex_to_rgb, resolve_theme

TEMPLATES_ROOT: Path = Path(__file__).resolve().parents[3] / "templates" / "booklet"
PDF_FILENAME = "heft.pdf"
RAW_PDF_FILENAME = "heft-weasyprint.pdf"
TEXT_MAX_CHARS = 400
MM_PER_PT = 25.4 / 72.0

# Nachspann: alles nach der letzten Seite mit diesen Typen
CONTENT_TYPES = ("cover", "divider", "project")


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha:g})"


def _markdown(text: Optional[str]) -> Optional[Markup]:
    if not text or not text.strip():
        return None
    html = markdown_lib.markdown(text, output_format="html")
    return Markup(html)


def _qr_svg(url: Optional[str]) -> Optional[Markup]:
    if not url:
        return None
    qr = segno.make(url, error="m")
    svg = qr.svg_inline(scale=1, border=0, dark="#1c2d3a", omitsize=True)
    return Markup(svg)


def pad_to_multiple_of_four(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Füllt mit Leerseiten auf ein Vielfaches von 4 auf.

    Die Leerseiten kommen vor den Nachspann (Textseiten, Rückseite nach dem letzten
    Projekt), damit Impressum und Rückseite hinten bleiben.
    """
    missing = (-len(pages)) % 4
    if missing == 0:
        return list(pages)
    last_content = -1
    for index, page in enumerate(pages):
        if page["type"] in CONTENT_TYPES:
            last_content = index
    # Ohne Inhaltsseiten gibt es keinen Nachspann: hinten anhängen
    insert_at = last_content + 1 if last_content >= 0 else len(pages)
    blanks = [
        {
            "type": "blank",
            "id": f"blank-{n + 1}",
            "theme": THEMES["marke"],
            "partial": "blank.html",
            "css_class": "auto-blank",
        }
        for n in range(missing)
    ]
    return list(pages[:insert_at]) + blanks + list(pages[insert_at:])


class BookletRenderer:
    """Rendert ein Heft aus Request und Bildberichten zu PDF."""

    def __init__(self, template: str = DEFAULT_TEMPLATE, templates_root: Optional[Path] = None) -> None:
        root = templates_root or TEMPLATES_ROOT
        self.template_name = template
        self.template_dir = root / template
        if not (self.template_dir / "base.html").is_file():
            raise ProcessingError(f"Booklet-Template nicht gefunden: {template} (erwartet {self.template_dir / 'base.html'})")
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["rgba"] = _rgba

    # ------------------------------------------------------------------ Seitenkontexte
    def _partial_for(self, page: BookletPage) -> str:
        if page.type == "text":
            candidate = f"text/{page.template or 'default'}.html"
            if (self.template_dir / candidate).is_file():
                return candidate
            return "text/default.html"
        return f"{page.type}.html"

    def build_pages(self, request: BookletRequest, images: BookletResult) -> List[Dict[str, Any]]:
        """Seitenkontexte für das Template, inklusive Auffüllen auf ein Vielfaches von 4."""
        files_by_page = {report.page_id: report.file for report in images.images if report.file}
        contexts: List[Dict[str, Any]] = []
        for page in request.pages:
            theme = resolve_theme(page.theme)
            text = page.text or None
            css_class = f"text-{page.template or 'default'}" if page.type == "text" else ""
            image = files_by_page.get(page.id)
            contexts.append({
                "type": page.type,
                "id": page.id,
                "theme": theme,
                "partial": self._partial_for(page),
                "css_class": css_class,
                "title": page.title,
                "subtitle": page.subtitle,
                "heading": page.heading,
                "text": text,
                "text_too_long": bool(text and len(text) > TEXT_MAX_CHARS),
                "body_html": _markdown(page.markdown),
                "image": f"images/{image}" if image else None,
                "qr_svg": _qr_svg(page.qr_url),
                "organization": (page.organization.name if page.organization and page.organization.name else None),
            })
        return pad_to_multiple_of_four(contexts)

    def render_html(self, request: BookletRequest, images: BookletResult) -> str:
        template = self.env.get_template("base.html")
        return template.render(
            title=request.title,
            pages=self.build_pages(request, images),
            themes=THEMES,
        )

    # ------------------------------------------------------------------ PDF
    def render(self, request: BookletRequest, images: BookletResult, work_dir: Path) -> Dict[str, Any]:
        """
        Schreibt heft.pdf in work_dir und liefert den Prüfbericht.

        Bilder werden relativ zu work_dir aufgelöst (images/<id>.jpg), Schriften relativ
        zum Template-Ordner (print.css).
        """
        try:
            from weasyprint import CSS, HTML  # type: ignore
        except Exception as e:  # ImportError oder OSError bei fehlendem Pango
            raise ProcessingError(
                "PDF-Renderer nicht verfügbar: WeasyPrint konnte nicht geladen werden "
                f"(Pango/HarfBuzz installiert?): {e}"
            ) from e

        html = self.render_html(request, images)
        (work_dir / "heft.html").write_text(html, encoding="utf-8")

        stylesheet = CSS(filename=str(self.template_dir / "print.css"))
        document = HTML(string=html, base_url=str(work_dir))
        raw_path = work_dir / RAW_PDF_FILENAME
        document.write_pdf(str(raw_path), stylesheets=[stylesheet])

        report = self._finalize_pdf(raw_path, work_dir / PDF_FILENAME, request.title)
        try:
            raw_path.unlink()
        except OSError:
            pass
        return report

    @staticmethod
    def _finalize_pdf(raw_path: Path, out_path: Path, title: Optional[str]) -> Dict[str, Any]:
        """Metadaten setzen, Maße, Schriften und Bild-ppi je Seite prüfen."""
        doc = fitz.open(str(raw_path))
        doc.set_metadata({
            "title": title or "Projektheft",
            "author": "b*coop",
            "creator": "Common Secretary Services, booklet",
            "producer": f"WeasyPrint + PyMuPDF {fitz.VersionBind}",
        })

        pages_report: List[Dict[str, Any]] = []
        fonts: set[str] = set()
        min_ppi: Optional[float] = None
        for page in doc:
            media = page.mediabox
            trim = page.trimbox
            for font in page.get_fonts(full=True):
                fonts.add(str(font[3]))
            page_images: List[Dict[str, Any]] = []
            for image in page.get_images(full=True):
                xref = image[0]
                try:
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                px_w = int(info.get("width", 0))
                px_h = int(info.get("height", 0))
                for rect in page.get_image_rects(xref):
                    if rect.width <= 0 or rect.height <= 0:
                        continue
                    ppi = min(px_w / (rect.width / 72.0), px_h / (rect.height / 72.0))
                    min_ppi = ppi if min_ppi is None else min(min_ppi, ppi)
                    page_images.append({
                        "pixels": {"width": px_w, "height": px_h},
                        "box_mm": {"width": round(rect.width * MM_PER_PT, 1), "height": round(rect.height * MM_PER_PT, 1)},
                        "ppi": int(round(ppi)),
                    })
            pages_report.append({
                "page": page.number + 1,
                "media_mm": {"width": round(media.width * MM_PER_PT, 1), "height": round(media.height * MM_PER_PT, 1)},
                "trim_mm": {"width": round(trim.width * MM_PER_PT, 1), "height": round(trim.height * MM_PER_PT, 1)},
                "images": page_images,
            })

        page_count = doc.page_count
        doc.save(str(out_path), garbage=3, deflate=True)
        doc.close()

        # Ein Subset-Präfix wie "ABCDEF+Jost-Bold" zeigt, dass die Schrift eingebettet ist
        embedded = sorted(f for f in fonts if "+" in f)
        not_embedded = sorted(f for f in fonts if "+" not in f)

        return {
            "file": out_path.name,
            "page_count": page_count,
            "page_count_ok": page_count % 4 == 0,
            "media_mm": pages_report[0]["media_mm"] if pages_report else None,
            "trim_mm": pages_report[0]["trim_mm"] if pages_report else None,
            "fonts_embedded": embedded,
            "fonts_not_embedded": not_embedded,
            "min_image_ppi": int(round(min_ppi)) if min_ppi is not None else None,
            "pages": pages_report,
        }


def deep_copy_result(result: BookletResult) -> BookletResult:
    """Kopie, damit das Rendern die Bildstufe nicht verändert."""
    return copy.deepcopy(result)


__all__ = ["BookletRenderer", "pad_to_multiple_of_four", "TEMPLATES_ROOT", "PDF_FILENAME", "TEXT_MAX_CHARS"]
