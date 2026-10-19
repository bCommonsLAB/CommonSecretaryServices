"""
@fileoverview Media Routes - POST /api/media/resolve, POST /api/media/download

@description
Medien einer Webseite oder Player-Adresse per yt-dlp fuer KnowledgeScout
(Webseite als Quelle erschliessen). Zwei Wege:

- /resolve loest die Adresse zur direkten Medienadresse auf, laedt nichts.
  KnowledgeScout laedt die Datei selbst, wenn das Protokoll http(s) ist
  (Rai-News-Podcasts, YouTube-Audio m4a).
- /download laedt per yt-dlp (mit ffmpeg fuer HLS/DASH, z. B. Rai-Videos) in ein
  Temp-Verzeichnis und liefert die Datei als Antwort — fuer alles, was keine
  direkte Audio-Datei ist. Mit `nur_audio` (Vorgabe true) zieht ffmpeg die
  Tonspur als m4a heraus: KnowledgeScout braucht fuer Videos nur die
  Transkription, und Audio-Optionen (Sprecher, Kontext, Begriffe) gelten nur
  fuer Audio.

Kein stiller Fallback: kennt yt-dlp die Seite nicht, kommt ein Fehler mit Grund.

Eingabe (JSON): { "url": "https://..." }; /download zusaetzlich optional "nur_audio": bool (Vorgabe true)
Ausgabe /resolve: { "status": "success", "data": { "extractor", "title", "duration", "ext",
  "url", "protocol", "http_headers", "ist_audio" } }
Ausgabe /download: Dateibytes; Header X-Media-Ext, X-Media-Title (URL-kodiert),
  X-Media-Duration, X-Media-Is-Audio, X-Media-Extractor

@module api.routes.media_routes
@exports
- media_ns: Namespace
@usedIn
- src.api.routes.__init__: registriert media_ns unter /media
"""
# pyright: reportMissingTypeStubs=false
# type: ignore
import os
import shutil
import tempfile
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import quote

from flask import Response, request
from flask_restx import Namespace, Resource, fields

# TLS-Regel VOR dem yt-dlp-Import anwenden (AP-04): PYTHONHTTPSVERIFY=0 wirkt nur mit FLASK_ENV=development.
from src.core.security import apply_tls_policy
apply_tls_policy()

import yt_dlp  # type: ignore

from src.utils.logger import get_logger

logger = get_logger(process_id="media-api")

media_ns = Namespace("media", description="Medien einer Webseite aufloesen oder laden (yt-dlp)")

request_model = media_ns.model("MediaRequest", {
    "url": fields.String(required=True, description="Webseiten- oder Player-Adresse"),
})

# Reine Tonspur zuerst (m4a spielt im Browser, ist klein), sonst beste Qualitaet.
FORMAT = 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best'

MIME_BY_EXT = {
    'mp3': 'audio/mpeg', 'm4a': 'audio/mp4', 'aac': 'audio/aac', 'ogg': 'audio/ogg', 'opus': 'audio/opus',
    'wav': 'audio/wav', 'flac': 'audio/flac', 'mp4': 'video/mp4', 'webm': 'video/webm', 'mkv': 'video/x-matroska',
}


def _error(code: str, message: str, status: int, details: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    return {"status": "error", "error": {"code": code, "message": message, "details": details}}, status


def _ydl_opts(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    opts: Dict[str, Any] = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'noplaylist': True,
        'format': FORMAT,
        'socket_timeout': 30,
        'retries': 5,
    }
    cookies_file = os.getenv('YTDLP_COOKIES_FILE')
    if cookies_file and os.path.isfile(cookies_file):
        opts['cookiefile'] = cookies_file
    if extra:
        opts.update(extra)
    return opts


def _first_entry(info: Any, url: str) -> Dict[str, Any]:
    if not isinstance(info, dict):
        raise ValueError("yt-dlp lieferte keine Metadaten")
    entries = info.get('entries')
    if isinstance(entries, list) and entries:
        logger.warning("Mehrere Eintraege, nehme den ersten", url=url, anzahl=len(entries))
        return entries[0]
    return info


def _read_url(payload: Dict[str, Any]) -> Optional[str]:
    url = payload.get("url")
    if not isinstance(url, str) or not url.strip().startswith(("http://", "https://")):
        return None
    return url.strip()


def resolve_media_url(url: str) -> Dict[str, Any]:
    """Metadaten und direkte Adresse per yt-dlp (download=False). Wirft bei unbekannter Seite."""
    with yt_dlp.YoutubeDL(_ydl_opts({'skip_download': True})) as ydl:
        info = _first_entry(ydl.extract_info(url, download=False), url)
    direct = info.get('url')
    if not isinstance(direct, str) or not direct:
        raise ValueError("yt-dlp kennt die Seite, fand aber keine direkte Medienadresse")
    return {
        "extractor": info.get('extractor'),
        "title": info.get('title'),
        "duration": info.get('duration'),
        "ext": info.get('ext'),
        "url": direct,
        "protocol": info.get('protocol'),
        "http_headers": info.get('http_headers') or {},
        "ist_audio": str(info.get('vcodec') or 'none') == 'none',
    }


def download_media(url: str, workdir: str, nur_audio: bool = True) -> Dict[str, Any]:
    """Laedt per yt-dlp (HLS/DASH ueber ffmpeg) nach workdir; liefert Pfad und Metadaten.

    nur_audio: Tonspur per ffmpeg als m4a herausziehen (auch aus Videos).
    """
    outtmpl = os.path.join(workdir, 'medium.%(ext)s')
    extra: Dict[str, Any] = {'outtmpl': outtmpl}
    if nur_audio:
        extra['postprocessors'] = [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}]
    with yt_dlp.YoutubeDL(_ydl_opts(extra)) as ydl:
        info = _first_entry(ydl.extract_info(url, download=True), url)
    files = [f for f in os.listdir(workdir) if f.startswith('medium.') and not f.endswith('.part')]
    if nur_audio:
        files = [f for f in files if f.lower().endswith('.m4a')]
    if not files:
        raise ValueError("yt-dlp hat keine Datei abgelegt" + (" (keine Tonspur extrahierbar)" if nur_audio else ""))
    path = os.path.join(workdir, files[0])
    return {
        "path": path,
        "ext": files[0].rsplit('.', 1)[-1].lower(),
        "title": info.get('title'),
        "duration": info.get('duration'),
        "extractor": info.get('extractor'),
        "ist_audio": True if nur_audio else str(info.get('vcodec') or 'none') == 'none',
    }


