"""
Youtube Processor für die Verarbeitung von Youtube-Videos.

LLM-Tracking Logik:
-----------------
Der YoutubeProcessor trackt die LLM-Nutzung auf zwei Ebenen:

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

import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, cast, TypedDict, List

import yt_dlp  # type: ignore

from core.models.audio import (
    AudioResponse, TranscriptionResult
)
from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.core.models.base import (
    ErrorInfo
)
from src.core.models.enums import ProcessingStatus
from src.core.models.llm import (
    LLMInfo
)
from src.core.models.youtube import YoutubeMetadata, YoutubeProcessingResult, YoutubeResponse
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.response_factory import ResponseFactory

from .base_processor import BaseProcessor
from .transformer_processor import TransformerProcessor
from .audio_processor import AudioProcessor

# Typ-Alias für YouTube Info Dictionary und YoutubeDL
class YoutubeDLInfo(TypedDict, total=False):
    """Type helper für YouTube-DL Info Dictionary."""
    duration: int
    title: str
    id: str
    availability: str
    categories: list[str]
    description: str
    tags: list[str]
    thumbnail: str
    upload_date: str
    uploader: str
    uploader_id: str
    chapters: list[Dict[str, Any]]
    view_count: int
    like_count: int
    dislike_count: int
    average_rating: float
    age_limit: int
    webpage_url: str
    language: str

YoutubeDLDict = Dict[str, Any]
YoutubeDL = Any  # type: ignore

class YoutubeDLOpts(TypedDict, total=False):
    """Type helper für YouTube-DL Optionen."""
    quiet: bool
    no_warnings: bool
    extract_audio: bool
    format: str
    postprocessors: list[dict[str, str]]
    http_headers: dict[str, str]
    outtmpl: str
    socket_timeout: int
    retries: int
    sleep_interval: int
    max_sleep_interval: int
    nocheckcertificate: bool
    extract_flat: bool
    no_playlist: bool
    playlist_items: str
    youtube_include_dash_manifest: bool
    cachedir: str

class ExtractOpts(TypedDict, total=False):
    """Type helper für minimale Extraktions-Optionen."""
    quiet: bool
    no_warnings: bool
    extract_flat: bool
    no_playlist: bool
    playlist_items: str
    http_headers: dict[str, str]
    socket_timeout: int
    retries: int
    sleep_interval: int
    nocheckcertificate: bool
    no_color: bool
    cachedir: str
    youtube_include_dash_manifest: bool

class YoutubeProcessor(BaseProcessor):
    """
    Prozessor für die Verarbeitung von YouTube-Videos.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    """
    
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration: Optional[float]
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        """
        Initialisiert den YoutubeProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Lade Konfiguration
        config = Config()
        self.max_duration = config.get('processors.youtube.max_duration', 3600)  # 1 Stunde
        
        # Zeitmessung
        self.start_time = None
        self.end_time = None
        self.duration = None
        
        # Basis-Optionen für yt-dlp
        self.ydl_opts: YoutubeDLOpts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }],
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            },
            'socket_timeout': 30,        # Erhöhe Timeout
            'retries': 10,               # Mehr Wiederholungsversuche
            'sleep_interval': 3,         # Warte zwischen Versuchen
            'max_sleep_interval': 10,
            'nocheckcertificate': True,  # Ignoriere SSL-Zertifikatsprüfungen
            'extract_flat': True,        # Flache Extraktion für bessere Kompatibilität
            'no_playlist': True,         # Keine Playlist-Verarbeitung
            'playlist_items': '1',       # Nur erstes Video wenn Teil einer Playlist
            'youtube_include_dash_manifest': True,  # DASH-Manifest einbeziehen
            'cachedir': str(self.temp_dir / 'yt-dlp-cache')  # Cache-Verzeichnis
        }
        
        # Initialisiere Prozessoren
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        self.transcriber = WhisperTranscriber({"process_id": process_id})
            
        # Erstelle Cache-Verzeichnis
        cache_dir = Path(self.ydl_opts['cachedir'])
        cache_dir.mkdir(parents=True, exist_ok=True)
        
    def _extract_video_id(self, url: str) -> str:
        """
        Extrahiert die Video-ID aus einer YouTube-URL.
        
        Args:
            url: Die YouTube-URL
            
        Returns:
            str: Die extrahierte Video-ID
            
        Raises:
            ProcessingError: Wenn die Video-ID nicht extrahiert werden kann
        """
        # Minimale Optionen für ID-Extraktion
        extract_opts: ExtractOpts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'no_playlist': True,
            'playlist_items': '1',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            },
            'socket_timeout': 60,
            'retries': 5,
            'sleep_interval': 5,
            'nocheckcertificate': True,
            'no_color': True
        }
        
        try:
            with yt_dlp.YoutubeDL(extract_opts) as ydl:  # type: ignore
                info: YoutubeDLDict = ydl.extract_info(url, download=False)  # type: ignore
                
                if not info:
                    raise ProcessingError(
                        "Keine Video-Informationen gefunden. "
                        "Bitte überprüfen Sie die URL und versuchen Sie es später erneut."
                    )
                    
                if 'id' not in info:
                    raise ProcessingError(
                        "Video-ID nicht gefunden. "
                        "Bitte stellen Sie sicher, dass die URL korrekt ist und das Video existiert."
                    )
                    
                video_id = cast(str, info['id'])
                self.logger.debug(f"Video-ID extrahiert: {video_id}")
                return video_id
                
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if "Private video" in error_msg:
                raise ProcessingError("Dieses Video ist privat und kann nicht verarbeitet werden.")
            elif "This video is unavailable" in error_msg:
                raise ProcessingError("Dieses Video ist nicht verfügbar.")
            elif "Video unavailable" in error_msg:
                raise ProcessingError("Das Video wurde möglicherweise gelöscht oder ist in Ihrem Land nicht verfügbar.")
            else:
                self.logger.error(
                    "YouTube Download Fehler",
                    error=e,
                    url=url,
                    error_details=error_msg
                )
                raise ProcessingError(
                    f"Fehler beim Zugriff auf das Video: {error_msg}. "
                    "Bitte versuchen Sie es später erneut."
                )
        except Exception as e:
            error_details = str(e)
            self.logger.error(
                "Unerwarteter Fehler bei der Video-ID Extraktion",
                error=e,
                url=url,
                error_type=type(e).__name__
            )
            raise ProcessingError(
                f"Unerwarteter Fehler bei der Verarbeitung der YouTube-URL: {error_details}. "
                "Bitte überprüfen Sie die URL und versuchen Sie es erneut."
            )
            
    def create_process_dir(self, video_id: str) -> Path:
        """Erstellt und gibt das Verarbeitungsverzeichnis für ein Video zurück."""
        process_dir = self.temp_dir / "youtube" / video_id
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir
        
    def _format_duration(self, seconds: int) -> str:
        """Formatiert Sekunden in ein lesbares Format (HH:MM:SS)."""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    async def process(
        self, 
        file_path: str, 
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None
    ) -> YoutubeResponse:
        """
        Verarbeitet ein YouTube-Video.
        
        Args:
            file_path: YouTube-URL
            target_language: Zielsprache für die Transkription
            source_language: Quellsprache (auto für automatische Erkennung)
            template: Optional Template für die Verarbeitung
            
        Returns:
            YoutubeResponse: Die standardisierte Response
        """
        llm_info: LLMInfo = LLMInfo(model="youtube-processing", purpose="youtube-processing")
        url: str = file_path
        working_dir = None
        video_info: Any = None
        
        try:
            self.start_time = datetime.now()
            self.logger.debug("Youtube Processing Start", 
                            target_language=target_language,
                            source_language=source_language,
                            template=template)

            # Extrahiere Video-ID und prüfe Cache
            video_id: str = self._extract_video_id(url)
            working_dir = self.create_process_dir(video_id)
            audio_path: Optional[Path] = None

            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:  # type: ignore
                # Video-Informationen abrufen
                self.logger.debug("Rufe Video-Informationen ab")
                video_info = cast(YoutubeDLInfo, ydl.extract_info(url, download=False))  # type: ignore
                
                if not video_info:
                    raise ProcessingError("Keine Video-Informationen gefunden")
                
                duration: int = int(video_info.get('duration', 0))
                # Extrahiere Sprache aus YouTube-Metadaten, Fallback auf 'de'
                
                self.logger.info("Video-Informationen erhalten",
                               title=video_info.get('title'),
                               duration=duration,
                               video_id=video_id)

                if duration > self.max_duration:
                    raise ProcessingError(
                        f"Video zu lang: {duration} Sekunden "
                        f"(Maximum: {self.max_duration} Sekunden)"
                    )

                # Prüfe ob bereits eine MP3-Datei existiert
                mp3_files: list[Path] = list(working_dir.glob("*.mp3"))
                if mp3_files:
                    self.logger.debug("Existierende MP3-Datei gefunden",
                                   audio_file=str(mp3_files[0]))
                    audio_path = mp3_files[0]
                else:
                    # Verwende die Basis-Optionen aus der Konfiguration
                    download_opts: YoutubeDLOpts = self.ydl_opts.copy()
                    
                    # Setze den Output-Template für das aktuelle Verzeichnis
                    output_path: str = str(working_dir / "%(title)s.%(ext)s")
                    download_opts.update({
                        'outtmpl': output_path,
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                        }]
                    })

                    # Video herunterladen und zu MP3 konvertieren
                    self.logger.debug("Starte Download und MP3-Konvertierung", 
                                    output_path=output_path,
                                    format=download_opts.get('format'))
                    
                    # Erstelle neuen YoutubeDL-Instance mit den aktualisierten Optionen
                    with yt_dlp.YoutubeDL(download_opts) as ydl_download:  # type: ignore
                        ydl_download.download([url])  # type: ignore
                    
                    # Nach der Konvertierung suchen wir die resultierende MP3-Datei
                    mp3_files = list(working_dir.glob("*.mp3"))
                    if not mp3_files:
                        raise ProcessingError("Keine MP3-Datei nach Download gefunden")
                    audio_path = mp3_files[0]
                    
                    self.logger.debug("MP3-Datei gefunden", audio_file=str(audio_path))

                # Erstelle die Metadaten
                metadata: YoutubeMetadata = YoutubeMetadata(
                    title=str(video_info.get('title', '')),
                    url=url,
                    video_id=video_id,
                    duration=duration,
                    duration_formatted=self._format_duration(duration),
                    file_size=audio_path.stat().st_size if audio_path else None,
                    process_dir=str(working_dir),
                    audio_file=str(audio_path) if audio_path else None,
                    availability=str(video_info.get('availability', '')),
                    categories=list(video_info.get('categories', [])),
                    description=str(video_info.get('description', '')),
                    tags=list(video_info.get('tags', [])),
                    thumbnail=str(video_info.get('thumbnail', '')),
                    upload_date=str(video_info.get('upload_date', '')),
                    uploader=str(video_info.get('uploader', '')),
                    uploader_id=str(video_info.get('uploader_id', '')),
                    chapters=list(video_info.get('chapters', [])),
                    view_count=int(video_info.get('view_count', 0)),
                    like_count=int(video_info.get('like_count', 0)),
                    dislike_count=int(video_info.get('dislike_count', 0)),
                    average_rating=float(video_info.get('average_rating', 0.0)) if video_info.get('average_rating') is not None else 0.0,
                    age_limit=int(video_info.get('age_limit', 0)),
                    webpage_url=str(video_info.get('webpage_url', ''))
                )

                # Verarbeite Audio mit AudioProcessor
                transcription_result: Optional[TranscriptionResult] = None
                if audio_path:
                    self.logger.debug("Starte Audio-Verarbeitung")
                    
                    # Konvertiere YouTube-Kapitel in das erwartete Format
                    chapters: List[Dict[str, Any]] = []
                    if video_info.get('chapters'):
                        for chapter in video_info.get('chapters', []):
                            chapters.append({
                                'title': chapter.get('title', ''),
                                'start_ms': int(chapter.get('start_time', 0) * 1000),  # Konvertiere zu Millisekunden
                                'end_ms': int(chapter.get('end_time', duration) * 1000)
                            })
                    
                    # Erstelle Audio-Processor
                    audio_processor = AudioProcessor(self.resource_calculator, self.process_id)
                    
                    # Verarbeite Audio mit Kapitelinformationen
                    audio_response: AudioResponse = await audio_processor.process(
                        audio_source=str(audio_path),
                        source_info={
                            'original_filename': metadata.title,
                            'video_id': video_id,
                            'uploader': metadata.uploader,
                            'description': metadata.description
                        },
                        chapters=chapters,
                        source_language=source_language,
                        target_language=target_language,
                        template='youtube'  # Verwende YouTube-Template
                    )
                    
                    if audio_response.data and audio_response.data.transcription:
                        if audio_response.data.transcription.source_language != source_language:
                            source_language = audio_response.data.transcription.source_language

                    # Prüfe auf Fehler in der AudioResponse
                    if audio_response.status == ProcessingStatus.ERROR:
                        error_info: ErrorInfo = audio_response.error or ErrorInfo(
                            code="AUDIO_PROCESSING_ERROR",
                            message="Fehler bei der Audio-Verarbeitung",
                            details={}
                        )
                        response = ResponseFactory.create_response(
                            processor_name="youtube",
                            result=YoutubeProcessingResult(
                                metadata=metadata,
                                transcription=None,
                                process_id=self.process_id
                            ),
                            request_info={
                                'url': url,
                                'source_language': source_language,
                                'target_language': target_language,
                                'template': 'youtube'
                            },
                            response_class=YoutubeResponse,
                            llm_info=llm_info,
                            error=error_info
                        )
                        return response
                    
                    # Extrahiere LLM-Requests aus der Audio-Response
                    if audio_response.process.llm_info:
                        # Übernehme die LLM-Requests direkt
                        llm_info.add_request(audio_response.process.llm_info.requests)
                    
                    # Konvertiere AudioResponse zu TranscriptionResult
                    if audio_response.data and audio_response.data.transcription:
                        transcription_result = TranscriptionResult(
                            text=audio_response.data.transcription.text,
                            source_language=audio_response.data.transcription.source_language,
                            segments=audio_response.data.transcription.segments,
                            requests=[],  # Leere Liste, da wir die Requests bereits im llm_info haben
                            llms=[]  # Leere Liste, da wir die LLMs bereits im llm_info haben
                        )

                # Erstelle das finale Ergebnis
                result: YoutubeProcessingResult = YoutubeProcessingResult(
                    metadata=metadata,
                    transcription=transcription_result,
                    process_id=self.process_id
                )

                # Erstelle die Response
                return ResponseFactory.create_response(
                    processor_name="youtube",
                    result=result,
                    request_info={
                        'url': url,
                        'source_language': source_language,
                        'target_language': target_language,
                        'template': 'youtube'
                    },
                    response_class=YoutubeResponse,
                    llm_info=llm_info
                )

        except Exception as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'stack_trace': traceback.format_exc(),
                'url': url,
                'process_dir': str(working_dir) if working_dir else None,
                'stage': ''
            }
            
            # Bestimme die Verarbeitungsstufe
            if 'video_info' not in locals():
                error_context['stage'] = 'video_info_extraction'
            elif 'audio_path' not in locals():
                error_context['stage'] = 'download'
            elif 'audio_transcription' not in locals():
                error_context['stage'] = 'transcription'
            else:
                error_context['stage'] = 'result_creation'
            
            # Füge zusätzliche Kontextinformationen hinzu
            if 'video_info' in locals() and video_info:
                error_context = {   
                    **error_context,
                    'video_title': str(video_info.get('title', '')),
                    'video_duration': int(video_info.get('duration', 0))
                }
            
            self.logger.error("Youtube-Verarbeitungsfehler", error=e, **error_context)
            
            # Erstelle Error-Response mit ResponseFactory
            error_info = ErrorInfo(
                code="YOUTUBE_PROCESSING_ERROR",
                message=str(e),
                details=error_context
            )
            
            return ResponseFactory.create_response(
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
                    'template': 'youtube'
                },
                response_class=YoutubeResponse,
                llm_info=llm_info,
                error=error_info
            ) 