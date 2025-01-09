"""
Zentrale Typdefinitionen für die Verarbeitung von Texten, Audio und anderen Medien.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field
from pathlib import Path

class Chapter(BaseModel):
    """Ein Kapitel mit Start- und Endzeit."""
    title: str = Field(description="Titel des Kapitels")
    start_time: float = Field(description="Startzeit in Sekunden")
    end_time: float = Field(description="Endzeit in Sekunden")

class AudioSegmentInfo(BaseModel):
    """Information über ein Audio-Segment.
    
    Attributes:
        file_path (Path): Pfad zur Audio-Datei
        title (Optional[str]): Titel des Segments (z.B. Kapitel-Titel)
        binary_data (Optional[bytes]): Binäre Audio-Daten (optional, wird nur bei Bedarf geladen)
    """
    file_path: Path
    title: Optional[str] = None
    binary_data: Optional[bytes] = None

class llModel(BaseModel):
    """Informationen über die Nutzung eines LLM."""
    model: str = Field(description="Name des verwendeten Modells")
    duration: float = Field(description="Verarbeitungsdauer in Sekunden")
    token_count: int = Field(description="Anzahl der verarbeiteten Tokens")

class TranscriptionSegment(BaseModel):
    """Ein Segment einer Transkription mit Zeitstempeln."""
    text: str = Field(description="Der transkribierte Text des Segments")
    segment_id: int = Field(description="ID des Segments für die Sortierung")
    title: Optional[str] = Field(None, description="Titel des Segments (z.B. Kapitel-Titel)")

class TranscriptionResult(BaseModel):
    """Ergebnis einer Transkription."""
    text: str = Field(description="Der transkribierte Text")
    detected_language: Optional[str] = Field(None, description="Erkannte Sprache (ISO 639-1)")
    segments: List[TranscriptionSegment] = Field(default_factory=list, description="Liste der Transkriptionssegmente")
    llms: List[llModel] = Field(default_factory=list, description="Verwendete LLM-Modelle")

    def to_dict(self) -> dict:
        """Convert the result to a dictionary."""
        result = {
            "text": self.text,
            "detected_language": self.detected_language,
            "segments": [segment.model_dump() for segment in self.segments],
            "llms": [llm.model_dump() for llm in self.llms]
        }
        return result

class TranslationResult(BaseModel):
    """Ergebnis einer Übersetzung."""
    text: str = Field(description="Der übersetzte Text")
    source_language: str = Field(description="Ausgangssprache (ISO 639-1)")
    target_language: str = Field(description="Zielsprache (ISO 639-1)")
    llms: List[llModel] = Field(default_factory=list, description="Verwendete LLM-Modelle")

class AudioMetadata(BaseModel):
    """Audio-spezifische Metadaten."""
    duration: float = Field(description="Dauer der Audio-Datei in Sekunden")
    process_dir: str = Field(description="Verzeichnis mit den Verarbeitungsdaten")
    args: Dict[str, Any] = Field(default_factory=dict, description="Verwendete Verarbeitungsparameter")

class AudioProcessingResult(BaseModel):
    """
    Ergebnis der Audio-Verarbeitung.
    Kombiniert TranscriptionResult mit Audio-spezifischen Metadaten.
    """
    transcription: TranscriptionResult = Field(description="Transkriptionsergebnis mit Text, Sprache und Segmenten")
    metadata: AudioMetadata = Field(description="Audio-spezifische Metadaten")
    process_id: str = Field(description="ID des Verarbeitungsprozesses")

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert das Ergebnis in ein Dictionary für die API-Antwort.
        
        Returns:
            Dict[str, Any]: API-kompatibles Dictionary
        """
        # Bestimme Original- und übersetzten Text basierend auf den LLMs
        has_translation = len(self.transcription.llms) > 1
        original_text = None
        translated_text = None
        
        if has_translation:
            # Wenn übersetzt wurde, ist der aktuelle Text der übersetzte
            # und wir müssen den Original-Text aus dem Kontext wiederherstellen
            translated_text = self.transcription.text
            original_text = self.metadata.args.get("original_text")
        else:
            # Wenn nicht übersetzt wurde, ist der aktuelle Text das Original
            original_text = self.transcription.text
            
        return {
            "duration": self.metadata.duration,
            "detected_language": self.transcription.detected_language,
            "output_text": self.transcription.text,
            "original_text": original_text,
            "translated_text": translated_text,
            "llm_model": self.transcription.llms[0].model if self.transcription.llms else None,
            "translation_model": self.transcription.llms[-1].model if has_translation else None,
            "token_count": sum(llm.token_count for llm in self.transcription.llms),
            "segments": [segment.model_dump() for segment in self.transcription.segments],
            "process_id": self.process_id,
            "process_dir": self.metadata.process_dir,
            "args": self.metadata.args
        } 

