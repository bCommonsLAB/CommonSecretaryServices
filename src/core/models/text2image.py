"""
@fileoverview Text2Image Models - Dataclasses for text-to-image generation

@description
Text2Image-specific types and models. This file defines all dataclasses for text-to-image
generation, including request parameters, image data, and API responses.

Main classes:
- Text2ImageData: Image generation result data
- Text2ImageResponse: Complete API response for text-to-image generation

Features:
- Validation of all fields in __post_init__
- Serialization to dictionary (to_dict)
- Deserialization from dictionary (from_dict)
- Integration with LLMInfo for generation tracking

@module core.models.text2image

@exports
- Text2ImageData: Dataclass - Image generation data
- Text2ImageResponse: Dataclass - API response for text-to-image generation

@usedIn
- src.processors.text2image_processor: Uses Text2ImageResponse
- src.api.routes.text2image_routes: Uses Text2ImageResponse for API responses

@dependencies
- Internal: src.core.models.base - BaseResponse, ProcessInfo, ErrorInfo
- Internal: src.core.models.enums - ProcessingStatus
"""
from dataclasses import dataclass
from typing import Optional, Dict, Any, List, cast
import base64

from .base import BaseResponse, ProcessInfo, ErrorInfo
from .enums import ProcessingStatus
from ..validation import is_non_empty_str


