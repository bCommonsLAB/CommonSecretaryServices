import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union
import yt_dlp
import time
import tempfile
from pydub import AudioSegment
import traceback

from .base_processor import BaseProcessor
from .audio_processor import AudioProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger, track_performance
from src.utils.transcription_utils import WhisperTranscriber
from src.core.config import Config
from src.core.config_keys import ConfigKeys

class YoutubeProcessor(BaseProcessor):
    """Youtube Processor für die Verarbeitung von Youtube-Videos.
    
    Diese Klasse lädt Videos von Youtube herunter, extrahiert die Audio-Spur
    und führt optional eine Transkription durch.
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        max_file_size (int): Maximale Dateigröße in Bytes (Default: 100MB)
        max_duration (int): Maximale Video-Länge in Sekunden (Default: 3600)
        temp_dir (Path): Verzeichnis für temporäre Verarbeitung
        audio_cache_dir (Path): Verzeichnis für Audio-Cache
        ydl_opts (dict): Optionen für youtube-dl
        output_template (str): Template für Output-Dateien
    """
    def __init__(self, resource_calculator):
        # Basis-Klasse zuerst initialisieren
        super().__init__(resource_calculator)
        
        # Konfiguration aus Config laden
        config = Config()
        processors_config = config.get('processors', {})
        youtube_config = processors_config.get('youtube', {})
        
        # Konfigurationswerte mit Validierung laden
        self.max_file_size = youtube_config.get('max_file_size', 104857600)  # Default: 100MB
        self.max_duration = youtube_config.get('max_duration')
        
        # Validierung der erforderlichen Konfigurationswerte
        if not self.max_duration:
            raise ValueError("max_duration muss in der Konfiguration angegeben werden")
        
        # Weitere Konfigurationswerte laden
        self.logger = get_logger(process_id=self.process_id, processor_name="YoutubeProcessor")
        self.temp_dir = Path(youtube_config.get('temp_dir', "temp-processing/video"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.audio_processor = AudioProcessor(resource_calculator)
        self.ydl_opts = youtube_config.get('ydl_opts', {})

    def create_process_dir(self) -> Path:
        """Erstellt ein eindeutiges Verarbeitungsverzeichnis."""
        process_dir = self.temp_dir / self.process_id
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir

    def _extract_video_id(self, url: str) -> str:
        """Extrahiert die Youtube Video-ID aus der URL."""
        import re
        # Unterstützt verschiedene Youtube URL-Formate
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu.be\/|youtube.com\/embed\/)([^&\n?]+)',
            r'youtube.com\/shorts\/([^&\n?]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ValueError(f"Konnte keine Youtube Video-ID aus der URL extrahieren: {url}")

    def _get_cached_audio_path(self, video_id: str) -> Path:
        """Gibt den Pfad zur zwischengespeicherten Audio-Datei zurück."""
        process_dir = self.create_process_dir()
        return process_dir / f"{video_id}.mp3"

    def _check_cached_audio(self, video_id: str) -> Path:
        """Prüft, ob eine Audio-Datei im Cache existiert."""
        cached_path = self._get_cached_audio_path(video_id)
        return cached_path if cached_path.exists() else None

    def _format_duration(self, seconds: int) -> str:
        """
        Formatiert die Dauer von Sekunden in ein lesbares Format (MM:SS).
        
        Args:
            seconds (int): Dauer in Sekunden
            
        Returns:
            str: Formatierte Dauer im Format MM:SS
        """
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return f"{minutes}:{remaining_seconds:02d}"

    @track_performance("youtube_processing")
    async def process(self, file_path: str, target_language: str = 'de', extract_audio: bool = True, template: str = 'Youtube') -> Dict[str, Any]:
        """
        Verarbeitet ein Youtube-Video.
        
        Args:
            file_path (str): Die URL des zu verarbeitenden Youtube-Videos
            target_language (str): Die Zielsprache für die Transkription (ISO 639-1 code)
            extract_audio (bool): Ob Audio extrahiert werden soll
            template (str): Name der zu verwendenden Vorlage
            
        Returns:
            Dict[str, Any]: Ein Dictionary mit den Verarbeitungsergebnissen
        """
        url = file_path  # file_path ist in diesem Fall die URL
        try:
            process_dir = self.create_process_dir()
            self.logger.debug("Youtube Processing Start", 
                            target_language=target_language,
                            extract_audio=extract_audio,
                            template=template)

            # Extrahiere Video-ID und prüfe Cache
            video_id = self._extract_video_id(url)
            audio_path = None

            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                # Video-Informationen abrufen
                self.logger.debug("Rufe Video-Informationen ab")
                info = ydl.extract_info(url, download=False)
                
                self.logger.info("Video-Informationen erhalten",
                               title=info.get('title'),
                               duration=info.get('duration'),
                               video_id=video_id)

                if info['duration'] > self.max_duration:
                    raise ProcessingError(
                        f"Video zu lang: {info['duration']} Sekunden "
                        f"(Maximum: {self.max_duration} Sekunden)"
                    )

                # Verwende die Basis-Optionen aus der Konfiguration
                download_opts = self.ydl_opts.copy()
                
                # Setze den Output-Template für das aktuelle Verzeichnis
                output_path = str(process_dir / "%(title)s.%(ext)s")
                download_opts.update({
                    'outtmpl': output_path,
                    'format': 'bestaudio/best',
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                    }]
                })

                # Video herunterladen und zu MP3 konvertieren
                # yt-dlp lädt zuerst die Datei herunter und konvertiert sie dann automatisch zu MP3
                # durch den konfigurierten FFmpeg postprocessor
                self.logger.debug("Starte Download und MP3-Konvertierung", 
                                output_path=output_path,
                                format=download_opts.get('format'))
                
                # Erstelle neuen YoutubeDL-Instance mit den aktualisierten Optionen
                with yt_dlp.YoutubeDL(download_opts) as ydl_download:
                    ydl_download.download([url])
                
                # Nach der Konvertierung suchen wir die resultierende MP3-Datei
                # Es sollte genau eine MP3-Datei im Verzeichnis sein
                mp3_files = list(process_dir.glob("*.mp3"))
                if not mp3_files:
                    raise ProcessingError("Keine MP3-Datei nach Download und Konvertierung gefunden")
                audio_path = mp3_files[0]
                
                self.logger.debug("MP3-Datei gefunden", audio_file=str(audio_path))

                # Initialisiere audio_result als None
                audio_result = None

                if extract_audio and audio_path:
                    source_info = {
                        "title": info.get('title'),
                        "url": url,
                        "source_type": "youtube",
                        "duration": info.get('duration'),
                        "duration_formatted": self._format_duration(info.get('duration')),
                        "video_id": video_id,
                        "availability": info.get('availability'),
                        "categories": info.get('categories'),
                        "description": info.get('description'),
                        "tags": info.get('tags'),
                        "thumbnail": info.get('thumbnail'),
                        "upload_date": info.get('upload_date'),
                        "uploader": info.get('uploader'),
                        "uploader_id": info.get('uploader_id'),
                        "chapters": info.get('chapters'),
                        "view_count": info.get('view_count'),
                        "like_count": info.get('like_count'),
                        "dislike_count": info.get('dislike_count'),
                        "average_rating": info.get('average_rating'),
                        "age_limit": info.get('age_limit'),
                        "webpage_url": info.get('webpage_url')
                    }

                    # Use the already initialized audio_processor instance
                    self.logger.debug("Vor Audio Processing Aufruf")
                    
                    # Pass the file path instead of bytes
                    audio_result = await self.audio_processor.process(audio_path, source_info, target_language, template)

                    self.logger.debug("Nach Audio Processing",
                                    audio_result_id=audio_result.get('process_id'))

                # Erstelle eigenes Result mit Youtube-spezifischen Informationen
                result = {
                    "title": info.get('title'),
                    "duration": info.get('duration', 0),
                    "url": url,
                    "video_id": video_id,
                    "file_size": audio_path.stat().st_size if audio_path else None,
                    "process_dir": str(process_dir),
                    "audio_file": str(audio_path) if audio_path else None
                }

                # Füge Audio-Verarbeitungsergebnisse hinzu, wenn vorhanden
                if audio_result:
                    result["audio_process"] = audio_result

                return result

        except Exception as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'stack_trace': traceback.format_exc(),
                'url': url,
                'process_dir': str(process_dir) if 'process_dir' in locals() else None,
                'stage': ''
            }
            
            # Bestimme die Verarbeitungsstufe
            if 'info' not in locals():
                error_context['stage'] = 'video_info_extraction'
            elif 'audio_path' not in locals():
                error_context['stage'] = 'download'
            elif 'audio_result' not in locals():
                error_context['stage'] = 'audio_processing'
            else:
                error_context['stage'] = 'result_creation'
            
            # Füge zusätzliche Kontextinformationen hinzu
            if 'info' in locals():
                error_context.update({
                    'video_title': info.get('title'),
                    'video_duration': info.get('duration')
                })
            
            self.logger.error("Youtube-Verarbeitungsfehler", 
                            **error_context)
            
            raise ProcessingError(
                f"Youtube Verarbeitungsfehler in Phase '{error_context['stage']}': {str(e)}"
            ) 