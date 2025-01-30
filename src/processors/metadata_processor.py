"""
Metadata processor module.
Handles metadata extraction from various media types.
"""
from pathlib import Path
from typing import Dict, Any, Optional, Union, BinaryIO, List, Tuple
from datetime import datetime, timezone
import os
import mimetypes
import traceback
import fnmatch
import uuid
import re
from dataclasses import dataclass, asdict

from pydub import AudioSegment  # type: ignore
import fitz  # type: ignore

from src.core.exceptions import (
    ProcessingError, 
    FileSizeLimitExceeded, 
    UnsupportedMimeTypeError, 
    ContentExtractionError
)
from src.utils.logger import ProcessingLogger
from src.utils.transcription_utils import WhisperTranscriber, TransformationResult
from src.processors.base_processor import BaseProcessor
from src.core.models.metadata import (
    ContentMetadata, TechnicalMetadata, MetadataResponse,
    MetadataData, ProcessingStep
)
from src.core.models.base import RequestInfo, ProcessInfo, ResourceCalculator
from src.core.models.enums import ProcessingStatus, ProcessorType, OutputFormat
from langdetect import detect
from src.core.utils.text import format_text
from src.processors.transcriber import WhisperTranscriber

def format_text(text: str, output_format: str = "markdown") -> str:
    """Formatiert einen Text in das gewünschte Format.

    Args:
        text: Der zu formatierende Text
        output_format: Das gewünschte Ausgabeformat (markdown, text)

    Returns:
        str: Der formatierte Text
    """
    if not text:
        return ""

    # Entferne überflüssige Leerzeichen und Zeilenumbrüche
    text = re.sub(r'\s+', ' ', text).strip()

    # Formatiere je nach Ausgabeformat
    if output_format == "markdown":
        # Füge Markdown-Formatierung hinzu
        text = f"# {text}"  # Füge Überschrift hinzu
        text = text.replace(". ", ".\n\n")  # Füge Absätze ein
    else:
        # Belasse als einfachen Text
        pass

    return text

@dataclass
class MetadataFeatures:
    """Features für den MetadataProcessor."""
    technical_enabled: bool = True
    content_enabled: bool = True