class YoutubeMetadata(BaseModel):
    """Metadaten eines YouTube-Videos."""
    title: str = Field(description="Titel des Videos")
    url: str = Field(description="YouTube-URL")
    video_id: str = Field(description="YouTube Video ID")
    duration: int = Field(description="Dauer des Videos in Sekunden")
    duration_formatted: str = Field(description="Formatierte Dauer (HH:MM:SS)")
    file_size: Optional[int] = Field(None, description="Größe der Audio-Datei in Bytes")
    process_dir: str = Field(description="Verzeichnis mit den Verarbeitungsdaten")
    audio_file: Optional[str] = Field(None, description="Pfad zur extrahierten Audio-Datei")
    
    # Video-spezifische Metadaten
    source_type: str = Field(default="youtube", description="Typ der Quelle")
    availability: Optional[str] = Field(None, description="Verfügbarkeitsstatus des Videos")
    categories: Optional[List[str]] = Field(default_factory=list, description="Video-Kategorien")
    description: Optional[str] = Field(None, description="Video-Beschreibung")
    tags: Optional[List[str]] = Field(default_factory=list, description="Video-Tags")
    thumbnail: Optional[str] = Field(None, description="URL des Video-Thumbnails")
    upload_date: Optional[str] = Field(None, description="Upload-Datum")
    uploader: Optional[str] = Field(None, description="Name des Uploaders")
    uploader_id: Optional[str] = Field(None, description="ID des Uploaders")
    chapters: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="Video-Kapitel")
    view_count: Optional[int] = Field(None, description="Anzahl der Aufrufe")
    like_count: Optional[int] = Field(None, description="Anzahl der Likes")
    dislike_count: Optional[int] = Field(None, description="Anzahl der Dislikes")
    average_rating: Optional[float] = Field(None, description="Durchschnittliche Bewertung")
    age_limit: Optional[int] = Field(None, description="Altersbeschränkung")
    webpage_url: Optional[str] = Field(None, description="Vollständige Webseiten-URL")

class YoutubeProcessingResult(BaseModel):
    """
    Ergebnis der YouTube-Verarbeitung.
    Kombiniert YoutubeMetadata mit optionalem AudioProcessingResult.
    """
    metadata: YoutubeMetadata = Field(description="YouTube-spezifische Metadaten")
    audio_result: Optional[AudioProcessingResult] = Field(None, description="Ergebnis der Audio-Verarbeitung")
    process_id: str = Field(description="ID des Verarbeitungsprozesses")

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert das Ergebnis in ein Dictionary für die API-Antwort.
        
        Returns:
            Dict[str, Any]: API-kompatibles Dictionary
        """
        result = {
            "title": self.metadata.title,
            "duration": self.metadata.duration,
            "url": self.metadata.url,
            "video_id": self.metadata.video_id,
            "process_id": self.process_id,
            "file_size": self.metadata.file_size,
            "process_dir": self.metadata.process_dir,
            "audio_file": self.metadata.audio_file,
            "youtube_metadata": {
                "upload_date": self.metadata.upload_date,
                "uploader": self.metadata.uploader,
                "view_count": self.metadata.view_count,
                "like_count": self.metadata.like_count,
                "description": self.metadata.description,
                "tags": self.metadata.tags,
                "categories": self.metadata.categories
            }
        }
        
        if self.audio_result and self.audio_result.transcription:
            result["transcription"] = self.audio_result.transcription.to_dict()
        if self.audio_result.metadata:
            result["audio_metadata"]= self.audio_result.metadata.model_dump() 
        

        return result 

class ChapterInfo(BaseModel):
    """Repräsentiert ein Kapitel mit seinen Audio-Segmenten.
    
    Attributes:
        title (Optional[str]): Der Titel des Kapitels
        segments (List[AudioSegmentInfo]): Liste der Audio-Segmente in diesem Kapitel
    """
    title: Optional[str] = None
    segments: List[AudioSegmentInfo]

    def __str__(self) -> str:
        return f"Chapter(title={self.title}, segments_count={len(self.segments)})" 