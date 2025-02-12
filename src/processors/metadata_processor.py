"""
Metadata processor module.
Handles metadata extraction from various media types.
"""
import fnmatch
import mimetypes
import os
import traceback
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Protocol, Tuple, Union, cast, TypeVar

import fitz  # type: ignore
from pydub import AudioSegment  # type: ignore
from werkzeug.datastructures import FileStorage

from src.core.exceptions import (ContentExtractionError, FileSizeLimitExceeded,
                                 ProcessingError, UnsupportedMimeTypeError)
from src.core.models.base import ProcessInfo, RequestInfo
from src.core.models.enums import ProcessingStatus
from src.core.models.metadata import (ContentMetadata, ErrorInfo, MetadataData,
                                      MetadataResponse, TechnicalMetadata)
from src.core.models.transformer import TransformerResponse
from src.processors.base_processor import BaseProcessor
from src.processors.transformer_processor import TransformerProcessor
from src.utils.resource_calculator import ResourceCalculator
from src.core.models.llm import LLMInfo

T = TypeVar('T', bound=AudioSegment)
from_file = AudioSegment.from_file  # type: ignore

class AudioSegmentProtocol(Protocol):
    frame_rate: int
    sample_width: int
    channels: int
    def __len__(self) -> int: ...

class FileStorageProtocol(Protocol):
    """Protocol für FileStorage-ähnliche Objekte."""
    filename: str
    content_type: Optional[str]
    def seek(self, offset: int, whence: int = 0) -> int: ...
    def tell(self) -> int: ...

@dataclass
class MetadataFeatures:
    """Features für den MetadataProcessor."""
    technical_enabled: bool = True
    content_enabled: bool = True

