"""
yt-dlp-Zusatzoptionen für YouTube-Downloads.

YouTube blockiert anonyme Stream-URLs mit HTTP 403. Für aktuelle
Player-APIs braucht yt-dlp zusätzlich einen JS-Challenge-Solver.
Diese Hilfsfunktionen bündeln beides, ohne Cookie-Werte zu loggen.

Vorrang der Cookie-Quellen:
1. YTDLP_YOUTUBE_COOKIES_FILE (Netscape-Datei, nur YouTube)
2. YTDLP_COOKIES_FROM_BROWSER (z. B. edge)
YTDLP_COOKIES_FILE wird bewusst nicht verwendet: dort liegt lokal
die Vimeo-Datei, die YouTube nicht authentifiziert.
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


# Node liegt in dieser Umgebung im PATH (v22). Deno ist Default von yt-dlp,
# ist hier aber nicht installiert. Node muss deshalb explizit aktiviert werden.
_DEFAULT_JS_RUNTIMES: Dict[str, Dict[str, str]] = {"node": {}}


def build_youtube_ytdlp_extra_opts() -> Dict[str, Any]:
    """Liefert JS-Runtime- und Cookie-Optionen für YoutubeDL.

    Cookie-Inhalte werden nicht zurückgegeben, nur Pfade bzw. Browsernamen.
    """
    opts: Dict[str, Any] = {"js_runtimes": dict(_DEFAULT_JS_RUNTIMES)}

    youtube_cookie_file: Optional[str] = _resolve_youtube_cookie_file()
    if youtube_cookie_file is not None:
        opts["cookiefile"] = youtube_cookie_file
        return opts

    browser: Optional[str] = _resolve_cookies_browser()
    if browser is not None:
        # Python-API verlangt ein Tuple. Ein String "edge" wird von
        # yt-dlp als Sequenz entpackt -> browser_name="e".
        opts["cookiesfrombrowser"] = _browser_spec_tuple(browser)
    return opts


def apply_youtube_ytdlp_opts(opts: Dict[str, Any]) -> Dict[str, Any]:
    """Mischt YouTube-spezifische Extra-Optionen in ein bestehendes Opts-Dict."""
    opts.update(build_youtube_ytdlp_extra_opts())
    return opts


@dataclass(frozen=True)
class YoutubeCookieFailure:
    """Klassifizierter Cookie-Fehler ohne Cookie-Werte."""

    code: str
    message: str


def classify_youtube_cookie_error(error: BaseException) -> Optional[YoutubeCookieFailure]:
    """Ordnet yt-dlp-Cookie-Fehler einer klaren Meldung zu.

    Zwei Windows-Fälle sind bekannt:
    1. Cookie-DB gesperrt, solange Edge/Chrome laeuft.
    2. DPAPI/App-Bound Encryption: Chromium-Cookies sind nicht
       mit --cookies-from-browser entschluesselbar (yt-dlp#10927).
    """
    text: str = str(error)
    if "Failed to decrypt with DPAPI" in text:
        return YoutubeCookieFailure(
            code="COOKIE_DPAPI",
            message=(
                "Edge/Chrome-Cookies lassen sich unter Windows nicht "
                "entschluesseln (App-Bound Encryption). Bitte in Firefox "
                "bei YouTube anmelden, Firefox schliessen und "
                "YTDLP_COOKIES_FROM_BROWSER=firefox setzen. Alternative: "
                "Netscape-Cookie-Datei in YTDLP_YOUTUBE_COOKIES_FILE."
            ),
        )
    locked: bool = (
        "Could not copy Chrome cookie database" in text
        or ("Permission denied" in text and "Cookies" in text)
    )
    if locked:
        return YoutubeCookieFailure(
            code="COOKIE_DB_LOCKED",
            message=(
                "YouTube-Cookies konnten nicht gelesen werden, weil der "
                "Browser die Cookie-Datei gesperrt hat. Browser bitte "
                "vollstaendig beenden und den Request erneut senden."
            ),
        )
    return None


def youtube_cookie_lock_message(error: BaseException) -> Optional[str]:
    """Kompatibilitaets-Wrapper: nur die Meldung, ohne Fehlercode."""
    failure = classify_youtube_cookie_error(error)
    if failure is None:
        return None
    return failure.message


def _resolve_youtube_cookie_file() -> Optional[str]:
    """Gibt nur eine existierende YouTube-Cookie-Datei zurück."""
    raw: Optional[str] = os.getenv("YTDLP_YOUTUBE_COOKIES_FILE")
    if raw is None or not raw.strip():
        return None
    path = Path(raw.strip())
    if not path.is_file():
        return None
    return str(path)


def _resolve_cookies_browser() -> Optional[str]:
    """Browsername für --cookies-from-browser, z. B. edge oder chrome."""
    raw: Optional[str] = os.getenv("YTDLP_COOKIES_FROM_BROWSER")
    if raw is None:
        return None
    browser: str = raw.strip().lower()
    if not browser:
        return None
    return browser


def _browser_spec_tuple(browser: str) -> Tuple[str, ...]:
    """Baut die cookiesfrombrowser-Angabe im yt-dlp-Format.

    Erwartete Form: (browser,) oder (browser, profile, keyring, container).
    CLI --cookies-from-browser edge macht dasselbe intern.
    """
    return (browser,)
