from src.processors.base_processor import BaseProcessor, BaseProcessorResponse
from src.utils.types import ContentMetadata, TechnicalMetadata, CompleteMetadata, ErrorInfo, RequestInfo, ProcessInfo, LLMInfo
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.logger import get_logger, ProcessingLogger
from src.core.config import Config
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, UnsupportedMimeTypeError, ContentExtractionError, ValidationError

import os
import mimetypes
import magic
from pathlib import Path
from typing import Dict, Any, Optional, Union, BinaryIO, Tuple, List
import mutagen
from PIL import Image
from pypdf import PdfReader
from datetime import datetime
import io
import traceback
import time
import uuid
import tempfile
import fitz
from pydub import AudioSegment
import fnmatch

class MetadataResponse(BaseProcessorResponse):
    """Response-Klasse für den MetadataProcessor."""
    
    def __init__(self):
        """Initialisiert die MetadataResponse."""
        super().__init__("metadata")
        self.technical_metadata: Optional[TechnicalMetadata] = None
        self.content_metadata: Optional[ContentMetadata] = None
        
    def add_technical_metadata(self, metadata: TechnicalMetadata):
        """Fügt technische Metadaten hinzu."""
        self.technical_metadata = metadata
        self.add_parameter("has_technical_metadata", True)
        
    def add_content_metadata(self, metadata: ContentMetadata):
        """Fügt inhaltliche Metadaten hinzu."""
        self.content_metadata = metadata
        self.add_parameter("has_content_metadata", True)

