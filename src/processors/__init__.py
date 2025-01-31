"""
Processor-Module für die Common Secretary Services.
"""

from src.core.models.metadata import MetadataResponse
from src.core.models.transformer import TransformerResponse
from src.core.models.youtube import YoutubeProcessingResult

from .base_processor import BaseProcessor, BaseProcessorResponse
from .metadata_processor import MetadataProcessor
from .transformer_processor import TransformerProcessor
from .youtube_processor import YoutubeProcessor

__all__ = [
    'BaseProcessor',
    'BaseProcessorResponse',
    'MetadataProcessor',
    'MetadataResponse',
    'TransformerProcessor',
    'TransformerResponse',
    'YoutubeProcessor',
    'YoutubeProcessingResult',
]
