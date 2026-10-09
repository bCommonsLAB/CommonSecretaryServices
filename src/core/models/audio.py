"""
@fileoverview Audio Models - Dataclasses for audio processing and transcription

@description
Audio-specific types and models. This file defines all dataclasses for audio processing,
including transcription, segmentation, and transformation.

Main classes:
- AudioProcessingError: Audio-specific exception class
- TranscriptionSegment: Single segment of a transcription
- TranscriptionResult: Complete transcription result
- AudioSegmentInfo: Information about an audio segment
- Chapter: Chapter information for structured audio content
- AudioProcessingResult: Cacheable processing result
- AudioResponse: API response for audio processing

Features:
- Validation of all fields in __post_init__
- Serialization to dictionary (to_dict)
- Deserialization from dictionary (from_dict)
- Integration with LLMInfo for transcription tracking

@module core.models.audio

@exports
- AudioProcessingError: Class - Audio-specific exception
- TranscriptionSegment: Dataclass - Transcription segment
- TranscriptionResult: Dataclass - Transcription result
- AudioSegmentInfo: Dataclass - Audio segment information
- Chapter: Dataclass - Chapter information
- AudioProcessingResult: Class - Cacheable processing result
- AudioResponse: Dataclass - API response for audio processing

@usedIn
- src.processors.audio_processor: Uses all audio models
- src.processors.video_processor: Uses TranscriptionResult for video audio
- src.api.routes.audio_routes: Uses AudioResponse for API responses

@dependencies
- Internal: src.core.models.base - BaseResponse, ProcessInfo, ErrorInfo
- Internal: src.core.models.llm - LLMInfo for tracking
- Internal: src.core.models.enums - ProcessingStatus
- Internal: src.core.exceptions - ProcessingError
"""
from dataclasses import dataclass, field, fields as dataclass_fields, replace as dataclass_replace
from typing import List, Optional, Dict, Any, Union, Protocol
from pathlib import Path
import io
import math

from .base import BaseResponse, ProcessInfo, ErrorInfo
from .llm import LLMInfo
from .enums import ProcessingStatus
from ..exceptions import ProcessingError