class MetadataProcessor(BaseProcessor):
    """Prozessor für die Extraktion von Metadaten aus verschiedenen Medientypen."""
    
    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        process_id: Optional[str] = None,
        max_file_size: int = 100 * 1024 * 1024,
        supported_mime_types: Optional[List[str]] = None,
        features: Optional[Dict[str, bool]] = None
    ) -> None:
        """Initialisiert den MetadataProcessor."""
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        try:
            # Konfiguration laden
            self.load_processor_config('metadata')
            
            # Basis-Konfiguration
            self.max_file_size = max_file_size
            
            # MIME-Type Konfiguration
            self.supported_mime_types = supported_mime_types or [
                "audio/*", "video/*", "image/*", "application/pdf",
                "text/markdown", "text/plain", "text/*"
            ]
            
            # Features initialisieren
            self.features = MetadataFeatures(**(features or {
                "technical_enabled": True,
                "content_enabled": True
            }))
            
            # Transformer für Content-Analyse
            self.transformer = TransformerProcessor(resource_calculator, process_id)
            
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
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des MetadataProcessors",
                            error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def validate_binary_data(self, data: Optional[Union[str, Path, BinaryIO]], param_name: str) -> Optional[Union[str, Path, BinaryIO]]:
        """Validiert die Binärdaten."""
        if data is None:
            return None
            
        if isinstance(data, (str, Path)):
            path = Path(data)
            if not path.exists():
                raise ValueError(f"{param_name}: Datei existiert nicht: {path}")
            if not path.is_file():
                raise ValueError(f"{param_name}: Ist kein File: {path}")
                
        return data

    def validate_mime_type(self, mime_type: Optional[str]) -> bool:
        """Validiert den MIME-Type."""
        if not mime_type:
            return True  # Akzeptiere fehlenden MIME-Type, da wir einen Standard verwenden
        return any(fnmatch.fnmatch(mime_type, pattern) for pattern in self.supported_mime_types)

    async def process(
        self,
        binary_data: Optional[Union[str, Path, BinaryIO]] = None,
        content: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> MetadataResponse:
        """Verarbeitet die Eingabedaten und extrahiert Metadaten."""
        start_time: datetime = datetime.now(timezone.utc)
        
        # Response initialisieren
        response = MetadataResponse(
            request=RequestInfo(
                processor="metadata",
                timestamp=start_time.isoformat(),
                parameters={
                    "has_binary": binary_data is not None,
                    "has_content": content is not None,
                    "context": context
                }
            ),
            process=ProcessInfo(
                id=self.process_id or str(uuid.uuid4()),
                main_processor="metadata",
                started=datetime.now().isoformat()
            ),
            data=MetadataData(
                technical=TechnicalMetadata(
                    file_name="unknown.tmp",
                    file_mime="application/octet-stream",
                    file_size=1,
                    created=start_time.isoformat(),
                    modified=start_time.isoformat()
                )
            ),
            status=ProcessingStatus.PENDING
        )
        
        try:
            # Validiere Eingaben
            binary_data = self.validate_binary_data(binary_data, "binary_data")
            
            # Technische Metadaten extrahieren
            technical_metadata = None
            if binary_data is not None and self.features.technical_enabled:
                try:
                    technical_metadata = await self.extract_technical_metadata(binary_data)
                except Exception as e:
                    if self.logger:
                        self.logger.error("Fehler bei der technischen Metadaten-Extraktion", error=e)
                    raise

            # Content Metadaten extrahieren
            content_metadata = None
            llm_info = None
            if content is not None and self.features.content_enabled:
                try:
                    llm_info, content_metadata = await self.extract_content_metadata(content, context)
                except Exception as e:
                    if self.logger:
                        self.logger.error("Fehler bei der Content-Metadaten-Extraktion", error=e)
                    raise

            # Erfolgreiche Response erstellen
            end_time: datetime = datetime.now(timezone.utc)
            return MetadataResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=end_time.isoformat(),
                    duration=float((end_time - start_time).total_seconds() * 1000),
                    sub_processors=['transformer'] if content_metadata else []
                ),
                data=MetadataData(
                    technical=technical_metadata,
                    content=content_metadata
                ),
                llm_info=llm_info,
                status=ProcessingStatus.SUCCESS
            )

        except Exception as e:
            if self.logger:
                self.logger.error(
                    "Fehler bei der Metadaten-Extraktion",
                    error=e,
                    traceback=traceback.format_exc()
                )
            
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            
            end_time = datetime.now(timezone.utc)
            return MetadataResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor="metadata",
                    started=start_time.isoformat(),
                    completed=end_time.isoformat(),
                    duration=float((end_time - start_time).total_seconds() * 1000)
                ),
                data=MetadataData(
                    technical=TechnicalMetadata(
                        file_name="error.tmp",
                        file_mime="application/octet-stream",
                        file_size=0,
                        created=end_time.isoformat(),
                        modified=end_time.isoformat()
                    ),
                    content=None
                ),
                error=error_info,
                status=ProcessingStatus.ERROR
            )

    async def extract_technical_metadata(self, file_path: Union[str, Path, FileStorage, BinaryIO]) -> TechnicalMetadata:
        """Extrahiert technische Metadaten aus einer Datei."""
        try:
            # Dateiinformationen extrahieren
            if isinstance(file_path, FileStorage):
                # FileStorage Objekt
                file_name = file_path.filename or 'unknown.tmp'
                mime_type = file_path.content_type or mimetypes.guess_type(file_name)[0]
                file_path.seek(0, os.SEEK_END)
                file_size = file_path.tell()
                file_path.seek(0)
            elif isinstance(file_path, (str, Path)):
                # String oder Path Objekt
                file_path = Path(file_path)
                if not file_path.exists():
                    raise ProcessingError(f"Datei nicht gefunden: {file_path}")
                file_name = file_path.name
                file_size = file_path.stat().st_size
                mime_type = mimetypes.guess_type(str(file_path))[0]
            else:
                # BinaryIO Objekt
                if hasattr(file_path, 'name'):
                    file_name = getattr(file_path, 'name', 'unknown.tmp')
                else:
                    file_name = 'unknown.tmp'
                mime_type = mimetypes.guess_type(file_name)[0]
                current_pos = file_path.tell()
                file_path.seek(0, os.SEEK_END)
                file_size = file_path.tell()
                file_path.seek(current_pos)
                

            # MIME-Type validieren
            if not any(fnmatch.fnmatch(mime_type or '', pattern) for pattern in self.supported_mime_types):
                raise UnsupportedMimeTypeError(f"MIME-Type nicht unterstützt: {mime_type}")

            # Dateigröße validieren
            if file_size > self.max_file_size:
                raise FileSizeLimitExceeded(
                    f"Datei zu groß: {file_size} Bytes (Maximum: {self.max_file_size} Bytes)"
                )

      
            # Spezifische Metadaten extrahieren
            doc_pages: Optional[int] = None
            media_duration: Optional[float] = None
            media_bitrate: Optional[int] = None
            media_codec: Optional[str] = None
            media_channels: Optional[int] = None
            media_sample_rate: Optional[int] = None

            if mime_type == "application/pdf":
                try:
                    with fitz.open(file_path) as pdf:
                        doc_pages = len(pdf)
                except Exception as e:
                    self.logger.warning(
                        "Fehler beim Extrahieren der PDF-Metadaten",
                        extra={"error": str(e)}
                    )

            elif mime_type and mime_type.startswith(('audio/', 'video/')):
                try:
                    # Format-Mapping für bekannte MIME-Types
                    format_mapping = {
                        'audio/x-m4a': 'm4a',
                        'audio/mp4': 'm4a',
                        'audio/mpeg': 'mp3',
                        'audio/ogg': 'ogg',
                        'audio/wav': 'wav',
                        'audio/x-wav': 'wav',
                        'audio/webm': 'webm',
                        'video/mp4': 'mp4',
                        'video/webm': 'webm'
                    }
                    
                    # Format aus MIME-Type oder Dateiendung ermitteln
                    format_from_mime = format_mapping.get(mime_type)
                    format_from_ext = file_name.split('.')[-1].lower() if '.' in file_name else None
                    audio_format = format_from_mime or format_from_ext or mime_type.split('/')[-1]
                    
                    # Für FileStorage Objekte müssen wir den Inhalt in einen temporären BytesIO Buffer lesen
                    if isinstance(file_path, FileStorage):
                        from io import BytesIO
                        file_data = BytesIO(file_path.read())
                        file_path.seek(0)  # Position zurücksetzen
                        try:
                            audio: AudioSegmentProtocol = cast(AudioSegmentProtocol, from_file(file_data, format=audio_format))
                        except Exception as decode_error:
                            self.logger.warning(
                                "Fehler beim Dekodieren mit primärem Format, versuche Alternativen",
                                extra={
                                    "error": str(decode_error),
                                    "primary_format": audio_format
                                }
                            )
                            # Versuche alternative Formate wenn primäres Format fehlschlägt
                            alternative_formats = ['m4a', 'mp4', 'mp3', 'wav']
                            for alt_format in alternative_formats:
                                if alt_format != audio_format:
                                    try:
                                        file_data.seek(0)
                                        audio = cast(AudioSegmentProtocol, from_file(file_data, format=alt_format))
                                        self.logger.info(
                                            f"Erfolgreich mit alternativem Format {alt_format} dekodiert"
                                        )
                                        break
                                    except Exception:
                                        continue
                            else:
                                raise ProcessingError(
                                    f"Konnte Audio-Datei in keinem der unterstützten Formate dekodieren. "
                                    f"Ursprünglicher Fehler: {str(decode_error)}"
                                )
                    else:
                        try:
                            audio = cast(AudioSegmentProtocol, from_file(str(file_path), format=audio_format))
                        except Exception as decode_error:
                            self.logger.warning(
                                "Fehler beim Dekodieren der Audio-Datei",
                                extra={
                                    "error": str(decode_error),
                                    "format": audio_format,
                                    "file": str(file_path)
                                }
                            )
                            # Versuche ohne Format-Spezifikation
                            audio = cast(AudioSegmentProtocol, from_file(str(file_path)))
                    
                    media_duration = float(len(audio)) / 1000.0  # ms to seconds
                    media_bitrate = int(audio.frame_rate * audio.sample_width * 8)
                    media_channels = int(audio.channels)
                    media_sample_rate = int(audio.frame_rate)
                    media_codec = audio_format
                    
                    self.logger.info(
                        "Audio-Metadaten erfolgreich extrahiert",
                        extra={
                            "format": audio_format,
                            "duration": media_duration,
                            "channels": media_channels,
                            "sample_rate": media_sample_rate
                        }
                    )
                        
                except Exception as e:
                    self.logger.warning(
                        "Fehler beim Extrahieren der Media-Metadaten",
                        extra={
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "mime_type": mime_type,
                            "file_name": file_name
                        }
                    )
                    # Setze Felder auf None bei Fehler
                    media_duration = None
                    media_bitrate = None
                    media_channels = None
                    media_sample_rate = None
                    media_codec = None

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
    ) -> Tuple[LLMInfo, ContentMetadata]:
        """Extrahiert inhaltliche Metadaten aus einem Text."""
        if not content:
            return LLMInfo(model="", purpose=""), ContentMetadata()
            
        try:
            self.logger.info("Starte inhaltliche Metadaten-Extraktion",
                           content_length=len(content),
                           context_keys=list(context.keys()) if context else None)
            
            # LLMInfo für Content-Analyse initialisieren
            llm_info = LLMInfo(
                model=self.transformer.model,
                purpose="content-metadata-extraction"
            )
            
            # Template-Transformation mit Metadaten-Template durchführen
            self.logger.info("Führe Template-Transformation durch")
                    
            transform_result: TransformerResponse = self.transformer.transformByTemplate(
                source_text=content,
                source_language="de",
                target_language="de",
                template="metadata",  # Verwendet ein spezielles Metadaten-Template
                context=context or {}
            )

            if transform_result.error:
                raise ContentExtractionError(
                    f"Fehler bei der Template-Transformation: {transform_result.error.message if transform_result.error else 'Unbekannter Fehler'}"
                )

            # LLM-Info aus der Transformation übernehmen
            if transform_result.llm_info:
                llm_info.add_request(transform_result.llm_info.requests)

            # Strukturierte Daten aus der Template-Transformation verwenden
            structured_data: Any | None = transform_result.data.output.structured_data if transform_result.data and transform_result.data.output else None
            metadata: Dict[str, Any] = structured_data if isinstance(structured_data, dict) else {}
            
            # ContentMetadata aus den strukturierten Daten erstellen
            content_metadata = ContentMetadata(
                type=str(metadata.get('type', "text")),
                title=metadata.get('title'),
                authors=metadata.get('authors'),
                language=str(metadata.get('language', "de")),
                spatial_location=metadata.get('spatial_location'),
                temporal_period=metadata.get('temporal_period'),
                keywords=metadata.get('keywords'),
                abstract=metadata.get('abstract'),
                created=datetime.now(timezone.utc).isoformat(),
                modified=datetime.now(timezone.utc).isoformat()
            )
            
            return llm_info, content_metadata
            
        except Exception as e:
            error_msg = f"Fehler bei der inhaltlichen Metadaten-Extraktion: {str(e)}"
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
        """
        Alias für process() zur Abwärtskompatibilität.
        Diese Methode ruft intern process() auf.
        
        Args:
            binary_data: Binärdaten oder Pfad zur Datei
            content: Optionaler Textinhalt
            context: Optionaler Kontext für die Verarbeitung
            
        Returns:
            MetadataResponse: Extrahierte Metadaten
        """
        self.logger.info("extract_metadata() wird als Alias für process() verwendet")
            
        return await self.process(
            binary_data=binary_data,
            content=content,
            context=context
        ) 