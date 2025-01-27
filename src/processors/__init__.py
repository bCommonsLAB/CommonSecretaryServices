"""
Prozessor-Module für Common Secretary Services.
"""

from .base_processor import BaseProcessor, BaseProcessorResponse
from .transformer_processor import TransformerProcessor
from .metadata_processor import MetadataProcessor, MetadataResponse
from .audio_processor import AudioProcessor, AudioProcessingResult
from .youtube_processor import YoutubeProcessor

__all__ = [
    # Base Classes
    'BaseProcessor',
    'BaseProcessorResponse',
    
    # Processors
    'TransformerProcessor',
    'MetadataProcessor',
    'YoutubeProcessor',
    'AudioProcessor',
    
    # Response Types
    'MetadataResponse',
    'AudioProcessingResult'
]
