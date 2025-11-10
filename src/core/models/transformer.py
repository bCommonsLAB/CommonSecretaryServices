"""
@fileoverview Transformer Models - Dataclasses for text transformation and templates

@description
Transformer-specific types and models. This file defines all dataclasses for text
transformation, including translation, template processing, summarization, and
format conversion.

Main classes:
- TemplateField: Definition of a template field
- TemplateFields: Collection of template fields
- TransformerInput: Input data for transformation
- TransformerData: Output data of transformation
- TranslationResult: Result of a translation
- TransformationResult: Result of a template transformation
- TransformerResponse: API response for transformer processing

Features:
- Template-based transformation with field definitions
- Support for various output formats (Markdown, HTML, JSON, etc.)
- Validation of all fields in __post_init__
- Serialization to dictionary (to_dict)
- Protocol-based typing for cacheable results

@module core.models.transformer

@exports
- CacheableResult: Protocol - Protocol for cacheable results
- TemplateField: Dataclass - Template field definition
- TemplateFields: Dataclass - Template fields collection
- TransformerInput: Dataclass - Transformer input data
- TransformerData: Dataclass - Transformer output data
- TranslationResult: Dataclass - Translation result
- TransformationResult: Dataclass - Transformation result
- TransformerResponse: Dataclass - API response for transformer processing

@usedIn
- src.processors.transformer_processor: Uses all transformer models
- src.processors.audio_processor: Uses TransformerResponse for audio transformation
- src.processors.pdf_processor: Uses TransformerResponse for PDF transformation
- src.api.routes.transformer_routes: Uses TransformerResponse for API responses

@dependencies
- Internal: src.core.models.base - BaseResponse, ProcessInfo, ErrorInfo
- Internal: src.core.models.enums - ProcessingStatus, OutputFormat
"""
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Protocol
from .base import BaseResponse, ErrorInfo
from .enums import ProcessingStatus, OutputFormat
from .base import ProcessInfo
from datetime import datetime, UTC


class CacheableResult(Protocol):
    """Protokoll für Cache-fähige Ergebnisse."""
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        ...

@dataclass(frozen=True)
class TemplateField:
    """Definiert die Felder eines Templates"""
    description: str
    max_length: int = 5000
    isFrontmatter: bool = False
    default: Optional[str] = None

@dataclass(frozen=True)
class TemplateFields:
    """Definiert die Felder eines Templates"""
    fields: Dict[str, TemplateField]

@dataclass(frozen=True)
class TransformerInput:
    """Eingabedaten für den Transformer"""
    text: str
    language: str
    format: OutputFormat
    translated_text: Optional[str] = None
    summarize: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Eingabedaten in ein Dictionary."""
        return {
            "text": self.text,
            "language": self.language,
            "format": self.format.value,
            "translated_text": self.translated_text,
            "summarize": self.summarize
        }

@dataclass(frozen=True)
class TransformerData:
    """Ausgabedaten des Transformers"""
    text: str
    language: str
    format: OutputFormat
    summarized: bool = False
    structured_data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Ausgabedaten in ein Dictionary."""
        return {
            "text": self.text,
            "language": self.language,
            "format": self.format.value,
            "summarized": self.summarized,
            "structured_data": self.structured_data
        }

@dataclass(frozen=True)
class TranslationResult:
    """Ergebnis einer Übersetzung"""
    text: str
    source_language: str
    target_language: str

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "text": self.text,
            "source_language": self.source_language,
            "target_language": self.target_language
        }

@dataclass(frozen=True)
class TransformationResult(CacheableResult):
    """
    Ergebnis einer Transformation.
    
    Attributes:
        text: Der transformierte Text
        target_language: Die Zielsprache
        structured_data: Optionale strukturierte Daten
        processed_at: Zeitstempel der Verarbeitung
    """
    text: str
    target_language: str
    structured_data: Optional[Any] = None
    processed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    
    def __post_init__(self) -> None:
        """Validiert das TransformationResult."""
        if not self.text:
            raise ValueError("'text' darf nicht leer sein")
        if not self.target_language:
            raise ValueError("'target_language' darf nicht leer sein")
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.text else ProcessingStatus.ERROR
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        # Nur die für den Cache relevanten Daten speichern
        result = {
            "text": self.text,
            "target_language": self.target_language,
            "structured_data": self.structured_data,
            "processed_at": self.processed_at
        }
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransformationResult':
        """
        Erstellt ein TransformationResult aus serialisierten Daten.
        
        Args:
            data: Die serialisierten Daten
            
        Returns:
            TransformationResult: Das deserialisierte Ergebnis
        """
        if not data:
            return cls(text="", target_language="unknown")
            
        return cls(
            text=data.get("text", ""),
            target_language=data.get("target_language", "unknown"),
            structured_data=data.get("structured_data"),
            processed_at=data.get("processed_at", datetime.now(UTC).isoformat())
        )
    
    @classmethod
    def from_cache(cls, data: Dict[str, Any]) -> 'TransformationResult':
        """
        Erstellt ein TransformationResult aus Cache-Daten.
        Bei Cache-Treffern gibt es keine LLM-Informationen.
        
        Args:
            data: Die serialisierten Daten aus dem Cache
            
        Returns:
            TransformationResult: Das deserialisierte Ergebnis
        """
        return cls.from_dict(data)

@dataclass(frozen=True, init=False)
class TransformerResponse(BaseResponse):
    """Response des Transformer-Prozessors"""
    data: Optional[TransformerData] = field(default=None)
    translation: Optional[TranslationResult] = field(default=None)

    def __init__(
        self,
        data: TransformerData,
        translation: Optional[TranslationResult] = None,
        **kwargs: Any  # Erlaubt die Übergabe der Basis-Parameter
    ) -> None:
        """Initialisiert die TransformerResponse."""
        super().__init__(**kwargs)  # Übergibt alle Parameter an die Basis-Klasse
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'translation', translation)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict.update({
            'data': self.data.to_dict() if self.data else None,
            'translation': self.translation.to_dict() if self.translation else None
        })
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[TransformerData] = None,
        translation: Optional[TranslationResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'TransformerResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        # Erstelle eine neue Instanz mit den Basis-Parametern
        response = cls(data=data, translation=translation, process=process, **kwargs)
        # Setze den Status
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        **kwargs: Any
    ) -> 'TransformerResponse':
        """Erstellt eine Error-Response."""
        # Erstelle eine neue Instanz mit den Basis-Parametern
        response = cls(
            data=TransformerData(
                text="",
                language="",
                format=OutputFormat.TEXT
            ),
            **kwargs
        )
        # Setze den Status und Fehler
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response 