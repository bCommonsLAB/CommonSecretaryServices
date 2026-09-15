"""
@fileoverview Booklet Images - Loading and cropping photos for the booklet photo field

@description
Loads a photo from an http(s) URL (e.g. an Azure SAS URL) or a local path,
applies the EXIF orientation and crops it to the 2.17:1 photo field around a
focus point. The crop is never upscaled: if the source is too small, the
output stays small and the effective dpi drops, so the caller can decide to
add a watermark.

@module processors.booklet.images

@exports
- load_image(): PIL.Image.Image - RGB image, EXIF-rotated
- CropResult: Dataclass - cropped image, crop box, effective dpi, source size
- crop_to_frame(): CropResult - crop around the focus point, downscale to PHOTO_PX

@usedIn
- src.processors.booklet_processor

@dependencies
- External: Pillow - image handling
- External: requests - HTTP download
- Internal: src.processors.booklet.tokens - geometry
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Dict, Tuple

import requests  # type: ignore
from PIL import Image, ImageOps

from src.core.exceptions import ProcessingError
from src.processors.booklet.tokens import MM_PER_INCH, PHOTO_ASPECT, PHOTO_MM, PHOTO_PX


DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_DOWNLOAD_BYTES = 60 * 1024 * 1024


def load_image(source: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Image.Image:
    """Lädt ein Bild von einer URL oder einem Pfad, dreht nach EXIF, liefert RGB."""
    if not source or not source.strip():
        raise ProcessingError("Bildquelle ist leer")

    if source.startswith("http://") or source.startswith("https://"):
        try:
            response = requests.get(source, timeout=timeout, stream=True)
        except requests.RequestException as e:
            raise ProcessingError(f"Bild konnte nicht geladen werden: {e}") from e
        if response.status_code != 200:
            raise ProcessingError(f"Bild konnte nicht geladen werden: HTTP {response.status_code}")
        content = response.content
        if len(content) > MAX_DOWNLOAD_BYTES:
            raise ProcessingError("Bild ist größer als 60 MB")
        raw = BytesIO(content)
    else:
        path = Path(source)
        if not path.is_file():
            raise ProcessingError(f"Bilddatei nicht gefunden: {source}")
        raw = BytesIO(path.read_bytes())

    try:
        image = Image.open(raw)
        image.load()
    except Exception as e:  # Pillow wirft verschiedene Fehlertypen
        raise ProcessingError(f"Bild konnte nicht gelesen werden: {e}") from e

    rotated = ImageOps.exif_transpose(image) or image
    return rotated.convert("RGB")


@dataclass
class CropResult:
    image: Image.Image
    crop: Dict[str, int]          # x, y, width, height im Quellbild
    dpi: float                    # effektive Auflösung im Fotofeld, aus dem Ausschnitt gerechnet
    source_size: Tuple[int, int]


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(value, high))


def crop_to_frame(
    image: Image.Image,
    focus_x: float = 50.0,
    focus_y: float = 50.0,
    frame_px: Tuple[int, int] = PHOTO_PX,
    frame_mm: Tuple[int, int] = PHOTO_MM,
) -> CropResult:
    """
    Schneidet auf das Seitenverhältnis des Fotofelds zu, Fenster um den Fokuspunkt.

    Ist das Bild schmaler als das Feld (4:3, 16:9), wird die volle Breite genutzt und
    das Höhenfenster nach focus_y gelegt. Ist es breiter, wird die volle Höhe genutzt
    und das Breitenfenster nach focus_x gelegt. Danach nur verkleinern, nie vergrößern.
    """
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ProcessingError("Bild hat keine Fläche")

    frame_aspect = frame_mm[0] / frame_mm[1]
    if width / height <= frame_aspect:
        crop_w = width
        crop_h = max(1, int(round(width / frame_aspect)))
        x0 = 0
        y0 = _clamp(int(round(height * (focus_y / 100.0) - crop_h / 2)), 0, height - crop_h)
    else:
        crop_h = height
        crop_w = max(1, int(round(height * frame_aspect)))
        y0 = 0
        x0 = _clamp(int(round(width * (focus_x / 100.0) - crop_w / 2)), 0, width - crop_w)

    cropped = image.crop((x0, y0, x0 + crop_w, y0 + crop_h))

    dpi_x = crop_w / (frame_mm[0] / MM_PER_INCH)
    dpi_y = crop_h / (frame_mm[1] / MM_PER_INCH)
    dpi = min(dpi_x, dpi_y)

    if crop_w > frame_px[0] or crop_h > frame_px[1]:
        cropped = cropped.resize(frame_px, Image.Resampling.LANCZOS)

    return CropResult(
        image=cropped,
        crop={"x": x0, "y": y0, "width": crop_w, "height": crop_h},
        dpi=dpi,
        source_size=(width, height),
    )


__all__ = ["load_image", "crop_to_frame", "CropResult", "PHOTO_ASPECT"]
