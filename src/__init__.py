"""
Common Secretary Services - Ein Framework für die Verarbeitung von Text und Medien.
"""

__version__ = "0.1.0"

from src.core.models import (  # LLM Models; Base Models; Metadata Models; Transformer Models; Audio Models; YouTube Models
    AudioMetadata, AudioProcessingResult, AudioSegmentInfo, Chapter,
    ContentMetadata, ErrorInfo, LLMInfo, LLModel, LLMRequest, ProcessInfo,
    RequestInfo, TechnicalMetadata, TransformerData, TransformerInput,
    TransformerOutput, TransformerResponse, YoutubeMetadata,
    YoutubeProcessingResult)
from src.processors import (  # Base Classes; Processors; Response Types
    BaseProcessor, MetadataProcessor, MetadataResponse,
    TransformerProcessor, YoutubeProcessor)

__all__ = [
    '__version__',
    
    # Models
    'LLModel', 'LLMRequest', 'LLMInfo',
    'ErrorInfo', 'RequestInfo', 'ProcessInfo',
    'ContentMetadata', 'TechnicalMetadata',
    'TransformerInput', 'TransformerOutput', 'TransformerData', 'TransformerResponse',
    'AudioSegmentInfo', 'Chapter', 'AudioMetadata', 'AudioProcessingResult',
    'YoutubeMetadata', 'YoutubeProcessingResult',
    
    # Processors
    'BaseProcessor', 
    'TransformerProcessor',
    'MetadataProcessor', 'MetadataResponse',
    'YoutubeProcessor'
]