@dataclass
class Text2ImageItem:
    """
    Einzelnes Bild aus der Text2Image-Generierung.
    
    Enthält Bilddaten und den zugehörigen Seed.
    """
    image_base64: str
    image_format: str
    size: str
    seed: Optional[int] = None
    
    def __post_init__(self) -> None:
        """Validiert ein einzelnes Bildobjekt."""
        if not is_non_empty_str(self.image_base64):
            raise ValueError("image_base64 darf nicht leer sein")
        if not is_non_empty_str(self.image_format):
            raise ValueError("image_format darf nicht leer sein")
        if self.image_format not in ["png", "jpeg", "jpg"]:
            raise ValueError(f"image_format muss 'png', 'jpeg' oder 'jpg' sein, nicht '{self.image_format}'")
        if not is_non_empty_str(self.size):
            raise ValueError("size darf nicht leer sein")
        if "x" not in self.size:
            raise ValueError(f"size muss Format 'WIDTHxHEIGHT' haben, nicht '{self.size}'")
        try:
            width, height = self.size.split("x")
            int(width)
            int(height)
        except ValueError:
            raise ValueError(f"size muss Format 'WIDTHxHEIGHT' haben, nicht '{self.size}'")
        if self.seed is not None and self.seed < 0:
            raise ValueError("seed muss positiv sein oder None")
        
        # Validiere Base64-Format
        try:
            base64.b64decode(self.image_base64)
        except Exception as e:
            raise ValueError(f"image_base64 ist kein gültiges Base64: {str(e)}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Bildobjekt in ein Dictionary."""
        result: Dict[str, Any] = {
            'image_base64': self.image_base64,
            'image_format': self.image_format,
            'size': self.size
        }
        if self.seed is not None:
            result['seed'] = self.seed
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Text2ImageItem':
        """Erstellt Text2ImageItem aus einem Dictionary."""
        return cls(
            image_base64=str(data.get('image_base64', '')),
            image_format=str(data.get('image_format', 'png')),
            size=str(data.get('size', '1024x1024')),
            seed=int(data['seed']) if data.get('seed') is not None else None
        )


@dataclass
class Text2ImageData:
    """
    Daten für Text2Image-Response.
    
    Enthält das generierte Bild als Base64-kodierte PNG-Daten sowie
    Metadaten über die Generierung.
    """
    image_base64: str
    image_format: str
    size: str
    model: str
    prompt: str
    seed: Optional[int] = None
    images: Optional[List[Text2ImageItem]] = None
    
    def __post_init__(self) -> None:
        """Validiert die Text2Image-Daten."""
        if not is_non_empty_str(self.image_base64):
            raise ValueError("image_base64 darf nicht leer sein")
        if not is_non_empty_str(self.image_format):
            raise ValueError("image_format darf nicht leer sein")
        if self.image_format not in ["png", "jpeg", "jpg"]:
            raise ValueError(f"image_format muss 'png', 'jpeg' oder 'jpg' sein, nicht '{self.image_format}'")
        if not is_non_empty_str(self.size):
            raise ValueError("size darf nicht leer sein")
        # Validiere Size-Format (z.B. "1024x1024")
        if "x" not in self.size:
            raise ValueError(f"size muss Format 'WIDTHxHEIGHT' haben, nicht '{self.size}'")
        try:
            width, height = self.size.split("x")
            int(width)
            int(height)
        except ValueError:
            raise ValueError(f"size muss Format 'WIDTHxHEIGHT' haben, nicht '{self.size}'")
        if not is_non_empty_str(self.model):
            raise ValueError("model darf nicht leer sein")
        if not is_non_empty_str(self.prompt):
            raise ValueError("prompt darf nicht leer sein")
        if self.seed is not None and self.seed < 0:
            raise ValueError("seed muss positiv sein oder None")
        
        # Validiere Base64-Format
        try:
            base64.b64decode(self.image_base64)
        except Exception as e:
            raise ValueError(f"image_base64 ist kein gültiges Base64: {str(e)}")
        
        # Optional: Liste von Bildern validieren
        if self.images is not None:
            if len(self.images) == 0:
                raise ValueError("images muss eine nicht-leere Liste sein, wenn gesetzt")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Text2Image-Daten in ein Dictionary."""
        result: Dict[str, Any] = {
            'image_base64': self.image_base64,
            'image_format': self.image_format,
            'size': self.size,
            'model': self.model,
            'prompt': self.prompt
        }
        if self.seed is not None:
            result['seed'] = self.seed
        if self.images is not None:
            result['images'] = [image.to_dict() for image in self.images]
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Text2ImageData':
        """
        Erstellt Text2ImageData aus einem Dictionary.
        
        Args:
            data: Dictionary mit Text2Image-Daten
            
        Returns:
            Text2ImageData: Text2ImageData-Instanz
        """
        images_raw = data.get('images')
        images_list: Optional[List[Text2ImageItem]] = None
        if isinstance(images_raw, list):
            images_list = [
                Text2ImageItem.from_dict(cast(Dict[str, Any], item))
                for item in images_raw
                if isinstance(item, dict)
            ]
        
        return cls(
            image_base64=str(data.get('image_base64', '')),
            image_format=str(data.get('image_format', 'png')),
            size=str(data.get('size', '1024x1024')),
            model=str(data.get('model', '')),
            prompt=str(data.get('prompt', '')),
            seed=int(data['seed']) if data.get('seed') is not None else None,
            images=images_list
        )


@dataclass(frozen=True)
class Text2ImageResponse(BaseResponse):
    """
    API-Response für Text-zu-Bild-Generierung.
    
    Folgt dem standardisierten Response-Format mit:
    - status: ProcessingStatus
    - request: RequestInfo
    - process: ProcessInfo (mit LLM-Tracking)
    - error: ErrorInfo (optional)
    - data: Text2ImageData (optional)
    """
    data: Optional[Text2ImageData] = None
    
    def __post_init__(self) -> None:
        """Validiert die Text2Image-Response."""
        super().__post_init__()
        if self.status == ProcessingStatus.SUCCESS and not self.data:
            raise ValueError("data darf nicht None sein wenn status SUCCESS ist")
        if self.status == ProcessingStatus.ERROR and self.data:
            # Bei Fehlern kann data None sein, aber wenn gesetzt, sollte es valide sein
            if self.data:
                # Validiere data falls vorhanden
                pass
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        if self.data:
            base_dict['data'] = self.data.to_dict()
        return base_dict
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Text2ImageResponse':
        """
        Erstellt Text2ImageResponse aus einem Dictionary.
        
        Args:
            data: Dictionary mit Response-Daten
            
        Returns:
            Text2ImageResponse: Text2ImageResponse-Instanz
        """
        from .base import RequestInfo
        
        # Parse RequestInfo
        request_data = data.get('request', {})
        request = RequestInfo(
            processor=str(request_data.get('processor', 'text2image')),
            timestamp=str(request_data.get('timestamp', '')),
            parameters=request_data.get('parameters', {})
        )
        
        # Parse ProcessInfo
        process_data = data.get('process')
        process: Optional[ProcessInfo] = None
        if process_data:
            from .llm import LLMInfo
            llm_info_data = process_data.get('llm_info', {})
            # LLMInfo hat eine from_dict Methode oder kann direkt erstellt werden
            llm_info: Optional[LLMInfo] = None
            if llm_info_data:
                try:
                    if hasattr(LLMInfo, 'from_dict'):
                        llm_info = LLMInfo.from_dict(llm_info_data)  # type: ignore
                    else:
                        # Fallback: Erstelle LLMInfo direkt
                        llm_info = LLMInfo()  # type: ignore
                except Exception:
                    llm_info = None
            
            process = ProcessInfo(
                id=str(process_data.get('id', '')),
                main_processor=str(process_data.get('main_processor', 'text2image')),
                started=str(process_data.get('started', '')),
                sub_processors=process_data.get('sub_processors', []),
                completed=process_data.get('completed'),
                duration=process_data.get('duration'),
                llm_info=llm_info,
                is_from_cache=process_data.get('is_from_cache', False),
                cache_key=process_data.get('cache_key')
            )
        
        # Parse ErrorInfo
        error_data = data.get('error')
        error: Optional[ErrorInfo] = None
        if error_data:
            error = ErrorInfo(
                code=str(error_data.get('code', '')),
                message=str(error_data.get('message', '')),
                details=error_data.get('details', {})
            )
        
        # Parse Text2ImageData
        data_obj: Optional[Text2ImageData] = None
        data_dict = data.get('data')
        if data_dict:
            data_obj = Text2ImageData.from_dict(data_dict)
        
        # Parse Status
        status_str = data.get('status', 'pending')
        status = ProcessingStatus(status_str) if isinstance(status_str, str) else ProcessingStatus.PENDING
        
        return cls(
            request=request,
            process=process,
            status=status,
            error=error,
            data=data_obj
        )
