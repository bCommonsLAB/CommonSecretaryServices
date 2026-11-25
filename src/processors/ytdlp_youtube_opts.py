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
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple


# yt-dlp loest YouTubes JS-Challenges nur mit einer JS-Laufzeit. Ohne sie gibt es
# seit 2026.8.19 fuer angemeldete Abrufe keine Formate mehr ("Requested format is
# not available"). Das Docker-Image bringt Deno mit (Dockerfile), lokal liegt Node
# (ab v22) im PATH. Beide sind freigeschaltet, yt-dlp nimmt die vorhandene.
# Ohne diese Angabe ist nur Deno aktiv.
_DEFAULT_JS_RUNTIMES: Dict[str, Dict[str, str]] = {"deno": {}, "node": {}}


def default_js_runtimes() -> Dict[str, Dict[str, str]]:
    """JS-Laufzeiten fuer die yt-dlp-Option `js_runtimes` (jeder Aufruf eine eigene Kopie)."""
    return {name: dict(config) for name, config in _DEFAULT_JS_RUNTIMES.items()}


def build_youtube_ytdlp_extra_opts() -> Dict[str, Any]:
    """Liefert JS-Runtime- und Cookie-Optionen für YoutubeDL.

    Cookie-Inhalte werden nicht zurückgegeben, nur Pfade bzw. Browsernamen.
    """
    opts: Dict[str, Any] = {"js_runtimes": default_js_runtimes()}

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


@dataclass(frozen=True)
class YoutubeAccessFailure:
    """Gedeuteter YouTube-Fehler: warum der Abruf scheitert und was zu tun ist."""

    code: str
    message: str


# Grund-Codes fuer `error.details.grund` der Medien-Routen.
YOUTUBE_LOGIN_MISSING = "YOUTUBE_ANMELDUNG_FEHLT"
YOUTUBE_LOGIN_REJECTED = "YOUTUBE_ANMELDUNG_NICHT_ANGENOMMEN"
YOUTUBE_SERVER_BLOCKED = "YOUTUBE_SERVER_GESPERRT"
YOUTUBE_CLIENT_OUTDATED = "YTDLP_VERALTET"
YOUTUBE_NO_FORMATS = "YOUTUBE_KEINE_FORMATE"

# YouTube schreibt "you’re" mit typografischem Apostroph, aeltere Texte mit geradem.
_BOT_CHECK = re.compile(r"Sign in to confirm you.{1,3}re not a bot", re.IGNORECASE)
_COOKIES_INVALID = "account cookies are no longer valid"
_SERVER_BLOCKED_MARKERS: Tuple[str, ...] = (
    "Your IP is likely being blocked",
    "has been rate-limited by YouTube",
    "available, try again later",
    "HTTP Error 429",
    "requiring a captcha challenge",
)
_PAGE_RELOAD = "The page needs to be reloaded"
_NO_FORMATS = "Requested format is not available"
_NO_JS_RUNTIME = "No supported JavaScript runtime"
_CHALLENGE_FAILED = "challenge solving failed"


def classify_youtube_access_error(
    error_text: str,
    cookies_given: bool,
    warnings: Sequence[str] = (),
) -> Optional[YoutubeAccessFailure]:
    """Deutet einen yt-dlp-Fehler von YouTube. None, wenn der Text nicht von YouTube stammt oder unbekannt ist.

    Unterschieden werden: Anmeldung fehlt; Anmeldung mitgegeben, aber von YouTube nicht angenommen;
    YouTube sperrt den Server unabhaengig von der Anmeldung; dazu zwei Faelle, die am Secretary selbst
    liegen (yt-dlp veraltet, keine Formate ohne JS-Laufzeit). `warnings` sind die Warnungen von yt-dlp
    aus demselben Aufruf: dort steht, wenn die Cookies ungueltig geworden sind oder die JS-Laufzeit fehlt.

    Args:
        error_text: Text der Ausnahme von yt-dlp.
        cookies_given: ob der Aufruf eine Anmeldung (Cookies) mitgegeben hat.
        warnings: Warnungen von yt-dlp aus demselben Aufruf.
    """
    if "[youtube" not in error_text:
        return None
    warning_text = " | ".join(warnings)

    if _COOKIES_INVALID in warning_text or (cookies_given and _BOT_CHECK.search(error_text)):
        return YoutubeAccessFailure(
            code=YOUTUBE_LOGIN_REJECTED,
            message=(
                "YouTube nimmt die hinterlegte Video-Anmeldung nicht an. Die Cookies sind vermutlich "
                "verbraucht: ein Browser, der angemeldet bleibt, ersetzt sie. Bitte neu exportieren: "
                "privates Fenster oeffnen, bei YouTube anmelden, cookies.txt exportieren, das Fenster "
                "schliessen, dann hochladen. Scheitert es auch mit frischen Cookies, sperrt YouTube den Server."
            ),
        )
    if _BOT_CHECK.search(error_text):
        return YoutubeAccessFailure(
            code=YOUTUBE_LOGIN_MISSING,
            message=(
                "YouTube verlangt von diesem Server eine Anmeldung, der Aufruf hat keine mitgegeben. "
                "Bitte eine Video-Anmeldung (cookies.txt) hinterlegen."
            ),
        )
    if any(marker in error_text for marker in _SERVER_BLOCKED_MARKERS):
        return YoutubeAccessFailure(
            code=YOUTUBE_SERVER_BLOCKED,
            message=(
                "YouTube sperrt oder bremst diesen Server, unabhaengig von der Anmeldung. Neue Cookies "
                "helfen nicht. Bis zu einer Stunde warten und Abrufe mit Abstand senden."
            ),
        )
    if _PAGE_RELOAD in error_text:
        return YoutubeAccessFailure(
            code=YOUTUBE_CLIENT_OUTDATED,
            message=(
                "YouTube weist den Client von yt-dlp ab. An der Anmeldung liegt es nicht, neue Cookies "
                "helfen nicht. yt-dlp im Secretary ist vermutlich veraltet und muss angehoben werden."
            ),
        )
    if _NO_FORMATS in error_text and (_NO_JS_RUNTIME in warning_text or _CHALLENGE_FAILED in warning_text):
        return YoutubeAccessFailure(
            code=YOUTUBE_NO_FORMATS,
            message=(
                "YouTube liefert keine abspielbaren Formate, weil yt-dlp die JS-Challenge nicht loesen "
                "konnte. Dem Secretary fehlt eine JS-Laufzeit (Deno oder Node ab v22) oder yt-dlp ist "
                "veraltet. An der Anmeldung liegt es nicht."
            ),
        )
    return None


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
