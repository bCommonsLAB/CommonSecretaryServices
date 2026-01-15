"""
@fileoverview OfficeProcessor - python-only Verarbeitung von DOCX/XLSX/PPTX zu Markdown + Assets

@description
Dieser Prozessor ist die Pipeline A aus `docs/architecture/office-endpoints.md`:
- Keine externen Binaries (pandoc/LibreOffice) – nur Python Libraries
- Extrahiert Text/Struktur nach Markdown
- Extrahiert Embedded-Images als Dateien
- Erzeugt Thumbnail-Previews (Pillow)

Der Prozessor ist bewusst schlank; Caching ist „best effort“ über einen Content-Hash.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union

from src.core.exceptions import ProcessingError
from src.core.models.office import OfficeData, OfficeMetadata, OfficeDocumentType, OfficeTextContent
from src.processors.office._common import ensure_dir, md5_file
from src.processors.office.docx_extractor import extract_docx_to_markdown
from src.processors.office.pptx_extractor import extract_pptx_to_markdown
from src.processors.office.xlsx_extractor import extract_xlsx_to_markdown


@dataclass(slots=True)
class OfficeProcessResult:
    data: OfficeData
    process_dir: str
    is_from_cache: bool
    markdown_path: str


def _doc_type_from_suffix(path: Path) -> OfficeDocumentType:
    s = path.suffix.lower().lstrip(".")
    if s in ("docx", "xlsx", "pptx"):
        return s  # type: ignore[return-value]
    raise ProcessingError(f"Nicht unterstütztes Office-Format: {path.suffix}")


def _make_thumbnail(src_path: Path, dest_path: Path, max_size_px: int = 512) -> None:
    """Erzeugt ein Thumbnail. Fehler sind nicht fatal (best effort)."""
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return
    try:
        with Image.open(src_path) as im:
            im.thumbnail((max_size_px, max_size_px))
            im.save(dest_path)
    except Exception:
        return


class OfficeProcessor:
    """Orchestrator für Office python-only Konvertierung."""

    def __init__(self, process_id: str) -> None:
        self.process_id = process_id

    async def process(
        self,
        file_path: Union[str, Path],
        *,
        include_images: bool = True,
        include_previews: bool = True,
        use_cache: bool = True,
        force_overwrite: bool = False,
        base_cache_dir: Union[str, Path] = "cache/office/temp",
    ) -> OfficeProcessResult:
        path = Path(file_path)
        if not path.exists():
            raise ProcessingError(f"Datei nicht gefunden: {path}")

        doc_type = _doc_type_from_suffix(path)

        # Cache-Key über Dateiinhalt. Das ist einfach, robust und unabhängig vom Dateinamen.
        file_hash = md5_file(path)
        cache_root = Path(base_cache_dir)
        ensure_dir(cache_root)
        cached_dir = cache_root / file_hash

        # Prozess-Verzeichnis: entweder Cache oder job-spezifisch
        process_dir = cached_dir if use_cache else (cache_root / self.process_id)
        ensure_dir(process_dir)

        output_md = process_dir / "output.md"
        images_dir = process_dir / "images"
        previews_dir = process_dir / "previews"

        if use_cache and not force_overwrite and output_md.exists():
            # Minimaler Cache-Hit: wir gehen davon aus, dass Artefakte vorhanden sind.
            metadata = OfficeMetadata(
                file_name=path.name,
                file_size=path.stat().st_size,
                format=doc_type,
                process_dir=str(process_dir),
                image_paths=[],
                preview_paths=[],
                text_contents=[],
            )
            data = OfficeData(extracted_text=output_md.read_text(encoding="utf-8"), metadata=metadata, markdown_file=str(output_md))
            return OfficeProcessResult(data=data, process_dir=str(process_dir), is_from_cache=True, markdown_path=str(output_md))

        # Neu erzeugen
        ensure_dir(images_dir)
        ensure_dir(previews_dir)

        if doc_type == "docx":
            extraction = extract_docx_to_markdown(path, images_dir)
        elif doc_type == "xlsx":
            extraction = extract_xlsx_to_markdown(path, images_dir)
        else:
            extraction = extract_pptx_to_markdown(path, images_dir)

        # Thumbnails erzeugen (best effort)
        preview_paths: List[str] = []
        if include_images and include_previews:
            for rel in extraction.image_paths:
                # rel ist "images/xyz.png"
                src = process_dir / rel
                thumb_name = Path(rel).name
                dest = previews_dir / thumb_name
                _make_thumbnail(src, dest)
                if dest.exists():
                    preview_paths.append(f"previews/{thumb_name}")

        # Markdown schreiben
        output_md.write_text(extraction.markdown, encoding="utf-8")

        # Metadaten
        text_contents: List[OfficeTextContent] = list(extraction.text_contents)
        metadata = OfficeMetadata(
            file_name=path.name,
            file_size=path.stat().st_size,
            format=doc_type,
            process_dir=str(process_dir),
            image_paths=list(extraction.image_paths) if include_images else [],
            preview_paths=preview_paths if include_images and include_previews else [],
            text_contents=text_contents,
        )
        data = OfficeData(
            extracted_text=extraction.markdown,
            metadata=metadata,
            markdown_file=str(output_md),
        )
        return OfficeProcessResult(data=data, process_dir=str(process_dir), is_from_cache=False, markdown_path=str(output_md))






