"""
Datenmodelle für die Anwendung.
"""

# Basis-Modelle und Enums
from .base import ErrorInfo, RequestInfo, ProcessInfo
from .enums import ProcessingStatus

# Protokolle
from .protocols import CacheableResult

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

# LLM-Modelle
from .llm import LLModel, LLMRequest, LLMInfo

# Metadaten-Modelle
from .metadata import ContentMetadata, TechnicalMetadata

# Transformer-Modelle
from .transformer import TransformerInput, TransformerData, TransformerResponse

# Audio-Modelle
from .audio import (
    AudioSegmentInfo,
    Chapter,
    AudioMetadata,
    AudioProcessingResult,
    TranscriptionResult,
    TranscriptionSegment
)

# Video-Modelle
from .video import VideoMetadata, VideoProcessingResult

# YouTube-Modelle
from .youtube import YoutubeMetadata, YoutubeProcessingResult

# Story-Modelle
from .story import (
    StoryProcessorInput,
    StoryProcessorOutput,
    StoryProcessingResult,
    StoryData,
    StoryResponse,
    TopicModel,
    TargetGroupModel,
    TopicDict,
    TargetGroupDict,
    SessionDict
)

__all__ = [
    # Basis-Modelle und Enums
    "ErrorInfo",
    "RequestInfo",
    "ProcessInfo",
    "ProcessingStatus",
    
    # Protokolle
    "CacheableResult",
    
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
    
    # LLM-Modelle
    "LLModel",
    "LLMRequest",
    "LLMInfo",
    
    # Metadaten-Modelle
    "ContentMetadata",
    "TechnicalMetadata",
    
    # Transformer-Modelle
    "TransformerInput",
    "TransformerData",
    "TransformerResponse",
    
    # Audio-Modelle
    "AudioSegmentInfo",
    "Chapter",
    "AudioMetadata",
    "AudioProcessingResult",
    "TranscriptionResult",
    "TranscriptionSegment",
    
    # Video-Modelle
    "VideoMetadata",
    "VideoProcessingResult",
    
    # YouTube-Modelle
    "YoutubeMetadata",
    "YoutubeProcessingResult",
    
    # Story-Modelle
    "StoryProcessorInput",
    "StoryProcessorOutput",
    "StoryProcessingResult",
    "StoryData",
    "StoryResponse",
    "TopicModel",
    "TargetGroupModel",
    "TopicDict",
    "TargetGroupDict",
    "SessionDict"
] 