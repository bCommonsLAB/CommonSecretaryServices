import os
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yt_dlp

from src.core.config import Config
from src.core.config_keys import ConfigKeys
from src.core.exceptions import ProcessingError
from src.core.models.audio import AudioProcessingResult
from src.core.models.base import ProcessInfo, RequestInfo
from src.core.models.enums import ProcessorType
from src.core.models.youtube import YoutubeMetadata, YoutubeProcessingResult
from src.core.resource_tracking import ResourceUsage
from src.utils.logger import get_logger
from src.utils.transcription_utils import WhisperTranscriber

from .base_processor import BaseProcessor
from .transformer_processor import TransformerProcessor


class YoutubeProcessor(BaseProcessor):
    """
    Prozessor für die Verarbeitung von YouTube-Videos.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    """
    
    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """
        Initialisiert den YoutubeProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Process-ID für Tracking
        """
        super().__init__(process_id)
        self.calculator = resource_calculator
        self.logger = get_logger(process_id, self.__class__.__name__)
        
        # Lade Konfiguration
        config = Config()
        self.max_duration = config.get('processors.youtube.max_duration', 3600)  # 1 Stunde
        
        # Basis-Optionen für yt-dlp
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }]
        }
        
        # Initialisiere Audio-Processor
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
    def _extract_video_id(self, url: str) -> str:
        """Extrahiert die Video-ID aus einer YouTube-URL."""
        try:
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info['id']
        except Exception as e:
            raise ProcessingError(f"Ungültige YouTube-URL: {str(e)}")
            
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

    async def process(self, file_path: str, target_language: str = 'de', 
                     extract_audio: bool = True, template: str = None) -> YoutubeProcessingResult:
        """
        Verarbeitet ein YouTube-Video.
        
        Args:
            file_path (str): YouTube-URL
            target_language (str): Zielsprache für die Transkription
            extract_audio (bool): Ob Audio extrahiert werden soll
            template (str): Name der zu verwendenden Vorlage
            
        Returns:
            YoutubeProcessingResult: Das typisierte Verarbeitungsergebnis
        """
        url = file_path  # file_path ist in diesem Fall die URL
        try:
            self.logger.debug("Youtube Processing Start", 
                            target_language=target_language,
                            extract_audio=extract_audio,
                            template=template)

            with self.measure_operation('youtube_processing'):
                # Extrahiere Video-ID und prüfe Cache
                video_id = self._extract_video_id(url)
                process_dir = self.create_process_dir(video_id)
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

                    # Prüfe ob bereits eine MP3-Datei existiert
                    mp3_files = list(process_dir.glob("*.mp3"))
                    if mp3_files:
                        self.logger.debug("Existierende MP3-Datei gefunden",
                                       audio_file=str(mp3_files[0]))
                        audio_path = mp3_files[0]
                    else:
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
                        self.logger.debug("Starte Download und MP3-Konvertierung", 
                                        output_path=output_path,
                                        format=download_opts.get('format'))
                        
                        # Erstelle neuen YoutubeDL-Instance mit den aktualisierten Optionen
                        with yt_dlp.YoutubeDL(download_opts) as ydl_download:
                            ydl_download.download([url])
                        
                        # Nach der Konvertierung suchen wir die resultierende MP3-Datei
                        mp3_files = list(process_dir.glob("*.mp3"))
                        if not mp3_files:
                            raise ProcessingError("Keine MP3-Datei nach Download gefunden")
                        audio_path = mp3_files[0]
                        
                        self.logger.debug("MP3-Datei gefunden", audio_file=str(audio_path))

                    # Initialisiere audio_result als None
                    audio_result = None

                    if extract_audio and audio_path:
                        # Erstelle die Metadaten
                        metadata = YoutubeMetadata(
                            title=info.get('title'),
                            url=url,
                            video_id=video_id,
                            duration=info.get('duration', 0),
                            duration_formatted=self._format_duration(info.get('duration', 0)),
                            file_size=audio_path.stat().st_size if audio_path else None,
                            process_dir=str(process_dir),
                            audio_file=str(audio_path) if audio_path else None,
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


                        # Verarbeite Audio
                        self.logger.debug("Vor Audio Processing Aufruf")
                        audio_result = await self.transformer.transform(
                            source_text=audio_path,
                            source_language="auto",
                            target_language=target_language,
                            context={"type": "audio"}
                        )

                        self.logger.debug("Nach Audio Processing",
                                        audio_result_id=audio_result.process_id)

                    # Erstelle das finale Ergebnis
                    result = YoutubeProcessingResult(
                        metadata=metadata,
                        audio_result=audio_result,
                        process_id=self.process_id
                    )

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