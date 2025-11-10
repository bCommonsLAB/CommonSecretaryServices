"""
@fileoverview Audio Utilities - Utility class for audio file segmentation

@description
Utility class for audio processing. This module provides functions for splitting
audio files into smaller segments for processing.

Main functionality:
- Split audio files into segments of specified length
- Convert audio formats (MP3)
- Handle audio data as bytes

Features:
- Segment-based audio processing
- MP3 format support
- Configurable segment length
- Bytes-based I/O

@module utils.audio_utils

@exports
- AudioProcessor: Class - Utility class for audio segmentation

@usedIn
- Can be used for audio preprocessing in processors
- Audio segmentation utilities

@dependencies
- External: pydub - Audio manipulation library
- Standard: io - BytesIO for in-memory file handling
"""

from typing import List
from io import BytesIO
from pydub import AudioSegment  # type: ignore

class AudioProcessor:
    """Utility-Klasse für Audio-Verarbeitung."""
    
    @staticmethod
    def split_audio(audio_data: bytes, segment_length_minutes: int = 5) -> List[bytes]:
        """Teilt eine Audio-Datei in Segmente bestimmter Länge.
        
        Args:
            audio_data: Die Audio-Daten als Bytes
            segment_length_minutes: Gewünschte Länge der Segmente in Minuten
            
        Returns:
            Liste von Audio-Segmenten als Bytes
        """
        # Konvertiere Bytes zu AudioSegment
        audio = AudioSegment.from_mp3(BytesIO(audio_data))  # type: ignore
        
        segment_length_ms = segment_length_minutes * 60 * 1000
        segments: List[bytes] = []
        
        # Teile Audio in Segmente
        for start in range(0, len(audio), segment_length_ms):  # type: ignore
            end = start + segment_length_ms
            segment = audio[start:end]  # type: ignore
            
            # Konvertiere Segment zurück zu Bytes
            buffer = BytesIO()
            segment.export(buffer, format="mp3")  # type: ignore
            segments.append(buffer.getvalue())
            
        return segments 