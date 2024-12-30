from pydub import AudioSegment
import io
from typing import List

class AudioProcessor:
    """Utility-Klasse für Audio-Verarbeitung.
    
    Diese Klasse bietet Funktionen zum Aufteilen von Audio-Dateien in kleinere Segmente.
    """
    
    @staticmethod
    def split_audio(audio_data: bytes, segment_length_minutes: int = 5) -> List[bytes]:
        """Teilt eine Audio-Datei in Segmente bestimmter Länge.
        
        Args:
            audio_data (bytes): Die Audio-Daten als Bytes
            segment_length_minutes (int): Gewünschte Länge der Segmente in Minuten
            
        Returns:
            List[bytes]: Liste von Audio-Segmenten als Bytes
        """
        # Konvertiere Bytes zu AudioSegment
        audio = AudioSegment.from_mp3(io.BytesIO(audio_data))
        
        segment_length_ms = segment_length_minutes * 60 * 1000
        segments = []
        
        # Teile Audio in Segmente
        for start in range(0, len(audio), segment_length_ms):
            end = start + segment_length_ms
            segment = audio[start:end]
            
            # Konvertiere Segment zurück zu Bytes
            buffer = io.BytesIO()
            segment.export(buffer, format="mp3")
            segments.append(buffer.getvalue())
            
        return segments 