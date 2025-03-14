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
import re  # Am Anfang der Datei

import yt_dlp  # type: ignore

from src.core.models.audio import (
    AudioResponse, TranscriptionResult, TranscriptionSegment
)
from src.core.config import Config
from src.core.exceptions import ProcessingError
from src.core.models.base import (
    ErrorInfo
)
from src.core.models.enums import ProcessingStatus, ProcessorType
from src.core.models.llm import (
    LLMInfo
)
from src.core.models.youtube import YoutubeMetadata, YoutubeProcessingResult, YoutubeResponse
from src.core.resource_tracking import ResourceCalculator
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.response_factory import ResponseFactory

from .cacheable_processor import CacheableProcessor
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

class YoutubeProcessor(CacheableProcessor[YoutubeProcessingResult]):
    """
    Prozessor für die Verarbeitung von YouTube-Videos.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der YoutubeProcessor erbt von CacheableProcessor, um MongoDB-Caching zu nutzen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "youtube_cache"
    
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
        import time
        init_start = time.time()
        
        # Zeit für Superklasse-Initialisierung messen
        super_init_start = time.time()
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        super_init_end = time.time()
        
        # Lade Konfiguration
        config_load_start = time.time()
        config = Config()
        processor_config = config.get('processors', {})
        youtube_config = processor_config.get('youtube', {})
        config_load_end = time.time()
        
        # YouTube-spezifische Konfigurationen
        self.max_duration = youtube_config.get('max_duration', 3600)  # 1 Stunde
        self.max_file_size = youtube_config.get('max_file_size', 140000000)  # 120 MB
        
        # Debug-Logging der YouTube-Konfiguration
        self.logger.debug("YoutubeProcessor initialisiert mit Konfiguration", 
                         max_duration=self.max_duration,
                         max_file_size=self.max_file_size,
                         temp_dir=str(self.temp_dir),
                         cache_dir=str(self.cache_dir))
        
        # Zeitmessung
        self.start_time = None
        self.end_time = None
        self.duration = None
        
        # Basis-Optionen für yt-dlp aus Konfiguration
        self.ydl_opts: YoutubeDLOpts = youtube_config.get('ydl_opts', {})
        
        # Ergänze Standard-Optionen, wenn nicht in der Konfiguration
        if not self.ydl_opts:
            self.ydl_opts = {
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
            }
        
        # Immer Cachedir-Verzeichnis setzen
        self.ydl_opts['cachedir'] = str(self.temp_dir / 'yt-dlp-cache')
        
        # Initialisiere Prozessoren
        processor_init_start = time.time()
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
        # Initialisiere den Transcriber mit YouTube-spezifischen Konfigurationen
        transcriber_config = {
            "process_id": process_id,
            "processor_name": "youtube",
            "cache_dir": str(self.cache_dir),  # Haupt-Cache-Verzeichnis
            "temp_dir": str(self.temp_dir),    # Temporäres Unterverzeichnis
            "debug_dir": str(self.temp_dir / "debug")
        }
        self.transcriber = WhisperTranscriber(transcriber_config)
        
        self.audio_processor = AudioProcessor(resource_calculator, process_id)
        processor_init_end = time.time()
            
        # Erstelle Cache-Verzeichnis
        cache_dir_start = time.time()
        cache_dir = Path(self.ydl_opts['cachedir'])
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_dir_end = time.time()
        
        init_end = time.time()
        
        # Log alle Zeitmessungen
        self.logger.info(f"Zeit für Super-Initialisierung: {(super_init_end - super_init_start) * 1000:.2f} ms")
        self.logger.info(f"Zeit für Konfiguration laden: {(config_load_end - config_load_start) * 1000:.2f} ms")
        self.logger.info(f"Zeit für Prozessor-Initialisierung: {(processor_init_end - processor_init_start) * 1000:.2f} ms")
        self.logger.info(f"Zeit für Cache-Verzeichnis Erstellung: {(cache_dir_end - cache_dir_start) * 1000:.2f} ms")
        self.logger.info(f"Gesamte Initialisierungszeit: {(init_end - init_start) * 1000:.2f} ms")
        
    def _extract_video_id_from_url(self, url: str) -> Optional[str]:
        """
        Extrahiert die Video-ID direkt aus einer YouTube-URL ohne API-Abfrage.
        
        Args:
            url: Die YouTube-URL
            
        Returns:
            Optional[str]: Die extrahierte Video-ID oder None, wenn keine ID gefunden wurde
        """
        # YouTube URL Muster
        patterns = [
            # Standard YouTube URLs
            r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/watch\?v=([a-zA-Z0-9_-]{11})',
            # Kurz-URLs
            r'(?:https?:\/\/)?(?:www\.)?youtu\.be\/([a-zA-Z0-9_-]{11})',
            # Embed URLs
            r'(?:https?:\/\/)?(?:www\.)?youtube\.com\/embed\/([a-zA-Z0-9_-]{11})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        
        return None

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
            'http_headers': self.ydl_opts.get('http_headers', {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            }),
            'socket_timeout': 60,
            'retries': 5,
            'sleep_interval': 5,
            'nocheckcertificate': True,
            'no_color': True,
            'cachedir': self.ydl_opts.get('cachedir', str(self.temp_dir / 'yt-dlp-cache'))
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
        """
        Erstellt und gibt das Verarbeitungsverzeichnis für ein Video zurück.
        
        Args:
            video_id: Die YouTube-Video-ID
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        process_dir = self.temp_dir / "youtube" / video_id
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir
        
    def _format_duration(self, seconds: int) -> str:
        """
        Formatiert Sekunden in ein lesbares Format (HH:MM:SS).
        
        Args:
            seconds: Die Dauer in Sekunden
            
        Returns:
            str: Formatierte Dauer im Format HH:MM:SS
        """
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        seconds = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _create_cache_key_from_id(self, video_id: str, target_language: str = 'de', template: Optional[str] = None) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf der Video-ID, Zielsprache und Template.
        
        Args:
            video_id: Die YouTube-Video-ID
            target_language: Die Zielsprache für die Verarbeitung
            template: Optionales Template für die Verarbeitung
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Schlüssel aus der Video-ID erstellen (statt URL)
        cache_key = f"youtube-id:{video_id}|lang={target_language}"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            cache_key += f"|template={template}"
            
        self.logger.debug(f"Cache-Schlüssel erstellt: {cache_key}")
        
        # Hash aus dem kombinierten Schlüssel erzeugen
        return self.generate_cache_key(cache_key)

    def serialize_for_cache(self, result: YoutubeProcessingResult) -> Dict[str, Any]:
        """
        Serialisiert das YoutubeProcessingResult für die Speicherung im Cache.
        
        Args:
            result: Das YoutubeProcessingResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern
        cache_data = {
            "result": result.to_dict(),
            "source_url": result.metadata.url if result.metadata else None,
            "processed_at": datetime.now().isoformat(),
            # Zusätzliche Metadaten für die Suche im Cache
            "video_id": result.metadata.video_id if result.metadata else None,
            "title": result.metadata.title if result.metadata else None
        }
        
        return cache_data

    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> YoutubeProcessingResult:
        """
        Deserialisiert die Cache-Daten zurück in ein YoutubeProcessingResult.
        
        Args:
            cached_data: Die gespeicherten Cache-Daten
            
        Returns:
            YoutubeProcessingResult: Das rekonstruierte Ergebnis
        """
        result_data = cached_data.get("result", {})
        
        # Erstelle YoutubeMetadata-Objekt und TranscriptionResult aus den Daten
        metadata_data = result_data.get("metadata", {})
        metadata = YoutubeMetadata(
            title=metadata_data.get("title", "Cached Video"),
            url=metadata_data.get("url", ""),
            video_id=metadata_data.get("video_id", ""),
            duration=metadata_data.get("duration", 0),
            duration_formatted=metadata_data.get("duration_formatted", "00:00:00"),
            file_size=metadata_data.get("file_size"),
            process_dir=metadata_data.get("process_dir"),
            audio_file=metadata_data.get("audio_file"),
            availability=metadata_data.get("availability"),
            categories=metadata_data.get("categories", []),
            description=metadata_data.get("description"),
            tags=metadata_data.get("tags", []),
            thumbnail=metadata_data.get("thumbnail"),
            upload_date=metadata_data.get("upload_date"),
            uploader=metadata_data.get("uploader"),
            uploader_id=metadata_data.get("uploader_id"),
            chapters=metadata_data.get("chapters", []),
            view_count=metadata_data.get("view_count"),
            like_count=metadata_data.get("like_count"),
            dislike_count=metadata_data.get("dislike_count"),
            average_rating=metadata_data.get("average_rating"),
            age_limit=metadata_data.get("age_limit"),
            webpage_url=metadata_data.get("webpage_url")
        )
        
        # Extrahiere Transkriptions-Daten
        transcription_data = result_data.get("transcription", {})
        
        # Extrahiere Segment-Daten
        segments = cast(List[TranscriptionSegment], [])
        for seg_data in transcription_data.get("segments", []):
            segments.append(TranscriptionSegment(
                text=seg_data.get("text", ""),
                segment_id=seg_data.get("segment_id", 0),
                start=seg_data.get("start", 0),
                end=seg_data.get("end", 0),
                title=seg_data.get("title", "")
            ))
        
        transcription = TranscriptionResult(
            text=transcription_data.get("text", ""),
            source_language=transcription_data.get("detected_language", "auto"),
            segments=segments,
            requests=[],
            llms=[]
        )
        
        return YoutubeProcessingResult(
            metadata=metadata,
            transcription=transcription,
            process_id=result_data.get("process_id")
        )

    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezielle Indizes für die YouTube-Cache-Collection.
        
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

    async def process(
        self, 
        file_path: str, 
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None,
        use_cache: bool = True
    ) -> YoutubeResponse:
        """
        Verarbeitet ein YouTube-Video.
        
        Args:
            file_path: YouTube-URL
            target_language: Zielsprache für die Transkription
            source_language: Quellsprache (auto für automatische Erkennung)
            template: Optional Template für die Verarbeitung
            use_cache: Ob der Cache verwendet werden soll (default: True)
            
        Returns:
            YoutubeResponse: Die standardisierte Response
        """
        import time
        process_method_start = time.time()
        self.logger.info(f"YouTube Processor process-Methode gestartet")

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

            # 1. Extrahiere Video-ID (schnell aus URL, falls möglich)
            extract_id_start = time.time()
            # Versuche zuerst, die ID aus der URL zu extrahieren (schnell)
            video_id: Optional[str] = self._extract_video_id_from_url(url)
            
            # Nur wenn die ID nicht aus der URL extrahiert werden konnte, API verwenden
            if not video_id:
                self.logger.debug("Konnte ID nicht aus URL extrahieren, verwende API")
                video_id = self._extract_video_id(url)
            else:
                self.logger.debug(f"Video-ID aus URL extrahiert: {video_id}")
                
            extract_id_end = time.time()
            self.logger.info(f"Zeit für Video-ID Extraktion: {(extract_id_end - extract_id_start) * 1000:.2f} ms")
            
            # 2. Generiere Cache-Schlüssel
            cache_key_start = time.time()
            cache_key: str = self._create_cache_key_from_id(video_id, target_language, template)
            cache_key_end = time.time()
            self.logger.info(f"Zeit für Cache-Key Generierung: {(cache_key_end - cache_key_start) * 1000:.2f} ms")
            
            # 3. Cache prüfen (wenn aktiviert)
            cache_check_start = time.time()
            cache_hit = False
            cached_result = None
            
            if use_cache and self.is_cache_enabled():
                # Versuche, aus dem MongoDB-Cache zu laden
                cache_hit, cached_result = self.get_from_cache(cache_key)
                
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Video: {cached_result.metadata.title}")
                    
                    # Response aus Cache erstellen
                    response_start = time.time()
                    response = ResponseFactory.create_response(
                        processor_name=ProcessorType.YOUTUBE.value,
                        result=cached_result,
                        request_info={
                            'url': url,
                            'target_language': target_language,
                            'source_language': source_language,
                            'template': template
                        },
                        response_class=YoutubeResponse,
                        llm_info=None,  # Keine LLM-Info bei Cache-Hit
                        from_cache=True
                    )
                    response_end = time.time()
                    self.logger.info(f"Zeit für Response-Erstellung aus Cache: {(response_end - response_start) * 1000:.2f} ms")
                    
                    process_method_end = time.time()
                    self.logger.info(f"Gesamte Processor-Zeit (Cache-Hit): {(process_method_end - process_method_start) * 1000:.2f} ms")
                    
                    return response
            cache_check_end = time.time()
            self.logger.info(f"Zeit für Cache-Prüfung: {(cache_check_end - cache_check_start) * 1000:.2f} ms")

            # Ab hier nur fortfahren, wenn kein Cache-Hit
            
            # 4. Erstelle Arbeitsverzeichnis
            dir_create_start = time.time()
            working_dir = self.create_process_dir(video_id)
            dir_create_end = time.time()
            self.logger.info(f"Zeit für Arbeitsverzeichniserstellung: {(dir_create_end - dir_create_start) * 1000:.2f} ms")
            
            audio_path: Optional[Path] = None

            # 5. Video-Informationen abrufen
            video_info_start = time.time()
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:  # type: ignore
                self.logger.debug("Rufe Video-Informationen ab")
                video_info = cast(YoutubeDLInfo, ydl.extract_info(url, download=False))  # type: ignore
                
                if not video_info:
                    raise ProcessingError("Keine Video-Informationen gefunden")
            video_info_end = time.time()
            self.logger.info(f"Zeit für Video-Info Abruf: {(video_info_end - video_info_start) * 1000:.2f} ms")
                
            duration: int = int(video_info.get('duration', 0))
                
            self.logger.info("Video-Informationen erhalten",
                           title=video_info.get('title'),
                           duration=duration,
                           video_id=video_id)

            # 6. Prüfe maximale Dauer
            if duration > self.max_duration:
                raise ProcessingError(
                    f"Video zu lang: {duration} Sekunden "
                    f"(Maximum: {self.max_duration} Sekunden)"
                )

            # 7. Prüfe ob bereits eine MP3-Datei existiert
            mp3_check_start = time.time()
            mp3_files: list[Path] = list(working_dir.glob("*.mp3"))
            if (mp3_files):
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

                # 8. Video herunterladen und zu MP3 konvertieren
                self.logger.debug("Starte Download und MP3-Konvertierung", 
                                output_path=output_path,
                                format=download_opts.get('format'))
                
                # Erstelle neuen YoutubeDL-Instance mit den aktualisierten Optionen
                download_start = time.time()
                with yt_dlp.YoutubeDL(download_opts) as ydl_download:  # type: ignore
                    ydl_download.download([url])  # type: ignore
                download_end = time.time()
                self.logger.info(f"Zeit für Video-Download und Konvertierung: {(download_end - download_start) * 1000:.2f} ms")
                
                # Nach der Konvertierung suchen wir die resultierende MP3-Datei
                mp3_files = list(working_dir.glob("*.mp3"))
                if not mp3_files:
                    raise ProcessingError("Keine MP3-Datei nach Download gefunden")
                audio_path = mp3_files[0]
                
                self.logger.debug("MP3-Datei gefunden", audio_file=str(audio_path))
            mp3_check_end = time.time()
            self.logger.info(f"Zeit für MP3-Prüfung/Verarbeitung: {(mp3_check_end - mp3_check_start) * 1000:.2f} ms")

            # 9. Erstelle die Metadaten
            metadata_start = time.time()
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
            metadata_end = time.time()
            self.logger.info(f"Zeit für Metadaten-Erstellung: {(metadata_end - metadata_start) * 1000:.2f} ms")

            # 10. Verarbeite Audio mit AudioProcessor
            transcription_result: Optional[TranscriptionResult] = None
            if audio_path:
                self.logger.debug("Starte Audio-Verarbeitung")
                
                # Konvertiere YouTube-Kapitel in das erwartete Format
                chapters_start = time.time()
                chapters: List[Dict[str, Any]] = []
                if video_info.get('chapters'):
                    for chapter in video_info.get('chapters', []):
                        chapters.append({
                            'title': chapter.get('title', ''),
                            'start_ms': int(chapter.get('start_time', 0) * 1000),  # Konvertiere zu Millisekunden
                            'end_ms': int(chapter.get('end_time', duration) * 1000)
                        })
                chapters_end = time.time()
                self.logger.info(f"Zeit für Kapitel-Konvertierung: {(chapters_end - chapters_start) * 1000:.2f} ms")
                
                # Erstelle Audio-Processor
                audio_proc_start = time.time()
                audio_processor = AudioProcessor(self.resource_calculator, self.process_id)
                audio_proc_end = time.time()
                self.logger.info(f"Zeit für Audio-Processor Erstellung: {(audio_proc_end - audio_proc_start) * 1000:.2f} ms")
                
                # Verarbeite Audio mit Kapitelinformationen
                audio_process_start = time.time()
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
                    template=template
                )
                audio_process_end = time.time()
                self.logger.info(f"Zeit für Audio-Verarbeitung: {(audio_process_end - audio_process_start) * 1000:.2f} ms")
                
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
                    response: YoutubeResponse = ResponseFactory.create_response(
                        processor_name=ProcessorType.YOUTUBE.value,
                        result=YoutubeProcessingResult(
                            metadata=metadata,
                            transcription=None,
                            process_id=self.process_id
                        ),
                        request_info={
                            'url': url,
                            'source_language': source_language,
                            'target_language': target_language,
                            'template': template
                        },
                        response_class=YoutubeResponse,
                        llm_info=llm_info,
                        error=error_info,
                        from_cache=False
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

            # 11. Erstelle das finale Ergebnis
            result_creation_start = time.time()
            result: YoutubeProcessingResult = YoutubeProcessingResult(
                metadata=metadata,
                transcription=transcription_result,
                process_id=self.process_id
            )
            result_creation_end = time.time()
            self.logger.info(f"Zeit für Ergebnis-Erstellung: {(result_creation_end - result_creation_start) * 1000:.2f} ms")
            
            # 12. Im MongoDB-Cache speichern (wenn aktiviert)
            cache_save_start = time.time()
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(
                    cache_key=cache_key,
                    result=result
                )
                self.logger.debug(f"Youtube-Ergebnis im MongoDB-Cache gespeichert: {cache_key}")
            cache_save_end = time.time()
            self.logger.info(f"Zeit für Cache-Speicherung: {(cache_save_end - cache_save_start) * 1000:.2f} ms")

            # 13. Erstelle die Response
            response_creation_start = time.time()
            response = ResponseFactory.create_response(
                processor_name=ProcessorType.YOUTUBE.value,
                result=result,
                request_info={
                    'url': url,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template
                },
                response_class=YoutubeResponse,
                llm_info=llm_info if llm_info.requests else None,
                from_cache=False
            )
            response_creation_end = time.time()
            self.logger.info(f"Zeit für Response-Erstellung: {(response_creation_end - response_creation_start) * 1000:.2f} ms")
            
            process_method_end = time.time()
            self.logger.info(f"Gesamte Processor-Zeit (ohne Cache): {(process_method_end - process_method_start) * 1000:.2f} ms")
            
            return response

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
                processor_name=ProcessorType.YOUTUBE.value,
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
                    'template': template
                },
                response_class=YoutubeResponse,
                llm_info=llm_info,
                error=error_info,
                from_cache=False
            )