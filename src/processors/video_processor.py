"""
@fileoverview Video Processor - Processing of video files with audio extraction and transcription

@description
Video Processor for processing video files. This processor processes video files
(MP4, MOV, WebM) and performs the following operations:
- Audio extraction from videos with FFmpeg
- Frame extraction at specific timestamps
- Transcription of extracted audio with Whisper API
- Optional: Template-based transformation via TransformerProcessor
- Metadata extraction (duration, resolution, codec, etc.)

LLM tracking logic:
The VideoProcessor tracks LLM usage on two levels:
1. Aggregated information (LLMInfo): Total tokens, duration, costs
2. Individual requests (LLMRequest):
   - Transcription: whisper-1 model, one request per audio segment
   - Template transformation: gpt-4 model (via TransformerProcessor)
   - Translation: gpt-4 model (via TransformerProcessor)

Features:
- Audio extraction with FFmpeg
- Frame extraction at specific timestamps
- Integration with AudioProcessor for transcription
- Support for various video formats
- Caching of processing results
- Metadata extraction from video files

@module processors.video_processor

@exports
- VideoProcessor: Class - Video processing processor

@usedIn
- src.processors.session_processor: Uses VideoProcessor for video processing in sessions
- src.api.routes.video_routes: API endpoint for video processing

@dependencies
- External: yt-dlp - Video download (for YouTube videos)
- External: ffmpeg - Audio/video processing (system binary)
- Internal: src.processors.cacheable_processor - CacheableProcessor base class
- Internal: src.processors.audio_processor - AudioProcessor for audio processing
- Internal: src.processors.transformer_processor - TransformerProcessor for text transformation
- Internal: src.utils.transcription_utils - WhisperTranscriber
- Internal: src.core.models.video - Video models (VideoResponse, VideoProcessingResult, etc.)
- Internal: src.core.config - Configuration
"""
from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple, List
from datetime import datetime
import uuid
import hashlib
import subprocess  # Importiere subprocess für die FFmpeg-Integration
import json
import os
import requests
import re

# Windows-TLS-Workaround: Deaktiviere SSL-Verifikation BEVOR yt-dlp geladen wird
# Dies muss VOR dem yt-dlp-Import passieren, damit yt-dlp den gepatchten Context nutzt
if os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore

import yt_dlp  # type: ignore

from src.core.config import Config
from src.core.models.base import ErrorInfo
from src.core.models.video import (
    VideoSource,
    VideoMetadata,
    VideoProcessingResult,
    VideoResponse,
    VideoFramesResult,
    VideoFramesResponse,
    FrameInfo
)
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.base import ProcessInfo
from .cacheable_processor import CacheableProcessor
from .transformer_processor import TransformerProcessor
from .audio_processor import AudioProcessor

# Typ-Alias für yt-dlp
YDLDict = Dict[str, Any]

from typing import Union as _UnionTypeAlias

VideoAnyResult = _UnionTypeAlias[VideoProcessingResult, VideoFramesResult]

