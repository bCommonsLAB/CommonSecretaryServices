"""
Transformer-spezifische Typen und Modelle.
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from .base import BaseResponse, RequestInfo, ProcessInfo, ErrorInfo
from .enums import ProcessingStatus, OutputFormat
from .llm import LLMInfo, LLMRequest


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
    summarize: bool = False

@dataclass(frozen=True)
class TransformerOutput:
    """Ausgabedaten des Transformers"""
    text: str
    language: str
    format: OutputFormat
    summarized: bool = False
    structured_data: Optional[Any] = None

@dataclass(frozen=True)
class TransformerData:
    """Daten für die Transformer-Verarbeitung"""
    input: TransformerInput
    output: TransformerOutput

@dataclass(frozen=True)
class TranslationResult:
    """Ergebnis einer Übersetzung"""
    text: str
    source_language: str
    target_language: str
    requests: List[LLMRequest] 

@dataclass(frozen=True)
class TransformationResult:
    """Ergebnis einer Zusammenfassung"""
    text: str
    target_language: str
    structured_data: Optional[Any] = None
    requests: Optional[List[LLMRequest]] = None

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

    @classmethod
    def create(cls, request: RequestInfo, process: ProcessInfo, data: TransformerData,
               translation: Optional[TranslationResult] = None,
               llm_info: Optional[LLMInfo] = None) -> 'TransformerResponse':
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
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error: ErrorInfo) -> 'TransformerResponse':
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