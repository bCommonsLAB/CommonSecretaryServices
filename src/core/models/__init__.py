"""
Core-Modelle für die Datenverarbeitung.
"""

from .llm import LLModel, LLMRequest, LLMInfo
from .metadata import ContentMetadata, TechnicalMetadata
from .transformer import TransformerInput, TransformerOutput, TransformerData, TransformerResponse
from .audio import AudioSegmentInfo, Chapter, AudioMetadata, AudioProcessingResult
from .youtube import YoutubeMetadata, YoutubeProcessingResult
from .base import ErrorInfo, RequestInfo, ProcessInfo

__all__ = [
    # LLM Models
    'LLModel',
    'LLMRequest',
    'LLMInfo',
    
    # Base Models
    'ErrorInfo',
    'RequestInfo',
    'ProcessInfo',
    
    # Metadata Models
    'ContentMetadata',
    'TechnicalMetadata',
    
    # Transformer Models
    'TransformerInput',
    'TransformerOutput',
    'TransformerData',
    'TransformerResponse',
    
    # Audio Models
    'AudioSegmentInfo',
    'Chapter',
    'AudioMetadata',
    'AudioProcessingResult',
    
    # YouTube Models
    'YoutubeMetadata',
    'YoutubeProcessingResult'
] 