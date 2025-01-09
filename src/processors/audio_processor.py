import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union
import time
import hashlib
import json
from pydub import AudioSegment
import traceback
import tempfile
import gc
import uuid
import math

from .base_processor import BaseProcessor
from src.core.resource_tracking import ResourceUsage
from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.types import (
    TranscriptionResult, 
    TranscriptionSegment,
    llModel,
    AudioProcessingResult, 
    AudioMetadata,
    AudioSegmentInfo,
    ChapterInfo
)
from src.core.config import Config
from src.core.config_keys import ConfigKeys
from .transformer_processor import TransformerProcessor

class AudioProcessor(BaseProcessor):
    """Audio Processor für die Verarbeitung von Audio-Dateien.
    
    Diese Klasse verarbeitet Audio-Dateien, segmentiert sie bei Bedarf und führt Transkription/Übersetzung durch.
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        max_file_size (int): Maximale Dateigröße in Bytes (Default: 100MB)
        segment_duration (int): Dauer der Audio-Segmente in Sekunden
        export_format (str): Format für exportierte Audio-Dateien
        temp_file_suffix (str): Suffix für temporäre Dateien
    """
    def __init__(self, resource_calculator, process_id: str = None):
        """
        Initialisiert den AudioProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID vom API-Layer
        """
        # Basis-Klasse zuerst initialisieren
        super().__init__(process_id=process_id)
        
        # Konfiguration aus Config laden
        config = Config()
        processors_config = config.get('processors', {})
        audio_config = processors_config.get('audio', {})
        
        # Konfigurationswerte mit Validierung laden
        self.max_file_size = audio_config.get('max_file_size', 104857600)  # Default: 100MB
        self.segment_duration = audio_config.get('segment_duration')
        
        # Validierung der erforderlichen Konfigurationswerte
        if not self.segment_duration:
            raise ValueError("segment_duration muss in der Konfiguration angegeben werden")
        
        # Weitere Konfigurationswerte laden
        self.logger = get_logger(process_id=self.process_id, processor_name="AudioProcessor")
        self.transcriber = WhisperTranscriber(audio_config)
        self.temp_dir = Path(audio_config.get('temp_dir', "temp-processing/audio"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.export_format = audio_config.get('export_format', 'mp3')
        self.temp_file_suffix = audio_config.get('temp_file_suffix', '.mp3')
        self.transformer = TransformerProcessor(process_id=process_id)

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
        """Löscht das Cache-Verzeichnis für eine bestimmte Datei."""
        try:
            # Berechne den Hash des Dateinamens
            filename_hash = hashlib.md5(filename.encode()).hexdigest()
            process_dir = self.temp_dir / filename_hash
            
            if process_dir.exists():
                if delete_transcript:
                    # Lösche das komplette Verzeichnis
                    self._safe_delete_dir(process_dir)
                    self.logger.info("Cache komplett gelöscht", 
                                  dir=str(process_dir))
                else:
                    # Lösche nur die Segment-Dateien
                    for segment_file in process_dir.glob("segment_*.txt"):
                        self._safe_delete(segment_file)
                    for segment_file in process_dir.glob(f"segment_*.{self.export_format}"):
                        self._safe_delete(segment_file)
                    self.logger.info("Cache-Segmente gelöscht", 
                                  dir=str(process_dir))
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen des Caches: {str(e)}")

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


    def get_process_dir(self, audio_path: str, original_filename: str=None, video_id: str=None) -> Path:
        """Erstellt ein Verzeichnis für die Verarbeitung basierend auf dem Dateinamen.
        
        Args:
            audio_path (str): Pfad zur Audio-Datei oder temporärer Pfad
            
        Returns:
            Path: Pfad zum Verarbeitungsverzeichnis
        """
        # Wenn es ein temporärer Pfad ist, versuche den originalen Dateinamen aus source_info zu verwenden
        if video_id:
            process_dir = self.temp_dir / video_id
        elif original_filename:
            path_hash = hashlib.md5(str(original_filename).encode()).hexdigest()
            process_dir = self.temp_dir / path_hash
        else:
            path_hash = hashlib.md5(str(audio_path).encode()).hexdigest()
            process_dir = self.temp_dir / path_hash
            
        process_dir.mkdir(parents=True, exist_ok=True)
        return process_dir


    def process_audio_file(self, audio_path: str) -> AudioSegment:
        """Lädt und analysiert eine Audio-Datei."""
        audio = AudioSegment.from_file(audio_path)
        
        self.logger.info("Audio-Analyse",
                        duration_seconds=len(audio) / 1000.0,
                        channels=audio.channels,
                        sample_width=audio.sample_width,
                        frame_rate=audio.frame_rate)
        return audio

    def _format_duration(self, seconds: float) -> str:
        """Formatiert Sekunden in ein lesbares Format (H:MM:SS).
        
        Args:
            seconds (float): Zeit in Sekunden
            
        Returns:
            str: Formatierte Zeit im Format H:MM:SS (ohne führende Nullen bei Stunden)
        """
        hours = int(seconds) // 3600
        minutes = (int(seconds) % 3600) // 60
        seconds = int(seconds) % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes}:{seconds:02d}"

    def _sanitize_filename(self, filename: str) -> str:
        """Bereinigt einen Dateinamen von ungültigen Zeichen.
        
        Args:
            filename (str): Der zu bereinigende Dateiname
            
        Returns:
            str: Der bereinigte Dateiname
        """
        # Ersetze Backslashes und andere problematische Zeichen
        invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
        original = filename
        for char in invalid_chars:
            filename = filename.replace(char, '-')
        
        if original != filename:
            self.logger.debug("Dateiname bereinigt",
                            original=original,
                            sanitized=filename)
        return filename

    def _check_segment_size(self, segment: AudioSegment, format: str = 'mp3') -> int:
        """Prüft die Größe eines Audio-Segments.
        
        Args:
            segment: Das zu prüfende AudioSegment
            format: Das Export-Format
            
        Returns:
            int: Größe in Bytes
        """
        # Erstelle einen zufälligen Dateinamen im process_dir
        temp_filename = f'temp_segment_{uuid.uuid4()}.{format}'
        temp_path = os.path.join(self.temp_dir, temp_filename)
        
        try:
            # Exportiere direkt in unser temp_dir
            segment.export(temp_path, format=format)
            size = os.path.getsize(temp_path)
            self.logger.debug("Segment-Größe geprüft",
                            duration_seconds=len(segment)/1000.0,
                            size_bytes=size)
            return size
        finally:
            # Aufräumen
            try:
                os.remove(temp_path)
            except OSError:
                self.logger.warning(f"Konnte temporäre Datei nicht löschen: {temp_path}")
                pass

    def _split_large_segment(self, segment: AudioSegment, max_size: int = 25*1024*1024) -> List[AudioSegment]:
        """Teilt ein Segment in kleinere Teile auf, wenn es zu groß ist.
        
        Args:
            segment (AudioSegment): Das aufzuteilende Segment
            max_size (int): Maximale Größe in Bytes (Default: 25MB)
            
        Returns:
            List[AudioSegment]: Liste der Teilsegmente
        """
        try:
            segments = []
            duration = len(segment)
            
            # Reduziere die maximale Größe um 20% als Sicherheitspuffer
            target_size = int(max_size * 0.9)  # Erhöht von 0.9 auf 0.8 für mehr Sicherheit
            
            # Schätze die Bytes pro Millisekunde basierend auf der Gesamtgröße
            total_size = self._check_segment_size(segment)
            bytes_per_ms = total_size / duration
            
            # Berechne die optimale Segmentdauer (maximal 10 Minuten)
            target_duration = min(
                int((target_size / bytes_per_ms)),
                10 * 60 * 1000  # 10 Minuten in ms
            )
            
            self.logger.info("Teile großes Segment auf",
                           total_duration=duration/1000,
                           total_size_mb=total_size/(1024*1024),
                           target_duration=target_duration/1000,
                           bytes_per_second=bytes_per_ms*1000)
            
            # Teile das Segment in Stücke auf
            current_position = 0
            part_number = 1
            
            while current_position < duration:
                end_position = min(current_position + target_duration, duration)
                part = segment[current_position:end_position]
                
                # Prüfe die tatsächliche Größe
                actual_size = self._check_segment_size(part)
                
                # Wenn das Teil immer noch zu groß ist, halbiere die Dauer und versuche erneut
                retry_count = 0
                while actual_size > max_size and retry_count < 5:
                    target_duration = target_duration // 2
                    end_position = min(current_position + target_duration, duration)
                    part = segment[current_position:end_position]
                    actual_size = self._check_segment_size(part)
                    retry_count += 1
                    
                    self.logger.warning(f"Segment Teil {part_number} zu groß, verkleinere",
                                    original_size_mb=actual_size/(1024*1024),
                                    new_duration=target_duration/1000,
                                    retry=retry_count)
                
                if actual_size > max_size:
                    self.logger.error(f"Segment Teil {part_number} konnte nicht ausreichend verkleinert werden",
                                    final_size_mb=actual_size/(1024*1024),
                                    max_size_mb=max_size/(1024*1024))
                    raise ValueError(f"Segment konnte nicht unter {max_size/(1024*1024)}MB verkleinert werden")
                
                segments.append(part)
                current_position = end_position
                
                self.logger.info(f"Segment Teil {part_number} erstellt",
                               duration_sec=len(part)/1000.0,
                               size_mb=actual_size/(1024*1024),
                               start_sec=current_position/1000,
                               end_sec=end_position/1000)
                
                part_number += 1
            
            return segments
            
        except Exception as e:
            self.logger.error("Fehler beim Aufteilen des Segments", error=str(e))
            raise
        finally:
            # Speicher freigeben
            gc.collect()

    def _create_standard_segments(self, audio: AudioSegment, process_dir: Path, skip_segments: List[int] = None) -> List[AudioSegmentInfo]:
        """Erstellt Standard-Segmente basierend auf der konfigurierten Segmentlänge.
        
        Args:
            audio (AudioSegment): Das zu segmentierende Audio
            process_dir (Path): Verzeichnis für die Segmente
            skip_segments (List[int], optional): Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            List[AudioSegmentInfo]: Liste der Audio-Segmente mit Metadaten
        """
        duration = len(audio)
        segments = []
        skip_segments = skip_segments or []

        # Wenn Audio kürzer als Segmentdauer, erstelle nur ein Segment
        if duration <= self.segment_duration * 1000:
            segment_path = process_dir / f"full.{self.export_format}"
            audio.export(str(segment_path), format=self.export_format)
            return [AudioSegmentInfo(
                    file_path=segment_path,
                    title=None
                )]

        # Teile in gleichmäßige Segmente auf
        segment_count = (duration // (self.segment_duration * 1000)) + 1
        for i in range(segment_count):
            if i in skip_segments:
                self.logger.info(f"Überspringe bereits verarbeitetes Segment {i}")
                continue
                
            start = i * self.segment_duration * 1000
            end = min((i + 1) * self.segment_duration * 1000, duration)
            
            segment = audio[start:end]
            segment_path = process_dir / f"segment_{i+1}.{self.export_format}"
            
            segment.export(str(segment_path), format=self.export_format)
            segments.append(AudioSegmentInfo(
                file_path=segment_path,
                title=None
            ))
            
            self.logger.debug(f"Segment {i+1}/{segment_count} erstellt",
                            duration=len(segment)/1000.0,
                            segment_path=str(segment_path))
                
        return segments

    def _split_by_duration(self, segment: AudioSegment, max_duration_minutes: int = 6) -> List[AudioSegment]:
        """Teilt ein AudioSegment basierend auf einer maximalen Dauer.
        
        Args:
            segment (AudioSegment): Das zu teilende AudioSegment
            max_duration_minutes (int): Maximale Dauer in Minuten (Standard: 6)
            
        Returns:
            List[AudioSegment]: Liste der geteilten Segmente
        """
        duration_ms = len(segment)
        max_duration_ms = max_duration_minutes * 60 * 1000
        
        # Wenn Segment kürzer als maximale Dauer, return direkt
        if duration_ms <= max_duration_ms:
            return [segment]
            
        # Berechne Anzahl der benötigten Segmente
        num_segments = math.ceil(duration_ms / max_duration_ms)
        segment_duration_ms = duration_ms // num_segments
        
        self.logger.info(f"Teile Segment in {num_segments} Teile",
                        original_duration=duration_ms/1000,
                        segment_duration=segment_duration_ms/1000)
        
        segments = []
        for i in range(num_segments):
            start = i * segment_duration_ms
            end = min((i + 1) * segment_duration_ms, duration_ms)
            
            part = segment[start:end]
            segments.append(part)
            
            self.logger.debug(f"Segment Teil {i+1}/{num_segments} erstellt",
                            duration_sec=len(part)/1000.0,
                            start_sec=start/1000,
                            end_sec=end/1000)
        
        return segments

    def _create_chapter_segments(self, audio: AudioSegment, process_dir: Path, chapters: List[Dict[str, Any]], skip_segments: List[int] = None) -> List[ChapterInfo]:
        """Erstellt Segmente basierend auf Kapitelinformationen.
        
        Args:
            audio (AudioSegment): Das zu segmentierende Audio
            process_dir (Path): Verzeichnis für die Segmente
            chapters (List[Dict[str, Any]]): Liste der Kapitel mit Start- und Endzeiten
            skip_segments (List[int], optional): Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            List[ChapterInfo]: Liste der Kapitel mit ihren Audio-Segmenten
        """
        duration = len(audio)
        chapter_infos = []
        max_duration_minutes = 5  # Maximale Dauer eines Segments in Minuten
        skip_segments = skip_segments or []

        self.logger.info("Verwende Kapitelinformationen für Segmentierung",
                        chapter_count=len(chapters))

        for i, chapter in enumerate(chapters):
            if i in skip_segments:
                self.logger.info(f"Überspringe bereits verarbeitetes Kapitel {i}")
                continue

            start_ms = int(chapter['start_time'] * 1000)
            end_ms = int(chapter['end_time'] * 1000)
            
            start_ms = max(0, min(start_ms, duration))
            end_ms = max(0, min(end_ms, duration))

            start_formatted = self._format_duration(chapter['start_time'])
            end_formatted = self._format_duration(chapter['end_time'])                    

            if start_ms >= end_ms:
                continue
            
            chapter_segment = audio[start_ms:end_ms]
            chapter_duration_minutes = len(chapter_segment) / (60 * 1000)
            chapter_segments = []
            
            try:
                # Teile Kapitel wenn es länger als max_duration_minutes ist
                if chapter_duration_minutes > max_duration_minutes:
                    self.logger.info(f"Kapitel {i+1} zu lang, teile es auf", 
                                   duration_minutes=chapter_duration_minutes,
                                   max_duration_minutes=max_duration_minutes)
                    
                    sub_segments = self._split_by_duration(chapter_segment, max_duration_minutes)
                    
                    for j, sub_segment in enumerate(sub_segments):
                        try:
                            segment_path = process_dir / f"chapter_{i+1}_part_{j+1}.{self.export_format}"
                            sub_segment.export(str(segment_path), format=self.export_format)
                            
                            chapter_segments.append(AudioSegmentInfo(
                                file_path=segment_path,
                                title=None  # Titel wird jetzt im ChapterInfo gespeichert
                            ))
                            
                            self.logger.debug(f"Kapitel {i+1}/{len(chapters)} Teil {j+1} erstellt",
                                            title=chapter['title'],
                                            duration=len(sub_segment) / 1000.0,
                                            segment_path=str(segment_path))
                        finally:
                            del sub_segment
                    
                    del sub_segments
                else:
                    segment_path = process_dir / f"chapter_{i+1}.{self.export_format}"
                    chapter_segment.export(str(segment_path), format=self.export_format)
                    
                    chapter_segments.append(AudioSegmentInfo(
                        file_path=segment_path,
                        title=None  # Titel wird jetzt im ChapterInfo gespeichert
                    ))
                    
                    self.logger.debug(f"Kapitel {i+1}/{len(chapters)} erstellt",
                                    title=chapter['title'],
                                    duration=len(chapter_segment) / 1000.0,
                                    segment_path=str(segment_path))

                # Erstelle ChapterInfo für dieses Kapitel
                chapter_info = ChapterInfo(
                    title=f"{chapter['title']} ({start_formatted} - {end_formatted})",
                    segments=chapter_segments
                )
                chapter_infos.append(chapter_info)
                
            finally:
                del chapter_segment
            
        return chapter_infos

    def get_audio_segments(self, audio: AudioSegment, process_dir: Path, chapters: List[Dict[str, Any]] = None, skip_segments: List[int] = None) -> Union[List[AudioSegmentInfo], List[ChapterInfo]]:
        """Teilt Audio in Segmente auf.
        
        Args:
            audio (AudioSegment): Das zu segmentierende Audio
            process_dir (Path): Verzeichnis für die Segmente
            chapters (List[Dict[str, Any]], optional): Liste der Kapitel mit Start- und Endzeiten
            skip_segments (List[int], optional): Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            Union[List[AudioSegmentInfo], List[ChapterInfo]]: Liste der Segmente oder Kapitel
        """
        try:
            # Wähle die passende Segmentierungsmethode
            if chapters:
                segments_or_chapters = self._create_chapter_segments(audio, process_dir, chapters, skip_segments)
            else:
                segments_or_chapters = self._create_standard_segments(audio, process_dir, skip_segments)

            # Speichere segment_infos im process_dir
            try:
                segment_info_path = process_dir / "segment_infos.json"
                if isinstance(segments_or_chapters[0], ChapterInfo):
                    # Für Kapitel-basierte Segmentierung
                    segment_info_data = [
                        {
                            "title": chapter.title,
                            "segments": [
                                {
                                    "file_path": str(segment.file_path.relative_to(process_dir)),
                                    "title": None  # Titel ist jetzt im Chapter
                                }
                                for segment in chapter.segments
                            ]
                        }
                        for chapter in segments_or_chapters
                    ]
                else:
                    # Für Standard-Segmentierung
                    segment_info_data = [
                        {
                            "file_path": str(segment.file_path.relative_to(process_dir)),
                            "title": segment.title
                        }
                            for segment in segments_or_chapters
                ]
                
                with open(segment_info_path, 'w', encoding='utf-8') as f:
                    json.dump(segment_info_data, f, indent=2, ensure_ascii=False)
                
                self.logger.info("Segment-Informationen gespeichert",
                               segment_count=len(segments_or_chapters),
                               file=str(segment_info_path))
            except Exception as e:
                self.logger.warning(f"Konnte Segment-Informationen nicht speichern: {str(e)}")
            
            return segments_or_chapters

        except Exception as e:
            self.logger.error("Fehler bei der Segmentierung", error=str(e))
            raise

    def _read_existing_transcript(self, process_dir: Path) -> Optional[TranscriptionResult]:
        """Liest eine existierende Transkriptionsdatei im JSON-Format.
        
        Args:
            process_dir (Path): Verzeichnis mit der Transkriptionsdatei
            
        Returns:
            Optional[TranscriptionResult]: Das validierte TranscriptionResult oder None wenn keine Datei existiert
        """
        transcript_file = process_dir / "segments_transcript.txt"
        if not transcript_file.exists():
            self.logger.info("Keine existierende Transkription gefunden ", process_dir=str(process_dir))
            return None
            
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.logger.info("Existierende Transkription gefunden", transcript_file=str(transcript_file))
                
                # Erstelle ein llModel für die Whisper-Nutzung
                whisper_model = llModel(
                    model=data.get('model', 'whisper-1'),
                    duration=0.0,  # Diese Information haben wir nicht
                    token_count=data.get('token_count', 0)
                )
                
                # Erstelle TranscriptionSegments aus den Segmentdaten
                segments = []
                for i, segment_data in enumerate(data.get('segments', [])):
                    segment = TranscriptionSegment(
                        text=segment_data.get('text', ''),
                        segment_id=i,  # Füge segment_id hinzu
                        title=segment_data.get('title')  # Füge auch title hinzu für Vollständigkeit
                    )
                    segments.append(segment)
                
                return TranscriptionResult(
                    text=data.get('text', ''),
                    detected_language=data.get('detected_language'),
                    segments=segments,
                    llms=[whisper_model]
                )
                
        except Exception as e:
            self.logger.warning(f"Fehler beim Lesen der existierenden Transkription: {str(e)}")
        return None

    async def process(self, audio_source: Union[str, Path, bytes], source_info: Dict[str, Any] = None, 
                     chapters: List[Dict[str, Any]] = None,
                     target_language: str = None, template: str = None,
                     skip_segments: List[int] = None) -> AudioProcessingResult:
        """
        Verarbeitet eine Audio-Datei.
        
        Args:
            audio_source: Kann sein:
                - bytes: Binäre Audio-Daten
                - str: URL oder lokaler Dateipfad
                - Path: Lokaler Dateipfad
            source_info: Zusätzliche Informationen über die Quelle
            chapters: Liste der Kapitel mit Start- und Endzeiten
            target_language: Zielsprache (ISO 639-1 code)
            template: Name der zu verwendenden Vorlage
            skip_segments: Liste von Segment-IDs die übersprungen werden sollen
            
        Returns:
            AudioProcessingResult: Typisiertes Ergebnis der Audio-Verarbeitung
        """
        temp_file_path = None
        audio = None
        try:
            # Speichere source_info für get_process_dir
            total_token_count = 0
            self.logger.info("2. Starte Audio-Verarbeitung")

            with self.measure_operation('audio_processing'):
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

                process_dir = self.get_process_dir(str(temp_file_path), source_info.get('original_filename'), source_info.get('video_id'))
                
                    # Prüfe auf existierende Transkription
                transcription_result = self._read_existing_transcript(process_dir)
                
                if transcription_result:
                    self.logger.info("Existierende Transkription gefunden")
                else:
                    audio = self.process_audio_file(str(temp_file_path))
                    
                    if not audio:
                        raise ProcessingError("Audio konnte nicht verarbeitet werden")

                    segment_infos = self.get_audio_segments(audio, process_dir, chapters, skip_segments)

                    # Transkription durchführen
                    self.logger.info(f"Verarbeite {len(segment_infos)} Segmente")
                    transcription_result = self.transcriber.transcribe_segments(
                        segment_infos, 
                        self.logger, 
                        target_language=target_language
                    )

                    # Cleanup segment files
                    # for info in segment_infos:
                    #    self._safe_delete(info.file_path)

                # Übersetze den kompletten Text wenn nötig
                detected_language = transcription_result.detected_language
                original_text = transcription_result.text
                duration = source_info.get('duration', 0)
                translated_text = None
                translation_model = None

                if template:
                    self.logger.info(f"3. Text transformation mit Vorlage wird ausgeführt {template}")
                    transformation_result = self.transformer.transformByTemplate(
                        source_text=transcription_result.text,
                        source_language=target_language,
                        target_language=target_language,
                        context=source_info,
                        template=template
                    )
                    # Token Count aus der Transformation hinzufügen
                    transcription_result = TranscriptionResult(
                        text=transformation_result.text,
                        detected_language=transcription_result.detected_language,
                        segments=transcription_result.segments,
                        llms=transcription_result.llms + transformation_result.llms
                    )

                elif detected_language and detected_language != target_language:
                    self.logger.info(f"4. Übersetze/Text-Zusammenfassung wird ausgeführt ({detected_language} -> {target_language})")
                    transformation_result = self.transformer.transform(
                        source_text=transcription_result.text,
                        source_language=detected_language,
                        target_language=target_language,
                        context=source_info
                    )
                    translated_text = transformation_result.text
                    translation_model = self.transformer.model
                    
                    # Token Count aus der Transformation hinzufügen
                    transcription_result = TranscriptionResult(
                        text=transformation_result.text,
                        detected_language=transcription_result.detected_language,
                        segments=transcription_result.segments,
                        llms=transcription_result.llms + transformation_result.llms
                    )

                # Erstelle das finale Ergebnis
                metadata = AudioMetadata(
                    duration=duration,
                    process_dir=str(process_dir),
                    args={
                        "target_language": target_language,
                        "template": template,
                        "original_text": original_text  # Speichere Original-Text für spätere Verwendung
                    }
                )
                
                result = AudioProcessingResult(
                    transcription=transcription_result,
                    metadata=metadata,
                    process_id=self.process_id  # Füge process_id hinzu
                )

                # Speichere das Ergebnis
                self._save_result(result, process_dir)
                
                return result

        except Exception as e:
            self.logger.error(f"Fehler bei der Audio-Verarbeitung: {str(e)}")
            self.logger.error(traceback.format_exc())
            raise ProcessingError(f"Audio-Verarbeitung fehlgeschlagen: {str(e)}")
            
                
    def _save_result(self, result: AudioProcessingResult, process_dir: Path) -> None:
        """
        Speichert das Verarbeitungsergebnis.
        
        Args:
            result (AudioProcessingResult): Das zu speichernde Ergebnis
            process_dir (Path): Verzeichnis für die Speicherung
        """
        try:
            # Speichere die komplette Transkription
            transcript_file = process_dir / "complete_transcript.txt"
            with open(transcript_file, 'w', encoding='utf-8') as f:
                json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
                
            self.logger.info("Ergebnis gespeichert", file=str(transcript_file))
            
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern des Ergebnisses: {str(e)}")
            raise ProcessingError(f"Speichern des Ergebnisses fehlgeschlagen: {str(e)}") 