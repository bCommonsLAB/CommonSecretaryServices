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

import hashlib
import uuid
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Union, Tuple

import yt_dlp  # type: ignore

from src.utils.video_cache import CacheMetadata
from src.core.models.audio import AudioResponse
from src.core.config import Config
from src.core.models.base import (
    ProcessInfo, RequestInfo, ErrorInfo
)
from src.core.models.enums import ProcessingStatus, ProcessorType
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
from src.utils.video_cache import VideoCache

from .base_processor import BaseProcessor
from .transformer_processor import TransformerProcessor
from .audio_processor import AudioProcessor

# Typ-Alias für yt-dlp
YDLDict = Dict[str, Any]

class VideoProcessor(BaseProcessor):
    """
    Prozessor für die Verarbeitung von Video-Dateien.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    """
    
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
        self.max_duration = config.get('processors.video.max_duration', 3600)  # 1 Stunde
        
        # Initialisiere Prozessoren
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        self.transcriber = WhisperTranscriber({"process_id": process_id})
        self.audio_processor = AudioProcessor(resource_calculator, process_id)
        self.cache = VideoCache()
        
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
    
    def create_process_dir(self, identifier: str) -> Path:
        """Erstellt und gibt das Verarbeitungsverzeichnis für ein Video zurück."""
        process_dir = self.temp_dir / "video" / identifier
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
        return VideoResponse(
            request=RequestInfo(
                processor=ProcessorType.VIDEO.value,
                timestamp=datetime.now().isoformat(),
                parameters=request_info
            ),
            process=ProcessInfo(
                id=self.process_id,
                main_processor=ProcessorType.VIDEO.value,
                started=datetime.now().isoformat(),
                completed=datetime.now().isoformat(),
                llm_info=llm_info if llm_info.requests else None
            ),
            data=result,
            status=ProcessingStatus.ERROR if error else ProcessingStatus.SUCCESS,
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

    async def process(
        self, 
        source: Union[str, VideoSource],
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None
    ) -> VideoResponse:
        """
        Verarbeitet ein Video.
        
        Args:
            source: URL oder VideoSource-Objekt mit Video-Datei
            target_language: Zielsprache für die Transkription
            source_language: Quellsprache (auto für automatische Erkennung)
            template: Optional Template für die Verarbeitung
            
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
                
            # 2. Cache prüfen
            cache_result: Optional[Tuple[VideoProcessingResult, Path, CacheMetadata]] = self.cache.load(video_source, target_language, template)
            if cache_result:
                result, _, metadata = cache_result
                self.logger.info(f"Cache-Hit für Video: {result.metadata.title}")
                
                # Response aus Cache erstellen
                response = ResponseFactory.create_response(
                    processor_name=ProcessorType.VIDEO.value,
                    result=result,
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
                
            # 3. Video-Informationen extrahieren
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
            
            # 4. Arbeitsverzeichnis erstellen
            self.logger.info(f"Verarbeite Video: {title}", 
                           video_id=video_id,
                           duration=duration,
                           working_dir=str(working_dir))
            
            # 5. Video herunterladen oder Datei verarbeiten
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
            
            # 6. MP3-Datei finden
            mp3_files = list(working_dir.glob("*.mp3"))
            if not mp3_files:
                raise ValueError("Keine MP3-Datei nach Verarbeitung gefunden")
            audio_path = mp3_files[0]
            
            # 7. Audio verarbeiten
            self.logger.info("Starte Audio-Verarbeitung")
            audio_response: AudioResponse = await self.audio_processor.process(
                audio_source=str(audio_path),
                source_info={
                    'original_filename': title,
                    'video_id': video_id
                },
                source_language=source_language,
                target_language=target_language,
                template=template
            )
            
            # LLM-Requests aus Audio-Verarbeitung übernehmen
            if audio_response.process.llm_info:
                # Übernehme die LLM-Requests direkt
                llm_info.add_request(audio_response.process.llm_info.requests)
            
            # Erkannte Quellsprache aktualisieren
            if audio_response.data and audio_response.data.transcription:
                if source_language == 'auto':
                    source_language = audio_response.data.transcription.source_language
            
            # 8. Metadaten erstellen
            metadata = VideoMetadata(
                title=title,
                source=video_source,
                duration=duration,
                duration_formatted=self._format_duration(duration),
                file_size=audio_path.stat().st_size if audio_path else None,
                process_dir=str(working_dir),
                audio_file=str(audio_path) if audio_path else None
            )
            
            # 9. Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=metadata,
                transcription=audio_response.data.transcription if audio_response.data else None,
                process_id=self.process_id
            )
            
            # Nach erfolgreicher Verarbeitung im Cache speichern
            self.cache.save(result, video_source, target_language, template, audio_path)
            
            # Response erstellen
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
            
            # Erstelle ein Dummy-Result für den Fehlerfall
            dummy_result = VideoProcessingResult(
                metadata=VideoMetadata(
                    title="",
                    source=video_source,
                    duration=0,
                    duration_formatted="00:00:00",
                    process_dir=str(working_dir) if working_dir else ""
                ),
                transcription=None,
                process_id=self.process_id
            )
            
            # Error-Response mit ResponseFactory
            response = ResponseFactory.create_response(
                processor_name=ProcessorType.VIDEO.value,
                result=dummy_result,
                request_info={
                    'source': str(source),
                    'target_language': target_language,
                    'source_language': source_language,
                    'template': template
                },
                response_class=VideoResponse,
                error=error_info,
                llm_info=None  # Keine LLM-Info im Fehlerfall
            )
            return response 