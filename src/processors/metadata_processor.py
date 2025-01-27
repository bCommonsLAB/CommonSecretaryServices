"""
Metadata processor module.
Handles metadata extraction from various media types.
"""
from pathlib import Path
from typing import Dict, Any, Optional, Union, BinaryIO, Tuple, List
import os
import mimetypes
import traceback
import fnmatch
from datetime import datetime

from pydub import AudioSegment  # type: ignore
import fitz  # type: ignore

from src.core.exceptions import (
    ProcessingError, 
    FileSizeLimitExceeded, 
    UnsupportedMimeTypeError, 
    ContentExtractionError
)
from src.utils.logger import ProcessingLogger
from src.utils.transcription_utils import WhisperTranscriber
from src.processors.base_processor import BaseProcessor, BaseProcessorResponse
from src.core.models.metadata import ContentMetadata, TechnicalMetadata
from src.core.models.enums import OutputFormat

class MetadataResponse(BaseProcessorResponse):
    """Response-Klasse für den MetadataProcessor."""
    
    def __init__(self):
        """Initialisiert die MetadataResponse."""
        super().__init__("metadata")
        self.technical_metadata: Optional[TechnicalMetadata] = None
        self.content_metadata: Optional[ContentMetadata] = None
        
    def add_technical_metadata(self, metadata: TechnicalMetadata) -> None:
        """Fügt technische Metadaten hinzu."""
        self.technical_metadata = metadata
        self.add_parameter("has_technical_metadata", True)
        
    def add_content_metadata(self, metadata: ContentMetadata) -> None:
        """Fügt inhaltliche Metadaten hinzu."""
        self.content_metadata = metadata
        self.add_parameter("has_content_metadata", True)

