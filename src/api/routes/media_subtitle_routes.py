"""
@fileoverview Media Routes - POST /api/media/subtitles

@description
Fertige Untertitel einer Videoseite als Transkript, ohne das Medium zu laden. Fuer KnowledgeScout:
Wer nur den Wortlaut braucht, spart den Download der Tonspur und die Transkription.

yt-dlp liest die Seite (wie /resolve, aber ohne Formate zu verlangen), `choose_track` waehlt genau
eine Spur, yt-dlp laedt nur diese eine Datei, und die Zeilen werden zu Absaetzen mit Zeitmarken
zusammengezogen (`src/processors/subtitle_tracks.py`).

Vorrang der Spuren: die von Hand gepflegte Spur der gewuenschten Sprache, sonst die automatische Spur
in der Originalsprache des Videos. Maschinell uebersetzte Spuren gelten nie als Transkript.

Kein stiller Rueckfall: Traegt das Video keine brauchbare Spur, kommt 422 SUBTITLES_NOT_AVAILABLE mit
`error.details.grund` (KEINE_UNTERTITEL, NUR_UEBERSETZTE_SPUREN, SPRACHE_NICHT_EINDEUTIG,
FORMAT_NICHT_LESBAR, SPUR_LEER, VIDEO_LAEUFT_NOCH) und `error.details.verfuegbar`. Ob dann die Tonspur
transkribiert wird, entscheidet der Aufrufer. Fehler von yt-dlp (Anmeldung, Sperre) werden wie bei
den anderen Medien-Routen gedeutet.

Eingabe (JSON): { "url": "https://...", "sprache": "en" (optional), "cookies": "..." (optional) }
Ausgabe: { "status": "success", "data": { "extractor", "id", "title", "duration",
  "sprache", "art" ("manuell" | "automatisch"), "spur", "format", "verfuegbar": { "manuell",
  "automatisch_original", "automatisch_uebersetzt", "originalsprache" },
  "abdeckung": { "beginn", "ende", "anteil", "groesste_luecke", "groesste_luecke_bei", "zeilen", "woerter" },
  "absaetze": [{ "start", "text" }], "text": "[00:00:00] ...", "metadata": { wie /resolve } } }

@module api.routes.media_subtitle_routes
@usedIn
- src.api.routes.__init__: importiert das Modul, die Route haengt an media_ns
"""
# pyright: reportMissingTypeStubs=false
# type: ignore
import os
import shutil
import tempfile
from typing import Any, Dict, Optional, Tuple, Union

from flask import request
from flask_restx import Resource, fields

from src.api.routes import media_routes
from src.api.routes.media_routes import (
    InvalidCookies, YtdlpNotes, _cookie_file, _error, _first_entry, _metadata_block, _read_cookies,
    _read_url, _ydl_opts, _ytdlp_error, media_ns,
)
from src.processors.subtitle_tracks import (
    SPUR_LEER, ChosenTrack, NoSubtitleTrack, build_paragraphs, choose_track, coverage, parse_cues, render_text,
)
from src.utils.error_responses import public_error_message, redact_sensitive
from src.utils.logger import get_logger
from src.utils.ssrf import GuardedYoutubeDL, SsrfBlocked, SSRF_BLOCKED, check_url

logger = get_logger(process_id="media-api")

subtitle_request_model = media_ns.model("MediaSubtitleRequest", {
    "url": fields.String(required=True, description="Adresse der Videoseite"),
    "sprache": fields.String(required=False, description="Gewuenschte Sprache der von Hand gepflegten Spur, z. B. 'en'; ohne Angabe die Originalsprache des Videos"),
    "cookies": fields.String(required=False, description="Optional: Inhalt einer Netscape-cookies.txt fuer diesen Aufruf, wie bei /resolve"),
})

# Untertitel sind Text; eine Datei ueber dieser Groesse ist keine Untertitelspur eines Videos.
SUBTITLE_MAX_BYTES = 20 * 1024 * 1024

# Formate werden nicht gebraucht: ein Video ohne abspielbares Format darf trotzdem Untertitel liefern.
# `writesubtitles`/`writeautomaticsub` schalten bei manchen Extraktoren erst das Lesen der Spuren ein.
SUBTITLE_OPTS: Dict[str, Any] = {
    'skip_download': True,
    'ignore_no_formats_error': True,
    'writesubtitles': True,
    'writeautomaticsub': True,
}


class InvalidLanguage(ValueError):
    """Feld `sprache` ist vorhanden, aber kein Sprachcode. Wird zum 400 INVALID_SPRACHE."""


def _read_language(payload: Dict[str, Any]) -> Optional[str]:
    """Optionales Feld `sprache`: None wenn nicht gesetzt, sonst der Code; wirft InvalidLanguage."""
    if "sprache" not in payload or payload["sprache"] is None:
        return None
    raw = payload["sprache"]
    if not isinstance(raw, str) or not raw.strip() or len(raw.strip()) > 20 or not raw.strip().replace("-", "").replace("_", "").isalnum():
        raise InvalidLanguage("Feld 'sprache' muss ein Sprachcode sein, z. B. 'en' oder 'pt-BR'")
    return raw.strip()