class MetadataProcessor(BaseProcessor):
    """Prozessor für die Extraktion von Metadaten aus verschiedenen Medientypen."""

    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """Initialisiert den MetadataProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Optionale Prozess-ID für das Logging
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Konfiguration laden
        metadata_config = self.load_processor_config('metadata')
        
        # Logger initialisieren
        self.init_logger("MetadataProcessor")
        
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
            ValidationError: Wenn die Validierung der Metadaten fehlschlägt
        """
        try:
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
            if not any(fnmatch.fnmatch(mime_type, pattern) for pattern in self.supported_mime_types):
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
                    self.logger.warning(
                        "Fehler beim Extrahieren der PDF-Metadaten",
                        extra={"error": str(e)}
                    )

            elif mime_type.startswith("audio/") or mime_type.startswith("video/"):
                try:
                    audio = AudioSegment.from_file(file_path)
                    media_duration = len(audio) / 1000.0  # Konvertiere zu Sekunden
                    media_bitrate = audio.frame_rate * audio.sample_width * 8
                    media_channels = audio.channels
                    media_sample_rate = audio.frame_rate
                    media_codec = mime_type.split("/")[1]
                except Exception as e:
                    self.logger.warning(
                        "Fehler beim Extrahieren der Media-Metadaten",
                        extra={"error": str(e)}
                    )

            # Metadaten erstellen
            technical_metadata = TechnicalMetadata(
                file_name=file_name,
                mime_type=mime_type,
                file_size=file_size,
                doc_pages=doc_pages,
                media_duration=media_duration,
                media_bitrate=media_bitrate,
                media_codec=media_codec,
                media_channels=media_channels,
                media_sample_rate=media_sample_rate
            )

            self.logger.info(
                "Technische Metadaten extrahiert",
                extra={
                    "args": {
                        "file_name": file_name,
                        "mime_type": mime_type,
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
            self.logger.info("Starte inhaltliche Metadaten-Extraktion",
                           content_length=len(content),
                           context_keys=list(context.keys()) if context else None)
            
            # Template-Transformation durchführen - ohne await, da keine Koroutine
            transformed_text, template_result, template_model_result = self.transcriber.transform_by_template(
                text=content,
                target_language="de",
                template="metadata",
                context=context
            )
            
            # LLM-Informationen aus template_result extrahieren
            llm_info = None
            if template_result and hasattr(template_result, 'llms') and template_result.llms:
                llm_info = [{
                    'model': llm.model,
                    'duration': llm.duration,
                    'tokens': llm.tokens
                } for llm in template_result.llms]
            
            return llm_info, template_model_result
            
        except Exception as e:
            error_msg = f"Fehler bei der inhaltlichen Metadaten-Extraktion: {str(e)}"
            self.logger.error(error_msg,
                            error_type=type(e).__name__,
                            traceback=traceback.format_exc())
            raise ContentExtractionError(error_msg)

    def _clean_metadata_dict(self, metadata: dict) -> dict:
        """Entfernt alle None-Werte aus einem Dictionary rekursiv und konvertiert Strings in Listen wo nötig.
        
        Args:
            metadata: Dictionary mit Metadaten
            
        Returns:
            Dict ohne None-Werte und mit konvertierten Listen
        """
        if not isinstance(metadata, dict):
            return metadata
            
        # Liste von Feldern, die Arrays sein sollten
        array_fields = {
            'authors', 'keywords', 'subject_areas', 'citations',
            'community_hashtags', 'community_mentions', 'blog_tags'
        }
            
        cleaned = {}
        for key, value in metadata.items():
            # None-Werte überspringen
            if value is None:
                continue
                
            # Wenn es ein Dict ist, rekursiv verarbeiten
            if isinstance(value, dict):
                cleaned[key] = self._clean_metadata_dict(value)
                
            # String zu Liste konvertieren wenn nötig
            elif key in array_fields and isinstance(value, str):
                # Kommaseparierte Werte splitten und trimmen
                items = [item.strip() for item in value.split(',') if item.strip()]
                if items:  # Nur nicht-leere Listen behalten
                    cleaned[key] = items
                    
            # Andere Werte direkt übernehmen
            else:
                cleaned[key] = value
                
        return cleaned

    def _prepare_technical_context(self, technical_metadata: TechnicalMetadata) -> dict:
        """Bereitet technische Metadaten als Kontext für das LLM vor.
        
        Args:
            technical_metadata: TechnicalMetadata Objekt
            
        Returns:
            Dict mit relevanten technischen Metadaten
        """
        # Konvertiere zu Dict und entferne None-Werte
        tech_dict = self._clean_metadata_dict(technical_metadata.model_dump())
        
        # Erstelle benutzerfreundliche Beschreibungen
        context = {}
        
        if 'file_size' in tech_dict:
            context['file_size'] = f"{tech_dict['file_size']} Bytes"
            
        if 'media_duration' in tech_dict:
            context['duration'] = f"{tech_dict['media_duration']} Sekunden"
            
        if 'doc_pages' in tech_dict:
            context['pages'] = tech_dict['doc_pages']
            
        if 'image_width' in tech_dict and 'image_height' in tech_dict:
            context['dimensions'] = f"{tech_dict['image_width']}x{tech_dict['image_height']}"
            
        # Füge Basis-Informationen hinzu
        context.update({
            'format': tech_dict.get('file_extension', ''),
            'mime_type': tech_dict.get('file_mime', '')
        })
        
        return context

    async def extract_metadata(self, binary_data: Union[str, Path, BinaryIO], content: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> MetadataResponse:
        """Extrahiert alle verfügbaren Metadaten aus einer Datei.

        Args:
            binary_data: Die Datei als Bytes, BinaryIO oder Pfad
            content: Optionaler Inhalt für die Extraktion von Content-Metadaten
            context: Optionaler Kontext für die Extraktion von Content-Metadaten

        Returns:
            MetadataResponse: Die extrahierten Metadaten mit Prozess-Informationen
        """
        # Response initialisieren
        response = MetadataResponse()
        response.add_parameter("has_content", content is not None)
        
        try:
            # Validiere Eingaben
            if content:
                content = self.validate_text(content, "content")
            context = self.validate_context(context)
            if context:
                response.add_parameter("context_keys", list(context.keys()))

            # Technische Metadaten extrahieren
            if self.features["technical_enabled"]:
                technical_metadata = await self.extract_technical_metadata(binary_data)
                response.add_technical_metadata(technical_metadata)
                response.add_sub_processor("technical_extractor")

            # Content-Metadaten extrahieren, wenn Inhalt vorhanden
            if content and self.features["content_enabled"]:
                llm_info, content_metadata = await self.extract_content_metadata(
                    content=content,
                    context=context or {}
                )
                if content_metadata:
                    response.add_content_metadata(content_metadata)
                    response.add_sub_processor("content_extractor")
                    
                if llm_info:
                    for info in llm_info:
                        response.add_llm_info(
                            model=info['model'],
                            purpose='content_extraction',
                            tokens=info['tokens'],
                            duration=info['duration']
                        )

            # Response vervollständigen
            response.set_completed()
            return response

        except Exception as e:
            # Fehler protokollieren
            self.logger.error(
                "Fehler bei der Metadaten-Extraktion",
                error=str(e),
                traceback=traceback.format_exc()
            )

            # Fehler-Response erstellen
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            response.set_error(error_info)
            return response 