class AudioProcessingError(ProcessingError):
    """Audio-spezifische Fehler."""
    ERROR_CODES = {
        'FILE_ERROR': 'Fehler beim Dateizugriff',
        'TRANSCRIPTION_ERROR': 'Fehler bei der Transkription',
        'TRANSFORMATION_ERROR': 'Fehler bei der Transformation',
        'VALIDATION_ERROR': 'Validierungsfehler',
        'SEGMENT_ERROR': 'Fehler bei der Segmentierung',
        'CACHE_ERROR': 'Fehler beim Cache-Management'
    }
    
    def __init__(
        self,
        message: str,
        error_code: str = 'AUDIO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        if error_code not in self.ERROR_CODES and error_code != 'AUDIO_PROCESSING_ERROR':
            raise ValueError(f"Unbekannter error_code: {error_code}")
        self.error_code = error_code
        self.details = details or {}

# Woher die Verlaesslichkeitswerte eines Segments stammen. Der Client darf nicht
# raten, ob eine fehlende Zahl „nicht geliefert" oder „nicht gemessen" heisst.
#   whisper  - verbose_json von whisper-1: alle drei Werte je Abschnitt vom Modell
#   logprobs - gpt-*-transcribe mit include=["logprobs"]: avg_logprob aus den
#              Token-Logprobs gemittelt, compression_ratio im Dienst berechnet,
#              no_speech_prob bleibt None
#   none     - das Modell liefert nichts (z.B. gpt-4o-transcribe-diarize)
QUALITY_SOURCES = ("whisper", "logprobs", "none")

# Woher start/end eines Segments stammen.
#   model     - vom Modell je Abschnitt geliefert (whisper-1)
#   chunk     - das Segment ist ein ganzes Stueck; die Grenzen sind die Schnittstellen
#   estimated - Satz innerhalb eines Stuecks; Zeit nach Textposition geschaetzt
#               (gpt-transcribe liefert keine Zeiten innerhalb einer Anfrage)
TIME_SOURCES = ("model", "chunk", "estimated")

# Zeitmarken auf Millisekunden runden: nach dem Verschieben um den Stueck-Offset
# entstehen sonst Werte wie 1843.2000000000003, und bei einigen tausend Woertern
# kostet jede Stelle Platz im Webhook.
_TIME_DIGITS = 3


@dataclass(frozen=True)
class TranscriptionWord:
    """Ein Wort mit Zeitmarken in Sekunden (absolut zur ganzen Datei, wie die Segmente).

    Nur ``whisper-1`` liefert Woerter (``timestamp_granularities=["word"]``).
    """
    word: str
    start: float
    end: float

    def __post_init__(self) -> None:
        """Validiert die Zeitmarken; ein Wort darf null Dauer haben (Whisper liefert das)."""
        if self.start < 0:
            raise ValueError("Wort-Start muss positiv sein")
        if self.end < self.start:
            raise ValueError("Wort-Ende darf nicht vor dem Start liegen")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Wort in ein Dictionary."""
        return {
            "word": self.word,
            "start": round(self.start, _TIME_DIGITS),
            "end": round(self.end, _TIME_DIGITS),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TranscriptionWord':
        """Erstellt ein Wort aus einem Dictionary."""
        return cls(word=str(data["word"]), start=float(data["start"]), end=float(data["end"]))

    def shifted(self, offset_seconds: float) -> 'TranscriptionWord':
        """Kopie mit verschobenen Zeitmarken."""
        return TranscriptionWord(self.word, self.start + offset_seconds, self.end + offset_seconds)


@dataclass
class TranscriptionSegment:
    """Ein Segment einer Transkription.

    Die drei Werte ``avg_logprob``, ``compression_ratio`` und ``no_speech_prob``
    sind die Rohwerte des Whisper-Decoders (oder ihr Ersatz, siehe
    ``quality_source``). ``None`` heisst „nicht geliefert" — das ist etwas anderes
    als 0.0 und wird nicht stillschweigend durch einen Default ersetzt.

    Sprache, zwei Meinungen:
    - ``language``: die Sprache, die das Modell fuer das ganze Stueck gemeldet hat
      (Whisper entscheidet je Anfrage, nicht je Satz)
    - ``text_language`` / ``text_language_prob``: aus dem Segmenttext bestimmt
      (lingua, reine Textstatistik). Weichen beide ab, hat Whisper den Abschnitt
      vermutlich uebersetzt statt transkribiert. Die Bewertung macht der Client.

    ``words`` gibt es nur bei ``whisper-1``; sonst None (und im Dict fehlt der
    Schluessel), nicht eine erfundene leere Liste.
    """
    text: str
    segment_id: int
    start: float
    end: float
    speaker: Optional[str] = None
    # Wahrscheinlichkeit 0–1, abgeleitet aus avg_logprob (exp, begrenzt). Ohne
    # avg_logprob bleibt sie None statt eines stummen 1.0.
    confidence: Optional[float] = None
    title: Optional[str] = None
    avg_logprob: Optional[float] = None
    compression_ratio: Optional[float] = None
    no_speech_prob: Optional[float] = None
    quality_source: str = "none"
    language: Optional[str] = None
    text_language: Optional[str] = None
    text_language_prob: Optional[float] = None
    words: Optional[List[TranscriptionWord]] = None
    # Alle Sprachen, die das Modell fuer das Stueck gemeldet hat (gpt-transcribe meldet
    # bei gemischter Rede mehrere, ohne Rangfolge). ``language`` ist nur gesetzt, wenn
    # es genau eine war.
    languages: Optional[List[str]] = None
    # Schlechtester Token-Logprob im Segment (nur quality_source "logprobs"): zeigt
    # einzelne unsichere Woerter, die im Mittelwert untergehen.
    min_logprob: Optional[float] = None
    time_source: str = "model"

    def __post_init__(self) -> None:
        """Validiert die Segment-Daten und leitet confidence aus avg_logprob ab."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if self.segment_id < 0:
            raise ValueError("Segment ID muss positiv sein")
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.quality_source not in QUALITY_SOURCES:
            raise ValueError(
                f"quality_source muss eines von {', '.join(QUALITY_SOURCES)} sein, nicht '{self.quality_source}'"
            )
        if self.confidence is None and self.avg_logprob is not None:
            self.confidence = min(1.0, max(0.0, math.exp(self.avg_logprob)))
        if self.confidence is not None and (self.confidence < 0 or self.confidence > 1):
            raise ValueError("Confidence muss zwischen 0 und 1 liegen")
        if self.title is not None and not self.title.strip():
            raise ValueError("Title darf nicht leer sein wenn gesetzt")
        if self.text_language_prob is not None and not 0.0 <= self.text_language_prob <= 1.0:
            raise ValueError("text_language_prob muss zwischen 0 und 1 liegen")
        if self.time_source not in TIME_SOURCES:
            raise ValueError(
                f"time_source muss eines von {', '.join(TIME_SOURCES)} sein, nicht '{self.time_source}'"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Segment in ein Dictionary.

        Alle Wertefelder stehen immer drin, auch wenn sie None sind. Nur ``words``
        fehlt, wenn das Modell keine Woerter liefert.
        """
        data: Dict[str, Any] = {
            "text": self.text,
            "segment_id": self.segment_id,
            "start": round(self.start, _TIME_DIGITS),
            "end": round(self.end, _TIME_DIGITS),
            "speaker": self.speaker,
            "confidence": self.confidence,
            "title": self.title,
            "avg_logprob": self.avg_logprob,
            "compression_ratio": self.compression_ratio,
            "no_speech_prob": self.no_speech_prob,
            "quality_source": self.quality_source,
            "language": self.language,
            "languages": list(self.languages) if self.languages is not None else None,
            "text_language": self.text_language,
            "text_language_prob": self.text_language_prob,
            "min_logprob": self.min_logprob,
            "time_source": self.time_source,
        }
        if self.words is not None:
            data["words"] = [w.to_dict() for w in self.words]
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TranscriptionSegment':
        """Erstellt ein Segment aus einem Dictionary; unbekannte Schluessel werden ignoriert.

        Alte Cache-Eintraege kennen die Verlaesslichkeitsfelder nicht, neuere koennten
        Felder tragen, die diese Version nicht kennt — beides darf nicht scheitern.
        """
        known = {f.name for f in dataclass_fields(cls)}
        values: Dict[str, Any] = {key: value for key, value in data.items() if key in known}
        raw_words: Any = values.get("words")
        if isinstance(raw_words, list):
            values["words"] = [
                w if isinstance(w, TranscriptionWord) else TranscriptionWord.from_dict(w)
                for w in raw_words
            ]
        return cls(**values)

    def shifted(self, offset_seconds: float, segment_id: Optional[int] = None) -> 'TranscriptionSegment':
        """Kopie mit um ``offset_seconds`` verschobenen Zeitmarken (Stueck -> ganze Datei).

        Verschiebt auch die Woerter; alle anderen Felder wandern unveraendert mit.
        """
        return dataclass_replace(
            self,
            segment_id=self.segment_id if segment_id is None else segment_id,
            start=self.start + offset_seconds,
            end=self.end + offset_seconds,
            words=[w.shifted(offset_seconds) for w in self.words] if self.words is not None else None,
        )

@dataclass
class TranscriptionResult:
    """Ein Transkriptionsergebnis mit Text, Sprache und Segmenten.

    ``source_language`` ist die Sprache, mit der weitergearbeitet wird (Vorgabe des
    Aufrufers oder, bei "auto", die erkannte). ``detected_language`` ist nur das,
    was das Modell selbst gemeldet hat — None, wenn es nichts gemeldet hat.
    """
    text: str
    source_language: str
    segments: List[TranscriptionSegment] = field(default_factory=list)
    detected_language: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert das Transkriptionsergebnis."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if not self.source_language.strip():
            raise ValueError("Source language darf nicht leer sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "text": self.text,
            "source_language": self.source_language,
            "detected_language": self.detected_language,
            "segments": [s.to_dict() for s in self.segments] if self.segments else []
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TranscriptionResult':
        """Erstellt ein TranscriptionResult aus einem Dictionary."""
        segments: List[TranscriptionSegment] = [
            TranscriptionSegment.from_dict(s) for s in data.get('segments', [])
        ]
        detected: Any = data.get('detected_language')

        return cls(
            text=data['text'],
            source_language=data['source_language'],
            segments=segments,
            detected_language=detected if isinstance(detected, str) and detected.strip() else None,
        )

@dataclass
class AudioSegmentInfo:
    """Informationen über ein Audio-Segment"""
    file_path: Union[Path, io.BytesIO]  # Pfad zur Audio-Datei oder BytesIO Objekt
    start: float  # Start in Sekunden
    end: float    # Ende in Sekunden
    duration: float
    size_bytes: Optional[int] = None  # Größe des Segments in Bytes
    title: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Segment-Informationen."""
        if isinstance(self.file_path, (str, Path)):
            self.file_path = Path(self.file_path)
            return
        if not hasattr(self.file_path, 'seek'):
            raise ValueError("file_path muss ein Path oder BytesIO Objekt sein")
            
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.duration <= 0:
            raise ValueError("Duration muss positiv sein")
        if self.size_bytes is not None and self.size_bytes <= 0:
            raise ValueError("size_bytes muss positiv sein wenn gesetzt")
            
    def get_audio_data(self) -> Union[Path, bytes]:
        """Gibt die Audio-Daten zurück."""
        if isinstance(self.file_path, io.BytesIO):
            self.file_path.seek(0)
            return self.file_path.getvalue()
        return self.file_path

@dataclass
class Chapter:
    """Ein Kapitel in der Audio-Datei"""
    title: str
    start: float
    end: float
    segments: List[AudioSegmentInfo] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert die Kapitel-Informationen."""
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")

class AudioMetadataProtocol(Protocol):
    """Protocol für die AudioMetadata-Klasse und ihre dynamischen Attribute."""
    duration: float
    duration_formatted: str
    file_size: int
    sample_rate: int
    channels: int
    bits_per_sample: int
    format: str
    codec: str
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_path: Optional[str]
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]
    original_filename: Optional[str]
    video_id: Optional[str]
    filename: Optional[str]

@dataclass
class AudioMetadata:
    """Metadaten einer Audio-Datei"""
    duration: float
    process_dir: str
    title: str = "Unbekannt"
    format: str = "mp3"
    channels: int = 2
    sample_rate: int = 44100
    bit_rate: int = 128000
    chapters: List[Chapter] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validiert die Metadaten."""
        if not self.title.strip():
            raise ValueError("Title darf nicht leer sein")
        # 0.0 ist erlaubt als Sentinel-Wert für Fehlerszenarien (z.B. fehlgeschlagene Transkription).
        # Nur negative Werte sind ungültig, da 0.0 "unbekannte Dauer" signalisiert.
        if self.duration < 0:
            raise ValueError("Duration darf nicht negativ sein")
        if not self.format.strip():
            raise ValueError("Format darf nicht leer sein")
        if self.channels <= 0:
            raise ValueError("Channels muss positiv sein")
        if self.sample_rate <= 0:
            raise ValueError("Sample rate muss positiv sein")
        if self.bit_rate <= 0:
            raise ValueError("Bit rate muss positiv sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Metadaten in ein Dictionary."""
        return {
            'title': self.title,
            'duration': self.duration,
            'format': self.format,
            'channels': self.channels,
            'sample_rate': self.sample_rate,
            'bit_rate': self.bit_rate,
            'process_dir': self.process_dir,
            'chapters': [
                {
                    'title': c.title,
                    'start': c.start,
                    'end': c.end,
                    'segments': [
                        {
                            'start': s.start,
                            'end': s.end,
                            'duration': s.duration,
                            'title': s.title
                        }
                        for s in c.segments
                    ]
                }
                for c in self.chapters
            ]
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioMetadata':
        """Erstellt ein AudioMetadata-Objekt aus einem Dictionary.
        
        Args:
            data: Dictionary mit den Metadaten
            
        Returns:
            AudioMetadata: Das erstellte AudioMetadata-Objekt
        """
        # Erstelle Chapters aus den Daten, falls vorhanden
        chapters: List[Chapter] = []
        for chapter_data in data.get('chapters', []):
            segments: List[AudioSegmentInfo] = []
            for segment_data in chapter_data.get('segments', []):
                # Erstelle ein AudioSegmentInfo für jedes Segment
                segments.append(AudioSegmentInfo(
                    file_path=Path(""),  # Leerer Pfad, da wir keine Dateien haben
                    start=segment_data.get('start', 0.0),
                    end=segment_data.get('end', 0.0),
                    duration=segment_data.get('duration', 0.0),
                    title=segment_data.get('title')
                ))
            
            # Erstelle ein Chapter mit den Segmenten
            chapters.append(Chapter(
                title=chapter_data.get('title', ''),
                start=chapter_data.get('start', 0.0),
                end=chapter_data.get('end', 0.0),
                segments=segments
            ))
        
        # Erstelle das AudioMetadata-Objekt
        return cls(
            title=data.get('title', 'Unbekannt'),
            duration=data.get('duration', 0.0),
            format=data.get('format', 'mp3'),
            channels=data.get('channels', 2),
            sample_rate=data.get('sample_rate', 44100),
            bit_rate=data.get('bit_rate', 128000),
            process_dir=data.get('process_dir', ''),
            chapters=chapters
        )

@dataclass(frozen=True)
class AudioProcessingResult:
    """Ergebnis der Audio-Verarbeitung."""
    transcription: TranscriptionResult
    metadata: AudioMetadata
    process_id: Optional[str] = None
    transformation_result: Optional[Any] = None
    
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses. Fehlgeschlagene Transkriptionen werden als ERROR markiert.
        Erkennt sowohl [Transkription fehlgeschlagen: ...] als auch [Transkriptionsfehler: ...]
        aus transcription_utils, damit API-Fehler (z.B. invalid_api_key) nicht als Erfolg gelten.
        """
        if not self.transcription or not self.transcription.text:
            return ProcessingStatus.ERROR
        text = self.transcription.text.strip()
        if text.startswith("[Transkription fehlgeschlagen") or text.startswith("[Transkriptionsfehler"):
            return ProcessingStatus.ERROR
        return ProcessingStatus.SUCCESS

    def __post_init__(self) -> None:
        """Initialisiert das AudioProcessingResult."""
        if not self.transcription:
            raise ValueError("Transcription darf nicht None sein")
        if not self.metadata:
            raise ValueError("Metadata darf nicht None sein")

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary.

        ``segments`` und ``language`` liegen zusaetzlich flach im Block: das ist der
        Vertrag fuer Clients (Sync-Antwort, Webhook und SSE lesen ``data.segments``
        mit den Verlaesslichkeitswerten je Abschnitt und ``data.language`` fuer die
        Sprachdrift-Pruefung). ``language`` ist None, wenn das Modell keine Sprache
        gemeldet hat.
        """
        transcription = self.transcription.to_dict() if self.transcription else None
        return {
            'transcription': transcription,
            'segments': list(transcription['segments']) if transcription else [],
            'language': self.transcription.detected_language if self.transcription else None,
            'metadata': self.metadata.to_dict() if self.metadata else None,
            'process_id': self.process_id,
            'transformation_result': self.transformation_result,
            'status': self.status.value
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AudioProcessingResult':
        """Erstellt ein AudioProcessingResult aus einem Dictionary."""
        return cls(
            transcription=TranscriptionResult.from_dict(data.get('transcription', {})) if data.get('transcription') else TranscriptionResult(text="", source_language="unknown"),
            metadata=AudioMetadata.from_dict(data.get('metadata', {})) if data.get('metadata') else AudioMetadata(duration=0.0, process_dir="", format="unknown", channels=0),
            process_id=data.get('process_id'),
            transformation_result=data.get('transformation_result')
        )

@dataclass(frozen=True, init=False)
class AudioResponse(BaseResponse):
    """Standardisierte Response für Audio-Verarbeitung."""
    data: Optional[AudioProcessingResult] = field(default=None)

    def __init__(
        self,
        data: AudioProcessingResult,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> None:
        """Initialisiert die AudioResponse."""
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        if process:
            object.__setattr__(self, 'process', process)

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Response in ein Dictionary."""
        base_dict = super().to_dict()
        base_dict['data'] = self.data.to_dict() if self.data else None
        return base_dict

    @classmethod
    def create(
        cls,
        data: Optional[AudioProcessingResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'AudioResponse':
        """Erstellt eine erfolgreiche Response.
        
        Args:
            data: Die Verarbeitungsergebnisse
            process: Optionale ProcessInfo mit LLM-Tracking
            **kwargs: Weitere Parameter für die Response
            
        Returns:
            AudioResponse: Die erstellte Response
            
        Raises:
            ValueError: Wenn data None ist
        """
        if data is None:
            raise ValueError("data must not be None")
            
        # Erstelle Response mit ProcessInfo
        response = cls(
            data=data,
            process=process,
            **kwargs
        )
        
        # Setze Status auf SUCCESS
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'AudioResponse':
        """Erstellt eine Error-Response.
        
        Args:
            error: Die Fehlerinformationen
            process: Optionale ProcessInfo mit LLM-Tracking
            **kwargs: Weitere Parameter für die Response
            
        Returns:
            AudioResponse: Die Error-Response
        """
        # Erstelle leeres Result für Error-Response
        empty_result = AudioProcessingResult(
            transcription=TranscriptionResult(
                text="",
                source_language="unknown"
            ),
            metadata=AudioMetadata(
                duration=0.0,
                process_dir="",
                format="unknown",
                channels=0
            )
        )
        
        # Erstelle Response mit Error
        response = cls(
            data=empty_result,
            process=process,
            **kwargs
        )
        
        # Setze Status und Error
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        
        return response

@dataclass
class WhisperSegment:
    """Ein Segment aus der Whisper API."""
    text: str
    start: float
    end: float
    confidence: float = 1.0
    
    def __post_init__(self) -> None:
        """Validiert die Segment-Daten."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if self.start < 0:
            raise ValueError("Start muss positiv sein")
        if self.end <= self.start:
            raise ValueError("End muss größer als Start sein")
        if self.confidence < 0 or self.confidence > 1:
            raise ValueError("Confidence muss zwischen 0 und 1 liegen")

@dataclass
class WhisperResponse:
    """Response von der Whisper API."""
    text: str
    language: str
    duration: float
    segments: List[WhisperSegment]
    task: str = "transcribe"
    
    def __post_init__(self) -> None:
        """Validiert die Response-Daten."""
        if not self.text.strip():
            raise ValueError("Text darf nicht leer sein")
        if not self.language.strip():
            raise ValueError("Language darf nicht leer sein")
        if self.duration <= 0:
            raise ValueError("Duration muss positiv sein")
        if not self.segments:
            raise ValueError("Segments darf nicht leer sein")
        if not self.task in ["transcribe", "translate"]:
            raise ValueError("Task muss 'transcribe' oder 'translate' sein")
            
    @classmethod
    def from_api_response(cls, response: Dict[str, Any]) -> 'WhisperResponse':
        """Erstellt eine WhisperResponse aus der API-Antwort."""
        segments = [
            WhisperSegment(
                text=seg.get('text', ''),
                start=seg.get('start', 0.0),
                end=seg.get('end', 0.0),
                confidence=seg.get('confidence', 1.0)
            )
            for seg in response.get('segments', [])
        ]
        
        return cls(
            text=response.get('text', ''),
            language=response.get('language', ''),
            duration=response.get('duration', 0.0),
            segments=segments,
            task=response.get('task', 'transcribe')
        )

@dataclass
class AudioTranscriptionParams:
    """Parameter für die Audio-Transkription."""
    model: str = "whisper-1"
    language: Optional[str] = None
    response_format: str = "verbose_json"
    temperature: float = 0.0
    
    def __post_init__(self) -> None:
        """Validiert die Parameter."""
        if not self.model.strip():
            raise ValueError("Model darf nicht leer sein")
        if self.language is not None and not self.language.strip():
            raise ValueError("Language darf nicht leer sein wenn gesetzt")
        if not self.response_format in ["json", "text", "srt", "verbose_json", "vtt"]:
            raise ValueError("Response format muss einer der folgenden Werte sein: json, text, srt, verbose_json, vtt")
        if self.temperature < 0 or self.temperature > 1:
            raise ValueError("Temperature muss zwischen 0 und 1 liegen")
            
    def to_api_params(self) -> Dict[str, Any]:
        """Konvertiert die Parameter in ein Dictionary für die API."""
        params = {
            "model": self.model,
            "response_format": self.response_format,
            "temperature": self.temperature
        }
        if self.language:
            params["language"] = self.language
        return params 

@dataclass
class AudioProcessingRequest:
    """Request-Daten für die Audio-Verarbeitung."""
    source: str
    source_language: Optional[str] = None
    target_language: Optional[str] = None
    template: Optional[str] = None
    original_filename: Optional[str] = None
    video_id: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert die Request-Daten."""
        if not self.source:
            raise ValueError("Source darf nicht leer sein")

@dataclass
class AudioProcessingProcess:
    """Process-Daten für die Audio-Verarbeitung."""
    elapsed_time: int  # in Millisekunden
    llm_info: Optional[LLMInfo] = None
