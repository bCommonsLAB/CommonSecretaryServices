from .base_processor import BaseProcessor
from utils.types import ContentMetadata, TechnicalMetadata, CompleteMetadata
from utils.transcription_utils import WhisperTranscriber
from utils.logger import get_logger, ProcessingLogger
from core.config import Config
from core.exceptions import ProcessingError, FileSizeLimitExceeded, UnsupportedMimeTypeError, ContentExtractionError, ValidationError

import os
import mimetypes
import magic
from pathlib import Path
from typing import Dict, Any, Optional, Union, BinaryIO
import mutagen
from PIL import Image
import PyPDF2
from datetime import datetime
import io
import traceback
import time

class MetadataProcessor(BaseProcessor):
    """Prozessor für die Extraktion von Metadaten aus verschiedenen Medientypen."""

    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """Initialisiert den MetadataProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Optionale Prozess-ID für das Logging
        """
        super().__init__(process_id=process_id)
        
        # Konfiguration laden
        config = Config()
        processors_config = config.get('processors', {})
        metadata_config = processors_config.get('metadata', {})
        
        # Logger initialisieren
        self.logger = get_logger(process_id=self.process_id, processor_name="MetadataProcessor")
        
        # Basis-Konfiguration
        self.max_file_size = metadata_config.get('max_file_size', 104857600)  # 100MB
        self.temp_dir = Path(metadata_config.get('temp_dir', "temp-processing/metadata"))
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # MIME-Type Konfiguration
        self.supported_mime_types = metadata_config.get('supported_mime_types', [
            'audio/*', 'video/*', 'image/*', 'application/pdf'
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

    async def extract_technical_metadata(self, 
                                      binary_data: Union[bytes, BinaryIO, Path],
                                      mime_type: str = None,
                                      file_extension: str = None,
                                      logger: ProcessingLogger = None) -> TechnicalMetadata:
        """Extrahiert technische Metadaten aus binären Daten oder einer Datei.
        
        Args:
            binary_data: Binäre Daten als bytes, file-like object oder Dateipfad
            mime_type: Optional vorgegebener MIME-Type
            file_extension: Optional vorgegebene Dateiendung
            logger: Logger-Instanz
            
        Returns:
            TechnicalMetadata: Die extrahierten technischen Metadaten
            
        Raises:
            FileSizeLimitExceeded: Wenn die Datei zu groß ist
            UnsupportedMimeTypeError: Wenn der MIME-Type nicht unterstützt wird
            ProcessingError: Bei anderen Fehlern während der Extraktion
        """
        logger = logger or self.logger
        start_time = time.time()
        logger.info("Starte technische Metadaten-Extraktion")

        if not self.features['technical_enabled']:
            logger.warning("Technische Metadaten-Extraktion deaktiviert")
            return TechnicalMetadata(
                file_size=0,
                file_mime="unknown",
                file_extension="unknown"
            )

        # Konvertiere Input in temporäre Datei wenn nötig
        temp_file = None
        try:
            if isinstance(binary_data, (str, Path)):
                file_path = Path(binary_data)
                if not file_path.exists():
                    raise ProcessingError(f"Datei nicht gefunden: {file_path}")
                
                # Prüfe Dateigröße
                if file_path.stat().st_size > self.max_file_size:
                    raise FileSizeLimitExceeded(
                        f"Datei zu groß: {file_path.stat().st_size} Bytes "
                        f"(Maximum: {self.max_file_size} Bytes)"
                    )
            else:
                # Erstelle temporäre Datei
                temp_file = Path(self.temp_dir) / f"temp_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                if isinstance(binary_data, bytes):
                    if len(binary_data) > self.max_file_size:
                        raise FileSizeLimitExceeded(
                            f"Daten zu groß: {len(binary_data)} Bytes "
                            f"(Maximum: {self.max_file_size} Bytes)"
                        )
                    temp_file.write_bytes(binary_data)
                else:  # file-like object
                    with open(temp_file, 'wb') as f:
                        f.write(binary_data.read())
                file_path = temp_file

            # Basis Datei-Informationen
            file_size = file_path.stat().st_size
            detected_mime = magic.from_file(str(file_path), mime=True)
            mime_type = mime_type or detected_mime
            file_extension = file_extension or file_path.suffix.lower()
            
            # Prüfe MIME-Type Support
            mime_base = mime_type.split('/')[0]
            if not any(supported.startswith(mime_base) or supported == mime_type 
                      for supported in self.supported_mime_types):
                raise UnsupportedMimeTypeError(f"Nicht unterstützter MIME-Type: {mime_type}")

            metadata_dict = {
                "file_size": file_size,
                "file_mime": mime_type,
                "file_extension": file_extension
            }

            # Medienspezifische Details basierend auf MIME-Type
            if mime_type.startswith('audio/') or mime_type.startswith('video/'):
                try:
                    with self.measure_operation('media_analysis'):
                        media_info = mutagen.File(file_path)
                        if media_info:
                            metadata_dict.update({
                                "media_duration": media_info.info.length if hasattr(media_info.info, 'length') else None,
                                "media_bitrate": getattr(media_info.info, 'bitrate', None),
                                "media_channels": getattr(media_info.info, 'channels', None),
                                "media_samplerate": getattr(media_info.info, 'sample_rate', None)
                            })
                            logger.debug("Audio/Video Metadaten extrahiert",
                                       duration=metadata_dict.get('media_duration'),
                                       bitrate=metadata_dict.get('media_bitrate'),
                                       operation_time=self.get_last_operation_time())
                except Exception as e:
                    logger.warning("Fehler bei der Medien-Analyse", 
                                 error=str(e),
                                 error_type=type(e).__name__,
                                 traceback=traceback.format_exc())

            # Bild-spezifische Details
            elif mime_type.startswith('image/'):
                try:
                    with self.measure_operation('image_analysis'):
                        with Image.open(file_path) as img:
                            metadata_dict.update({
                                "image_width": img.width,
                                "image_height": img.height,
                                "image_colorspace": img.mode,
                                "image_dpi": img.info.get('dpi', None)
                            })
                            logger.debug("Bild Metadaten extrahiert",
                                       dimensions=f"{img.width}x{img.height}",
                                       colorspace=img.mode,
                                       operation_time=self.get_last_operation_time())
                except Exception as e:
                    logger.warning("Fehler bei der Bild-Analyse", 
                                 error=str(e),
                                 error_type=type(e).__name__,
                                 traceback=traceback.format_exc())

            # PDF-spezifische Details
            elif mime_type == 'application/pdf':
                try:
                    with self.measure_operation('pdf_analysis'):
                        with open(file_path, 'rb') as pdf_file:
                            pdf_reader = PyPDF2.PdfReader(pdf_file)
                            metadata_dict.update({
                                "doc_pages": len(pdf_reader.pages),
                                "doc_encrypted": pdf_reader.is_encrypted,
                                "doc_software": pdf_reader.metadata.get('/Producer', None) if pdf_reader.metadata else None
                            })
                            logger.debug("PDF Metadaten extrahiert",
                                       pages=metadata_dict['doc_pages'],
                                       encrypted=metadata_dict['doc_encrypted'],
                                       operation_time=self.get_last_operation_time())
                except Exception as e:
                    logger.warning("Fehler bei der PDF-Analyse", 
                                 error=str(e),
                                 error_type=type(e).__name__,
                                 traceback=traceback.format_exc())

            processing_time = time.time() - start_time
            logger.info("Technische Metadaten extrahiert",
                       file_size=metadata_dict['file_size'],
                       mime_type=metadata_dict['file_mime'],
                       processing_time=processing_time)

            return TechnicalMetadata(**metadata_dict)

        except (FileSizeLimitExceeded, UnsupportedMimeTypeError) as e:
            logger.error(str(e), 
                        error_type=type(e).__name__)
            raise
        except Exception as e:
            error_msg = f"Fehler bei der technischen Metadaten-Extraktion: {str(e)}"
            logger.error(error_msg, 
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            raise ProcessingError(error_msg)
        finally:
            # Cleanup
            if temp_file and temp_file.exists():
                temp_file.unlink()

    async def extract_content_metadata(self,
                                    content: str,
                                    context: Dict[str, Any] = None,
                                    logger: ProcessingLogger = None) -> ContentMetadata:
        """Extrahiert inhaltliche Metadaten aus einem Text mittels LLM.
        
        Args:
            content: Der zu analysierende Text (z.B. Beschreibung, Transkription)
            context: Zusätzliche Kontextinformationen
            logger: Logger-Instanz
            
        Returns:
            ContentMetadata: Die extrahierten inhaltlichen Metadaten
            
        Raises:
            ContentExtractionError: Bei Fehlern während der Extraktion
            ValidationError: Bei ungültigen Metadaten
        """
        logger = logger or self.logger
        start_time = time.time()
        logger.info("Starte inhaltliche Metadaten-Extraktion",
                   content_length=len(content),
                   context_keys=list(context.keys()) if context else None)

        if not self.features['content_enabled']:
            logger.warning("Inhaltliche Metadaten-Extraktion deaktiviert")
            return ContentMetadata(
                type="unknown",
                created=datetime.now(),
                modified=datetime.now(),
                title="",
                authors=[],
                language="unknown"
            )

        try:
            # Prüfe Content-Länge
            if len(content) > self.llm_config['max_content_length']:
                logger.warning("Content zu lang, wird gekürzt",
                             original_length=len(content),
                             max_length=self.llm_config['max_content_length'])
                content = content[:self.llm_config['max_content_length']]

            # Template-Transformation durchführen
            with self.measure_operation('llm_processing'):
                content_result, _ = await self.transcriber.transform_by_template(
                    text=content,
                    target_language="de",
                    template=self.llm_config['template'],
                    context=context,
                    logger=logger
                )
                logger.debug("LLM Verarbeitung abgeschlossen",
                           operation_time=self.get_last_operation_time())

            # Ergebnis validieren
            try:
                content_metadata = ContentMetadata.parse_raw(content_result)
            except Exception as e:
                raise ValidationError(f"Ungültige Metadaten: {str(e)}")

            processing_time = time.time() - start_time
            logger.info("Inhaltliche Metadaten extrahiert",
                       type=content_metadata.type,
                       title=content_metadata.title,
                       processing_time=processing_time)

            return content_metadata

        except ValidationError as e:
            logger.error("Validierungsfehler", 
                        error=str(e),
                        error_type=type(e).__name__)
            raise
        except Exception as e:
            error_msg = f"Fehler bei der inhaltlichen Metadaten-Extraktion: {str(e)}"
            logger.error(error_msg, 
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            raise ContentExtractionError(error_msg)

    async def extract_metadata(self, 
                             binary_data: Union[bytes, BinaryIO, Path],
                             content: str = None,
                             context: Dict[str, Any] = None,
                             logger: ProcessingLogger = None) -> CompleteMetadata:
        """Extrahiert sowohl technische als auch inhaltliche Metadaten.
        
        Args:
            binary_data: Binäre Daten oder Dateipfad
            content: Optional vorhandener Text für die Analyse
            context: Zusätzliche Kontextinformationen
            logger: Logger-Instanz
            
        Returns:
            CompleteMetadata: Kombinierte technische und inhaltliche Metadaten
            
        Raises:
            FileSizeLimitExceeded: Wenn die Datei zu groß ist
            UnsupportedMimeTypeError: Wenn der MIME-Type nicht unterstützt wird
            ContentExtractionError: Bei Fehlern während der Inhaltsextraktion
            ValidationError: Bei ungültigen Metadaten
            ProcessingError: Bei anderen Fehlern während der Extraktion
        """
        logger = logger or self.logger
        start_time = time.time()
        logger.info("Starte kombinierte Metadaten-Extraktion")

        try:
            # 1. Technische Metadaten extrahieren
            with self.measure_operation('technical_extraction'):
                technical_metadata = await self.extract_technical_metadata(
                    binary_data=binary_data,
                    logger=logger
                )
                logger.debug("Technische Extraktion abgeschlossen",
                           operation_time=self.get_last_operation_time())

            # 2. Kontext mit technischen Metadaten erweitern
            full_context = {
                'file_info': technical_metadata.dict(),
                **(context or {})
            }

            # 3. Inhaltliche Metadaten extrahieren
            with self.measure_operation('content_extraction'):
                content_metadata = await self.extract_content_metadata(
                    content=content or f"Datei: {getattr(binary_data, 'name', 'Unbekannt')}",
                    context=full_context,
                    logger=logger
                )
                logger.debug("Inhaltliche Extraktion abgeschlossen",
                           operation_time=self.get_last_operation_time())

            # 4. Ergebnisse kombinieren
            result = CompleteMetadata(
                content=content_metadata,
                technical=technical_metadata
            )

            processing_time = time.time() - start_time
            logger.info("Metadaten-Extraktion abgeschlossen",
                       file_type=technical_metadata.file_mime,
                       content_type=content_metadata.type,
                       total_processing_time=processing_time)

            return result

        except (FileSizeLimitExceeded, UnsupportedMimeTypeError, 
                ContentExtractionError, ValidationError) as e:
            logger.error(str(e), 
                        error_type=type(e).__name__)
            raise
        except Exception as e:
            error_msg = f"Fehler bei der Metadaten-Extraktion: {str(e)}"
            logger.error(error_msg, 
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            raise ProcessingError(error_msg) 