def _load_track(ydl: Any, track: ChosenTrack, info: Dict[str, Any], workdir: str) -> str:
    """Laedt die gewaehlte Spur ueber yt-dlp (Anmeldung, Client und Adresspruefung wie beim Medium) und liefert ihren Inhalt."""
    if isinstance(track.entry.get("data"), str):
        return track.entry["data"]
    path = os.path.join(workdir, f"untertitel.{track.entry['ext']}")
    sub = dict(track.entry)
    sub.setdefault('http_headers', info.get('http_headers'))
    ydl.dl(path, sub, subtitle=True)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise NoSubtitleTrack(SPUR_LEER, f"Die Spur '{track.key}' ist angekuendigt, lieferte aber keinen Inhalt", track.verfuegbar)
    if os.path.getsize(path) > SUBTITLE_MAX_BYTES:
        raise ValueError(f"Untertiteldatei ist groesser als {SUBTITLE_MAX_BYTES // (1024 * 1024)} MiB; das ist keine Untertitelspur")
    with open(path, 'r', encoding='utf-8-sig', errors='replace') as fh:
        return fh.read()


def fetch_subtitles(url: str, workdir: str, sprache: Optional[str] = None, cookies: Optional[str] = None, notes: Optional[YtdlpNotes] = None) -> Dict[str, Any]:
    """Untertitel einer Videoseite als Transkript. Wirft NoSubtitleTrack ohne brauchbare Spur.

    sprache: gewuenschte Sprache der von Hand gepflegten Spur; ohne Angabe die Originalsprache.
    cookies: optionaler Inhalt einer Netscape-cookies.txt, nur fuer diesen Aufruf.
    notes: sammelt die Warnungen von yt-dlp fuer die Fehlerdeutung.
    """
    with _cookie_file(cookies) as cookiefile, GuardedYoutubeDL(_ydl_opts(SUBTITLE_OPTS, cookiefile, notes)) as ydl:
        info = _first_entry(ydl.extract_info(url, download=False), url)
        track = choose_track(info, sprache)
        raw = _load_track(ydl, track, info, workdir)
    cues = parse_cues(raw, track.entry["ext"])
    if not cues:
        raise NoSubtitleTrack(SPUR_LEER, f"Die Spur '{track.key}' enthaelt keine Textzeilen", track.verfuegbar)
    paragraphs = build_paragraphs(cues, info.get('chapters'))
    return {
        "extractor": info.get('extractor'),
        "id": info.get('id'),
        "title": info.get('title'),
        "duration": info.get('duration'),
        "sprache": track.sprache,
        "art": track.art,
        "spur": track.key,
        "format": track.entry["ext"],
        "verfuegbar": track.verfuegbar,
        "abdeckung": coverage(cues, info.get('duration')),
        "absaetze": paragraphs,
        "text": render_text(paragraphs),
        "metadata": _metadata_block(info),
    }


@media_ns.route("/subtitles")
class MediaSubtitlesEndpoint(Resource):
    """Fertige Untertitel einer Videoseite als Transkript; laedt das Medium nicht."""

    @media_ns.expect(subtitle_request_model)
    @media_ns.doc(description="Liefert die Untertitel einer Videoseite als Transkript mit Zeitmarken, ohne das Medium zu laden. Vorrang: von Hand gepflegte Spur der gewuenschten Sprache, sonst die automatische Spur in der Originalsprache; uebersetzte Spuren nie. Ohne brauchbare Spur 422 SUBTITLES_NOT_AVAILABLE mit Grund. Optional `sprache` und `cookies`.")
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        url = _read_url(payload)
        if not url:
            return _error("MISSING_URL", "Feld 'url' (http/https) ist erforderlich", 400)
        try:
            sprache = _read_language(payload)
        except InvalidLanguage as e:
            return _error("INVALID_SPRACHE", public_error_message(e), 400)
        try:
            cookies = _read_cookies(payload)
        except InvalidCookies as e:
            return _error("INVALID_COOKIES", public_error_message(e), 400)
        workdir = tempfile.mkdtemp(prefix='ks-subs-')
        notes = YtdlpNotes()
        try:
            check_url(url)
            data = fetch_subtitles(url, workdir, sprache=sprache, cookies=cookies, notes=notes)
        except media_routes.yt_dlp.utils.DownloadError as e:  # type: ignore[attr-defined]
            return _ytdlp_error("SUBTITLES_NOT_AVAILABLE", "Untertitel nicht ladbar", e, url, cookies is not None, notes, "yt-dlp konnte die Untertitel nicht laden")
        except SsrfBlocked as e:
            logger.warning("Adresse abgelehnt (SSRF-Schutz)", url=url)
            return _error(SSRF_BLOCKED, public_error_message(e), 400)
        except NoSubtitleTrack as e:
            logger.info(
                "Keine brauchbare Untertitelspur", url=url, grund=e.grund, anmeldung=cookies is not None,
                ytdlp_warnungen=[redact_sensitive(w) for w in notes.warnings[:5]],
            )
            return _error("SUBTITLES_NOT_AVAILABLE", public_error_message(e, expected=True), 422, {"grund": e.grund, "verfuegbar": e.verfuegbar})
        except ValueError as e:
            return _error("SUBTITLES_NOT_AVAILABLE", public_error_message(e, expected=True), 422)
        except Exception as e:
            logger.error("Unerwarteter Fehler beim Laden der Untertitel", error=e, url=url)
            return _error("INTERNAL_ERROR", public_error_message(e), 500)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        logger.info(
            "Untertitel geladen", url=url, extractor=data.get("extractor"), sprache=data.get("sprache"), art=data.get("art"),
            format=data.get("format"), zeilen=data["abdeckung"]["zeilen"], anmeldung=cookies is not None,
        )
        return {"status": "success", "data": data}
