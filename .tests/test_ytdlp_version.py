"""
Prueft, dass yt-dlp neu genug ist, um aktuelle YouTube-Player-Antworten
zu parsen.

Hintergrund: Mit 2024.3.10 scheitert die Extraktion an
"Failed to extract any player response" bzw. HTTP 400 auf den
alten iOS-/Android-Clients. Die Untergrenze entspricht dem Pin
in requirements.txt.

Ausfuehren (aus dem Projektroot, in der venv):
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_ytdlp_version.py -q
"""

from typing import Tuple

import yt_dlp  # type: ignore


def _parse_ytdlp_version(version: str) -> Tuple[int, ...]:
    """Wandelt eine yt-dlp-Datumsversion (z. B. 2026.7.4) in ein Tupel.

    Nur numerische Segmente werden beruecksichtigt, damit Suffixe wie
    .dev0 den Vergleich nicht brechen.
    """
    parts: list[int] = []
    for segment in version.split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        if digits:
            parts.append(int(digits))
    return tuple(parts)


def _installed_ytdlp_version() -> str:
    """Liest die installierte yt-dlp-Version ohne Stub-Abhaengigkeit.

    yt_dlp hat keine vollstaendigen Typstubs. getattr vermeidet
    attr-defined-Fehler, der isinstance-Check haelt den Rueckgabetyp fest.
    """
    version_module = getattr(yt_dlp, "version", None)
    raw = getattr(version_module, "__version__", None)
    if not isinstance(raw, str) or not raw:
        raise AssertionError("yt_dlp.version.__version__ fehlt oder ist kein String")
    return raw


def test_ytdlp_version_meets_extractor_floor() -> None:
    """Installierte yt-dlp-Version muss mindestens 2026.7.4 sein."""
    installed: str = _installed_ytdlp_version()
    assert _parse_ytdlp_version(installed) >= (2026, 7, 4), (
        f"yt-dlp {installed} ist zu alt fuer aktuelle YouTube-Player-APIs. "
        "Bitte auf >= 2026.7.4 aktualisieren."
    )


def test_parse_ytdlp_version_handles_dev_suffix() -> None:
    """Datumsversionen mit Dev-Suffix muessen vergleichbar bleiben."""
    assert _parse_ytdlp_version("2026.7.4.dev0") == (2026, 7, 4, 0)
    assert _parse_ytdlp_version("2024.3.10") < (2026, 7, 4)
