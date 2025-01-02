from pathlib import Path
from typing import Dict, Any, List, Tuple, Union
import tempfile
from pydub import AudioSegment
import time
import os
import requests
import hashlib
import json
import shutil

from .base_processor import BaseProcessor
from core.resource_tracking import ResourceUsage
from core.exceptions import ProcessingError
from utils.logger import ProcessingLogger
from utils.transcription_utils import WhisperTranscriber
from core.config import Config
from .transformer_processor import TransformerProcessor

class AudioProcessor(BaseProcessor):
    def __init__(self, resource_calculator, max_file_size: int = None, segment_duration: int = None, batch_size: int = None):
        # Lade Konfiguration
        config = Config()
        audio_config = config.get('processors.audio', {})
        
        # Verwende entweder übergebene Parameter oder Werte aus der Konfiguration
        max_file_size = max_file_size or audio_config.get('max_file_size')
        segment_duration = segment_duration or audio_config.get('segment_duration')
        batch_size = batch_size or audio_config.get('batch_size')
        super().__init__(resource_calculator, max_file_size)
        # Eigener Logger ohne externe Übergabe
        self.logger = ProcessingLogger(
            process_id=self.process_id,
            processor_name="AudioProcessor"
        )
        self.transcriber = WhisperTranscriber(config.openai_api_key)
        self.temp_dir = Path(audio_config.get('temp_dir', "temp-processing/audio"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.segment_duration = segment_duration
        self.batch_size = batch_size
        self.export_format = audio_config.get('export_format', 'mp3')
        self.temp_file_suffix = audio_config.get('temp_file_suffix', '.mp3')
        self.transformer = TransformerProcessor() 

    def _safe_delete(self, file_path: Union[str, Path]) -> None:
        """Löscht eine Datei sicher und ignoriert Fehler wenn die Datei nicht gelöscht werden kann.
        
        Args:
            file_path: Pfad zur Datei die gelöscht werden soll
        """
        try:
            if file_path and os.path.exists(str(file_path)):
                os.unlink(str(file_path))
        except Exception as e:
            self.logger.warning(f"Konnte temporäre Datei nicht löschen: {str(e)}")

    def _safe_delete_dir(self, dir_path: Union[str, Path]) -> None:
        """Löscht ein Verzeichnis rekursiv und sicher.
        
        Args:
            dir_path: Pfad zum Verzeichnis das gelöscht werden soll
        """
        try:
            if dir_path and os.path.exists(str(dir_path)):
                shutil.rmtree(str(dir_path))
        except Exception as e:
            self.logger.warning(f"Konnte Verzeichnis nicht löschen: {str(e)}")

    def cleanup_cache(self, max_age_days: int = 7, delete_transcripts: bool = False) -> None:
        """Löscht alte Cache-Verzeichnisse die älter als max_age_days sind.
        
        Args:
            max_age_days: Maximales Alter in Tagen, nach dem ein Cache-Verzeichnis gelöscht wird
            delete_transcripts: Wenn True, werden auch die Transkriptionen gelöscht, sonst nur die Segmente
        """
        try:
            now = time.time()
            for dir_path in self.temp_dir.glob("*"):
                if dir_path.is_dir():
                    dir_age = now - dir_path.stat().st_mtime
                    if dir_age > (max_age_days * 24 * 60 * 60):
                        if delete_transcripts:
                            # Lösche das komplette Verzeichnis
                            self._safe_delete_dir(dir_path)
                            self.logger.info("Cache-Verzeichnis komplett gelöscht", 
                                           dir=str(dir_path), 
                                           age_days=dir_age/(24*60*60))
                        else:
                            # Lösche nur die Segment-Dateien und deren Transkriptionen
                            for segment_file in dir_path.glob("segment_*.txt"):
                                self._safe_delete(segment_file)
                            for segment_file in dir_path.glob(f"segment_*.{self.export_format}"):
                                self._safe_delete(segment_file)
                            self.logger.info("Cache-Segmente und deren Transkriptionen gelöscht", 
                                           dir=str(dir_path), 
                                           age_days=dir_age/(24*60*60))
        except Exception as e:
            self.logger.error(f"Fehler beim Cache-Cleanup: {str(e)}")

    def delete_cache(self, filename: str, delete_transcript: bool = False) -> None:
        """Löscht das Cache-Verzeichnis für eine bestimmte Datei.
        
        Args:
            filename: Name der Datei deren Cache gelöscht werden soll
            delete_transcript: Wenn True, wird auch die Transkription gelöscht, sonst nur die Segmente
        """
        try:
            path_hash = hashlib.md5(str(filename).encode()).hexdigest()
            cache_dir = self.temp_dir / path_hash
            if cache_dir.exists():
                if delete_transcript:
                    # Lösche das komplette Verzeichnis
                    self._safe_delete_dir(cache_dir)
                    self.logger.info("Cache-Verzeichnis für Datei komplett gelöscht", 
                                   filename=filename, 
                                   dir=str(cache_dir))
                else:
                    # Lösche nur die Segment-Dateien und deren Transkriptionen
                    for segment_file in cache_dir.glob("segment_*.txt"):
                        self._safe_delete(segment_file)
                    for segment_file in cache_dir.glob(f"segment_*.{self.export_format}"):
                        self._safe_delete(segment_file)
                    self.logger.info("Cache-Segmente und deren Transkriptionen für Datei gelöscht", 
                                   filename=filename, 
                                   dir=str(cache_dir))
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen des Cache-Verzeichnisses: {str(e)}")

    def _load_audio_from_url(self, url: str) -> Path:
        """Lädt eine Audio-Datei von einer URL herunter.
        
        Args:
            url (str): URL der Audio-Datei
            
        Returns:
            Path: Pfad zur heruntergeladenen Datei
        """
        temp_file = tempfile.NamedTemporaryFile(suffix=self.temp_file_suffix, delete=False)
        response = requests.get(url, stream=True)
        response.raise_for_status()
        
        for chunk in response.iter_content(chunk_size=8192):
            temp_file.write(chunk)
        temp_file.close()
        return Path(temp_file.name)

    def _load_audio_from_bytes(self, audio_data: bytes) -> Path:
        """Speichert Audio-Bytes in einer temporären Datei.
        
        Args:
            audio_data (bytes): Audio-Daten
            
        Returns:
            Path: Pfad zur temporären Datei
        """
        temp_file = tempfile.NamedTemporaryFile(suffix=self.temp_file_suffix, delete=False)
        temp_file.write(audio_data)
        temp_file.close()
        return Path(temp_file.name)


    def get_process_dir(self, audio_path: str) -> Path:
        """Erstellt ein Verzeichnis für die Verarbeitung basierend auf dem Dateinamen.
        
        Args:
            audio_path (str): Pfad zur Audio-Datei oder temporärer Pfad
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Wenn es ein temporärer Pfad ist, versuche den originalen Dateinamen aus source_info zu verwenden
        if hasattr(self, '_current_source_info') and self._current_source_info:
            original_filename = self._current_source_info.get('original_filename')
            if original_filename:
                path_hash = hashlib.md5(str(original_filename).encode()).hexdigest()
            else:
                path_hash = hashlib.md5(str(audio_path).encode()).hexdigest()
        else:
            path_hash = hashlib.md5(str(audio_path).encode()).hexdigest()
            
        process_dir = self.temp_dir / path_hash
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir


    def process_audio_file(self, audio_path: str, process_dir: Path) -> AudioSegment:
        """Lädt und analysiert eine Audio-Datei."""
        audio = AudioSegment.from_file(audio_path)
        
        self.logger.info("Audio-Analyse",
                        duration_seconds=len(audio) / 1000.0,
                        channels=audio.channels,
                        sample_width=audio.sample_width,
                        frame_rate=audio.frame_rate)
        return audio

    def get_audio_segments(self, audio: AudioSegment, process_dir: Path) -> Tuple[List[bytes], List[Path]]:
        """Teilt Audio in Segmente auf."""
        duration = len(audio)
        segments = []
        segment_paths = []

        if duration <= self.segment_duration * 1000:
            segment_path = process_dir / f"full.{self.export_format}"
            audio.export(str(segment_path), format=self.export_format)
            segments.append(segment_path.read_bytes())
            segment_paths.append(segment_path)
            return segments, segment_paths

        segment_count = (duration // (self.segment_duration * 1000)) + 1
        
        for i in range(segment_count):
            start = i * self.segment_duration * 1000
            end = min((i + 1) * self.segment_duration * 1000, duration)
            
            segment = audio[start:end]
            segment_path = process_dir / f"segment_{i+1}.{self.export_format}"
            segment.export(str(segment_path), format=self.export_format)
            segments.append(segment_path.read_bytes())
            segment_paths.append(segment_path)
            
            self.logger.debug(f"Segment {i+1}/{segment_count} erstellt",
                            duration=len(segment) / 1000.0,
                            segment_path=str(segment_path))
                
        return segments, segment_paths

    def _read_existing_transcript(self, process_dir: Path) -> Dict[str, Any]:
        """Liest eine existierende Transkriptionsdatei im JSON-Format.
        
        Args:
            process_dir (Path): Verzeichnis mit der Transkriptionsdatei
            
        Returns:
            Dict[str, Any]: Dictionary mit text, model und detected_language oder None wenn keine Datei existiert
        """


        transcript_file = process_dir / "complete_transcript.txt"
        if not transcript_file.exists():
            self.logger.info("Keine existierende Transkription gefunden ", process_dir=str(process_dir))
            return None
            
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.logger.info("Existierende Transkription gefunden", transcript_file=str(transcript_file))
                return {
                    'text': data.get('text', ''),
                    'model': data.get('model', ''),
                    'detected_language': data.get('detected_language', ''),
                    'token_count': 0,  
                    'segments': []
                }
        except Exception as e:
            self.logger.warning(f"Fehler beim Lesen der existierenden Transkription: {str(e)}")
        return None

    @ProcessingLogger.track_performance("audio_processing")
    async def process(self, audio_source: Union[str, bytes, Path], source_info: Dict[str, Any] = None, target_language: str = 'en', template: str = '') -> Dict[str, Any]:
        """Verarbeitet eine Audio-Quelle.
        
        Args:
            audio_source: Kann sein:
                - bytes: Binäre Audio-Daten
                - str: URL oder lokaler Dateipfad
                - Path: Lokaler Dateipfad
            source_info: Zusätzliche Informationen über die Quelle
            target_language: Zielsprache (ISO 639-1 code)
            template: Name der zu verwendenden Vorlage
        """
        temp_file_path = None
        try:
            # Speichere source_info für get_process_dir
            self._current_source_info = source_info
            
            self.logger.debug("1. Audio Processing Start",
                            source_info=source_info,
                            source_type=type(audio_source).__name__,
                            target_language=target_language,
                            template=template)
            
            self.logger.info("2. Starte Audio-Verarbeitung")

            # Bestimme die Audio-Quelle
            if isinstance(audio_source, bytes):
                temp_file_path = self._load_audio_from_bytes(audio_source)
            elif isinstance(audio_source, (str, Path)):
                audio_path = str(audio_source)
                if audio_path.startswith(('http://', 'https://')):
                    temp_file_path = self._load_audio_from_url(audio_path)
                else:
                    # Lokale Datei, verwende direkt
                    temp_file_path = Path(audio_path)
            else:
                raise ValueError(f"Nicht unterstützter Audio-Quellen-Typ: {type(audio_source)}")

            process_dir = self.get_process_dir(str(temp_file_path))

            # Prüfe auf existierende Transkription
            transcription_result = self._read_existing_transcript(process_dir)
            audio = self.process_audio_file(str(temp_file_path), process_dir)
            
            if transcription_result:
                self.logger.info("Existierende Transkription gefunden")
            else:
                segments, segment_paths = self.get_audio_segments(audio, process_dir)
                # Transkription durchführen
                self.logger.info(f"Verarbeite {len(segments)} Segmente")
                transcription_result = self.transcriber.transcribe_segments(segments, segment_paths, self.logger, self.batch_size)
                # Cleanup segment files
                for segment_path in segment_paths:
                    self._safe_delete(segment_path)

            # Übersetze den kompletten Text wenn nötig
            detected_language = transcription_result.get('detected_language')


            if template:
                self.logger.info(f"3. Text transformation mit Vorlage wird ausgeführt {template}")
                transformation_result = self.transformer.transformByTemplate(
                    source_text=transcription_result['text'],
                    source_language=detected_language,
                    target_language=target_language,
                    context=source_info,
                    template=template
                )
                transcription_result = {
                    **transcription_result,
                    'text': transformation_result['text'],
                    'original_text': transcription_result['text'],
                    'translation_model': transformation_result['translation_model'],
                    'token_count': transcription_result['token_count'] + transformation_result['token_count']
                }

            elif detected_language and detected_language != target_language:
                self.logger.info(f"4. Übersetze/Text-Zusammenfassung wird ausgeführt ({detected_language} -> {target_language})")
                transformation_result = self.transformer.transform(
                    source_text=transcription_result['text'],
                    source_language=detected_language,
                    target_language=target_language
                )
                transcription_result = {
                    **transcription_result,
                    'text': transformation_result['text'],
                    'original_text': transcription_result['text'],
                    'translation_model': transformation_result['translation_model'],
                    'token_count': transcription_result['token_count'] + transformation_result['token_count']
                }

            result = {
                "duration": len(audio) / 1000.0,
                "detected_language": detected_language,
                "text": transcription_result['text'],
                "original_text": transcription_result.get('original_text'),
                "llm_model": transcription_result['model'],
                "translation_model": transcription_result.get('translation_model'),
                "token_count": transcription_result['token_count'],
                "segments": transcription_result.get('segments', []),
                "process_id": self.process_id,
                "process_dir": str(process_dir),
                "args": {
                    "target_language": target_language,
                    "template": template
                }
            }
            
            if source_info:
                source_info_clean = {k: v for k, v in source_info.items() if k not in ['process_id', 'language']}
                result.update(source_info_clean)

            return result

        except Exception as e:
            self.logger.error("Audio-Verarbeitungsfehler", 
                            error=str(e))
            raise ProcessingError(f"Audio-Verarbeitungsfehler: {str(e)}")
        finally:
            # Cleanup: Versuche temporäre Dateien zu löschen
            if temp_file_path and isinstance(audio_source, (bytes, str)) and str(temp_file_path) != str(audio_source):
                self._safe_delete(temp_file_path) 