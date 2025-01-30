"""
Prozessor-Module für Common Secretary Services.
"""

from .metadata_processor import MetadataProcessor
from .transcriber import WhisperTranscriber
from .transformer import TransformerProcessor

__all__ = [
    "MetadataProcessor",
    "WhisperTranscriber",
    "TransformerProcessor"
]
