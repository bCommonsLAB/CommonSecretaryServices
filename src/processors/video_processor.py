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
import subprocess  # Importiere subprocess für die FFmpeg-Integration
import json

import yt_dlp  # type: ignore

from src.core.models.audio import AudioResponse
from src.core.config import Config
from src.core.models.base import ErrorInfo
from src.core.models.enums import ProcessorType
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
        self.transcriber = WhisperTranscriber(transcriber_config)
        
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
        binary_data: Optional[bytes] = None  # Neuer Parameter für die Binärdaten
    ) -> VideoResponse:
        """
        Verarbeitet ein Video.
        
        Args:
            source: URL oder VideoSource-Objekt mit Video-Datei
            target_language: Zielsprache für die Transkription
            source_language: Quellsprache (auto für automatische Erkennung)
            template: Optional Template für die Verarbeitung
            use_cache: Ob der Cache verwendet werden soll (default: True)
            binary_data: Optionale Binärdaten des Videos (für hochgeladene Dateien)
            
        Returns:
            VideoResponse: Die standardisierte Response mit Transkription und Metadaten
        """
        # Initialisiere Variablen
        working_dir: Path = Path(self.temp_dir) / "video" / str(uuid.uuid4())
        working_dir.mkdir(parents=True, exist_ok=True)
        audio_path: Optional[Path] = None
        temp_video_path: Optional[Path] = None  # Pfad für temporär gespeicherte Binärdaten
        
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
                    
                    # Response aus Cache erstellen
                    response = self.create_response(
                        processor_name=ProcessorType.VIDEO.value,
                        result=cached_result,
                        request_info={
                            'source': str(source),
                            'target_language': target_language,
                            'source_language': source_language,
                            'template': template
                        },
                        response_class=VideoResponse,
                        from_cache=True,  # Explizit True, da wir aus dem Cache lesen
                        cache_key=cache_key
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
                # Datei in Arbeitsverzeichnis speichern - GEÄNDERT zur Verwendung der separaten Binärdaten
                if not video_source.file_name:
                    raise ValueError("Dateiname fehlt für Upload")
                
                # Speichere die Binärdaten temporär
                if binary_data:
                    # Binärdaten wurden separat bereitgestellt
                    file_path = working_dir / video_source.file_name
                    file_path.write_bytes(binary_data)
                    temp_video_path = file_path  # Merken für späteres Aufräumen
                else:
                    raise ValueError("Keine Binärdaten für Datei-Upload gefunden")
                
                # Konvertiere die hochgeladene Datei zu MP3, falls es keine MP3-Datei ist
                if not file_path.suffix.lower() == '.mp3':
                    self.logger.debug(f"Konvertiere Video zu MP3: {file_path.name}")
                    try:
                        # Definiere den Ausgabepfad für die MP3-Datei
                        output_mp3 = file_path.with_suffix('.mp3')
                        
                        # FFmpeg aufrufen, um Audio zu extrahieren
                        cmd = [
                            'ffmpeg', '-i', str(file_path), 
                            '-vn',                  # Keine Video-Streams
                            '-acodec', 'libmp3lame', # MP3-Codec
                            '-q:a', '4',            # Qualitätsstufe (0-9, wobei 0 die beste Qualität ist)
                            '-y',                   # Überschreiben ohne Nachfrage
                            str(output_mp3)
                        ]
                        
                        self.logger.debug(f"FFmpeg-Befehl: {' '.join(cmd)}")
                        
                        # Führe FFmpeg aus und fange die Ausgabe ab
                        process: subprocess.CompletedProcess[str] = subprocess.run(
                            cmd, 
                            check=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        
                        self.logger.debug("FFmpeg-Ausgabe", stdout=process.stdout, stderr=process.stderr)
                        
                        # Prüfe, ob die MP3-Datei erstellt wurde
                        if not output_mp3.exists():
                            raise ValueError(f"MP3-Datei wurde nicht erstellt: {output_mp3}")
                            
                        self.logger.info(f"Video erfolgreich zu MP3 konvertiert: {output_mp3.name}")
                        
                        # Lösche die ursprüngliche Videodatei, um Speicherplatz zu sparen
                        # (nur wenn die MP3-Extraktion erfolgreich war)
                        if temp_video_path and temp_video_path.exists():
                            temp_video_path.unlink()
                            self.logger.debug(f"Ursprüngliche Videodatei gelöscht: {file_path.name}")
                            temp_video_path = None  # Setze auf None, da wir sie bereits aufgeräumt haben
                        
                    except subprocess.CalledProcessError as e:
                        self.logger.error("Fehler bei der FFmpeg-Verarbeitung", 
                                         error=e,
                                         stdout=e.stdout if hasattr(e, 'stdout') else "",
                                         stderr=e.stderr if hasattr(e, 'stderr') else "")
                        raise ValueError(f"Fehler bei der Konvertierung zu MP3: {str(e)}")
                    except Exception as e:
                        self.logger.error(f"Unerwarteter Fehler bei der Konvertierung: {str(e)}")
                        raise
            
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
            
            # Debug-Ausgabe der Audio-Response
            self.logger.debug("Audio-Verarbeitung abgeschlossen", 
                             status=audio_response.status,
                             has_data=bool(audio_response.data),
                             has_transcription=bool(audio_response.data and audio_response.data.transcription),
                             error=bool(audio_response.error))
                             
            if not audio_response.data or not audio_response.data.transcription:
                self.logger.warning("Audio-Response enthält keine Transkriptionsdaten",
                                   audio_response_status=audio_response.status,
                                   error=audio_response.error.message if audio_response.error else "Kein Fehler")
            
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
            
            # Debug-Ausgabe der Metadaten
            self.logger.debug("Erstellte Metadaten",
                             title=title,
                             duration=duration,
                             file_size=audio_path.stat().st_size if audio_path else None)
            
            # Prüfe Transkriptionsdaten aus der Audio-Response
            transcription = None
            if audio_response.data and audio_response.data.transcription:
                transcription = audio_response.data.transcription
                self.logger.debug("Transkriptionsdaten gefunden",
                                 text_length=len(transcription.text) if transcription and hasattr(transcription, 'text') else 0,
                                 segments_count=len(transcription.segments) if transcription and hasattr(transcription, 'segments') else 0)
            else:
                self.logger.warning("Keine Transkriptionsdaten in der Audio-Response")
            
            # 10. Ergebnis erstellen
            result = VideoProcessingResult(
                metadata=metadata,
                transcription=transcription,
                process_id=self.process_id
            )
            
            # Debug-Ausgabe des Ergebnisses
            self.logger.debug("Erstelltes VideoProcessingResult", 
                             has_metadata=bool(result.metadata),
                             has_transcription=bool(result.transcription))
            
            # 11. Im MongoDB-Cache speichern (wenn aktiviert)
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(
                    cache_key=cache_key,
                    result=result
                )
                self.logger.debug(f"Video-Ergebnis im MongoDB-Cache gespeichert: {cache_key}")
            
            
            response: VideoResponse = self.create_response(
                processor_name=ProcessorType.VIDEO.value,
                result=result,
                request_info={
                    'source': str(source),
                    'target_language': target_language,
                    'source_language': source_language,
                    'template': template,
                    'video_id': video_id,
                    'video_duration': duration
                },
                response_class=VideoResponse,
                from_cache=False,  # Neue Berechnung, nicht aus dem Cache
                cache_key=cache_key            )
            
            # Überprüfe die Response auf Vollständigkeit
            response_dict = response.to_dict()
            self.logger.debug("Erzeugte Response", 
                             has_data=bool(response_dict.get('data')),
                             has_metadata=bool(response_dict.get('data', {}).get('metadata')),
                             has_transcription=bool(response_dict.get('data', {}).get('transcription')),
                             status=response_dict.get('status'))
            
            return response

        except Exception as e:
            # Beim Fehler aufräumen - sicherstellen, dass die temporären Binärdaten gelöscht werden
            if temp_video_path and temp_video_path.exists():
                try:
                    temp_video_path.unlink()
                    self.logger.debug(f"Temporäre Videodatei bei Fehler gelöscht: {temp_video_path}")
                except Exception as cleanup_error:
                    self.logger.warning(f"Konnte temporäre Datei nicht löschen: {cleanup_error}")
            
            # Originalen Error-Handling-Code beibehalten
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
            response: VideoResponse = self.create_response(
                processor_name=ProcessorType.VIDEO.value,
                result=result,
                request_info={
                    'source': str(source),
                    'target_language': target_language,
                    'source_language': source_language,
                    'template': template
                },
                response_class=VideoResponse,
                from_cache=False,  # Lese is_from_cache vom Ergebnisobjekt
                cache_key="",
                error=error_info
            )
            return response
        finally:
            # Immer sicherstellen, dass temporäre Binärdaten gelöscht werden
            if temp_video_path and temp_video_path.exists():
                try:
                    temp_video_path.unlink()
                    self.logger.debug(f"Temporäre Videodatei nach Verarbeitung gelöscht: {temp_video_path}")
                except Exception as cleanup_error:
                    self.logger.warning(f"Konnte temporäre Datei nicht löschen: {cleanup_error}") 