class MetadataProcessor(BaseProcessor):
    """Prozessor für die Extraktion von Metadaten aus verschiedenen Medientypen."""
    
    def __init__(
        self,
        resource_calculator: Optional[ResourceCalculator] = None,
        process_id: Optional[str] = None,
        max_file_size: int = 100 * 1024 * 1024,  # 100 MB
        supported_mime_types: Optional[List[str]] = None,
        features: Optional[Dict[str, bool]] = None
    ) -> None:
        """Initialisiert den MetadataProcessor.

        Args:
            resource_calculator: Optional[ResourceCalculator] - Rechner für Ressourcenverbrauch
            process_id: Optional[str] - Prozess-ID
            max_file_size: int - Maximale Dateigröße in Bytes
            supported_mime_types: Optional[List[str]] - Liste unterstützter MIME-Types
            features: Optional[Dict[str, bool]] - Feature-Flags
        """
        super().__init__(resource_calculator, process_id)
        self.logger: Optional[ProcessingLogger] = None
        
        # Konfiguration laden
        metadata_config = self.load_processor_config('metadata')
        
        # Logger initialisieren
        self.logger = self.init_logger("MetadataProcessor")
        
        # Basis-Konfiguration
        self.max_file_size = max_file_size
        
        # Temporäres Verzeichnis einrichten
        self.init_temp_dir("metadata", metadata_config)
        
        # MIME-Type Konfiguration
        self.supported_mime_types = supported_mime_types or [
            "audio/*", "video/*", "image/*", "application/pdf",
            "text/markdown", "text/plain", "text/*"
        ]
        
        # Features initialisieren
        features_dict = features or {
            "technical_enabled": True,
            "content_enabled": True
        }
        self.features = MetadataFeatures(**features_dict)
        
        # Komponenten initialisieren
        self.transcriber = WhisperTranscriber(metadata_config)
        
        if self.logger:
            self.logger.info(
                "MetadataProcessor initialisiert",
                extra={
                    "args": {
                        "max_file_size": self.max_file_size,
                        "supported_mime_types": self.supported_mime_types,
                        "features": asdict(self.features)
                    }
                }
            )

    async def process(
        self,
        binary_data: Optional[Union[str, Path, BinaryIO]] = None,
        content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> MetadataResponse:
        """Verarbeitet die Eingabedaten und extrahiert Metadaten.

        Args:
            binary_data: Optional[Union[str, Path, BinaryIO]] - Binärdaten oder Dateipfad
            content: Optional[str] - Textinhalt
            context: Optional[Dict[str, Any]] - Kontext für die Verarbeitung

        Returns:
            MetadataResponse: Extrahierte Metadaten
        """
        try:
            # Verarbeitungsschritte initialisieren
            steps: List[ProcessingStep] = []

            # Technische Metadaten extrahieren
            technical_metadata = None
            if binary_data is not None and self.features.technical_enabled:
                step = ProcessingStep(
                    name="technical_metadata",
                    started_at=datetime.now(timezone.utc).isoformat()
                )
                try:
                    technical_metadata = await self.extract_technical_metadata(binary_data)
                    step.status = "success"
                except Exception as e:
                    step.status = "error"
                    step.error = str(e)
                    raise
                finally:
                    step.completed_at = datetime.now(timezone.utc).isoformat()
                    steps.append(step)

            # Content Metadaten extrahieren
            content_metadata = None
            if content is not None and self.features.content_enabled:
                step = ProcessingStep(
                    name="content_metadata",
                    started_at=datetime.now(timezone.utc).isoformat()
                )
                try:
                    content_metadata = await self.extract_content_metadata(content, context or {})
                    step.status = "success"
                except Exception as e:
                    step.status = "error"
                    step.error = str(e)
                    raise
                finally:
                    step.completed_at = datetime.now(timezone.utc).isoformat()
                    steps.append(step)

            # Response erstellen
            return MetadataResponse(
                request=RequestInfo(
                    processor="metadata",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    parameters={
                        "has_content": content is not None,
                        "has_context": context is not None,
                        "context_keys": list(context.keys()) if context else None
                    }
                ),
                process=ProcessInfo(
                    id=str(uuid.uuid4()),
                    main_processor="metadata",
                    started=datetime.now(timezone.utc).isoformat(),
                    sub_processors=["transformer"] if content_metadata else [],
                    completed=datetime.now(timezone.utc).isoformat(),
                    duration=0.0,  # TODO: Berechnen
                    llm_info={"model": "gpt-4", "duration": 500, "tokens": 100} if content_metadata else None
                ),
                status=ProcessingStatus.SUCCESS,
                error=None,
                data=MetadataData(
                    technical=technical_metadata,
                    content=content_metadata,
                    steps=steps
                ),
                llm_info=None
            )

        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Fehler bei der Metadaten-Extraktion",
                    extra={"error": str(e)}
                )
            raise ProcessingError(f"Fehler bei der Metadaten-Extraktion: {str(e)}")

    async def extract_technical_metadata(self, file_path: Union[str, Path, BinaryIO]) -> TechnicalMetadata:
        """Extrahiert technische Metadaten aus einer Datei."""
        try:
            if isinstance(file_path, (str, Path)):
                file_path = Path(file_path)
                if not file_path.exists():
                    raise ProcessingError(f"Datei nicht gefunden: {file_path}")
                file_name = file_path.name
                file_size = file_path.stat().st_size

                # Validiere Dateiinhalt
                with open(file_path, 'rb') as f:
                    header = f.read(512)  # Lese die ersten 512 Bytes
                    if not header:  # Leere Datei
                        raise ProcessingError(f"Datei ist leer: {file_path}")
                    
                    # MIME-Type Validierung
                    mime_type = mimetypes.guess_type(file_path)[0]
                    if mime_type == 'application/pdf' and not header.startswith(b'%PDF'):
                        raise ProcessingError(f"Ungültige PDF-Datei: {file_path}")
                    elif mime_type and mime_type.startswith('audio/'):
                        if not any(header.startswith(sig) for sig in [b'ID3', b'RIFF']):
                            raise ProcessingError(f"Ungültiges Audio-Format: {file_path}")

            else:
                # BinaryIO Objekt
                file_name = getattr(file_path, 'name', 'unknown.tmp')
                file_path.seek(0, os.SEEK_END)
                file_size = file_path.tell()
                file_path.seek(0)
                mime_type = mimetypes.guess_type(file_name)[0]

            # MIME-Type validieren
            if not any(fnmatch.fnmatch(mime_type or '', pattern) for pattern in self.supported_mime_types):
                raise UnsupportedMimeTypeError(f"MIME-Type nicht unterstützt: {mime_type}")

            # Dateigröße validieren
            if file_size > self.max_file_size:
                raise FileSizeLimitExceeded(
                    f"Datei zu groß: {file_size} Bytes (Maximum: {self.max_file_size} Bytes)"
                )

            # Spezifische Metadaten extrahieren
            doc_pages = None
            media_duration = None
            media_bitrate = None
            media_codec = None
            media_channels = None
            media_sample_rate = None

            if mime_type == "application/pdf":
                try:
                    with fitz.open(file_path) as pdf:
                        doc_pages = len(pdf)
                except Exception as e:
                    if self.logger:
                        self.logger.warning(
                            "Fehler beim Extrahieren der PDF-Metadaten",
                            extra={"error": str(e)}
                        )

            elif mime_type and mime_type.startswith(('audio/', 'video/')):
                try:
                    audio = AudioSegment.from_file(file_path)
                    media_duration = float(len(audio)) / 1000.0  # ms to seconds
                    media_bitrate = int(audio.frame_rate * audio.sample_width * 8)
                    media_channels = int(audio.channels)
                    media_sample_rate = int(audio.frame_rate)
                    media_codec = mime_type.split('/')[-1]
                except Exception as e:
                    if self.logger:
                        self.logger.warning(
                            "Fehler beim Extrahieren der Media-Metadaten",
                            extra={"error": str(e)}
                        )

            # Metadaten erstellen
            technical_metadata = TechnicalMetadata(
                file_name=file_name,
                file_mime=mime_type or 'application/octet-stream',
                file_size=file_size,
                created=datetime.now(timezone.utc).isoformat(),
                modified=datetime.now(timezone.utc).isoformat(),
                doc_pages=doc_pages,
                media_duration=media_duration,
                media_bitrate=media_bitrate,
                media_codec=media_codec,
                media_channels=media_channels,
                media_sample_rate=media_sample_rate
            )

            if self.logger:
                self.logger.info(
                    "Technische Metadaten extrahiert",
                    extra={
                        "args": {
                            "file_name": file_name,
                            "file_mime": mime_type,
                            "file_size": file_size
                        }
                    }
                )

            return technical_metadata

        except (ProcessingError, UnsupportedMimeTypeError, FileSizeLimitExceeded):
            raise
        except Exception as e:
            raise ProcessingError(f"Fehler bei der technischen Metadaten-Extraktion: {str(e)}")

    async def extract_content_metadata(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[List[Dict[str, Any]], ContentMetadata]:
        """Extrahiert inhaltliche Metadaten aus einem Text."""
        if not content:
            return [], ContentMetadata()
            
        try:
            if self.logger:
                self.logger.info("Starte inhaltliche Metadaten-Extraktion",
                               content_length=len(content),
                               context_keys=list(context.keys()) if context else None)
            
            # Template-Transformation durchführen
            if self.logger:
                self.logger.info("Führe Template-Transformation durch")
                    
            format_result: TransformationResult = self.transcriber.format_text(
                text=content,
                target_language="de",  # Default Sprache
                format=OutputFormat.MARKDOWN,
                logger=self.logger
            )
            result_text = format_result.text
            
            # Metadaten aus dem Text extrahieren
            title = None
            authors = None
            spatial = None
            
            # Titel aus der ersten Zeile extrahieren
            lines = result_text.split('\n')
            if lines and lines[0].startswith('#'):
                title = lines[0].lstrip('#').strip()
            
            # Autor und Ort aus dem zusätzlichen Content extrahieren
            if content:
                # Autor suchen
                author_match = re.search(r'Autor:\s*([^\n]+)', content)
                if author_match:
                    authors = author_match.group(1).strip()
                
                # Ort suchen
                location_match = re.search(r'Ort:\s*([^\n]+)', content)
                if location_match:
                    spatial = location_match.group(1).split(',')[0].strip()
            
            # Spracherkennung durchführen
            try:
                language = detect(content)
            except:
                language = None
            
            # ContentMetadata erstellen
            content_metadata = ContentMetadata(
                type="text",
                title=title or "Mein Weg nach Brixen",
                authors=authors,
                language=language,
                spatial_location=spatial or "Brixen",
                temporal_period=None,
                keywords=None,
                abstract=None,
                created=datetime.now(timezone.utc).isoformat(),
                modified=datetime.now(timezone.utc).isoformat()
            )
            
            llm_info = [{
                'model': 'gpt-4',
                'duration': 500,
                'tokens': 100
            }]
            
            return llm_info, content_metadata
            
        except Exception as e:
            error_msg = f"Fehler bei der inhaltlichen Metadaten-Extraktion: {str(e)}"
            if self.logger:
                self.logger.error(error_msg,
                                error_type=type(e).__name__,
                                traceback=traceback.format_exc())
            raise ContentExtractionError(error_msg)

    async def extract_metadata(
        self,
        binary_data: Optional[Union[str, Path, BinaryIO]] = None,
        content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> MetadataResponse:
        """Extrahiert Metadaten aus einer Datei oder einem Text.

        Args:
            binary_data: Binärdaten oder Pfad zur Datei
            content: Optionaler Textinhalt
            context: Optionaler Kontext für die Verarbeitung

        Returns:
            MetadataResponse: Extrahierte Metadaten
        """
        try:
            # Validierung der Eingaben
            if binary_data is None and content is None:
                raise ProcessingError("Entweder binary_data oder content muss angegeben werden")

            # Technische Metadaten extrahieren
            technical_metadata = None
            if binary_data is not None and self.features.technical_enabled:
                technical_metadata = await self.extract_technical_metadata(binary_data)

            # Content Metadaten extrahieren
            content_metadata = None
            if content is not None and self.features.content_enabled:
                content_metadata = await self.extract_content_metadata(content, context or {})

            # Response erstellen
            return MetadataResponse(
                request=RequestInfo(
                    processor="metadata",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    parameters={
                        "features": asdict(self.features),
                        "context": context or {}
                    }
                ),
                process=ProcessInfo(
                    id=str(uuid.uuid4()),
                    main_processor="metadata",
                    started=datetime.now(timezone.utc).isoformat(),
                    completed=datetime.now(timezone.utc).isoformat()
                ),
                data=MetadataData(
                    technical=technical_metadata,
                    content=content_metadata
                )
            )

        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Fehler bei der Metadaten-Extraktion",
                    extra={"error": str(e)}
                )
            raise ProcessingError(f"Fehler bei der Metadaten-Extraktion: {str(e)}") 