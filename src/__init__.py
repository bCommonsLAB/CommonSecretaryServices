"""
Common Secretary Services - Ein Framework für die Verarbeitung von Text und Medien.
"""

__version__ = "0.1.0"

from src.core.models import (
    # LLM Models
    LLModel, LLMRequest, LLMInfo,
    
    # Base Models
    ErrorInfo, RequestInfo, ProcessInfo,
    
    # Metadata Models
    ContentMetadata, TechnicalMetadata,
    
    # Transformer Models
    TransformerInput, TransformerOutput, TransformerData, TransformerResponse,
    
    # Audio Models
    AudioSegmentInfo, Chapter, AudioMetadata, AudioProcessingResult,
    
    # YouTube Models
    YoutubeMetadata, YoutubeProcessingResult
)

from src.processors import (
    # Base Classes
    BaseProcessor, BaseProcessorResponse,
    
    # Processors
    TransformerProcessor,
    MetadataProcessor,
    YoutubeProcessor,
    
    # Response Types
    MetadataResponse
)

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
    'BaseProcessor', 'BaseProcessorResponse',
    'TransformerProcessor',
    'MetadataProcessor', 'MetadataResponse',
    'YoutubeProcessor'
]
