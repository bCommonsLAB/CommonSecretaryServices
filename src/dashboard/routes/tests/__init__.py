"""
Test route handlers initialization
"""
from .youtube_test import run_youtube_test
from .audio_test import run_audio_test
from .transformer_test import run_transformer_test
from .health_test import run_health_test

__all__ = [
    'run_youtube_test',
    'run_audio_test',
    'run_transformer_test',
    'run_health_test'
] 