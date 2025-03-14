"""
Transformer-spezifische Typen und Modelle.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .base import BaseResponse, RequestInfo, ProcessInfo, ErrorInfo
from .enums import ProcessingStatus, OutputFormat
from .llm import LLMInfo, LLMRequest, LLModel


@dataclass(frozen=True)
class TemplateField:
    """Definiert die Felder eines Templates"""
    description: str
    max_length: int = 5000
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
class TransformerOutput:
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
class TransformerData:
    """Daten für die Transformer-Verarbeitung"""
    input: TransformerInput
    output: TransformerOutput

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Daten in ein Dictionary."""
        return {
            "input": self.input.to_dict() if self.input else None,
            "output": self.output.to_dict() if self.output else None
        }

@dataclass(frozen=True)
class TranslationResult:
    """Ergebnis einer Übersetzung"""
    text: str
    source_language: str
    target_language: str
    requests: List[LLMRequest]

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "text": self.text,
            "source_language": self.source_language,
            "target_language": self.target_language,
            "requests": [req.to_dict() for req in self.requests] if self.requests else []
        }

@dataclass
class TransformationResult:
    """
    Ergebnis einer Transformation.
    
    Attributes:
        text: Der transformierte Text
        target_language: Die Zielsprache
        structured_data: Optionale strukturierte Daten
        requests: Liste der LLM-Requests (nur bei direkter Verarbeitung, nicht bei Cache-Treffern)
        llms: Liste der verwendeten LLM-Modelle (nur bei direkter Verarbeitung)
        llm_info: LLM-Informationen für die Transformation (nur bei direkter Verarbeitung)
    """
    text: str
    target_language: str
    structured_data: Optional[Any] = None
    requests: Optional[List[LLMRequest]] = None
    llms: List[LLModel] = field(default_factory=list)  # Liste der verwendeten LLM-Modelle
    llm_info: Optional[LLMInfo] = None  # LLM-Informationen für die Transformation
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        # Nur die für den Cache relevanten Daten speichern
        result = {
            "text": self.text,
            "target_language": self.target_language,
            "structured_data": self.structured_data
        }
        
        # LLM-Informationen nur hinzufügen, wenn vorhanden (bei direkter Verarbeitung)
        if self.requests:
            result["requests"] = [r.to_dict() for r in self.requests]
            
        if self.llms:
            result["llms"] = [l.to_dict() for l in self.llms]
            
        if self.llm_info:
            result["llm_info"] = self.llm_info.to_dict()
            
        return result
    
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
        if not data:
            return cls(text="", target_language="unknown")
            
        return cls(
            text=data.get("text", ""),
            target_language=data.get("target_language", "unknown"),
            structured_data=data.get("structured_data"),
            # Keine LLM-Informationen bei Cache-Treffern
        )

@dataclass(frozen=True, init=False)
class TransformerResponse(BaseResponse):
    """Response des Transformer-Prozessors"""
    data: TransformerData
    translation: Optional[TranslationResult] = None
    llm_info: Optional[LLMInfo] = None  # Optional, da nicht immer LLM-Nutzung vorhanden

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: TransformerData,
        translation: Optional[TranslationResult] = None,
        llm_info: Optional[LLMInfo] = None,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die TransformerResponse."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'translation', translation)
        object.__setattr__(self, 'llm_info', llm_info)
        if self.llm_info:
            object.__setattr__(self.process, 'llm_info', self.llm_info.to_dict())

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict.update({
            'translation': self.translation.to_dict() if self.translation else None,
            'llm_info': self.llm_info.to_dict() if self.llm_info else None
        })
        return base_dict

    @classmethod
    def create(
        cls,
        request: RequestInfo,
        process: ProcessInfo,
        data: TransformerData,
        translation: Optional[TranslationResult] = None,
        llm_info: Optional[LLMInfo] = None
    ) -> 'TransformerResponse':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            request=request,
            process=process,
            data=data,
            translation=translation,
            llm_info=llm_info,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(
        cls,
        request: RequestInfo,
        process: ProcessInfo,
        error: ErrorInfo
    ) -> 'TransformerResponse':
        """Erstellt eine Error-Response."""
        return cls(
            request=request,
            process=process,
            data=TransformerData(
                input=TransformerInput(text="", language="", format=OutputFormat.TEXT),
                output=TransformerOutput(text="", language="", format=OutputFormat.TEXT)
            ),
            status=ProcessingStatus.ERROR,
            error=error
        ) 