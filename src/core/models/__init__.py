"""
Datenmodelle für die Anwendung.
"""

# Job und Batch Datenmodelle
from .job_models import (
    JobStatus,
    AccessVisibility,
    AccessControl,
    LogEntry,
    JobProgress,
    JobParameters,
    JobResults,
    JobError,
    Job,
    Batch
)

# Ältere Modelle für Abwärtskompatibilität
try:
    from .llm import LLModel, LLMRequest, LLMInfo
    from .metadata import ContentMetadata, TechnicalMetadata
    from .transformer import TransformerInput, TransformerOutput, TransformerData, TransformerResponse
    from .audio import AudioSegmentInfo, Chapter, AudioMetadata, AudioProcessingResult
    from .youtube import YoutubeMetadata, YoutubeProcessingResult
    from .base import ErrorInfo, RequestInfo, ProcessInfo
except ImportError:
    # Ältere Module sind optional
    pass

__all__ = [
    # Job und Batch Modelle
    "JobStatus",
    "AccessVisibility",
    "AccessControl",
    "LogEntry",
    "JobProgress",
    "JobParameters",
    "JobResults",
    "JobError",
    "Job",
    "Batch",
    
    # Ältere Modelle
    "LLModel",
    "LLMRequest",
    "LLMInfo",
    "ErrorInfo",
    "RequestInfo",
    "ProcessInfo",
    "ContentMetadata",
    "TechnicalMetadata",
    "TransformerInput",
    "TransformerOutput",
    "TransformerData",
    "TransformerResponse",
    "AudioSegmentInfo",
    "Chapter",
    "AudioMetadata",
    "AudioProcessingResult",
    "YoutubeMetadata",
    "YoutubeProcessingResult"
] 