import os
import time
from pathlib import Path
import tempfile
import yt_dlp
from typing import Dict, Any
import glob
from pydub import AudioSegment
import traceback

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import ProcessingLogger
from src.utils.transcription_utils import WhisperTranscriber
from src.core.config import Config

class YoutubeProcessor(BaseProcessor):
    def __init__(self, resource_calculator, max_file_size: int = None, max_duration: int = None):
        # Lade Konfiguration
        config = Config()
        youtube_config = config.get('processors.youtube', {})
        
        # Verwende entweder übergebene Parameter oder Werte aus der Konfiguration
        max_file_size = max_file_size or youtube_config.get('max_file_size')
        max_duration = max_duration or youtube_config.get('max_duration')
        
        super().__init__(resource_calculator, max_file_size)
        self.max_duration = max_duration
        self.logger = ProcessingLogger(process_id=self.process_id)
        
        # Erstelle absolute Pfade für die Verzeichnisse
        self.temp_dir = Path(youtube_config.get('temp_dir', "temp-processing/video")).resolve()
        self.audio_cache_dir = Path(youtube_config.get('audio_cache_dir', "temp-processing/youtube-audio")).resolve()
        self.ydl_opts = youtube_config.get('ydl_opts', {})
        self.output_template = youtube_config.get('output_template')
        
        # Erstelle Verzeichnisse
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.audio_cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.debug("YouTube Processor initialisiert",
                         temp_dir=str(self.temp_dir),
                         audio_cache_dir=str(self.audio_cache_dir))

    def create_process_dir(self) -> Path:
        """Erstellt ein eindeutiges Verarbeitungsverzeichnis."""
        process_dir = self.temp_dir / self.process_id
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir

    def _extract_video_id(self, url: str) -> str:
        """Extrahiert die YouTube Video-ID aus der URL."""
        import re
        # Unterstützt verschiedene YouTube URL-Formate
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu.be\/|youtube.com\/embed\/)([^&\n?]+)',
            r'youtube.com\/shorts\/([^&\n?]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        raise ValueError(f"Konnte keine YouTube Video-ID aus der URL extrahieren: {url}")

    def _get_cached_audio_path(self, video_id: str) -> Path:
        """Gibt den Pfad zur zwischengespeicherten Audio-Datei zurück."""
        return self.audio_cache_dir / f"{video_id}.mp3"

    def _check_cached_audio(self, video_id: str) -> Path:
        """Prüft, ob eine Audio-Datei im Cache existiert."""
        cached_path = self._get_cached_audio_path(video_id)
        return cached_path if cached_path.exists() else None

    @ProcessingLogger.track_performance("youtube_processing")
    async def process(self, url: str, language: str = 'en', extract_audio: bool = True, summarize: bool = False) -> Dict[str, Any]:
        """
        Verarbeitet ein YouTube-Video.
        
        Args:
            url (str): Die URL des zu verarbeitenden YouTube-Videos
            language (str): Die Sprache für die Transkription (ISO 639-1 code)
            extract_audio (bool): Ob Audio extrahiert werden soll
            summarize (bool): Ob eine Zusammenfassung generiert werden soll
            
        Returns:
            Dict[str, Any]: Ein Dictionary mit den Verarbeitungsergebnissen
        """
        try:
            process_dir = self.create_process_dir()
            self.logger.debug("YouTube Processing Start", 
                            language=language,
                            extract_audio=extract_audio,
                            summarize=summarize)

            # Extrahiere Video-ID und prüfe Cache
            video_id = self._extract_video_id(url)
            cached_audio_path = self._get_cached_audio_path(video_id)
            
            # Initialisiere audio_path als None
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

                # Prüfe, ob Audio bereits im Cache ist
                audio_path = self._check_cached_audio(video_id)
                if audio_path:
                    self.logger.info("Verwende zwischengespeicherte Audio-Datei",
                                   path=str(audio_path))
                else:
                    # Verwende die Basis-Optionen aus der Konfiguration
                    download_opts = self.ydl_opts.copy()
                    # Überschreibe den Output-Template für das Caching
                    # Entferne .mp3 aus dem Pfad, da yt-dlp die Endung automatisch hinzufügt
                    output_path = str(cached_audio_path).replace('.mp3', '')
                    download_opts.update({
                        'outtmpl': output_path,  # Ohne Endung
                        'format': 'bestaudio/best',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                        }]
                    })

                    # Video herunterladen
                    self.logger.debug("Starte Download", 
                                    output_path=output_path,
                                    format=download_opts.get('format'))
                    with yt_dlp.YoutubeDL(download_opts) as ydl:
                        ydl.download([url])
                    audio_path = Path(f"{output_path}.mp3")  # Füge Endung für den weiteren Gebrauch hinzu

                # Initialisiere audio_result als None
                audio_result = None

                if extract_audio and audio_path:
                    source_info = {
                        "title": info.get('title'),
                        "url": url,
                        "source_type": "youtube",
                        "duration": info.get('duration'),
                        "video_id": video_id
                    }

                    # Direkter Aufruf des AudioProcessors
                    from src.processors.audio_processor import AudioProcessor
                    audio_processor = AudioProcessor(self.calculator, self.max_file_size, logger=self.logger)
                    
                    self.logger.debug("Vor Audio Processing Aufruf")

                    # Übergebe den Dateipfad statt der Bytes
                    audio_result = await audio_processor.process(audio_path, source_info, language, summarize)

                    self.logger.debug("Nach Audio Processing",
                                    audio_result_id=audio_result.get('process_id'))

                # Erstelle eigenes Result mit YouTube-spezifischen Informationen
                result = {
                    "title": info.get('title'),
                    "duration": info.get('duration'),
                    "url": url,
                    "video_id": video_id,
                    "cached_audio_path": str(audio_path) if audio_path else None,
                    "process_dir": str(process_dir),
                    "process_id": self.process_id,
                    "args": {
                        "language": language,
                        "extract_audio": extract_audio,
                        "summarize": summarize
                    }
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
                'stage': 'unknown'
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
            
            self.logger.error("YouTube-Verarbeitungsfehler", 
                            **error_context)
            
            raise ProcessingError(
                f"YouTube Verarbeitungsfehler in Phase '{error_context['stage']}': {str(e)}"
            ) 