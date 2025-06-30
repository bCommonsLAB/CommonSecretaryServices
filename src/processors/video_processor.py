"""
Video Processor für die Verarbeitung von Video-Dateien.

LLM-Tracking Logik:
-----------------
Der VideoProcessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
   a) Transkription (Whisper API):
      - Model: whisper-1
      - Purpose: transcription
      - Pro Audio-Segment ein Request

   b) Template-Transformation (wenn Template verwendet):
      - Model: gpt-4
      - Purpose: template_transform
      - Requests vom TransformerProcessor

   c) Übersetzung (wenn Zielsprache != Quellsprache):
      - Model: gpt-4
      - Purpose: translation
      - Requests vom TransformerProcessor
"""

from pathlib import Path
from typing import Dict, Any, Optional, Union, Tuple
from datetime import datetime
import uuid
import hashlib
import subprocess  # Importiere subprocess für die FFmpeg-Integration
import json

import yt_dlp  # type: ignore

from src.core.config import Config
from src.core.models.base import ErrorInfo
from src.core.models.video import (
    VideoSource,
    VideoMetadata,
    VideoProcessingResult,
    VideoResponse
)
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.base import ProcessInfo
from .cacheable_processor import CacheableProcessor
from .transformer_processor import TransformerProcessor
from .audio_processor import AudioProcessor

# Typ-Alias für yt-dlp
YDLDict = Dict[str, Any]

class VideoProcessor(CacheableProcessor[VideoProcessingResult]):
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

    def _normalize_vimeo_url(self, url: str) -> str:
        """
        Konvertiert Vimeo-Player-URLs in direkte Vimeo-URLs.
        
        Args:
            url: Die ursprüngliche URL
            
        Returns:
            str: Die normalisierte Vimeo-URL
        """
        import re
        
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

    def serialize_for_cache(self, result: VideoProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das VideoProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das VideoProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "source_url": result.metadata.source.url if result.metadata.source else None,
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten aus dem Result-Objekt extrahieren
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None)
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> VideoProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein VideoProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            VideoProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        return VideoProcessingResult.from_dict(result_data)

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
                
                # Video herunterladen
                download_opts = self.ydl_opts.copy()
                output_path = str(working_dir / "%(title)s.%(ext)s")
                download_opts['outtmpl'] = output_path
                
                self.logger.info(f"Starte Download von: {normalized_url}")
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