@media_ns.route("/resolve")
class MediaResolveEndpoint(Resource):
    """Direkte Medienadresse einer Seite; laedt nichts herunter."""

    @media_ns.expect(request_model)
    @media_ns.doc(description="Loest eine Webseiten-/Player-Adresse per yt-dlp zur direkten Medienadresse auf. Unbekannte Seiten sind ein Fehler.")
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        url = _read_url(request.get_json(silent=True) or {})
        if not url:
            return _error("MISSING_URL", "Feld 'url' (http/https) ist erforderlich", 400)
        try:
            data = resolve_media_url(url)
        except yt_dlp.utils.DownloadError as e:  # type: ignore[attr-defined]
            logger.warning("yt-dlp kennt die Seite nicht oder kein Medium", url=url, error=str(e))
            return _error("MEDIA_NOT_RESOLVABLE", f"Kein Medium aufloesbar: {e}", 422)
        except ValueError as e:
            return _error("MEDIA_NOT_RESOLVABLE", str(e), 422)
        except Exception as e:
            logger.error("Unerwarteter Fehler beim Aufloesen", error=e, url=url)
            return _error("INTERNAL_ERROR", str(e), 500)
        logger.info("Medium aufgeloest", url=url, extractor=data.get("extractor"), ext=data.get("ext"), protocol=data.get("protocol"))
        return {"status": "success", "data": data}


@media_ns.route("/download")
class MediaDownloadEndpoint(Resource):
    """Laedt das Medium per yt-dlp (auch HLS/DASH) und liefert die Datei."""

    @media_ns.expect(request_model)
    @media_ns.doc(description="Laedt das Medium einer Webseiten-/Player-Adresse per yt-dlp (ffmpeg fuer Streams) und liefert die Datei; Metadaten in X-Media-*-Headern.")
    def post(self) -> Union[Response, Tuple[Dict[str, Any], int]]:
        payload: Dict[str, Any] = request.get_json(silent=True) or {}
        url = _read_url(payload)
        if not url:
            return _error("MISSING_URL", "Feld 'url' (http/https) ist erforderlich", 400)
        nur_audio_raw = payload.get("nur_audio", True)
        if not isinstance(nur_audio_raw, bool):
            return _error("INVALID_NUR_AUDIO", "Feld 'nur_audio' muss true oder false sein", 400)
        workdir = tempfile.mkdtemp(prefix='ks-media-')
        try:
            meta = download_media(url, workdir, nur_audio=nur_audio_raw)
            with open(meta["path"], 'rb') as fh:
                data = fh.read()
        except yt_dlp.utils.DownloadError as e:  # type: ignore[attr-defined]
            logger.warning("yt-dlp konnte nicht laden", url=url, error=str(e))
            return _error("MEDIA_NOT_DOWNLOADABLE", f"Medium nicht ladbar: {e}", 422)
        except ValueError as e:
            return _error("MEDIA_NOT_DOWNLOADABLE", str(e), 422)
        except Exception as e:
            logger.error("Unerwarteter Fehler beim Laden", error=e, url=url)
            return _error("INTERNAL_ERROR", str(e), 500)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        ext = meta["ext"]
        logger.info("Medium geladen", url=url, extractor=meta.get("extractor"), ext=ext, bytes=len(data))
        headers = {
            'X-Media-Ext': ext,
            'X-Media-Title': quote(str(meta.get("title") or ''), safe=''),
            'X-Media-Duration': str(meta.get("duration") or ''),
            'X-Media-Is-Audio': 'true' if meta.get("ist_audio") else 'false',
            'X-Media-Extractor': str(meta.get("extractor") or ''),
        }
        return Response(data, status=200, mimetype=MIME_BY_EXT.get(ext, 'application/octet-stream'), headers=headers)
