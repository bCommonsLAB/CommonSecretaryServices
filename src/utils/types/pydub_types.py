"""
Type-Definitionen für die pydub-Bibliothek.
"""

from typing import Protocol, Any, Union
from io import BytesIO

class AudioSegmentProtocol(Protocol):
    """Protocol für die AudioSegment-Klasse von pydub."""
    
    def __len__(self) -> int:
        """Gibt die Länge des AudioSegments in Millisekunden zurück."""
        ...
        
    def __getitem__(self, millisecond: Union[int, slice]) -> "AudioSegmentProtocol":
        """Gibt ein Segment des AudioSegments zurück."""
        ...
        
    @classmethod
    def from_mp3(cls, file: Union[str, BytesIO], parameters: Any = None) -> "AudioSegmentProtocol":
        """Erstellt ein AudioSegment aus einer MP3-Datei."""
        ...
        
    def export(self, file: Union[str, BytesIO], format: str = "mp3", **kwargs: Any) -> Any:
        """Exportiert das AudioSegment in eine Datei."""
        ... 