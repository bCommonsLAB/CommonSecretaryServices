from pathlib import Path
from typing import Dict, Any, List, Tuple, Union
import tempfile
from pydub import AudioSegment
import time
import os
import requests
import hashlib
import json

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import ProcessingLogger
from src.utils.transcription_utils import WhisperTranscriber
from src.core.config import Config

class AudioProcessor(BaseProcessor):
    def __init__(self, resource_calculator, max_file_size: int = None, segment_duration: int = None, logger=None):
        # Lade Konfiguration
        config = Config()
        audio_config = config.get('processors.audio', {})
        
        # Verwende entweder übergebene Parameter oder Werte aus der Konfiguration
        max_file_size = max_file_size or audio_config.get('max_file_size')
        segment_duration = segment_duration or audio_config.get('segment_duration')
        
        super().__init__(resource_calculator, max_file_size)
        self.logger = logger or ProcessingLogger(process_id=self.process_id)
        self.transcriber = WhisperTranscriber(config.openai_api_key)
        self.temp_dir = Path(audio_config.get('temp_dir', "temp-processing/audio"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.segment_duration = segment_duration
        self.export_format = audio_config.get('export_format', 'mp3')
        self.temp_file_suffix = audio_config.get('temp_file_suffix', '.mp3')

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
        """analysiert eine Audio-Datei."""
        
        # Erstelle Hash des Pfads für das Verzeichnis
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
            return None
            
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
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
    async def process(self, audio_source: Union[str, bytes, Path], source_info: Dict[str, Any] = None, language: str = 'en', summarize: bool = False) -> Dict[str, Any]:
        """Verarbeitet eine Audio-Quelle.
        
        Args:
            audio_source: Kann sein:
                - bytes: Binäre Audio-Daten
                - str: URL oder lokaler Dateipfad
                - Path: Lokaler Dateipfad
            source_info: Zusätzliche Informationen über die Quelle
            language: Zielsprache (ISO 639-1 code)
            summarize: Ob eine Zusammenfassung erstellt werden soll
        """
        try:
            self.logger.debug("Audio Processing Start",
                            source_info=source_info,
                            source_type=type(audio_source).__name__)
            
            self.logger.info("Starte Audio-Verarbeitung")
            
            # Temporäre Datei für die Verarbeitung
            temp_file_path = None
            try:
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
                    transcription_result = self.transcriber.transcribe_segments(segments, segment_paths, self.logger)
                
                # Übersetze den kompletten Text wenn nötig
                detected_language = transcription_result.get('detected_language')
                if summarize or (detected_language and detected_language != language):
                    self.logger.info(f"Übersetze kompletten Text von {detected_language} nach {language}")
                    translation_result = self.transcriber.translate_text(
                        transcription_result['text'],
                        language,
                        self.logger, 
                        summarize
                    )
                    transcription_result = {
                        **transcription_result,
                        'text': translation_result['text'],
                        'original_text': transcription_result['text'],
                        'translation_model': 'gpt-4',
                        'token_count': transcription_result['token_count'] + translation_result['token_count']  # Addiere Tokens
                    }

                result = {
                    "duration": len(audio) / 1000.0,
                    "language": language,
                    "detected_language": detected_language,
                    "text": transcription_result['text'],
                    "original_text": transcription_result.get('original_text'),
                    "llm_model": transcription_result['model'],
                    "translation_model": transcription_result.get('translation_model'),
                    "token_count": transcription_result['token_count'],  # Enthält jetzt Tokens von Transkription und Übersetzung
                    "segments": transcription_result.get('segments', []),
                    "process_id": self.process_id,
                    "process_dir": str(process_dir),
                }
                
                if source_info:
                    source_info_clean = {k: v for k, v in source_info.items() if k not in ['process_id', 'language']}
                    result.update(source_info_clean)

                return result

            finally:
                if temp_file_path:
                    os.unlink(str(temp_file_path))

        except Exception as e:
            self.logger.error("Audio-Verarbeitungsfehler", 
                            error=str(e))
            raise ProcessingError(f"Audio-Verarbeitungsfehler: {str(e)}") 