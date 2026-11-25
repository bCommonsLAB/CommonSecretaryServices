"""
Prueft, dass das Image eine JS-Laufzeit fuer yt-dlp mitbringt.

Hintergrund (25.11.2026): Ohne JS-Laufzeit loest yt-dlp YouTubes JS-Challenges nicht.
Angemeldete Abrufe finden dann keine Formate ("Requested format is not available").
Der Fehler faellt lokal nicht auf, weil dort Node im PATH liegt. Deshalb prueft dieser
Test das Dockerfile selbst.

Ausfuehren (aus dem Projektroot, in der venv):
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_ytdlp_js_runtime.py -q
"""

import re
from pathlib import Path
from typing import Tuple

from src.processors.ytdlp_youtube_opts import default_js_runtimes

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"

# yt-dlp verlangt Deno ab 2.3.0 (yt_dlp/utils/_jsruntime.py, MIN_SUPPORTED_VERSION).
DENO_MINDESTVERSION: Tuple[int, int, int] = (2, 3, 0)

_DENO_COPY = re.compile(
    r"^COPY --from=denoland/deno:bin-(\d+)\.(\d+)\.(\d+)@sha256:[0-9a-f]{64} /deno /usr/local/bin/deno\s*$",
    re.MULTILINE,
)


def test_dockerfile_bringt_deno_per_digest_gepinnt() -> None:
    """Deno kommt als einzelne Datei aus dem offiziellen Image, mit Version und Digest."""
    match = _DENO_COPY.search(DOCKERFILE.read_text(encoding="utf-8"))
    assert match is not None, "Dockerfile kopiert kein per Digest gepinntes Deno nach /usr/local/bin/deno"
    version = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    assert version >= DENO_MINDESTVERSION, f"Deno {version} ist aelter als die Mindestversion von yt-dlp"


def test_deno_ist_fuer_ytdlp_freigeschaltet() -> None:
    """Die Laufzeit im Image nuetzt nur, wenn yt-dlp sie auch verwenden darf."""
    runtimes = default_js_runtimes()
    assert "deno" in runtimes
    assert "node" in runtimes


def test_default_js_runtimes_liefert_eigene_kopie() -> None:
    """Ein Aufrufer darf die Vorgabe nicht fuer alle anderen veraendern."""
    first = default_js_runtimes()
    first["deno"]["path"] = "/tmp/anders"
    first["bun"] = {}
    assert default_js_runtimes() == {"deno": {}, "node": {}}
