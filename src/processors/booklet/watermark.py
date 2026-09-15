"""
@fileoverview Booklet Watermark - Marks photos that are too small for print, draws placeholders

@description
Two helpers for the visible warnings on booklet pages:
- add_too_small_band(): a diagonal, semi-transparent band with "BILD ZU KLEIN · <dpi> dpi"
  across the photo. The page is still produced; the band tells the reader of the
  proof that a larger original is needed.
- placeholder_image(): a plate in the theme's bar colour with "KEIN BILD" for pages
  without a photo.

Uses Pillow's bundled default font (load_default with size, Pillow >= 10.1), so no
system fonts are needed in the container.

@module processors.booklet.watermark

@exports
- add_too_small_band(): PIL.Image.Image
- placeholder_image(): PIL.Image.Image

@usedIn
- src.processors.booklet_processor

@dependencies
- External: Pillow - ImageDraw, ImageFont
- Internal: src.processors.booklet.tokens - Theme, PHOTO_PX, hex_to_rgb
"""
from __future__ import annotations

import math
from typing import Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from src.processors.booklet.tokens import PHOTO_PX, Theme, hex_to_rgb


BAND_COLOR = (178, 34, 34, 190)     # gedecktes Rot, halbtransparent
BAND_TEXT_COLOR = (255, 255, 255, 255)
BAND_ANGLE_DEGREES = 18.0


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # sehr altes Pillow ohne size-Parameter
        return ImageFont.load_default()


def add_too_small_band(image: Image.Image, dpi: float, label: Optional[str] = None) -> Image.Image:
    """
    Legt ein diagonales Band mit „BILD ZU KLEIN · <dpi> dpi“ über das Bild.

    Das Band ist so lang wie die Bilddiagonale, damit es an beiden Rändern hinausläuft.
    """
    text = label or f"BILD ZU KLEIN · {int(round(dpi))} dpi"
    width, height = image.size
    base = image.convert("RGBA")

    band_height = max(24, int(height * 0.16))
    font = _font(max(12, int(band_height * 0.55)))
    diagonal = int(math.hypot(width, height)) + band_height

    band = Image.new("RGBA", (diagonal, band_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(band)
    draw.rectangle((0, 0, diagonal, band_height), fill=BAND_COLOR)
    text_box = draw.textbbox((0, 0), text, font=font)
    text_w = text_box[2] - text_box[0]
    text_h = text_box[3] - text_box[1]
    draw.text(
        ((diagonal - text_w) / 2 - text_box[0], (band_height - text_h) / 2 - text_box[1]),
        text,
        font=font,
        fill=BAND_TEXT_COLOR,
    )

    rotated = band.rotate(BAND_ANGLE_DEGREES, resample=Image.Resampling.BICUBIC, expand=True)
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    offset = ((width - rotated.width) // 2, (height - rotated.height) // 2)
    layer.alpha_composite(rotated, dest=(max(0, offset[0]), max(0, offset[1])), source=(
        max(0, -offset[0]), max(0, -offset[1])
    ))

    return Image.alpha_composite(base, layer).convert("RGB")


def placeholder_image(theme: Theme, size: Tuple[int, int] = PHOTO_PX, label: str = "KEIN BILD") -> Image.Image:
    """Fläche in der Balkenfarbe des Themas mit zentriertem Hinweis in der dunklen Themenfarbe."""
    image = Image.new("RGB", size, hex_to_rgb(theme.bar))
    draw = ImageDraw.Draw(image)
    font = _font(max(16, int(size[1] * 0.12)))
    box = draw.textbbox((0, 0), label, font=font)
    text_w = box[2] - box[0]
    text_h = box[3] - box[1]
    draw.text(
        ((size[0] - text_w) / 2 - box[0], (size[1] - text_h) / 2 - box[1]),
        label,
        font=font,
        fill=hex_to_rgb(theme.dark),
    )
    return image


__all__ = ["add_too_small_band", "placeholder_image"]
