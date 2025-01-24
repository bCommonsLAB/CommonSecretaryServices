from src.processors.base_processor import BaseProcessor
from src.utils.types import ContentMetadata, TechnicalMetadata, CompleteMetadata
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.logger import get_logger, ProcessingLogger
from src.core.config import Config
from src.core.exceptions import ProcessingError, FileSizeLimitExceeded, UnsupportedMimeTypeError, ContentExtractionError, ValidationError

import os
import mimetypes
import magic
from pathlib import Path
from typing import Dict, Any, Optional, Union, BinaryIO
import mutagen
from PIL import Image
from pypdf import PdfReader
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
                                     logger: ProcessingLogger = None) -> TechnicalMetadata:
        """Extrahiert technische Metadaten aus einer Datei.
        
        Args:
            binary_data: Binäre Daten oder Dateipfad
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

        try:
            # Binärdaten in temporäre Datei schreiben wenn nötig
            if isinstance(binary_data, (bytes, BinaryIO)):
                temp_file = self.temp_dir / f"temp_{self.process_id}"
                if isinstance(binary_data, bytes):
                    temp_file.write_bytes(binary_data)
                else:
                    binary_data.seek(0)
                    temp_file.write_bytes(binary_data.read())
                file_path = temp_file
            else:
                file_path = binary_data

            # Dateigröße prüfen
            file_size = os.path.getsize(file_path)
            if file_size > self.max_file_size:
                raise FileSizeLimitExceeded(
                    f"Datei zu groß: {file_size} Bytes (Maximum: {self.max_file_size} Bytes)")

            # MIME-Type ermitteln
            mime = magic.Magic(mime=True)
            file_mime = mime.from_file(str(file_path))
            
            # Prüfen ob MIME-Type unterstützt wird
            mime_base = file_mime.split('/')[0]
            if not any(supported.startswith(mime_base) or supported == file_mime 
                      for supported in self.supported_mime_types):
                raise UnsupportedMimeTypeError(f"MIME-Type nicht unterstützt: {file_mime}")

            # Basis-Metadaten
            metadata = {
                'file_size': file_size,
                'file_mime': file_mime,
                'file_extension': file_path.suffix.lower()
            }

            # Medienspezifische Metadaten extrahieren
            if file_mime.startswith('audio/') or file_mime.startswith('video/'):
                try:
                    media_info = mutagen.File(file_path)
                    if media_info:
                        metadata.update({
                            'media_duration': media_info.info.length if hasattr(media_info.info, 'length') else None,
                            'media_bitrate': getattr(media_info.info, 'bitrate', None),
                            'media_channels': getattr(media_info.info, 'channels', None),
                            'media_samplerate': getattr(media_info.info, 'sample_rate', None)
                        })
                except Exception as e:
                    logger.warning(f"Fehler bei Medien-Metadaten Extraktion: {str(e)}")

            elif file_mime.startswith('image/'):
                try:
                    with Image.open(file_path) as img:
                        metadata.update({
                            'image_width': img.width,
                            'image_height': img.height,
                            'image_colorspace': img.mode,
                        })
                except Exception as e:
                    logger.warning(f"Fehler bei Bild-Metadaten Extraktion: {str(e)}")

            elif file_mime == 'application/pdf':
                try:
                    with open(file_path, 'rb') as pdf_file:
                        pdf = PdfReader(pdf_file)
                        metadata.update({
                            'doc_pages': len(pdf.pages),
                            'doc_encrypted': pdf.is_encrypted,
                            'doc_software': pdf.metadata.get('/Producer', None) if pdf.metadata else None
                        })
                except Exception as e:
                    logger.warning(f"Fehler bei PDF-Metadaten Extraktion: {str(e)}")

            # Temporäre Datei löschen wenn erstellt
            if isinstance(binary_data, (bytes, BinaryIO)) and temp_file.exists():
                temp_file.unlink()

            # Metadaten validieren und zurückgeben
            technical_metadata = TechnicalMetadata(**metadata)
            
            processing_time = time.time() - start_time
            logger.info("Technische Metadaten extrahiert",
                       mime_type=file_mime,
                       file_size=file_size,
                       processing_time=processing_time)

            return technical_metadata

        except (FileSizeLimitExceeded, UnsupportedMimeTypeError) as e:
            if isinstance(binary_data, (bytes, BinaryIO)) and temp_file.exists():
                temp_file.unlink()
            raise
        except Exception as e:
            if isinstance(binary_data, (bytes, BinaryIO)) and temp_file.exists():
                temp_file.unlink()
            error_msg = f"Fehler bei der technischen Metadaten-Extraktion: {str(e)}"
            logger.error(error_msg,
                        error=str(e),
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc())
            raise ProcessingError(error_msg)

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
                transformed_content, template_result = self.transcriber.transform_by_template(
                    text=content,
                    target_language="de",
                    template=self.llm_config['template'],
                    context=context,
                    logger=logger
                )
                logger.debug("LLM Verarbeitung abgeschlossen")

            # Ergebnis validieren
            try:
                content_metadata = ContentMetadata.model_validate_json(transformed_content)
                
                # LLM Informationen aus template_result übernehmen wenn vorhanden
                if template_result and hasattr(template_result, 'llms'):
                    logger.debug("LLM Informationen gefunden", llm_count=len(template_result.llms))
                    # Hier könnten wir die LLM Informationen speichern
                
            except ValidationError as e:
                # Detaillierte Fehlerbehandlung
                error_details = []
                for error in e.errors():
                    error_details.append({
                        'field': '.'.join(str(x) for x in error['loc']),
                        'error': error['msg'],
                        'type': error['type']
                    })
                logger.error("Validierungsfehler bei Metadaten", 
                           error_details=error_details,
                           error_type="ValidationError")
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
                logger.debug("Technische Extraktion abgeschlossen")

            # 2. Kontext mit technischen Metadaten erweitern
            full_context = {
                'file_info': technical_metadata.serializable_dict(),  # Verwende die neue Methode
                **(context or {})
            }

            # 3. Inhaltliche Metadaten extrahieren
            with self.measure_operation('content_extraction'):
                content_metadata = await self.extract_content_metadata(
                    content=content or f"Datei: {getattr(binary_data, 'name', 'Unbekannt')}",
                    context=full_context,
                    logger=logger
                )
                logger.debug("Inhaltliche Extraktion abgeschlossen")

            # 4. Ergebnisse kombinieren - Verwende construct_validated da die Daten bereits validiert wurden
            result = CompleteMetadata.construct_validated(
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