class VideoProcessor(CacheableProcessor[VideoAnyResult]):
    """
    Prozessor für die Verarbeitung von Video-Dateien.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der VideoProcessor erbt von CacheableProcessor, um MongoDB-Caching zu nutzen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "video_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den VideoProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Lade Konfiguration
        config = Config()
        processor_config = config.get('processors', {})
        video_config = processor_config.get('video', {})
        
        # Video-spezifische Konfigurationen
        self.max_duration = video_config.get('max_duration', 3600)  # 1 Stunde
        
        # Debug-Logging der Video-Konfiguration
        self.logger.debug("VideoProcessor initialisiert mit Konfiguration", 
                         max_duration=self.max_duration,
                         temp_dir=str(self.temp_dir),
                         cache_dir=str(self.cache_dir))
        
        # Initialisiere Prozessoren
        self.transformer = TransformerProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Initialisiere den Transcriber mit Video-spezifischen Konfigurationen
        transcriber_config = {
            "process_id": process_id,
            "processor_name": "video",
            "cache_dir": str(self.cache_dir),  # Haupt-Cache-Verzeichnis
            "temp_dir": str(self.temp_dir),    # Temporäres Unterverzeichnis
            "debug_dir": str(self.temp_dir / "debug")
        }
        self.transcriber = WhisperTranscriber(transcriber_config, processor=self)
        
        self.audio_processor = AudioProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Download-Optionen
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'socket_timeout': 30,
            'retries': 10,
            'sleep_interval': 3,
            'max_sleep_interval': 10,
            'nocheckcertificate': True,
            'legacy_server_connect': True,  # Hilft bei TLS-Problemen auf Windows
            'source_address': '0.0.0.0',  # Bindet an alle Interfaces (Windows-TLS-Workaround)
            'ignoreerrors': False,
            'no_playlist': True,
            'extract_flat': False,
            'youtube_include_dash_manifest': False,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            },
            'extractor_args': {
                'vimeo': {
                    'password': None,
                    'access_token': None
                }
            },
            'format_sort': ['ext:mp4:m4a', 'ext:webm:webma', 'ext:mp3'],
            'prefer_ffmpeg': True,
            'keepvideo': False
        }

        # Optionale Authentifizierung/Cookies für Vimeo/Plattformen per Umgebung aktivieren
        # Diese Konfiguration ist bewusst minimal und rückwärtskompatibel:
        # - YTDLP_COOKIES_FROM_BROWSER: z.B. "chrome" oder "edge" (nur lokal sinnvoll)
        # - YTDLP_COOKIES_FILE: Pfad zu cookies.txt im Netscape-Format (für Serverbetrieb)
        # - VIMEO_USERNAME / VIMEO_PASSWORD: Konto-Login (falls notwendig/erlaubt)
        # - YTDLP_NETRC=1: .netrc verwenden (Alternative zu USERNAME/PASSWORD)
        try:
            cookies_from_browser: Optional[str] = os.getenv('YTDLP_COOKIES_FROM_BROWSER')
            cookies_file: Optional[str] = os.getenv('YTDLP_COOKIES_FILE')
            vimeo_username: Optional[str] = os.getenv('VIMEO_USERNAME')
            vimeo_password: Optional[str] = os.getenv('VIMEO_PASSWORD')
            use_netrc: bool = os.getenv('YTDLP_NETRC', '').lower() in {'1', 'true', 'yes'}
            # Optional: explizites CA-Bundle für yt-dlp (falls Standard nicht greift)
            ca_bundle: Optional[str] = (
                os.getenv('YTDLP_CA_BUNDLE')
                or os.getenv('SSL_CERT_FILE')
                or os.getenv('REQUESTS_CA_BUNDLE')
            )
            
            # Debug-Logging: Zeige alle geladenen ENV-Variablen für Diagnose
            self.logger.info(
                "yt-dlp ENV-Variablen geladen",
                YTDLP_COOKIES_FROM_BROWSER=cookies_from_browser,
                YTDLP_COOKIES_FILE=cookies_file,
                VIMEO_USERNAME=bool(vimeo_username),
                VIMEO_PASSWORD=bool(vimeo_password),
                YTDLP_NETRC=use_netrc,
                YTDLP_CA_BUNDLE=os.getenv('YTDLP_CA_BUNDLE'),
                SSL_CERT_FILE=os.getenv('SSL_CERT_FILE'),
                REQUESTS_CA_BUNDLE=os.getenv('REQUESTS_CA_BUNDLE'),
                PYTHONHTTPSVERIFY=os.getenv('PYTHONHTTPSVERIFY'),
                ca_bundle_resolved=ca_bundle,
                ca_bundle_exists=os.path.isfile(ca_bundle) if ca_bundle else False
            )

            # Browser-Cookies nur setzen, wenn explizit gewünscht
            if cookies_from_browser:
                # Einfacher Modus: nur den Browsernamen übergeben ("chrome"/"edge"/...)
                # Für erweiterte Profile kann später auf Tuple erweitert werden
                self.ydl_opts['cookiesfrombrowser'] = cookies_from_browser
                self.logger.info("yt-dlp: Cookies aus Browser aktiviert", browser=cookies_from_browser)

            # Cookie-Datei für Headless/Server-Betrieb
            if cookies_file:
                self.ydl_opts['cookiefile'] = cookies_file
                self.logger.info("yt-dlp: Cookies-Datei aktiviert", cookiefile=cookies_file)

            # .netrc Unterstützung
            if use_netrc:
                self.ydl_opts['usenetrc'] = True
                self.logger.info("yt-dlp: NETRC aktiviert")

            # Direkter Benutzer/Passwort-Login (wenn gesetzt)
            if vimeo_username:
                self.ydl_opts['username'] = vimeo_username
            if vimeo_password:
                self.ydl_opts['password'] = vimeo_password
            if vimeo_username or vimeo_password:
                self.logger.info("yt-dlp: Username/Password Login konfiguriert", username=bool(vimeo_username), password=bool(vimeo_password))

            # CA-Bundle für yt-dlp: Setze Umgebungsvariable, die yt-dlp intern prüft
            # yt-dlp nutzt SSL_CERT_FILE/REQUESTS_CA_BUNDLE automatisch, wenn gesetzt
            # Zusätzlich: Falls PYTHONHTTPSVERIFY=0 gesetzt ist, wird TLS-Prüfung deaktiviert
            if ca_bundle and os.path.isfile(ca_bundle):
                # Stelle sicher, dass die Env-Variable auch für Subprozesse (yt-dlp) gesetzt ist
                os.environ['SSL_CERT_FILE'] = ca_bundle
                os.environ['REQUESTS_CA_BUNDLE'] = ca_bundle
                self.logger.info("yt-dlp: CA-Bundle in Umgebung gesetzt", ca_bundle=ca_bundle)
            
            # Windows-TLS-Workaround: SSL-Context-Patch wird bereits beim Modul-Import gemacht (Zeile 42-44)
            if os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
                self.logger.warning("SSL-Verifikation global deaktiviert (PYTHONHTTPSVERIFY=0) - nur für Debug!")
        except Exception as _e:
            # Niemals Initialisierung brechen – nur loggen
            self.logger.warning("yt-dlp Auth/Cookies Konfiguration konnte nicht angewendet werden", error=str(_e))
    
    def create_process_dir(self, identifier: str, use_temp: bool = True) -> Path:
        """
        Erstellt und gibt das Verarbeitungsverzeichnis für ein Video zurück.
        
        Args:
            identifier: Eindeutige Kennung des Videos (URL, ID, etc.)
            use_temp: Ob das temporäre Verzeichnis (temp_dir) oder das dauerhafte Cache-Verzeichnis (cache_dir) verwendet werden soll
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Basis-Verzeichnis je nach Verwendungszweck wählen
        base_dir = self.temp_dir if use_temp else self.cache_dir
        
        # Verzeichnis mit Unterordner "video" erstellen
        process_dir = base_dir / "video" / identifier
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir
        
    def _format_duration(self, seconds: int) -> str:
        """Formatiert Sekunden in ein lesbares Format (HH:MM:SS)."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _extract_vimeo_id(self, url: str) -> Optional[str]:
        """
        Extrahiert die Video-ID aus einer Vimeo-URL.
        
        Args:
            url: Vimeo-URL (player oder direkt)
            
        Returns:
            Video-ID oder None
        """
        patterns = [
            r'https?://player\.vimeo\.com/video/(\d+)',
            r'https?://vimeo\.com/(\d+)',
            r'https?://vimeo\.com/video/(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None
    
    def _normalize_vimeo_url(self, url: str) -> str:
        """
        Konvertiert Vimeo-Player-URLs in direkte Vimeo-URLs.
        
        Args:
            url: Die ursprüngliche URL
            
        Returns:
            str: Die normalisierte Vimeo-URL
        """
        # Vimeo-Player-URL-Muster
        player_pattern = r'https?://player\.vimeo\.com/video/(\d+)'
        match = re.match(player_pattern, url)
        
        if match:
            video_id = match.group(1)
            normalized_url = f"https://vimeo.com/{video_id}"
            self.logger.info(f"Vimeo-Player-URL normalisiert: {url} -> {normalized_url}")
            return normalized_url
        
        # Direkte Vimeo-URL bereits korrekt
        if 'vimeo.com' in url:
            return url
            
        return url
    
    def _get_vimeo_video_via_api(self, video_id: str) -> Optional[Tuple[str, int, str]]:
        """
        Holt Video-Informationen und Download-Link via Vimeo API (Fallback für yt-dlp).
        
        Args:
            video_id: Vimeo Video-ID
            
        Returns:
            Tuple (title, duration, download_url) oder None bei Fehler
        """
        access_token = os.getenv('VIMEO_ACCESS_TOKEN')
        if not access_token:
            self.logger.warning("VIMEO_ACCESS_TOKEN nicht gesetzt, kann API nicht nutzen")
            return None
        
        try:
            # Hole Video-Informationen
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/vnd.vimeo.*+json;version=3.4'
            }
            
            response = requests.get(
                f'https://api.vimeo.com/videos/{video_id}',
                headers=headers,
                timeout=30,
                verify=False if os.getenv('PYTHONHTTPSVERIFY') == '0' else True
            )
            response.raise_for_status()
            
            data = response.json()
            title = data.get('name', 'Unbekanntes Video')
            duration = data.get('duration', 0)
            
            # Debug: Logge verfügbare Felder UND play-Struktur
            play_data = data.get('play', {})
            self.logger.info(
                "Vimeo API Response erhalten",
                title=title,
                duration=duration,
                has_files=bool(data.get('files')),
                has_play=bool(play_data),
                play_keys=list(play_data.keys()) if play_data else [],
                has_download=bool(data.get('download')),
                privacy_view=data.get('privacy', {}).get('view', 'unknown')
            )
            
            # Hole Download-Links - zuerst files Feld
            files = data.get('files', [])
            audio_url = None
            
            if files:
                # Suche Audio-Datei oder kleinste Qualität in files
                for file_info in files:
                    quality = file_info.get('quality', '')
                    link = file_info.get('link')
                    
                    # Bevorzuge Audio-only oder niedrige Qualität
                    if 'audio' in quality.lower() or quality in ['hls', 'dash']:
                        audio_url = link
                        break
                    elif link and not audio_url:
                        audio_url = link  # Fallback: erster verfügbarer Link
            
            # Fallback: play.progressive (öffentliche Videos ohne Auth)
            if not audio_url:
                play_data = data.get('play', {})
                progressive = play_data.get('progressive', [])
                if progressive:
                    # Nimm niedrigste Qualität (kleinste Datei)
                    sorted_progressive = sorted(progressive, key=lambda x: x.get('width', 9999))
                    if sorted_progressive:
                        audio_url = sorted_progressive[0].get('link')
                        self.logger.info("Nutze progressive Play-Link (niedrige Qualität)")
                
                # Fallback: HLS-Stream
                if not audio_url:
                    hls_data = play_data.get('hls', {})
                    if hls_data and hls_data.get('link'):
                        audio_url = hls_data.get('link')
                        self.logger.info("Nutze HLS-Stream-Link")
            
            if not audio_url:
                self.logger.warning(f"Keine Download/Stream-Links für Vimeo {video_id} gefunden")
                return None
            
            self.logger.info(f"Vimeo API: Video-Info geholt", title=title, duration=duration)
            return title, duration, audio_url
            
        except Exception as e:
            self.logger.error(f"Vimeo API Fehler: {str(e)}", video_id=video_id)
            return None
    
    def _download_vimeo_via_api(self, video_id: str, working_dir: Path) -> Optional[Path]:
        """
        Lädt Vimeo-Video via API herunter und konvertiert zu MP3.
        
        Args:
            video_id: Vimeo Video-ID
            working_dir: Arbeitsverzeichnis für Downloads
            
        Returns:
            Path zur MP3-Datei oder None bei Fehler
        """
        api_result = self._get_vimeo_video_via_api(video_id)
        if not api_result:
            return None
        
        title, _duration, download_url = api_result
        
        try:
            # Lade Video-Datei herunter
            self.logger.info(f"Lade Video via Vimeo API: {title}")
            response = requests.get(
                download_url,
                stream=True,
                timeout=300,
                verify=False if os.getenv('PYTHONHTTPSVERIFY') == '0' else True
            )
            response.raise_for_status()
            
            # Speichere als temporäre Videodatei
            video_file = working_dir / f"{title[:50]}.mp4"
            with open(video_file, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            self.logger.info(f"Video heruntergeladen: {video_file.stat().st_size} bytes")
            
            # Konvertiere zu MP3 mit ffmpeg
            audio_file = working_dir / f"{title[:50]}.mp3"
            cmd = [
                'ffmpeg', '-i', str(video_file),
                '-vn', '-acodec', 'libmp3lame',
                '-q:a', '4', '-y', str(audio_file)
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=120)
            
            self.logger.info(f"Audio extrahiert: {audio_file}")
            
            # Lösche Video-Datei
            video_file.unlink()
            
            return audio_file
            
        except Exception as e:
            self.logger.error(f"Vimeo API Download fehlgeschlagen: {str(e)}")
            return None

    def _extract_video_info(self, url: str) -> Tuple[str, int, str]:
        """
        Extrahiert grundlegende Informationen aus einem Video.
        
        Args:
            url: URL des Videos
            
        Returns:
            Tuple mit (Titel, Dauer in Sekunden, Video-ID)
        """
        # URL normalisieren (besonders für Vimeo)
        normalized_url = self._normalize_vimeo_url(url)
        
        # Windows-TLS-Workaround: Bei PYTHONHTTPSVERIFY=0 nutze yt-dlp CLI statt Python-API
        # weil das CLI besser mit SSL-ENV-Variablen umgeht
        if os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
            try:
                # Finde yt-dlp im venv oder System-PATH
                import shutil
                yt_dlp_exe = shutil.which('yt-dlp')
                if not yt_dlp_exe:
                    # Versuche venv/Scripts/yt-dlp.exe
                    import sys
                    venv_ytdlp = Path(sys.executable).parent / 'yt-dlp.exe'
                    if venv_ytdlp.exists():
                        yt_dlp_exe = str(venv_ytdlp)
                
                if not yt_dlp_exe:
                    raise FileNotFoundError("yt-dlp CLI nicht im PATH gefunden")
                
                # Verwende yt-dlp CLI für Info-Extraktion
                cmd = [yt_dlp_exe, '--no-check-certificate', '--dump-json', '--no-playlist', normalized_url]
                cookies_file = os.getenv('YTDLP_COOKIES_FILE')
                if cookies_file and os.path.isfile(cookies_file):
                    cmd.extend(['--cookies', cookies_file])
                
                # Übergebe ENV-Variablen explizit an subprocess
                env = os.environ.copy()
                env['PYTHONHTTPSVERIFY'] = '0'
                if os.getenv('SSL_CERT_FILE'):
                    env['SSL_CERT_FILE'] = str(os.getenv('SSL_CERT_FILE'))
                
                result = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=30, env=env)
                info_json = json.loads(result.stdout)
                
                video_id = str(info_json.get('id', hashlib.md5(normalized_url.encode()).hexdigest()))
                title = str(info_json.get('title', 'Unbekanntes Video'))
                duration = int(info_json.get('duration', 0))
                
                self.logger.info("Video-Info via CLI extrahiert (TLS-Workaround)", title=title, duration=duration)
                return title, duration, video_id
            except subprocess.CalledProcessError as cli_error:
                self.logger.warning("CLI-Fallback fehlgeschlagen, versuche Python-API", 
                                  error=str(cli_error),
                                  stdout=cli_error.stdout[:500] if cli_error.stdout else None,
                                  stderr=cli_error.stderr[:500] if cli_error.stderr else None)
                # Fallback auf Python-API
            except FileNotFoundError as fnf_error:
                self.logger.warning("yt-dlp CLI nicht gefunden, versuche Python-API", error=str(fnf_error))
                # Fallback auf Python-API
            except Exception as cli_error:
                self.logger.warning("CLI-Fallback fehlgeschlagen (unexpected), versuche Python-API", error=str(cli_error))
                # Fallback auf Python-API
        
        # Vimeo-API-Fallback: Wenn es eine Vimeo-URL ist, versuche API
        vimeo_id = self._extract_vimeo_id(url)
        if vimeo_id and os.getenv('VIMEO_ACCESS_TOKEN'):
            try:
                api_result = self._get_vimeo_video_via_api(vimeo_id)
                if api_result:
                    title, duration, _download_url = api_result
                    self.logger.info("Vimeo API Fallback erfolgreich", title=title)
                    return title, duration, vimeo_id
            except Exception as api_error:
                self.logger.warning("Vimeo API Fallback fehlgeschlagen", error=str(api_error))
        
        # Standard-Pfad: Python-API
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info: YDLDict = ydl.extract_info(normalized_url, download=False)  # type: ignore
            if not info:
                raise ValueError("Keine Video-Informationen gefunden")
            
            video_id = str(info.get('id', hashlib.md5(normalized_url.encode()).hexdigest()))
            title = str(info.get('title', 'Unbekanntes Video'))
            duration = int(info.get('duration', 0))
            
            return title, duration, video_id

    def _create_cache_key(self, source: Union[str, VideoSource], target_language: str = 'de', template: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf der Video-Quelle, Zielsprache und Template.
        
        Args:
            source: Die Video-Quelle (URL oder VideoSource-Objekt)
            target_language: Die Zielsprache für die Verarbeitung
            template: Optionales Template für die Verarbeitung
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Schlüssel aus der Quelle erstellen
        base_key = ""
        
        # Bei VideoSource das URL-Attribut verwenden
        if isinstance(source, VideoSource):
            if source.url:
                base_key = source.url
            elif source.file_name:
                # Bei hochgeladenen Dateien einen erweiterten Schlüssel mit mehreren Attributen erstellen
                file_info = {
                    'name': source.file_name,
                    'size': source.file_size
                }
                # Serialisieren und hashen
                base_key = hashlib.md5(json.dumps(file_info, sort_keys=True).encode()).hexdigest()
            else:
                raise ValueError("VideoSource muss entweder URL oder file_name haben")
        else:
            # Bei String direkt als URL verwenden
            base_key = source
        
        # Zielsprache hinzufügen
        cache_key = f"{base_key}|lang={target_language}"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            cache_key += f"|template={template}"
            
        self.logger.debug(f"Cache-Schlüssel erstellt: {cache_key}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(cache_key)

    def serialize_for_cache(self, result: Union[VideoProcessingResult, VideoFramesResult]) -> Dict[str, Any]:
        """
        Serialisiert das VideoProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das VideoProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern, inkl. Typ-Kennzeichnung
        result_type = "video_frames" if isinstance(result, VideoFramesResult) else "video_processing"
        cache_data = {
            "result_type": result_type,
            "result": result.to_dict(),
            "source_url": result.metadata.source.url if result.metadata.source else None,
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten aus dem Result-Objekt extrahieren
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None)
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> VideoAnyResult:
        """
        Deserialisiert die Cache-Daten zurück in ein VideoProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            VideoProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        result_type = cached_data.get("result_type", "video_processing")
        if result_type == "video_frames":
            return VideoFramesResult.from_dict(result_data)
        return VideoProcessingResult.from_dict(result_data)

    def _create_cache_key_frames(
        self,
        source: Union[str, VideoSource],
        interval_seconds: int,
        width: Optional[int],
        height: Optional[int],
        image_format: str = "jpg"
    ) -> str:
        """Erstellt Cache-Key für Frame-Extraktion."""
        if isinstance(source, VideoSource):
            base_key = source.url or (source.file_name or "uploaded_file")
        else:
            base_key = source
        size_part = f"size={width}x{height}" if width or height else "size=orig"
        key_str = f"frames|{base_key}|interval={interval_seconds}|{size_part}|fmt={image_format}"
        return self.generate_cache_key(key_str)

    async def extract_frames(
        self,
        source: Union[str, VideoSource],
        interval_seconds: int = 5,
        width: Optional[int] = None,
        height: Optional[int] = None,
        image_format: str = "jpg",
        use_cache: bool = True,
        binary_data: Optional[bytes] = None
    ) -> VideoFramesResponse:
        """Extrahiert Frames in festem Intervall und speichert sie lokal."""
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        frames_dir: Path = working_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        temp_video_path: Optional[Path] = None
        title: str = ""
        duration: int = 0
        video_id: str = ""

        try:
            # Quelle normalisieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source = source

            cache_key = self._create_cache_key_frames(video_source,
                                                      interval_seconds, width, height, image_format)
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and isinstance(cached_result, VideoFramesResult):
                    return self.create_response(
                        processor_name="video",
                        result=cached_result,
                        request_info={
                            'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                            'interval_seconds': interval_seconds,
                            'width': width,
                            'height': height,
                            'format': image_format,
                            'use_cache': use_cache
                        },
                        response_class=VideoFramesResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # Video vorbereiten (vollständiges Video, nicht nur Audio)
            if video_source.url:
                normalized_url = self._normalize_vimeo_url(video_source.url)
                with yt_dlp.YoutubeDL({
                    'quiet': True,
                    'no_warnings': True,
                    'format': 'bestvideo+bestaudio/best',
                    'merge_output_format': 'mp4',
                    'outtmpl': str(working_dir / '%(title)s.%(ext)s'),
                    'retries': 10,
                    'socket_timeout': 30,
                    'nocheckcertificate': True,
                }) as ydl:
                    info: YDLDict = ydl.extract_info(normalized_url, download=True)  # type: ignore
                    if not info:
                        raise ValueError("Keine Video-Informationen gefunden")
                    video_id = str(info.get('id'))
                    title = str(info.get('title', 'video'))
                    duration = int(info.get('duration', 0))
                # Eingangsdatei finden
                candidates = list(working_dir.glob("*.mp4")) + list(working_dir.glob("*.mkv")) + list(working_dir.glob("*.webm"))
                if not candidates:
                    raise ValueError("Heruntergeladenes Video nicht gefunden")
                temp_video_path = candidates[0]
            else:
                # Upload-Fall
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "uploaded_video"
                if not video_source.file_name or not binary_data:
                    raise ValueError("Dateiname und Binärdaten erforderlich für Upload")
                temp_video_path = working_dir / video_source.file_name
                temp_video_path.write_bytes(binary_data)

            # ffmpeg-Filterkette aufbauen
            filters: List[str] = []
            # 1 Frame alle N Sekunden
            filters.append(f"fps=1/{max(1, int(interval_seconds))}")
            # Optional skalieren
            if width or height:
                w = width if width else -1
                h = height if height else -1
                filters.append(f"scale={w}:{h}:flags=lanczos")
            filter_str = ",".join(filters)

            # Ausgabeformat und Pfad
            image_ext = image_format.lower()
            if image_ext not in {"jpg", "jpeg", "png"}:
                image_ext = "jpg"
            output_pattern = frames_dir / f"frame_%06d.{image_ext}"

            # ffmpeg ausführen
            cmd = [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', str(temp_video_path),
                '-vf', filter_str,
                str(output_pattern)
            ]
            subprocess.run(cmd, check=True, capture_output=True, text=True)

            # erzeugte Dateien einsammeln
            files = sorted(frames_dir.glob(f"*.{image_ext}"))
            frames: List[FrameInfo] = []
            for idx, fpath in enumerate(files, start=0):
                frames.append(FrameInfo(
                    index=idx,
                    timestamp_s=float(idx * max(1, int(interval_seconds))),
                    file_path=str(fpath),
                    width=width,
                    height=height
                ))

            # Metadaten
            metadata = VideoMetadata(
                title=title or "",
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration if duration else 0),
                process_dir=str(working_dir),
                video_id=video_id
            )

            frames_result = VideoFramesResult(
                metadata=metadata,
                process_id=self.process_id,
                output_dir=str(frames_dir),
                interval_seconds=int(interval_seconds),
                frame_count=len(frames),
                frames=frames
            )

            # Optional cachen
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=frames_result)

            return self.create_response(
                processor_name="video",
                result=frames_result,
                request_info={
                    'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                    'interval_seconds': interval_seconds,
                    'width': width,
                    'height': height,
                    'format': image_format,
                    'use_cache': use_cache
                },
                response_class=VideoFramesResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error("Fehler bei der Frame-Extraktion",
                              error=e,
                              error_type=type(e).__name__)
            error_source = VideoSource()
            return self.create_response(
                processor_name="video",
                result=VideoFramesResult(
                    metadata=VideoMetadata(
                        title="Error",
                        source=error_source,
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    process_id=self.process_id,
                    output_dir=str(frames_dir),
                    interval_seconds=int(interval_seconds),
                    frame_count=0,
                    frames=[]
                ),
                request_info={
                    'source': str(source),
                    'interval_seconds': interval_seconds,
                    'width': width,
                    'height': height,
                    'format': image_format,
                    'use_cache': use_cache
                },
                response_class=VideoFramesResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_FRAME_EXTRACTION_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )
        finally:
            # temp video optional nicht löschen, da frames im selben Ordner liegen; hier keine zusätzliche Bereinigung
            pass

    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die Video-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Index für source_url
            if "source_url_1" not in index_info:
                collection.create_index([("source_url", 1)])
                self.logger.debug("source_url-Index erstellt")
            
            # Index für processed_at
            if "processed_at_1" not in index_info:
                collection.create_index([("processed_at", 1)])
                self.logger.debug("processed_at-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")

    async def process(
        self, 
        source: Union[str, VideoSource],
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None,
        use_cache: bool = True,
        binary_data: Optional[bytes] = None
    ) -> VideoResponse:
        """Verarbeitet ein Video."""
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        temp_video_path: Optional[Path] = None
        audio_path: Optional[Path] = None

        try:
            # Video-Quelle validieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source: VideoSource = source

            # Cache-Schlüssel generieren und prüfen
            cache_key = self._create_cache_key(source, target_language, template)
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Video: {cached_result.metadata.title}")
                    return self.create_response(
                        processor_name="video",
                        result=cached_result,
                        request_info={
                            'source': source.to_dict() if isinstance(source, VideoSource) and hasattr(source, 'to_dict') else str(source),
                            'source_language': source_language,
                            'target_language': target_language,
                            'template': template,
                            'use_cache': use_cache
                        },
                        response_class=VideoResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )

            # Video-Informationen extrahieren
            if video_source.url:
                # URL normalisieren (besonders für Vimeo)
                normalized_url = self._normalize_vimeo_url(video_source.url)
                title, duration, video_id = self._extract_video_info(normalized_url)
                
                # Video herunterladen - Vimeo API Fallback zuerst versuchen
                vimeo_id = self._extract_vimeo_id(normalized_url)
                download_success = False
                
                # Versuch 1: Vimeo API (wenn Token vorhanden und Vimeo-URL)
                if vimeo_id and os.getenv('VIMEO_ACCESS_TOKEN'):
                    api_audio = self._download_vimeo_via_api(vimeo_id, working_dir)
                    if api_audio and api_audio.exists():
                        audio_path = api_audio
                        download_success = True
                        self.logger.info("Video erfolgreich via Vimeo API heruntergeladen")
                
                # Versuch 2: yt-dlp CLI (bei PYTHONHTTPSVERIFY=0)
                if not download_success and os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
                    try:
                        self.logger.info(f"Versuche Download via CLI (TLS-Workaround): {normalized_url}")
                        
                        import shutil
                        import sys as _sys
                        yt_dlp_exe = shutil.which('yt-dlp')
                        if not yt_dlp_exe:
                            venv_ytdlp = Path(_sys.executable).parent / 'yt-dlp.exe'
                            if venv_ytdlp.exists():
                                yt_dlp_exe = str(venv_ytdlp)
                        
                        if yt_dlp_exe:
                            cmd = [
                                yt_dlp_exe, '--no-check-certificate',
                                '--extract-audio', '--audio-format', 'mp3',
                                '--output', str(working_dir / "%(title)s.%(ext)s"),
                                '--retries', '10',
                                '--socket-timeout', '30'
                            ]
                            cookies_file = os.getenv('YTDLP_COOKIES_FILE')
                            if cookies_file and os.path.isfile(cookies_file):
                                cmd.extend(['--cookies', cookies_file])
                            cmd.append(normalized_url)
                            
                            # Übergebe ENV-Variablen explizit
                            env = os.environ.copy()
                            env['PYTHONHTTPSVERIFY'] = '0'
                            
                            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300, env=env)
                            download_success = True
                            self.logger.info("Video erfolgreich via yt-dlp CLI heruntergeladen")
                    except Exception as cli_err:
                        self.logger.warning(f"CLI-Download fehlgeschlagen: {str(cli_err)}")
                
                # Versuch 3: yt-dlp Python API (Standard)
                if not download_success:
                    download_opts = self.ydl_opts.copy()
                    output_path = str(working_dir / "%(title)s.%(ext)s")
                    download_opts['outtmpl'] = output_path
                    
                    self.logger.info(f"Starte Download via yt-dlp Python-API: {normalized_url}")
                    with yt_dlp.YoutubeDL(download_opts) as ydl:
                        ydl.download([normalized_url])  # type: ignore
            else:
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "Hochgeladenes Video"
                duration = 0
                
                if not video_source.file_name or not binary_data:
                    raise ValueError("Dateiname und Binärdaten erforderlich für Upload")
                
                # Binärdaten speichern
                temp_video_path = working_dir / video_source.file_name
                temp_video_path.write_bytes(binary_data)

                # Zu MP3 konvertieren
                if not temp_video_path.suffix.lower() == '.mp3':
                    audio_path = temp_video_path.with_suffix('.mp3')
                    cmd = [
                        'ffmpeg', '-i', str(temp_video_path),
                        '-vn', '-acodec', 'libmp3lame',
                        '-q:a', '4', '-y', str(audio_path)
                    ]
                    subprocess.run(cmd, check=True, capture_output=True, text=True)

            # MP3-Datei finden wenn nicht schon gesetzt
            if not audio_path:
                mp3_files = list(working_dir.glob("*.mp3"))
                if not mp3_files:
                    raise ValueError("Keine MP3-Datei gefunden")
                audio_path = mp3_files[0]

            # Dauer prüfen
            if duration > self.max_duration:
                raise ValueError(f"Video zu lang: {duration} Sekunden (Maximum: {self.max_duration} Sekunden)")

            # Audio verarbeiten
            self.logger.info("Starte Audio-Verarbeitung")
            audio_response = await self.audio_processor.process(
                audio_source=str(audio_path),
                source_info={
                    'original_filename': title,
                    'video_id': video_id
                },
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache
            )

            # Erkannte Quellsprache aktualisieren
            if audio_response.data and audio_response.data.transcription:
                if source_language == 'auto':
                    source_language = audio_response.data.transcription.source_language

            # Metadaten erstellen
            metadata = VideoMetadata(
                title=title,
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration),
                file_size=audio_path.stat().st_size if audio_path else None,
                process_dir=str(working_dir),
                audio_file=str(audio_path) if audio_path else None
            )

            # Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=metadata,
                transcription=audio_response.data.transcription if audio_response.data else None,
                process_id=self.process_id
            )

            # Im Cache speichern
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=result)

            # Response erstellen
            return self.create_response(
                processor_name="video",
                result=result,
                request_info={
                    'source': video_source.to_dict() if hasattr(video_source, 'to_dict') else str(video_source),
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=VideoResponse,
                from_cache=False,
                cache_key=cache_key
            )

        except Exception as e:
            self.logger.error("Fehler bei der Video-Verarbeitung",
                            error=e,
                            error_type=type(e).__name__)

            # Erstelle eine standardmäßige VideoSource für den Fehlerfall
            error_source = VideoSource()
            
            # Einfache String-Repräsentation des Quellobjekts
            source_repr = str(source)

            return self.create_response(
                processor_name="video",
                result=VideoProcessingResult(
                    metadata=VideoMetadata(
                        title="Error",
                        source=error_source,
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    transcription=None,
                    process_id=self.process_id
                ),
                request_info={
                    'source': source_repr,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=VideoResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_PROCESSING_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )

        finally:
            # Aufräumen
            if temp_video_path and temp_video_path.exists():
                try:
                    temp_video_path.unlink()
                    self.logger.debug(f"Temporäre Videodatei gelöscht: {temp_video_path}")
                except Exception as cleanup_error:
                    self.logger.warning(f"Konnte temporäre Datei nicht löschen: {cleanup_error}") 