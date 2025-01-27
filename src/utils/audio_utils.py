"""
Utility-Klasse für Audio-Verarbeitung.

Diese Klasse bietet Funktionen zum Aufteilen von Audio-Dateien in kleinere Segmente.
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