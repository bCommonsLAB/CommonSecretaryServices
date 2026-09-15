"""
@fileoverview Booklet Tokens - Theme colours and page geometry of the b*coop Projektheft

@description
Single source for the values the booklet template and the image pipeline share.
Dark theme colours and text colours come from the Figma file `bcoop-buechlein`
(variable collection `bcoop`). Bar colours and duotone endpoints were measured
from the designer's layout `bCoop-Heft_120x120_v3.pdf` on 2026-09-15; see the
concept note "2026-09-14 Korrespondenz und Plan.md" in the project archive.

Geometry: page 120 x 120 mm, bleed 3 mm, photo 120 x 55 mm running into the
bleed on top, left and right, i.e. 126 x 58 mm in the print file. At 300 dpi
that is 1488 x 685 px.

@module processors.booklet.tokens

@exports
- Theme: Dataclass - one theme with label, dark, bar, duotone shadow and light
- THEMES: Dict[str, Theme] - all themes by key
- resolve_theme(): Theme - theme by key, label or bwiki enum value, default `marke`
- hex_to_rgb(): Tuple[int, int, int]
- PAGE_MM, BLEED_MM, PHOTO_MM, PHOTO_PX, DPI_READY, DPI_BORDERLINE, CONTRAST, JPEG_QUALITY

@usedIn
- src.processors.booklet.duotone
- src.processors.booklet.watermark
- src.processors.booklet.images
- src.api.routes.booklet_routes: GET /api/booklet/themes
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------- Geometrie
PAGE_MM: Tuple[int, int] = (120, 120)
BLEED_MM: int = 3
PHOTO_TRIM_MM: Tuple[int, int] = (120, 55)
PHOTO_MM: Tuple[int, int] = (PHOTO_TRIM_MM[0] + 2 * BLEED_MM, PHOTO_TRIM_MM[1] + BLEED_MM)  # 126 x 58
MM_PER_INCH = 25.4
DPI_READY = 300
DPI_BORDERLINE = 220
PHOTO_PX: Tuple[int, int] = (
    int(round(PHOTO_MM[0] / MM_PER_INCH * DPI_READY)),  # 1488
    int(round(PHOTO_MM[1] / MM_PER_INCH * DPI_READY)),  # 685
)
PHOTO_ASPECT: float = PHOTO_MM[0] / PHOTO_MM[1]  # 2.172

# Umschlag: Foto 78 mm hoch plus 3 mm Beschnitt oben, volle Breite mit Beschnitt
COVER_PHOTO_TRIM_MM: Tuple[int, int] = (120, 78)
COVER_PHOTO_MM: Tuple[int, int] = (COVER_PHOTO_TRIM_MM[0] + 2 * BLEED_MM, COVER_PHOTO_TRIM_MM[1] + BLEED_MM)  # 126 x 81
COVER_PHOTO_PX: Tuple[int, int] = (
    int(round(COVER_PHOTO_MM[0] / MM_PER_INCH * DPI_READY)),  # 1488
    int(round(COVER_PHOTO_MM[1] / MM_PER_INCH * DPI_READY)),  # 957
)


def photo_frame_for(page_type: str) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """(Rahmen in mm, Rahmen in px bei 300 dpi) je Seitentyp. Umschlag ist höher als die Projektseite."""
    if page_type == "cover":
        return COVER_PHOTO_MM, COVER_PHOTO_PX
    return PHOTO_MM, PHOTO_PX

# ---------------------------------------------------------------- Bildlook
CONTRAST = 1.10          # Kontrast +10 vor dem Duoton
JPEG_QUALITY = 92        # Druckvariante

# ---------------------------------------------------------------- Farben
TEXT_DARK = "#1c2d3a"
TEXT = "#3a4a55"
PAPER = "#ffffff"


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    dark: str      # dunkle Themenfarbe (Akzentlinie, Kategorie-Text)
    bar: str       # Pastellbalken
    shadow: str    # Duoton: dunkelstes Bildpixel
    light: str     # Duoton: hellstes Bildpixel

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


THEMES: Dict[str, Theme] = {
    "arbeiten": Theme("arbeiten", "ARBEITEN", "#673161", "#b494b2", "#262026", "#e8e1e7"),
    "natur": Theme("natur", "NATUR", "#216826", "#adb151", "#2b2b18", "#e0e0cd"),
    # Balkenton LERNEN fehlt in Irmis Liste; #9ec5bd ist aus dem Duoton zurückgerechnet und noch zu bestätigen.
    "lernen": Theme("lernen", "LERNEN", "#118474", "#9ec5bd", "#222927", "#e5ecea"),
    "leben": Theme("leben", "LEBEN", "#a33104", "#cfa089", "#312723", "#ebe2de"),
    "zusammenhalt": Theme("zusammenhalt", "ZUSAMMENHALT", "#995300", "#d4b989", "#2f291e", "#f1e9d9"),
    # Markenfarben für Umschlag, Einleitung und Projekte ohne Thema
    "marke": Theme("marke", "B*COOP", "#93b6cb", "#f3a3b0", "#20282d", "#dce8ee"),
}

DEFAULT_THEME_KEY = "marke"

# Schreibweisen, die Clients liefern: bwiki-Enum ("Leben"), Versalien ("LEBEN"), Schlüssel ("leben")
_ALIASES: Dict[str, str] = {
    "bcoop": "marke",
    "b*coop": "marke",
    "brand": "marke",
    "": "marke",
}


def resolve_theme(value: Optional[str]) -> Theme:
    """Liefert das Thema zu einem Schlüssel, Label oder bwiki-Wert. Unbekannt oder leer: Marke."""
    key = (value or "").strip().lower()
    key = _ALIASES.get(key, key)
    return THEMES.get(key, THEMES[DEFAULT_THEME_KEY])


def hex_to_rgb(value: str) -> Tuple[int, int, int]:
    """'#rrggbb' oder 'rrggbb' zu (r, g, b)."""
    v = value.strip().lstrip("#")
    if len(v) != 6:
        raise ValueError(f"Ungültige Hex-Farbe: {value}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def readiness(dpi: float) -> str:
    """Bewertet die effektive Auflösung im Fotofeld."""
    if dpi >= DPI_READY:
        return "ready"
    if dpi >= DPI_BORDERLINE:
        return "borderline"
    return "not-ready"
