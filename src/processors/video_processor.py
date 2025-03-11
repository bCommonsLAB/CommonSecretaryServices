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
import traceback

import yt_dlp  # type: ignore

from src.core.models.audio import AudioResponse
from src.core.config import Config
from src.core.models.base import ErrorInfo
from src.core.models.enums import ProcessorType
from src.core.models.llm import LLMInfo
from src.core.models.video import (
    VideoSource,
    VideoMetadata,
    VideoProcessingResult,
    VideoResponse
)
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.response_factory import ResponseFactory

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
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        """
        Initialisiert den VideoProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
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
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
        # Initialisiere den Transcriber mit Video-spezifischen Konfigurationen
        transcriber_config = {
            "process_id": process_id,
            "processor_name": "video",
            "cache_dir": str(self.cache_dir),  # Haupt-Cache-Verzeichnis
            "temp_dir": str(self.temp_dir),    # Temporäres Unterverzeichnis
            "debug_dir": str(self.temp_dir / "debug")
        }
        self.transcriber = WhisperTranscriber(transcriber_config)
        
        self.audio_processor = AudioProcessor(resource_calculator, process_id)
        
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
            }
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

    def _create_response(
        self,
        result: VideoProcessingResult,
        request_info: Dict[str, Any],
        llm_info: LLMInfo,
        error: Optional[ErrorInfo] = None
    ) -> VideoResponse:
        """
        Erstellt die standardisierte Response.
        
        Args:
            result: Das Video-Verarbeitungsergebnis
            request_info: Die Request-Parameter
            llm_info: Die gesammelten LLM-Informationen
            error: Optionale Fehlerinformationen
            
        Returns:
            VideoResponse: Die standardisierte Response
        """
        return ResponseFactory.create_response(
            processor_name=ProcessorType.VIDEO.value,
            result=result,
            request_info=request_info,
            response_class=VideoResponse,
            llm_info=llm_info if llm_info.requests else None,
            error=error
        )

    def _extract_video_info(self, url: str) -> Tuple[str, int, str]:
        """
        Extrahiert grundlegende Informationen aus einem Video.
        
        Args:
            url: URL des Videos
            
        Returns:
            Tuple mit (Titel, Dauer in Sekunden, Video-ID)
        """
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info: YDLDict = ydl.extract_info(url, download=False)  # type: ignore
            if not info:
                raise ValueError("Keine Video-Informationen gefunden")
            
            video_id = str(info.get('id', hashlib.md5(url.encode()).hexdigest()))
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
                # Bei hochgeladenen Dateien Hash aus Dateiinhalt erzeugen
                base_key = source.file_name
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
        # Stelle sicher, dass is_from_cache auf True gesetzt ist
        if "is_from_cache" not in result_data:
            result_data["is_from_cache"] = True
        else:
            result_data["is_from_cache"] = True
            
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
        use_cache: bool = True
    ) -> VideoResponse:
        """
        Verarbeitet ein Video.
        
        Args:
            source: URL oder VideoSource-Objekt mit Video-Datei
            target_language: Zielsprache für die Transkription
            source_language: Quellsprache (auto für automatische Erkennung)
            template: Optional Template für die Verarbeitung
            use_cache: Ob der Cache verwendet werden soll (default: True)
            
        Returns:
            VideoResponse: Die standardisierte Response mit Transkription und Metadaten
        """
        # Initialisiere Variablen
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        audio_path: Optional[Path] = None
        
        # Initialisiere LLM-Info
        llm_info = LLMInfo(
            model="video-processing",
            purpose="video-processing"
        )
        
        try:
            # 1. Quelle validieren und Video-ID generieren
            if isinstance(source, str):
                video_source = VideoSource(url=source)
            else:
                video_source: VideoSource = source

            # 2. Generiere Cache-Schlüssel
            cache_key: str = self._create_cache_key(source, target_language, template)
            
            # 3. Cache prüfen (wenn aktiviert)
            if use_cache and self.is_cache_enabled():
                # Versuche, aus dem MongoDB-Cache zu laden
                cache_hit, cached_result = self.get_from_cache(cache_key)
                
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Video: {cached_result.metadata.title}")
                    
                    # Stelle sicher, dass is_from_cache auf True gesetzt ist
                    cached_result.is_from_cache = True
                    
                    # Response aus Cache erstellen
                    response = ResponseFactory.create_response(
                        processor_name=ProcessorType.VIDEO.value,
                        result=cached_result,
                        request_info={
                            'source': str(source),
                            'target_language': target_language,
                            'source_language': source_language,
                            'template': template
                        },
                        response_class=VideoResponse,
                        llm_info=None  # Keine LLM-Info bei Cache-Hit
                    )
                    return response
                
            # 4. Video-Informationen extrahieren
            if video_source.url:
                title, duration, video_id = self._extract_video_info(video_source.url)
            else:
                # Bei File-Upload
                video_id = hashlib.md5(str(uuid.uuid4()).encode()).hexdigest()
                title = video_source.file_name or "Hochgeladenes Video"
                duration = 0  # Wird später aktualisiert
            
            # Prüfe Dauer
            if duration > self.max_duration:
                raise ValueError(
                    f"Video zu lang: {duration} Sekunden "
                    f"(Maximum: {self.max_duration} Sekunden)"
                )
            
            # 5. Arbeitsverzeichnis erstellen
            self.logger.info(f"Verarbeite Video: {title}", 
                           video_id=video_id,
                           duration=duration,
                           working_dir=str(working_dir))
            
            # 6. Video herunterladen oder Datei verarbeiten
            if video_source.url:
                # Download-Optionen aktualisieren
                download_opts = self.ydl_opts.copy()
                output_path = str(working_dir / "%(title)s.%(ext)s")
                download_opts['outtmpl'] = output_path
                
                # Video herunterladen
                self.logger.debug("Starte Download", url=video_source.url)
                with yt_dlp.YoutubeDL(download_opts) as ydl:
                    ydl.download([video_source.url])  # type: ignore
            else:
                # Datei in Arbeitsverzeichnis speichern
                if not video_source.file_name:
                    raise ValueError("Dateiname fehlt für Upload")
                    
                file_path = working_dir / video_source.file_name
                if isinstance(video_source.file, bytes):
                    file_path.write_bytes(video_source.file)
                elif isinstance(video_source.file, Path):
                    file_path.write_bytes(video_source.file.read_bytes())
                else:
                    raise ValueError("Ungültiger Dateityp")
            
            # 7. MP3-Datei finden
            mp3_files = list(working_dir.glob("*.mp3"))
            if not mp3_files:
                raise ValueError("Keine MP3-Datei nach Verarbeitung gefunden")
            audio_path = mp3_files[0]
            
            # 8. Audio verarbeiten
            self.logger.info("Starte Audio-Verarbeitung")
            audio_response: AudioResponse = await self.audio_processor.process(
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
            
            # LLM-Requests aus Audio-Verarbeitung übernehmen
            if audio_response.process.llm_info:
                # Übernehme die LLM-Requests direkt
                llm_info.add_request(audio_response.process.llm_info.requests)
            
            # Erkannte Quellsprache aktualisieren
            if audio_response.data and audio_response.data.transcription:
                if source_language == 'auto':
                    source_language = audio_response.data.transcription.source_language
            
            # 9. Metadaten erstellen
            metadata = VideoMetadata(
                title=title,
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration),
                file_size=audio_path.stat().st_size if audio_path else None,
                process_dir=str(working_dir),
                audio_file=str(audio_path) if audio_path else None
            )
            
            # 10. Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=metadata,
                transcription=audio_response.data.transcription if audio_response.data else None,
                process_id=self.process_id
            )
            
            # 11. Im MongoDB-Cache speichern (wenn aktiviert)
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(
                    cache_key=cache_key,
                    result=result
                )
                self.logger.debug(f"Video-Ergebnis im MongoDB-Cache gespeichert: {cache_key}")
            
            # 12. Response erstellen
            self.logger.info(f"Verarbeitung abgeschlossen - Requests: {llm_info.requests_count}, Tokens: {llm_info.total_tokens}")
            
            response: VideoResponse = ResponseFactory.create_response(
                processor_name=ProcessorType.VIDEO.value,
                result=result,
                request_info={
                    'source': str(source),
                    'target_language': target_language,
                    'source_language': source_language,
                    'template': template
                },
                response_class=VideoResponse,
                llm_info=llm_info if llm_info.requests else None
            )
            return response

        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            self.logger.error(f"Fehler bei der Verarbeitung: {str(e)}")
            
            # Erstelle ein gültiges VideoSource Objekt
            video_source = VideoSource(url=str(source)) if isinstance(source, str) else source
            
            # Leeres Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=VideoMetadata(
                    title="Fehlgeschlagene Verarbeitung",
                    source=video_source,
                    duration=0,
                    duration_formatted="00:00:00"
                ),
                process_id=self.process_id
            )
            
            # Fehler-Response erstellen
            response = self._create_response(
                result=result,
                request_info={
                    'source': str(source),
                    'target_language': target_language,
                    'source_language': source_language,
                    'template': template
                },
                llm_info=llm_info,
                error=error_info
            )
            return response 