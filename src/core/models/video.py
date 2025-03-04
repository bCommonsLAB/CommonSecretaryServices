"""
Video-spezifische Typen und Modelle.
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any

from .base import BaseResponse, ProcessingStatus, RequestInfo, ProcessInfo, ErrorInfo
from .audio import TranscriptionResult
from .llm import LLMInfo
from ..exceptions import ProcessingError

class VideoProcessingError(ProcessingError):
    """Video-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'DOWNLOAD_ERROR': 'Fehler beim Download',
        'CONVERSION_ERROR': 'Fehler bei der Konvertierung',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'VIDEO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'VIDEO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

@dataclass
class VideoSource:
    """Quelle eines Videos (URL oder Datei)"""
    url: Optional[str] = None
    file: Optional[bytes] = None
    file_name: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'url': self.url,
            'file_name': self.file_name
            # file wird nicht serialisiert
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoSource':
        """Erstellt aus Dict"""
        return cls(
            url=data.get('url'),
            file_name=data.get('file_name')
        )

@dataclass
class VideoMetadata:
    """Metadaten eines Videos"""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: Optional[str] = None
    audio_file: Optional[str] = None
    video_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert zu Dict"""
        return {
            'title': self.title,
            'source': self.source.to_dict(),
            'duration': self.duration,
            'duration_formatted': self.duration_formatted,
            'file_size': self.file_size,
            'process_dir': self.process_dir,
            'audio_file': self.audio_file,
            'video_id': self.video_id
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoMetadata':
        """Erstellt aus Dict"""
        return cls(
            title=data['title'],
            source=VideoSource.from_dict(data['source']),
            duration=data['duration'],
            duration_formatted=data['duration_formatted'],
            file_size=data.get('file_size'),
            process_dir=data.get('process_dir'),
            audio_file=data.get('audio_file'),
            video_id=data.get('video_id')
        )

@dataclass
class VideoProcessingResult:
    """Ergebnis der Video-Verarbeitung.
    
    Attributes:
        metadata (VideoMetadata): Metadaten zum Video
        audio_result (Optional[AudioProcessingResult]): Ergebnis der Audio-Verarbeitung
        process_id (str): ID des Verarbeitungsprozesses
        transcription (Optional[TranscriptionResult]): Transkriptionsergebnis
        is_from_cache (bool): Gibt an, ob das Ergebnis aus dem Cache geladen wurde
    """
    
    def __init__(
        self,
        metadata: VideoMetadata,
        process_id: str,
        audio_result: Optional[Any] = None,
        transcription: Optional[Any] = None,
        is_from_cache: bool = False
    ):
        """Initialisiert das VideoProcessingResult."""
        self.metadata = metadata
        self.process_id = process_id
        self.audio_result = audio_result
        self.transcription = transcription
        self.is_from_cache = is_from_cache
        
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'audio_result': self.audio_result.to_dict() if self.audio_result and hasattr(self.audio_result, 'to_dict') else self.audio_result,
            'transcription': self.transcription.to_dict() if self.transcription and hasattr(self.transcription, 'to_dict') else self.transcription,
            'is_from_cache': self.is_from_cache
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VideoProcessingResult':
        """Erstellt ein VideoProcessingResult aus einem Dictionary."""
        from src.core.models.audio import AudioProcessingResult
        
        # Metadaten extrahieren
        metadata_dict = data.get('metadata', {})
        metadata = VideoMetadata.from_dict(metadata_dict) if metadata_dict else VideoMetadata(
            title="",
            source=VideoSource(),
            duration=0,
            duration_formatted="00:00:00"
        )
        
        # Audio-Ergebnis extrahieren
        audio_result = None
        audio_result_dict = data.get('audio_result')
        if audio_result_dict and isinstance(audio_result_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_dict: Dict[str, Any] = audio_result_dict
                audio_result = AudioProcessingResult.from_dict(typed_dict)
            except:
                pass
                
        # Transkription extrahieren
        transcription = None
        transcription_dict = data.get('transcription')
        if transcription_dict and isinstance(transcription_dict, dict):
            try:
                # Explizite Typ-Konvertierung für den Linter
                typed_dict: Dict[str, Any] = transcription_dict
                transcription = TranscriptionResult.from_dict(typed_dict)
            except:
                pass
                
        return cls(
            metadata=metadata,
            process_id=data.get('process_id', ''),
            audio_result=audio_result,
            transcription=transcription,
            is_from_cache=data.get('is_from_cache', False)
        )

@dataclass(frozen=True, init=False)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    # Keine explizite Deklaration von data, da es in __init__ gesetzt wird

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: VideoProcessingResult,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die VideoResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)

    @classmethod
    def create(cls, request: RequestInfo, process: ProcessInfo, data: VideoProcessingResult,
               llm_info: Optional[LLMInfo] = None) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        if llm_info:
            process.llm_info = llm_info
        return cls(
            data=data,
            request=request,
            process=process,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error: ErrorInfo) -> 'VideoResponse':
        """Erstellt eine Fehler-Response."""
        dummy_source = VideoSource(url="")
        dummy_metadata = VideoMetadata(
            title="",
            source=dummy_source,
            duration=0,
            duration_formatted="00:00:00",
            process_dir=""
        )
        dummy_result = VideoProcessingResult(
            metadata=dummy_metadata,
            transcription=None,
            process_id=""
        )
        return cls(
            data=dummy_result,
            request=request,
            process=process,
            error=error,
            status=ProcessingStatus.ERROR
        )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict 