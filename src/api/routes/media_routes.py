"""
@fileoverview Media Routes - POST /api/media/resolve, /download, /playlist

@description
Medien einer Webseite oder Player-Adresse per yt-dlp fuer KnowledgeScout
(Webseite als Quelle erschliessen). Drei Wege:

- /resolve loest die Adresse zur direkten Medienadresse auf, laedt nichts.
  KnowledgeScout laedt die Datei selbst, wenn das Protokoll http(s) ist
  (Rai-News-Podcasts, YouTube-Audio m4a). Dazu kommt ein Block `metadata`
  mit allem, was yt-dlp ueber die Seite weiss (Beschreibung, Datum, Kanal,
  Kapitel, Tags, Vorschaubild) — fuer Videoseiten die bessere Quelle als das
  Server-HTML.
- /download laedt per yt-dlp (mit ffmpeg fuer HLS/DASH, z. B. Rai-Videos) in ein
  Temp-Verzeichnis und liefert die Datei als Antwort — fuer alles, was keine
  direkte Audio-Datei ist. Mit `nur_audio` (Vorgabe true) zieht ffmpeg die
  Tonspur als m4a heraus: KnowledgeScout braucht fuer Videos nur die
  Transkription, und Audio-Optionen (Sprecher, Kontext, Begriffe) gelten nur
  fuer Audio.
- /playlist loest eine Playlist (YouTube, Vimeo, PeerTube — alles, was yt-dlp
  als Playlist kennt) flach auf: nur die Liste der Eintraege, kein Abruf je
  Video, kein Download. Private oder geloeschte Eintraege bleiben in der Liste
  und tragen einen Grund.

`noplaylist` bleibt fuer /resolve und /download gesetzt: ein Video-Link mit
`&list=` liefert dort nur das eine Video, nie die ganze Playlist.

Kein stiller Fallback: kennt yt-dlp die Seite nicht, kommt ein Fehler mit Grund.

Eingabe (JSON): { "url": "https://..." }; /download zusaetzlich optional "nur_audio": bool (Vorgabe true)
Ausgabe /resolve: { "status": "success", "data": { "extractor", "title", "duration", "ext",
  "url", "protocol", "http_headers", "ist_audio", "metadata": { "id", "description",
  "upload_date" (ISO JJJJ-MM-TT oder null), "uploader", "channel", "chapters", "tags",
  "thumbnail", "webpage_url" } } }
Ausgabe /download: Dateibytes; Header X-Media-Ext, X-Media-Title (URL-kodiert),
  X-Media-Duration, X-Media-Is-Audio, X-Media-Extractor
Ausgabe /playlist: { "status": "success", "data": { "extractor", "id", "title", "uploader",
  "channel", "description", "webpage_url", "anzahl", "anzahl_verfuegbar",
  "entries": [{ "position", "id", "url", "title", "duration", "verfuegbar", "grund" }] } }

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

# Windows-TLS-Workaround wie in video_processor: VOR dem yt-dlp-Import.
if os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore

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


def _iso_date(raw: Any) -> Optional[str]:
    """yt-dlp liefert Daten als 'JJJJMMTT'; nach ISO 'JJJJ-MM-TT'. Unbekannt bleibt None — nie geraten."""
    if isinstance(raw, str) and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return None


def _best_thumbnail(info: Dict[str, Any]) -> Optional[str]:
    """Vorschaubild in der hoechsten bekannten Aufloesung; sonst das von yt-dlp gewaehlte."""
    best_url: Optional[str] = None
    best_pixels = -1
    thumbs = info.get('thumbnails')
    if isinstance(thumbs, list):
        for thumb in thumbs:
            if not isinstance(thumb, dict) or not isinstance(thumb.get('url'), str):
                continue
            width, height = thumb.get('width'), thumb.get('height')
            pixels = width * height if isinstance(width, int) and isinstance(height, int) else 0
            if pixels > best_pixels:
                best_pixels, best_url = pixels, thumb['url']
    fallback = info.get('thumbnail')
    if best_pixels > 0 and best_url:
        return best_url
    if isinstance(fallback, str) and fallback:
        return fallback
    return best_url


def _metadata_block(info: Dict[str, Any]) -> Dict[str, Any]:
    """Alles, was yt-dlp ueber die Seite weiss und KnowledgeScout fuer die Sammeldatei braucht."""
    chapters = []
    chapters_raw = info.get('chapters')
    if isinstance(chapters_raw, list):
        for chapter in chapters_raw:
            if isinstance(chapter, dict):
                chapters.append({
                    "title": chapter.get('title'),
                    "start_time": chapter.get('start_time'),
                    "end_time": chapter.get('end_time'),
                })
    tags_raw = info.get('tags')
    tags = [t for t in tags_raw if isinstance(t, str)] if isinstance(tags_raw, list) else []
    return {
        "id": info.get('id'),
        "description": info.get('description'),
        "upload_date": _iso_date(info.get('upload_date')),
        "uploader": info.get('uploader'),
        "channel": info.get('channel'),
        "chapters": chapters,
        "tags": tags,
        "thumbnail": _best_thumbnail(info),
        "webpage_url": info.get('webpage_url'),
    }


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
        "metadata": _metadata_block(info),
    }


# Flache Auflösung: yt-dlp holt nur die Liste, nicht die Seite jedes Videos.
PLAYLIST_OPTS: Dict[str, Any] = {'extract_flat': 'in_playlist', 'noplaylist': False, 'skip_download': True}

_UNAVAILABLE_TITLES = {'[private video]': 'privat', '[deleted video]': 'geloescht'}
_UNAVAILABLE_AVAILABILITY = {
    'private': 'privat',
    'premium_only': 'nur Premium',
    'subscriber_only': 'nur Abonnenten',
    'needs_auth': 'Anmeldung noetig',
}


def _entry_availability(entry: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """(verfuegbar, grund) eines flachen Playlist-Eintrags. YouTube nennt private und geloeschte Videos nur im Titel."""
    title = entry.get('title')
    if isinstance(title, str) and title.strip().lower() in _UNAVAILABLE_TITLES:
        return False, _UNAVAILABLE_TITLES[title.strip().lower()]
    availability = entry.get('availability')
    if isinstance(availability, str) and availability in _UNAVAILABLE_AVAILABILITY:
        return False, _UNAVAILABLE_AVAILABILITY[availability]
    if entry.get('live_status') == 'is_upcoming':
        return False, 'angekuendigt, noch nicht gesendet'
    return True, None


def resolve_playlist(url: str) -> Dict[str, Any]:
    """Flache Liste einer Playlist per yt-dlp. Wirft bei unbekannter Seite, leerer Playlist oder wenn die Adresse keine Playlist ist."""
    with yt_dlp.YoutubeDL(_ydl_opts(PLAYLIST_OPTS)) as ydl:
        info = ydl.extract_info(url, download=False)
    if not isinstance(info, dict):
        raise ValueError("yt-dlp lieferte keine Metadaten")
    entries_raw = info.get('entries')
    if entries_raw is None:
        raise ValueError("Adresse ist keine Playlist: yt-dlp lieferte ein einzelnes Medium")
    entries_list = [e for e in list(entries_raw) if isinstance(e, dict)]
    if not entries_list:
        raise ValueError("Playlist ist leer oder ihre Eintraege sind nicht lesbar")
    entries = []
    for position, entry in enumerate(entries_list, start=1):
        index = entry.get('playlist_index')
        verfuegbar, grund = _entry_availability(entry)
        entries.append({
            "position": index if isinstance(index, int) and index > 0 else position,
            "id": entry.get('id'),
            "url": entry.get('url') or entry.get('webpage_url'),
            "title": entry.get('title'),
            "duration": entry.get('duration'),
            "verfuegbar": verfuegbar,
            "grund": grund,
        })
    return {
        "extractor": info.get('extractor'),
        "id": info.get('id'),
        "title": info.get('title'),
        "uploader": info.get('uploader'),
        "channel": info.get('channel'),
        "description": info.get('description'),
        "webpage_url": info.get('webpage_url'),
        "anzahl": len(entries),
        "anzahl_verfuegbar": sum(1 for e in entries if e["verfuegbar"]),
        "entries": entries,
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


@media_ns.route("/playlist")
class MediaPlaylistEndpoint(Resource):
    """Flache Liste einer Playlist; ruft keine Video-Seite ab und laedt nichts herunter."""

    @media_ns.expect(request_model)
    @media_ns.doc(description="Loest eine Playlist-Adresse per yt-dlp flach auf (Titel, Besitzer, Beschreibung, Eintraege mit Position, Id, Adresse, Titel, Dauer). Private oder geloeschte Eintraege stehen mit Grund in der Liste. Keine Playlist oder leere Playlist ist ein Fehler.")
    def post(self) -> Union[Dict[str, Any], Tuple[Dict[str, Any], int]]:
        url = _read_url(request.get_json(silent=True) or {})
        if not url:
            return _error("MISSING_URL", "Feld 'url' (http/https) ist erforderlich", 400)
        try:
            data = resolve_playlist(url)
        except yt_dlp.utils.DownloadError as e:  # type: ignore[attr-defined]
            logger.warning("yt-dlp kennt die Playlist nicht oder sie ist nicht erreichbar", url=url, error=str(e))
            return _error("PLAYLIST_NOT_RESOLVABLE", f"Playlist nicht aufloesbar: {e}", 422)
        except ValueError as e:
            return _error("PLAYLIST_NOT_RESOLVABLE", str(e), 422)
        except Exception as e:
            logger.error("Unerwarteter Fehler beim Aufloesen der Playlist", error=e, url=url)
            return _error("INTERNAL_ERROR", str(e), 500)
        logger.info("Playlist aufgeloest", url=url, extractor=data.get("extractor"), anzahl=data.get("anzahl"), anzahl_verfuegbar=data.get("anzahl_verfuegbar"))
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
