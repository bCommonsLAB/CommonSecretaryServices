"""
YouTube Processor für die Verarbeitung von YouTube-Videos.

LLM-Tracking Logik:
-----------------
Der YoutubeProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen in ProcessInfo:
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Hierarchisches Tracking über Sub-Prozessoren:
   a) AudioProcessor (Audio-Verarbeitung):
      - Eigene ProcessInfo
      - Wird in Haupt-ProcessInfo integriert

   b) TransformerProcessor (Template/Übersetzung):
      - Eigene ProcessInfo
      - Wird in Haupt-ProcessInfo integriert
"""

from pathlib import Path
from typing import Dict, Any, Optional, List, TypedDict, cast, NotRequired
from datetime import datetime
import time

import yt_dlp  # type: ignore

from src.core.config import Config
from src.core.models.base import ErrorInfo, ProcessInfo
from src.core.models.youtube import (
    YoutubeMetadata,
    YoutubeProcessingResult,
    YoutubeResponse
)
from src.core.exceptions import ProcessingError
from src.core.resource_tracking import ResourceCalculator
from src.processors.audio_processor import AudioProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.processors.cacheable_processor import CacheableProcessor

class YoutubeDLInfo(TypedDict, total=True):
    """Type helper für YouTube-DL Info Dictionary."""
    id: str
    title: str
    duration: int
    availability: NotRequired[str]
    categories: NotRequired[List[str]]
    description: NotRequired[str]
    tags: NotRequired[List[str]]
    thumbnail: NotRequired[str]
    upload_date: NotRequired[str]
    uploader: NotRequired[str]
    uploader_id: NotRequired[str]
    chapters: NotRequired[List[Dict[str, Any]]]
    view_count: NotRequired[int]
    like_count: NotRequired[int]
    dislike_count: NotRequired[int]
    average_rating: NotRequired[float]
    age_limit: NotRequired[int]
    webpage_url: NotRequired[str]
    language: NotRequired[str]

class YoutubeDLOpts(TypedDict, total=True):
    """Type helper für YouTube-DL Optionen."""
    quiet: bool
    no_warnings: bool
    extract_audio: bool
    format: str
    postprocessors: List[Dict[str, str]]
    http_headers: Dict[str, str]
    outtmpl: NotRequired[str]
    socket_timeout: int
    retries: int
    sleep_interval: int
    max_sleep_interval: int
    nocheckcertificate: bool
    extract_flat: NotRequired[bool]
    no_playlist: bool
    playlist_items: NotRequired[str]
    youtube_include_dash_manifest: bool
    cachedir: NotRequired[str]
    cookiefile: NotRequired[str]  # Optionales Feld für Cookie-Dateipfad

class ExtractOpts(TypedDict, total=True):
    """Type helper für minimale Extraktions-Optionen."""
    quiet: bool
    no_warnings: bool
    extract_flat: bool
    no_playlist: bool
    http_headers: Dict[str, str]
    socket_timeout: int
    retries: int
    sleep_interval: int
    nocheckcertificate: bool
    youtube_include_dash_manifest: bool

