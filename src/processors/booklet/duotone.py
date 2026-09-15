"""
@fileoverview Booklet Duotone - Tones a photo in the colours of its theme

@description
Reproduces the designer's image look: greyscale, slight contrast boost, then a
per-channel linear ramp from the theme's shadow colour (black) to its light
colour (white). Measured endpoints per theme live in tokens.py. The Figma file
builds the same look with SCREEN and MULTIPLY fills; here it is one lookup
table per channel, which is exact and fast.

@module processors.booklet.duotone

@exports
- apply_duotone(): PIL.Image.Image - RGB image toned between shadow and light

@usedIn
- src.processors.booklet_processor

@dependencies
- External: Pillow - ImageOps, ImageEnhance
- Internal: src.processors.booklet.tokens - Theme, CONTRAST, hex_to_rgb
"""
from __future__ import annotations

from typing import List, Optional, Tuple, Union

from PIL import Image, ImageEnhance, ImageOps

from src.processors.booklet.tokens import CONTRAST, Theme, hex_to_rgb


ColorLike = Union[str, Tuple[int, int, int]]


def _rgb(value: ColorLike) -> Tuple[int, int, int]:
    if isinstance(value, str):
        return hex_to_rgb(value)
    return value


def _ramp(shadow: int, light: int) -> List[int]:
    """Lookup-Tabelle 0..255 -> shadow..light, linear."""
    return [int(round(shadow + (light - shadow) * i / 255.0)) for i in range(256)]


def apply_duotone(
    image: Image.Image,
    shadow: ColorLike,
    light: ColorLike,
    contrast: float = CONTRAST,
) -> Image.Image:
    """
    Graustufe, Kontrast, dann je Kanal linear von shadow (Schwarz) nach light (Weiß).

    Args:
        image: Quellbild, beliebiger Modus
        shadow: Farbe für das dunkelste Pixel, Hex oder (r, g, b)
        light: Farbe für das hellste Pixel
        contrast: Kontrastfaktor vor dem Einfärben, 1.0 = unverändert
    """
    grey = ImageOps.grayscale(image)
    if contrast and abs(contrast - 1.0) > 1e-6:
        grey = ImageEnhance.Contrast(grey).enhance(contrast)

    s = _rgb(shadow)
    l = _rgb(light)
    channels = [grey.point(_ramp(s[i], l[i])) for i in range(3)]
    return Image.merge("RGB", channels)


def apply_theme_duotone(image: Image.Image, theme: Theme, contrast: Optional[float] = None) -> Image.Image:
    """Bequemer Aufruf mit den Werten eines Themas."""
    return apply_duotone(image, theme.shadow, theme.light, CONTRAST if contrast is None else contrast)


__all__ = ["apply_duotone", "apply_theme_duotone"]