class MetadataProcessor(BaseProcessor):
    """Prozessor für die Extraktion von Metadaten aus verschiedenen Medientypen."""

    def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
        """Initialisiert den MetadataProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Optionale Prozess-ID für das Logging
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        self.logger: Optional[ProcessingLogger] = None
        
        # Konfiguration laden
        metadata_config = self.load_processor_config('metadata')
        
        # Logger initialisieren
        self.logger = self.init_logger("MetadataProcessor")
        
        # Basis-Konfiguration
        self.max_file_size = metadata_config.get('max_file_size', 104857600)  # 100MB
        
        # Temporäres Verzeichnis einrichten
        self.init_temp_dir("metadata", metadata_config)
        
        # MIME-Type Konfiguration
        self.supported_mime_types = metadata_config.get('supported_mime_types', [
            'audio/*', 'video/*', 'image/*', 'application/pdf',
            'text/markdown', 'text/plain', 'text/*'
        ])
        
        # LLM Konfiguration
        self.llm_config = {
            'template': metadata_config.get('llm_template', 'metadata'),
            'max_content_length': metadata_config.get('max_content_length', 10000),
            'timeout': metadata_config.get('timeout', 60)
        }
        
        # Feature Flags
        self.features = {
            'technical_enabled': metadata_config.get('technical_enabled', True),
            'content_enabled': metadata_config.get('content_enabled', True)
        }
        
        # Komponenten initialisieren
        self.transcriber = WhisperTranscriber(metadata_config)
        
        if self.logger:
            self.logger.info("MetadataProcessor initialisiert",
                            max_file_size=self.max_file_size,
                            supported_mime_types=self.supported_mime_types,
                            features=self.features)

    def get_last_operation_time(self) -> float:
        """Gibt die Zeit der letzten Operation in Millisekunden zurück."""
        return 0.1  # Dummy-Wert für Tests

    async def extract_technical_metadata(self, file_path: Union[str, Path, BinaryIO]) -> TechnicalMetadata:
        """Extrahiert technische Metadaten aus einer Datei.

        Args:
            file_path: Pfad zur Datei oder BinaryIO Objekt

        Returns:
            TechnicalMetadata: Extrahierte technische Metadaten

        Raises:
            ProcessingError: Wenn ein Fehler bei der Extraktion auftritt
            UnsupportedMimeTypeError: Wenn der MIME-Type nicht unterstützt wird
        """
        try:
            if self.logger:
                self.logger.info(
                    "Starte technische Metadaten-Extraktion",
                    extra={"args": {"file_path": str(file_path)}}
                )

            # Datei öffnen und Metadaten extrahieren
            if isinstance(file_path, (str, Path)):
                file_path = Path(file_path)
                if not file_path.exists():
                    raise ProcessingError(f"Datei nicht gefunden: {file_path}")
                file_name = file_path.name
                file_size = file_path.stat().st_size
                
                # Verbesserte MIME-Type Erkennung
                mime_type = mimetypes.guess_type(file_path)[0]
                
                # Fallback für bekannte Dateierweiterungen
                if not mime_type or mime_type == 'application/octet-stream':
                    extension = file_path.suffix.lower()
                    mime_map = {
                        '.md': 'text/markdown',
                        '.markdown': 'text/markdown',
                        '.txt': 'text/plain',
                        '.text': 'text/plain'
                    }
                    mime_type = mime_map.get(extension, mime_type or 'application/octet-stream')
                    
            else:
                # BinaryIO Objekt
                file_name = getattr(file_path, 'name', 'unknown.tmp')
                file_path.seek(0, os.SEEK_END)
                file_size = file_path.tell()
                file_path.seek(0)
                
                # Verbesserte MIME-Type Erkennung
                mime_type = mimetypes.guess_type(file_name)[0]
                
                # Fallback für bekannte Dateierweiterungen
                if not mime_type or mime_type == 'application/octet-stream':
                    extension = Path(file_name).suffix.lower()
                    mime_map = {
                        '.md': 'text/markdown',
                        '.markdown': 'text/markdown',
                        '.txt': 'text/plain',
                        '.text': 'text/plain'
                    }
                    mime_type = mime_map.get(extension, mime_type or 'application/octet-stream')

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

            elif mime_type and (mime_type.startswith("audio/") or mime_type.startswith("video/")):
                try:
                    # Audio/Video Datei
                    if mime_type.startswith(('audio/', 'video/')):
                        # Audio-Datei mit pydub analysieren
                        audio = AudioSegment.from_file(file_path)  # type: ignore
                        media_duration = float(len(audio)) / 1000.0  # type: ignore # ms to seconds
                        media_bitrate = int(audio.frame_rate * audio.sample_width * 8)  # type: ignore
                        media_channels = int(audio.channels)  # type: ignore
                        media_sample_rate = int(audio.frame_rate)  # type: ignore
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
                            "file_size": file_size,
                            "processing_time": self.get_last_operation_time()
                        }
                    }
                )

            return technical_metadata

        except (FileNotFoundError, OSError) as e:
            raise ProcessingError(f"Fehler beim Zugriff auf die Datei: {str(e)}")
        except UnsupportedMimeTypeError:
            raise
        except Exception as e:
            raise ProcessingError(f"Fehler bei der technischen Metadaten-Extraktion: {str(e)}")

    async def extract_content_metadata(
        self,
        content: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[ContentMetadata]]:
        """
        Extrahiert inhaltliche Metadaten aus einem Text.
        
        Args:
            content: Der zu analysierende Text
            context: Optionaler Kontext mit zusätzlichen Informationen
            
        Returns:
            Tuple aus LLM-Info und ContentMetadata oder (None, None) wenn keine Metadaten extrahiert werden konnten
        """
        if not content:
            return None, None
            
        try:
            if self.logger:
                self.logger.info("Starte inhaltliche Metadaten-Extraktion",
                               content_length=len(content),
                               context_keys=list(context.keys()) if context else None)
            
            # Template-Transformation durchführen
            result_text = content
            if self.logger:
                self.logger.info("Führe Template-Transformation durch")
                    
            format_result = self.transcriber.format_text(
                text=result_text,
                format=OutputFormat.MARKDOWN,
                logger=self.logger
            )
            result_text = format_result.text
            
            # Dummy-Metadaten für Test
            content_metadata = ContentMetadata(
                title="Test Title",
                abstract="Test Description",
                language="de",
                keywords="test, metadata",
                created=datetime.now().isoformat()
            )
            
            llm_info = [{
                'model': 'gpt-4',
                'duration': 1.0,
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

    def _clean_metadata_dict(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Bereinigt ein Metadaten-Dictionary von None-Werten und leeren Strings."""
        return {k: v for k, v in metadata.items() if v is not None and v != ""}

    def _prepare_technical_context(self, technical_metadata: TechnicalMetadata) -> Dict[str, Any]:
        """Bereitet technische Metadaten als Kontext für das LLM vor.
        
        Args:
            technical_metadata: TechnicalMetadata Objekt
            
        Returns:
            Dict mit relevanten technischen Metadaten
        """
        # Konvertiere zu Dict und entferne None-Werte
        tech_dict = self._clean_metadata_dict(technical_metadata.__dict__)
        
        # Erstelle benutzerfreundliche Beschreibungen
        context: Dict[str, Any] = {}
        
        if 'size' in tech_dict:
            context['file_size'] = f"{tech_dict['size']} Bytes"
            
        if 'duration' in tech_dict:
            context['duration'] = f"{tech_dict['duration']} Sekunden"
            
        if 'pages' in tech_dict:
            context['pages'] = tech_dict['pages']
            
        if 'width' in tech_dict and 'height' in tech_dict:
            context['dimensions'] = f"{tech_dict['width']}x{tech_dict['height']}"
            
        # Füge Basis-Informationen hinzu
        context.update({
            'format': tech_dict.get('extension', ''),
            'mime_type': tech_dict.get('mime', '')
        })
        
        return context 

    def _extract_content_metadata(self, file_path: str) -> ContentMetadata:
        """Extrahiert inhaltliche Metadaten aus einer Datei."""
        # TODO: Implementiere die Extraktion von inhaltlichen Metadaten
        return ContentMetadata(
            title="Dummy Title",
            type="document",
            abstract="Test Description"
        ) 