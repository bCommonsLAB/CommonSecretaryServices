"""
@fileoverview OpenAI Types - Type definitions for OpenAI API interactions

@description
Type definitions for OpenAI API calls. This file contains all type definitions
for interacting with the OpenAI API, particularly for Whisper (audio) and GPT (chat) calls.

Main functionality:
- Type definitions for OpenAI API responses
- Pydantic models for structured responses
- Protocol definitions for type checking
- TypedDict definitions for API structures

Features:
- Type-safe OpenAI API interactions
- Pydantic models for Whisper responses
- Protocol definitions for type checking
- TypedDict for API response structures
- Support for Whisper and GPT API types

@module utils.openai_types

@exports
- WhisperSegment: Pydantic BaseModel - Whisper transcription segment
- WhisperResponse: Pydantic BaseModel - Whisper API response
- OpenAIDict: TypedDict - Base type for OpenAI API responses
- Various Protocol definitions

@usedIn
- src.utils.transcription_utils: Uses WhisperResponse for type safety
- OpenAI API integrations: Use type definitions for API calls

@dependencies
- External: pydantic - Data validation and model creation
- External: openai - OpenAI API types
- Standard: typing - Type annotations and protocols
"""

from typing import Dict, List, Optional, Any, Literal, TypeVar, Protocol, TypedDict, Type
from datetime import datetime
from pydantic import Field, BaseModel
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.audio import Transcription

T = TypeVar('T')

class OpenAIDict(TypedDict, total=False):
    """Basistyp für OpenAI API Responses."""
    text: str
    language: Optional[str]
    duration: float
    segments: List[Dict[str, Any]]
    task: str
    id: str
    object: str
    created: datetime
    model: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, Any]

class SupportsIndex(Protocol):
    """Protocol für Typen, die einen Index unterstützen."""
    def __index__(self) -> int: ...

class WhisperSegment(BaseModel):
    """Ein Segment einer Whisper-Transkription."""
    id: int = Field(description="ID des Segments")
    seek: int = Field(description="Position im Audio in Millisekunden")
    start: float = Field(description="Startzeit in Sekunden")
    end: float = Field(description="Endzeit in Sekunden")
    text: str = Field(description="Transkribierter Text")
    tokens: List[int] = Field(description="Token-IDs")
    temperature: float = Field(description="Verwendete Sampling-Temperatur")
    avg_logprob: float = Field(description="Durchschnittliche Log-Wahrscheinlichkeit")
    compression_ratio: float = Field(description="Kompressionsverhältnis")
    no_speech_prob: float = Field(description="Wahrscheinlichkeit für Stille")

class WhisperResponse(BaseModel):
    """Response von der Whisper API."""
    text: str = Field(description="Transkribierter Text")
    language: Optional[str] = Field(None, description="Erkannte Sprache (ISO 639-1)")
    duration: float = Field(description="Länge des Audio in Sekunden")
    segments: List[WhisperSegment] = Field(default_factory=list, description="Einzelne Segmente der Transkription")
    task: Literal["transcribe", "translate"] = Field(description="Durchgeführte Aufgabe")

    @classmethod
    def from_api_response(cls: Type["WhisperResponse"], response: Transcription) -> "WhisperResponse":
        """Erstellt eine WhisperResponse aus der API-Antwort."""
        data = response.model_dump()
        return cls.model_validate(data)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        return self.model_dump(exclude_none=True)

class ChatMessage(BaseModel):
    """Eine einzelne Chat-Nachricht."""
    role: Literal["system", "user", "assistant", "function"] = Field(description="Rolle des Absenders")
    content: str = Field(description="Inhalt der Nachricht")
    name: Optional[str] = Field(None, description="Name bei Funktionsaufrufen")

    def to_api_message(self) -> ChatCompletionMessageParam:
        """Konvertiert die Nachricht in ein API-kompatibles Format."""
        data = {
            "role": self.role,
            "content": self.content
        }
        if self.name is not None:
            data["name"] = self.name
        return data  # type: ignore

class ChatFunctionCall(BaseModel):
    """Ein Funktionsaufruf im Chat."""
    name: str = Field(description="Name der aufgerufenen Funktion")
    arguments: str = Field(description="JSON-String der Funktionsargumente")

class ChatChoice(BaseModel):
    """Eine Antwortmöglichkeit vom Chat-Modell."""
    index: int = Field(description="Index der Antwort")
    message: ChatMessage = Field(description="Die Chat-Nachricht")
    finish_reason: Literal["stop", "length", "function_call", "content_filter"] = Field(description="Grund für Beendigung")

class ChatUsage(BaseModel):
    """Nutzungsinformationen eines Chat-Aufrufs."""
    prompt_tokens: int = Field(description="Anzahl der Token in der Anfrage")
    completion_tokens: int = Field(description="Anzahl der Token in der Antwort")
    total_tokens: int = Field(description="Gesamtanzahl der Token")

class ChatResponse(BaseModel):
    """Vollständige Response von der Chat API."""
    id: str = Field(description="ID der Antwort")
    object: Literal["chat.completion"] = Field(description="Typ des Objekts")
    created: datetime = Field(description="Erstellungszeitpunkt")
    model: str = Field(description="Verwendetes Modell")
    choices: List[ChatChoice] = Field(description="Liste der Antwortmöglichkeiten")
    usage: ChatUsage = Field(description="Nutzungsinformationen")

    @classmethod
    def from_api_response(cls: Type["ChatResponse"], response: ChatCompletion) -> "ChatResponse":
        """Erstellt eine ChatResponse aus der API-Antwort."""
        data = response.model_dump()
        return cls.model_validate(data)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        return self.model_dump(exclude_none=True)

class AudioTranscriptionParams(BaseModel):
    """Parameter für Audio-Transkriptionen."""
    model: Literal["whisper-1"] = Field(default="whisper-1", description="Zu verwendendes Modell")
    language: Optional[str] = Field(None, description="Sprache des Inputs (ISO 639-1)")
    prompt: Optional[str] = Field(None, description="Optionaler Prompt für bessere Transkription")
    response_format: Literal["json", "text", "srt", "verbose_json", "vtt"] = Field(
        default="verbose_json",
        description="Format der Antwort"
    )
    temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Sampling temperature"
    )

    def to_api_params(self) -> Dict[str, Any]:
        """Konvertiert die Parameter in ein API-kompatibles Format."""
        return self.model_dump(exclude_none=True) 