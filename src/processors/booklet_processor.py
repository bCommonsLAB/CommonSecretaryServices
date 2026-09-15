"""
@fileoverview Booklet Processor - Prepares the images of the b*coop Projektheft

@description
Stage "images" of the booklet job: for every page that carries a photo (cover,
project) the processor loads the image, crops it to the 126 x 58 mm photo field
around the focus point, tones it in the theme's duotone, marks it when the
effective resolution is below 220 dpi, and writes a JPEG (quality 92) into the
job's work directory. Pages without an image get a placeholder plate.

The processor never fails the whole job because of one image: a page with a
missing or unreadable image is reported with status `missing` or `error` and
gets a placeholder, so the booklet can still be rendered and proofed.

Stage "pdf": render_pdf() fills the Jinja2 template of the requested template
set with the prepared images, renders it with WeasyPrint (see
src.processors.booklet.render) and stores heft.pdf plus a check report.
process() runs both stages.

@module processors.booklet_processor

@exports
- BookletProcessor: Class - image preparation for booklet jobs

@usedIn
- src.core.processing.handlers.booklet_handler: Runs the processor for a job

@dependencies
- External: Pillow - via src.processors.booklet.*
- Internal: src.processors.base_processor - BaseProcessor
- Internal: src.core.models.booklet - BookletRequest, BookletResult, BookletImageReport
- Internal: src.processors.booklet.tokens, images, duotone, watermark
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, ClassVar, Optional

from src.core.exceptions import ProcessingError
from src.core.models.base import ProcessInfo
from src.core.models.booklet import (
    BookletImageReport,
    BookletPage,
    BookletRequest,
    BookletResult,
)
from src.core.resource_tracking import ResourceCalculator
from src.processors.base_processor import BaseProcessor
from src.processors.booklet.duotone import apply_theme_duotone
from src.processors.booklet.images import crop_to_frame, load_image
from src.processors.booklet.tokens import DPI_BORDERLINE, JPEG_QUALITY, PHOTO_PX, Theme, readiness, resolve_theme
from src.processors.booklet.watermark import add_too_small_band, placeholder_image
from src.processors.booklet.render import PDF_FILENAME, BookletRenderer


ProgressCallback = Callable[[int, str], None]

IMAGES_SUBDIR = "images"
REPORT_FILENAME = "report.json"


class BookletProcessor(BaseProcessor[BookletResult]):
    """
    Bildaufbereitung für das Projektheft.

    Attributes:
        work_root: Optionales Wurzelverzeichnis für Arbeitsordner. Standard ist das
            Temp-Verzeichnis des Prozessors (cache/booklet/temp). Tests setzen es um.
    """

    work_root: ClassVar[Optional[Path]] = None

    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        process_id: Optional[str] = None,
        parent_process_info: Optional[ProcessInfo] = None,
    ) -> None:
        super().__init__(
            resource_calculator=resource_calculator,
            process_id=process_id,
            parent_process_info=parent_process_info,
        )

    # ------------------------------------------------------------------ Pfade
    def work_dir_for(self, job_id: Optional[str] = None) -> Path:
        """Arbeitsordner eines Jobs, wird angelegt."""
        root = self.work_root if self.work_root is not None else self.temp_dir
        path = Path(root) / (job_id or self.process_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    # ------------------------------------------------------------------ Stufe images
    def prepare_images(
        self,
        request: BookletRequest,
        work_dir: Optional[Path] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> BookletResult:
        """
        Bereitet die Fotos aller Seiten mit Bildplatz auf und schreibt report.json.

        Args:
            request: Validierte Job-Parameter
            work_dir: Arbeitsordner, sonst work_dir_for(process_id)
            progress: Rückruf (prozent, meldung) für Statusmeldungen
        """
        started = time.time()
        target_dir = work_dir or self.work_dir_for()
        images_dir = target_dir / IMAGES_SUBDIR
        images_dir.mkdir(parents=True, exist_ok=True)

        image_pages = [p for p in request.pages if p.has_image_slot]
        total = max(1, len(image_pages))
        reports: list[BookletImageReport] = []
        assets: list[str] = []

        self.logger.info(
            "Booklet-Bildaufbereitung gestartet",
            pages=len(request.pages),
            image_pages=len(image_pages),
            work_dir=str(target_dir),
        )

        for index, page in enumerate(image_pages):
            report = self._prepare_page_image(page, images_dir)
            reports.append(report)
            if report.file:
                assets.append(f"{IMAGES_SUBDIR}/{report.file}")
            if progress:
                percent = 10 + int(80 * (index + 1) / total)
                progress(percent, f"Bild {index + 1} von {total}: {page.id} ({report.status})")

        result = BookletResult(
            stage="images",
            work_dir=str(target_dir),
            template=request.template,
            title=request.title,
            page_count=len(request.pages),
            images=reports,
            assets=assets,
        )

        report_path = target_dir / REPORT_FILENAME
        report_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        result.assets.append(REPORT_FILENAME)

        self.logger.info(
            "Booklet-Bildaufbereitung abgeschlossen",
            summary=result.summary,
            duration_ms=int((time.time() - started) * 1000),
        )
        return result

    # ------------------------------------------------------------------ Stufe pdf
    def render_pdf(
        self,
        request: BookletRequest,
        images: BookletResult,
        progress: Optional[ProgressCallback] = None,
    ) -> BookletResult:
        """
        Rendert heft.pdf aus dem Template und den aufbereiteten Bildern.

        Erwartet das Ergebnis von prepare_images (work_dir mit images/). Ergänzt
        stage, pdf_file, pdf (Prüfbericht) und assets im übergebenen Ergebnis.
        """
        started = time.time()
        work_dir = Path(images.work_dir)
        if progress:
            progress(92, "PDF wird gesetzt")

        renderer = BookletRenderer(template=request.template)
        report = renderer.render(request, images, work_dir)

        images.stage = "pdf"
        images.pdf_file = PDF_FILENAME
        images.pdf = report
        if PDF_FILENAME not in images.assets:
            images.assets.append(PDF_FILENAME)

        report_path = work_dir / REPORT_FILENAME
        report_path.write_text(json.dumps(images.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

        self.logger.info(
            "Booklet-PDF gesetzt",
            page_count=report.get("page_count"),
            min_image_ppi=report.get("min_image_ppi"),
            fonts_embedded=report.get("fonts_embedded"),
            duration_ms=int((time.time() - started) * 1000),
        )
        return images

    def process(
        self,
        request: BookletRequest,
        work_dir: Optional[Path] = None,
        progress: Optional[ProgressCallback] = None,
    ) -> BookletResult:
        """Beide Stufen: Bilder aufbereiten, dann PDF setzen."""
        images = self.prepare_images(request, work_dir=work_dir, progress=progress)
        return self.render_pdf(request, images, progress=progress)

    def _prepare_page_image(self, page: BookletPage, images_dir: Path) -> BookletImageReport:
        theme: Theme = resolve_theme(page.theme)
        filename = f"{page.id}.jpg"
        report = BookletImageReport(page_id=page.id, page_type=page.type, status="missing", theme=theme.key)

        if not page.image_url:
            plate = placeholder_image(theme)
            plate.save(images_dir / filename, "JPEG", quality=JPEG_QUALITY)
            report.file = filename
            report.output_width, report.output_height = plate.size
            report.warnings.append("Kein Bild angegeben, Platzhalter gesetzt")
            return report

        try:
            source = load_image(page.image_url)
        except ProcessingError as e:
            self.logger.warning("Booklet-Bild konnte nicht geladen werden", page_id=page.id, error=str(e))
            plate = placeholder_image(theme, label="BILD FEHLT")
            plate.save(images_dir / filename, "JPEG", quality=JPEG_QUALITY)
            report.status = "error"
            report.file = filename
            report.output_width, report.output_height = plate.size
            report.warnings.append(f"Bild konnte nicht geladen werden: {e}")
            return report

        cropped = crop_to_frame(source, page.focus.x, page.focus.y)
        toned = apply_theme_duotone(cropped.image, theme)

        status = readiness(cropped.dpi)
        if cropped.dpi < DPI_BORDERLINE:
            toned = add_too_small_band(toned, cropped.dpi)
            report.warnings.append(
                f"Bild zu klein: {int(round(cropped.dpi))} dpi im Fotofeld, mindestens {DPI_BORDERLINE} dpi nötig, "
                f"{PHOTO_PX[0]}×{PHOTO_PX[1]} px für 300 dpi"
            )
        elif status == "borderline":
            report.warnings.append(f"Für den Druck knapp: {int(round(cropped.dpi))} dpi im Fotofeld")

        toned.save(images_dir / filename, "JPEG", quality=JPEG_QUALITY, optimize=True)

        report.status = status
        report.dpi = int(round(cropped.dpi))
        report.source_width, report.source_height = cropped.source_size
        report.crop = cropped.crop
        report.output_width, report.output_height = toned.size
        report.file = filename
        return report


__all__ = ["BookletProcessor", "IMAGES_SUBDIR", "REPORT_FILENAME"]
