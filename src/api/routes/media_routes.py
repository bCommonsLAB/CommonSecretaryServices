"""
@fileoverview Media Routes - POST /api/media/resolve

@description
Loest eine Webseiten- oder Player-Adresse per yt-dlp zur direkten Medienadresse
auf, OHNE etwas herunterzuladen. KnowledgeScout laedt die Datei danach selbst
und legt sie als Quelle neben der Sammeldatei ab (Webseite als Quelle
erschliessen). Fuer Rai News, YouTube, Vimeo, PeerTube und alles, was yt-dlp
kennt. Kein stiller Fallback: kennt yt-dlp die Seite nicht, kommt ein Fehler
mit dem Grund, keine leere Antwort.

Eingabe (JSON):
    { "url": "https://..." }
Ausgabe:
    { "status": "success", "data": { "extractor": "RaiNews", "title": "...",
      "duration": 544, "ext": "mp3", "url": "https://...direkt...",
      "http_headers": {...}, "ist_audio": true } }

@module api.routes.media_routes
@exports
- media_ns: Namespace
@usedIn
- src.api.routes.__init__: registriert media_ns unter /media
"""
# pyright: reportMissingTypeStubs=false
# type: ignore
import os
from typing import Any, Dict, Optional, Tuple, Union

from flask import request
from flask_restx import Namespace, Resource, fields

# Windows-TLS-Workaround wie in video_processor: VOR dem yt-dlp-Import.
if os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore

import yt_dlp  # type: ignore

from src.utils.logger import get_logger

logger = get_logger(process_id="media-api")

media_ns = Namespace("media", description="Medienadressen aufloesen (laedt nichts herunter)")

request_model = media_ns.model("MediaResolveRequest", {
    "url": fields.String(required=True, description="Webseiten- oder Player-Adresse"),
})


def _error(code: str, message: str, status: int, details: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    return {"status": "error", "error": {"code": code, "message": message, "details": details}}, status


def _ydl_opts() -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'skip_download': True,
        'format': 'bestaudio/best',
        'socket_timeout': 30,
    }
    cookies_file = os.getenv('YTDLP_COOKIES_FILE')
    if cookies_file and os.path.isfile(cookies_file):
        opts['cookiefile'] = cookies_file
    return opts


def resolve_media_url(url: str) -> Dict[str, Any]:
    """Metadaten und direkte Adresse per yt-dlp (download=False). Wirft bei unbekannter Seite."""
    with yt_dlp.YoutubeDL(_ydl_opts()) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise ValueError("yt-dlp lieferte keine Metadaten")
    # Bei Playlists/Mehrfachtreffern den ersten Eintrag nehmen — laut, nicht still.
    entries = info.get('entries')
    if isinstance(entries, list) and entries:
        logger.warning("Mehrere Eintraege, nehme den ersten", url=url, anzahl=len(entries))
        info = entries[0]
    direct = info.get('url')
    if not isinstance(direct, str) or not direct:
        raise ValueError("yt-dlp kennt die Seite, fand aber keine direkte Medienadresse")
    vcodec = str(info.get('vcodec') or 'none')
    return {
        "extractor": info.get('extractor'),
        "title": info.get('title'),
        "duration": info.get('duration'),
        "ext": info.get('ext'),
        "url": direct,
        "http_headers": info.get('http_headers') or {},
        "ist_audio": vcodec == 'none',
    }


@media_ns.route("/resolve")
class MediaResolveEndpoint(Resource):
    """Direkte Medienadresse einer Seite; laedt nichts herunter."""

    @media_ns.expect(request_model)
    @media_ns.doc(description=(
        "Loest eine Webseiten-/Player-Adresse per yt-dlp zur direkten Medienadresse auf (Titel, Dauer, "
        "Endung, Header). KnowledgeScout laedt die Datei selbst. Unbekannte Seiten sind ein Fehler."
    ))
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        url = payload.get("url")
        if not isinstance(url, str) or not url.strip().startswith(("http://", "https://")):
            return _error("MISSING_URL", "Feld 'url' (http/https) ist erforderlich", 400)
        try:
            data = resolve_media_url(url.strip())
        except yt_dlp.utils.DownloadError as e:  # type: ignore[attr-defined]
            logger.warning("yt-dlp kennt die Seite nicht oder kein Medium", url=url, error=str(e))
            return _error("MEDIA_NOT_RESOLVABLE", f"Kein Medium aufloesbar: {e}", 422)
        except ValueError as e:
            return _error("MEDIA_NOT_RESOLVABLE", str(e), 422)
        except Exception as e:
            logger.error("Unerwarteter Fehler beim Aufloesen", error=e, url=url)
            return _error("INTERNAL_ERROR", str(e), 500)
        logger.info("Medium aufgeloest", url=url, extractor=data.get("extractor"), ext=data.get("ext"), duration=data.get("duration"))
        return {"status": "success", "data": data}