class YoutubeProcessor(CacheableProcessor[YoutubeProcessingResult]):
    """
    Prozessor für die Verarbeitung von YouTube-Videos.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der YoutubeProcessor erbt von CacheableProcessor, um MongoDB-Caching zu nutzen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "youtube_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, 
                 process_id: Optional[str] = None, 
                 parent_process_info: Optional[ProcessInfo] = None):
        """Initialisiert den YoutubeProcessor."""
        # Zeit für Gesamtinitialisierung starten
        init_start = time.time()
        
        # Superklasse-Initialisierung
        super().__init__(resource_calculator=resource_calculator, 
                        process_id=process_id, 
                        parent_process_info=parent_process_info)
        
        try:
            # Konfiguration laden
            config = Config()
            processor_config = config.get('processors', {})
            youtube_config = processor_config.get('youtube', {})
            
            # YouTube-spezifische Konfiguration
            self.max_duration = youtube_config.get('max_duration', 3600)  # 1 Stunde
            self.max_file_size = youtube_config.get('max_file_size', 125829120)  # 120 MB
            self.export_format = youtube_config.get('export_format', 'mp3')
            self.temp_file_suffix = f".{self.export_format}"
            
            # Sub-Prozessoren mit ProcessInfo initialisieren
            self.audio_processor = AudioProcessor(
                resource_calculator, 
                process_id,
                parent_process_info=self.process_info
            )
            
            self.transformer = TransformerProcessor(
                resource_calculator, 
                process_id,
                parent_process_info=self.process_info
            )
            
            # Download-Optionen
            self.ydl_opts: YoutubeDLOpts = {
                'quiet': True,
                'no_warnings': True,
                'extract_audio': True,
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': self.export_format,
                }],
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-us,en;q=0.5',
                    'Sec-Fetch-Mode': 'navigate'
                },
                'socket_timeout': 30,
                'retries': 10,
                'sleep_interval': 3,
                'max_sleep_interval': 10,
                'nocheckcertificate': True,
                'no_playlist': True,
                'youtube_include_dash_manifest': False
            }
            
            # Performance-Logging
            init_end = time.time()
            self.logger.info(f"Gesamte Initialisierungszeit: {(init_end - init_start) * 1000:.2f} ms")
            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des YoutubeProcessors",
                            error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def _extract_video_info(self, url: str) -> YoutubeDLInfo:
        """Extrahiert Informationen aus einem YouTube-Video.
        
        Args:
            url: URL des Videos
            
        Returns:
            YoutubeDLInfo: Die extrahierten Video-Informationen
            
        Raises:
            ProcessingError: Wenn die Extraktion fehlschlägt
        """
        try:
            extract_opts: ExtractOpts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'no_playlist': True,
                'http_headers': self.ydl_opts['http_headers'],
                'socket_timeout': self.ydl_opts['socket_timeout'],
                'retries': self.ydl_opts['retries'],
                'sleep_interval': self.ydl_opts['sleep_interval'],
                'nocheckcertificate': True,
                'youtube_include_dash_manifest': False
            }
            
            with yt_dlp.YoutubeDL(extract_opts) as ydl:
                info: YoutubeDLInfo = cast(YoutubeDLInfo, ydl.extract_info(url, download=False))  # type: ignore
                if not info:
                    raise ProcessingError("Keine Video-Informationen gefunden")
                return info
                
        except Exception as e:
            self.logger.error("Fehler beim Extrahieren der Video-Informationen", error=e)
            raise ProcessingError(
                f"Fehler beim Extrahieren der Video-Informationen: {str(e)}",
                details={"error_code": 'EXTRACTION_ERROR'}
            )

    def create_process_dir(self, video_id: str) -> Path:
        """Erstellt ein Verarbeitungsverzeichnis für ein Video.
        
        Args:
            video_id: ID des Videos
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        process_dir = self.temp_dir / video_id
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir

    def _format_duration(self, seconds: int) -> str:
        """Formatiert Sekunden in ein lesbares Format (HH:MM:SS).
        
        Args:
            seconds: Anzahl der Sekunden
            
        Returns:
            str: Formatierte Dauer
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _create_cache_key_from_id(self, video_id: str, target_language: str = 'de', template: Optional[str] = None) -> str:
        """Erstellt einen Cache-Schlüssel basierend auf der Video-ID.
        
        Args:
            video_id: ID des Videos
            target_language: Zielsprache für die Verarbeitung
            template: Optionales Template
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Schlüssel aus Video-ID
        base_key = video_id
        
        # Zielsprache hinzufügen
        base_key += f"|lang={target_language}"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            base_key += f"|template={template}"
            
        self.logger.debug(f"Cache-Schlüssel erstellt: {base_key}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(base_key)

    def serialize_for_cache(self, result: YoutubeProcessingResult) -> Dict[str, Any]:
        """Serialisiert das YoutubeProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das YoutubeProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "video_id": result.metadata.video_id,
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten aus dem Result-Objekt extrahieren
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None)
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> YoutubeProcessingResult:
        """Deserialisiert die Cache-Daten zurück in ein YoutubeProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            YoutubeProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        return YoutubeProcessingResult.from_dict(result_data)

    def _create_specialized_indexes(self, collection: Any) -> None:
        """Erstellt spezielle Indizes für die YouTube-Cache-Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        try:
            # Vorhandene Indizes abrufen
            index_info = collection.index_information()
            
            # Index für video_id
            if "video_id_1" not in index_info:
                collection.create_index([("video_id", 1)])
                self.logger.debug("video_id-Index erstellt")
            
            # Index für processed_at
            if "processed_at_1" not in index_info:
                collection.create_index([("processed_at", 1)])
                self.logger.debug("processed_at-Index erstellt")
                
        except Exception as e:
            self.logger.error(f"Fehler beim Erstellen spezialisierter Indizes: {str(e)}")

    def _extract_video_id_from_url(self, url: str) -> str:
        """
        Extrahiert die Video-ID direkt aus einer YouTube-URL.
        
        Args:
            url: Die YouTube-URL
            
        Returns:
            str: Die extrahierte Video-ID oder None, wenn keine gefunden wurde
            
        Hinweis: Diese Methode versucht verschiedene URL-Formate zu berücksichtigen:
        - Standard: https://www.youtube.com/watch?v=VIDEO_ID
        - Kurzform: https://youtu.be/VIDEO_ID
        - Mit Playlist: https://www.youtube.com/watch?v=VIDEO_ID&list=...
        """
        import re
        from urllib.parse import urlparse, parse_qs
        
        # YouTube URL-Muster
        youtube_patterns = [
            # Standard YouTube-URL
            r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})(?:&.+)?',
            # Kurz-URL (youtu.be)
            r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})(?:\?.+)?',
            # Eingebettete URL
            r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})(?:\?.+)?'
        ]
        
        # Versuche, das Muster anzuwenden
        for pattern in youtube_patterns:
            match = re.match(pattern, url)
            if match:
                self.logger.debug(f"Video-ID direkt aus URL extrahiert: {match.group(1)}")
                return match.group(1)
        
        # Fallback: Versuche, die ID über die URL-Parameter zu extrahieren
        parsed_url = urlparse(url)
        if parsed_url.netloc in ['youtube.com', 'www.youtube.com']:
            query_params = parse_qs(parsed_url.query)
            if 'v' in query_params:
                self.logger.debug(f"Video-ID aus URL-Parameter extrahiert: {query_params['v'][0]}")
                return query_params['v'][0]
        
        # Wenn keine ID gefunden wurde, Hash der URL verwenden
        self.logger.warning(f"Konnte keine Video-ID aus URL extrahieren: {url}")
        import hashlib
        return hashlib.md5(url.encode()).hexdigest()

    async def process(
        self, 
        url: str, 
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None,
        use_cache: bool = True,
        youtube_cookie: Optional[str] = None
    ) -> YoutubeResponse:
        """
        Verarbeitet ein YouTube-Video.
        Optional kann ein YouTube-Cookie als String (Inhalt einer cookies.txt) übergeben werden.
        Wird ein Cookie übergeben, wird es als temporäre Datei gespeichert und yt-dlp verwendet diese Datei für die Authentifizierung.
        Das Cookie hat KEINEN Einfluss auf den Cache-Key oder die Response-Metadaten.
        """
        try:
            # 1. Wenn Cache aktiviert, versuche direkt die Video-ID aus der URL zu extrahieren
            if use_cache and self.is_cache_enabled():
                video_id = self._extract_video_id_from_url(url)
                cache_key = self._create_cache_key_from_id(video_id, target_language, template)
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Video-ID: {video_id}")
                    return self.create_response(
                        processor_name="youtube",
                        result=cached_result,
                        request_info={
                            'url': url,
                            'source_language': source_language,
                            'target_language': target_language,
                            'template': template,
                            'use_cache': use_cache
                        },
                        response_class=YoutubeResponse,
                        from_cache=True,
                        cache_key=cache_key
                    )
            # 2. Kein Cache-Hit: Video-Informationen extrahieren
            info = self._extract_video_info(url)
            video_id = info['id']
            cache_key = self._create_cache_key_from_id(video_id, target_language, template)
            process_dir = self.create_process_dir(video_id)
            download_opts = self.ydl_opts.copy()
            output_path = str(process_dir / "%(title)s.%(ext)s")
            download_opts['outtmpl'] = output_path
            # Cookie-Handling: Wenn youtube_cookie gesetzt, speichere als Datei und setze Option
            # Das Cookie wird nur für den Download verwendet und beeinflusst NICHT den Cache-Key
            cookiefile_path = None
            if youtube_cookie:
                # Schreibe das Cookie als temporäre Datei für yt-dlp
                cookiefile_path = process_dir / "cookies.txt"
                with open(cookiefile_path, "w", encoding="utf-8") as f:
                    f.write(youtube_cookie)
                download_opts['cookiefile'] = str(cookiefile_path)
                self.logger.info(f"YouTube-Cookie für yt-dlp verwendet: {cookiefile_path}")
            with yt_dlp.YoutubeDL(download_opts) as ydl:
                ydl.download([url])  # type: ignore
            audio_files = list(process_dir.glob(f"*.{self.export_format}"))
            if not audio_files:
                raise ProcessingError("Keine Audio-Datei gefunden")
            audio_file = audio_files[0]
            metadata = YoutubeMetadata(
                title=info['title'],
                url=url,
                video_id=video_id,
                duration=info['duration'],
                duration_formatted=self._format_duration(info['duration']),
                file_size=audio_file.stat().st_size,
                process_dir=str(process_dir),
                audio_file=str(audio_file),
                availability=info.get('availability'),
                categories=info.get('categories', []),
                description=info.get('description'),
                tags=info.get('tags', []),
                thumbnail=info.get('thumbnail'),
                upload_date=info.get('upload_date'),
                uploader=info.get('uploader'),
                uploader_id=info.get('uploader_id'),
                chapters=info.get('chapters', []),
                view_count=info.get('view_count'),
                like_count=info.get('like_count'),
                dislike_count=info.get('dislike_count'),
                average_rating=info.get('average_rating'),
                age_limit=info.get('age_limit'),
                webpage_url=info.get('webpage_url')
            )
            self.logger.info("Starte Audio-Verarbeitung")
            audio_response = await self.audio_processor.process(
                audio_source=str(audio_file),
                source_info={
                    'original_filename': metadata.title,
                    'video_id': video_id
                },
                source_language=source_language,
                target_language=target_language,
                template=template,
                use_cache=use_cache
            )
            result = YoutubeProcessingResult(
                metadata=metadata,
                transcription=audio_response.data.transcription if audio_response.data else None,
                process_id=self.process_id,
                processed_at=datetime.now()
            )
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(cache_key=cache_key, result=result)
            return self.create_response(
                processor_name="youtube",
                result=result,
                request_info={
                    'url': url,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=YoutubeResponse,
                from_cache=False,
                cache_key=cache_key
            )
        except Exception as e:
            self.logger.error("Fehler bei der Video-Verarbeitung",
                            error=e,
                            error_type=type(e).__name__)
            return self.create_response(
                processor_name="youtube",
                result=YoutubeProcessingResult(
                    metadata=YoutubeMetadata(
                        title="Error",
                        url=url,
                        video_id="error",
                        duration=0,
                        duration_formatted="00:00:00"
                    ),
                    transcription=None,
                    process_id=self.process_id
                ),
                request_info={
                    'url': url,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=YoutubeResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_PROCESSING_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )