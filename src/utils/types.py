"""
Zentrale Typdefinitionen für die Verarbeitung von Texten, Audio und anderen Medien.
"""
from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field, ConfigDict
from pathlib import Path
from datetime import datetime
import json
from enum import Enum

def make_json_serializable(obj: Any) -> Any:
    """Konvertiert ein Objekt in ein JSON-serialisierbares Format."""
    if isinstance(obj, (datetime, Path)):
        return str(obj)
    elif isinstance(obj, (list, tuple, set)):
        return [make_json_serializable(item) for item in obj]
    elif isinstance(obj, dict):
        return {key: make_json_serializable(value) for key, value in obj.items()}
    elif hasattr(obj, 'model_dump'):
        return make_json_serializable(obj.model_dump())
    return obj

class CustomModel(BaseModel):
    """Basismodell mit erweiterten Serialisierungs- und Validierungsfunktionen."""
    
    model_config = ConfigDict(
        validate_assignment=True,  # Validierung bei Zuweisung
        populate_by_name=True,     # Erlaubt Zugriff auf Felder via Alias
    )
    
    def serializable_dict(self, **kwargs) -> dict:
        """Gibt ein Dict zurück, das nur serialisierbare Felder enthält."""
        default_dict = self.model_dump(**kwargs)
        return make_json_serializable(default_dict)
    
    @classmethod
    def construct_validated(cls, **data):
        """Erstellt eine Instanz ohne Validierung, wenn die Daten bereits validiert wurden."""
        return cls.model_construct(**data)

class Chapter(CustomModel):
    """Ein Kapitel mit Start- und Endzeit."""
    title: str = Field(description="Titel des Kapitels")
    start_time: float = Field(description="Startzeit in Sekunden")
    end_time: float = Field(description="Endzeit in Sekunden")

class AudioSegmentInfo(CustomModel):
    """Information über ein Audio-Segment.
    
    Attributes:
        file_path (Path): Pfad zur Audio-Datei
        title (Optional[str]): Titel des Segments (z.B. Kapitel-Titel)
        binary_data (Optional[bytes]): Binäre Audio-Daten (optional, wird nur bei Bedarf geladen)
    """
    file_path: Path
    title: Optional[str] = None
    binary_data: Optional[bytes] = None

class llModel(CustomModel):
    """Informationen über die Nutzung eines LLM."""
    model: str = Field(description="Name des verwendeten Modells")
    duration: float = Field(description="Verarbeitungsdauer in Sekunden")
    token_count: int = Field(description="Anzahl der verarbeiteten Tokens")

class TranscriptionSegment(CustomModel):
    """Ein Segment einer Transkription mit Zeitstempeln."""
    text: str = Field(description="Der transkribierte Text des Segments")
    segment_id: int = Field(description="ID des Segments für die Sortierung")
    title: Optional[str] = Field(None, description="Titel des Segments (z.B. Kapitel-Titel)")

class TranscriptionResult(CustomModel):
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

class TranslationResult(CustomModel):
    """Ergebnis einer Übersetzung."""
    text: str = Field(description="Der übersetzte Text")
    source_language: str = Field(description="Ausgangssprache (ISO 639-1)")
    target_language: str = Field(description="Zielsprache (ISO 639-1)")
    llms: List[llModel] = Field(default_factory=list, description="Verwendete LLM-Modelle")

class AudioMetadata(CustomModel):
    """Audio-spezifische Metadaten."""
    duration: float = Field(description="Dauer der Audio-Datei in Sekunden")
    process_dir: str = Field(description="Verzeichnis mit den Verarbeitungsdaten")
    args: Dict[str, Any] = Field(default_factory=dict, description="Verwendete Verarbeitungsparameter")

class AudioProcessingResult(CustomModel):
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

class YoutubeMetadata(CustomModel):
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

class YoutubeProcessingResult(CustomModel):
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

class ChapterInfo(CustomModel):
    """Repräsentiert ein Kapitel mit seinen Audio-Segmenten.
    
    Attributes:
        title (Optional[str]): Der Titel des Kapitels
        segments (List[AudioSegmentInfo]): Liste der Audio-Segmente in diesem Kapitel
    """
    title: Optional[str] = None
    segments: List[AudioSegmentInfo]

    def __str__(self) -> str:
        return f"Chapter(title={self.title}, segments_count={len(self.segments)})" 

class EventFormat(str, Enum):
    ONLINE = "online"
    HYBRID = "hybrid"
    PHYSICAL = "physical"

class PublicationStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"

class ContentMetadata(CustomModel):
    """Inhaltliche Metadaten für verschiedene Medientypen."""
    
    # Basis-Metadaten
    type: str = Field(description="Art der Metadaten (z.B. video, audio, article)")
    created: str = Field(description="Erstellungszeitpunkt (ISO 8601)")
    modified: str = Field(description="Letzter Änderungszeitpunkt (ISO 8601)")
    
    # Bibliographische Grunddaten
    title: str = Field(description="Haupttitel des Werks")
    subtitle: Optional[str] = Field(None, description="Untertitel des Werks")
    authors: List[str] = Field(description="Liste der Autoren")
    publisher: Optional[str] = Field(None, description="Verlag oder Publisher")
    publicationDate: Optional[str] = Field(None, description="Erscheinungsdatum")
    isbn: Optional[str] = Field(None, description="ISBN (bei Büchern)")
    doi: Optional[str] = Field(None, description="Digital Object Identifier")
    edition: Optional[str] = Field(None, description="Auflage")
    language: str = Field(description="Sprache (ISO 639-1)")
    
    # Wissenschaftliche Klassifikation
    subject_areas: Optional[List[str]] = Field(None, description='Fachgebiete')
    keywords: Optional[List[str]] = Field(None, description='Schlüsselwörter')
    abstract: Optional[str] = Field(None, description='Kurzzusammenfassung')
    
    # Räumliche und zeitliche Einordnung
    temporal_start: Optional[str] = Field(None, description="Beginn des behandelten Zeitraums")
    temporal_end: Optional[str] = Field(None, description="Ende des behandelten Zeitraums")
    temporal_period: Optional[str] = Field(None, description="Bezeichnung der Periode")
    spatial_location: Optional[str] = Field(None, description="Ortsname")
    spatial_latitude: Optional[float] = Field(None, description="Geografische Breite")
    spatial_longitude: Optional[float] = Field(None, description="Geografische Länge")
    spatial_habitat: Optional[str] = Field(None, description="Lebensraum/Biotop")
    spatial_region: Optional[str] = Field(None, description="Region/Gebiet")
    
    # Rechte und Lizenzen
    rights_holder: Optional[str] = Field(None, description="Rechteinhaber")
    rights_license: Optional[str] = Field(None, description="Lizenz")
    rights_access: Optional[str] = Field(None, description="Zugriffsrechte")
    rights_usage: Optional[List[str]] = Field(None, description="Nutzungsbedingungen")
    rights_attribution: Optional[str] = Field(None, description="Erforderliche Namensnennung")
    rights_commercial: Optional[bool] = Field(None, description="Kommerzielle Nutzung erlaubt")
    rights_modifications: Optional[bool] = Field(None, description="Modifikationen erlaubt")
    
    # Medienspezifische Metadaten
    resource_type: Optional[str] = Field(None, description="Art der Ressource")
    resource_format: Optional[str] = Field(None, description="Physisches/digitales Format")
    resource_extent: Optional[str] = Field(None, description="Umfang")
    
    # Quellenangaben
    source_title: Optional[str] = Field(None, description="Titel der Quelle")
    source_type: Optional[str] = Field(None, description="Art der Quelle")
    source_identifier: Optional[str] = Field(None, description="Eindeutige Kennung der Quelle")
    
    # Digitale Plattform
    platform_type: Optional[str] = Field(None, description="Art der Plattform")
    platform_url: Optional[str] = Field(None, description="URL zur Ressource")
    platform_id: Optional[str] = Field(None, description="Plattform-spezifische ID")
    platform_uploader: Optional[str] = Field(None, description="Uploader/Kanal")
    platform_category: Optional[str] = Field(None, description="Plattform-Kategorie")
    platform_language: Optional[List[str]] = Field(None, description="Unterstützte Sprachen")
    platform_region: Optional[List[str]] = Field(None, description="Verfügbare Regionen")
    platform_age_rating: Optional[str] = Field(None, description="Altersfreigabe")
    platform_subscription: Optional[str] = Field(None, description="Erforderliches Abonnement")
    
    # Event-spezifische Details
    event_type: Optional[str] = Field(None, description="Art der Veranstaltung")
    event_start: Optional[str] = Field(None, description="Startzeit (ISO 8601)")
    event_end: Optional[str] = Field(None, description="Endzeit (ISO 8601)")
    event_timezone: Optional[str] = Field(None, description="Zeitzone")
    event_format: Optional[str] = Field(None, description="Veranstaltungsformat")
    event_platform: Optional[str] = Field(None, description="Verwendete Plattform")
    event_recording_url: Optional[str] = Field(None, description="Link zur Aufzeichnung")
    
    # Social Media spezifisch
    social_platform: Optional[str] = Field(None, description="Plattform")
    social_handle: Optional[str] = Field(None, description="Benutzername/Handle")
    social_post_id: Optional[str] = Field(None, description="Original Post-ID")
    social_post_url: Optional[str] = Field(None, description="Permalink zum Beitrag")
    social_metrics_likes: Optional[int] = Field(None, description="Anzahl der Likes")
    social_metrics_shares: Optional[int] = Field(None, description="Anzahl der Shares")
    social_metrics_comments: Optional[int] = Field(None, description="Anzahl der Kommentare")
    social_metrics_views: Optional[int] = Field(None, description="Anzahl der Aufrufe")
    social_thread: Optional[List[str]] = Field(None, description="IDs verknüpfter Beiträge")
    
    # Blog/Artikel spezifisch
    blog_url: Optional[str] = Field(None, description="Permalink zum Artikel")
    blog_section: Optional[str] = Field(None, description="Rubrik/Kategorie")
    blog_series: Optional[str] = Field(None, description="Zugehörige Serie/Reihe")
    blog_reading_time: Optional[int] = Field(None, description="Geschätzte Lesezeit in Minuten")
    blog_tags: Optional[List[str]] = Field(None, description="Blog-spezifische Tags")
    blog_comments_url: Optional[str] = Field(None, description="Link zu Kommentaren")
    
    # Interaktive Medien (neu hinzugefügt)
    interactive_type: Optional[str] = Field(None, description="Art des interaktiven Inhalts")
    interactive_requirements: Optional[List[str]] = Field(None, description="Technische Anforderungen")
    interactive_version: Optional[str] = Field(None, description="Version der Anwendung")
    interactive_url: Optional[str] = Field(None, description="URL zur Anwendung")
    
    # Community und Engagement
    community_target: Optional[List[str]] = Field(None, description="Zielgruppe")
    community_hashtags: Optional[List[str]] = Field(None, description="Verwendete Hashtags")
    community_mentions: Optional[List[str]] = Field(None, description="Erwähnte Accounts/Personen")
    community_context: Optional[str] = Field(None, description="Kontext/Anlass")
    
    # Qualitätssicherung
    quality_review_status: Optional[str] = Field(None, description="Review-Status")
    quality_fact_checked: Optional[bool] = Field(None, description="Faktencheck durchgeführt")
    quality_peer_reviewed: Optional[bool] = Field(None, description="Peer-Review durchgeführt")
    quality_verified_by: Optional[List[str]] = Field(None, description="Verifiziert durch")
    
    # Wissenschaftliche Zusatzinformationen
    citations: Optional[List[str]] = Field(None, description="Zitierte Werke")
    methodology: Optional[str] = Field(None, description="Verwendete Methodik")
    funding: Optional[str] = Field(None, description="Förderung/Finanzierung")
    
    # Verwaltung
    collection: Optional[str] = Field(None, description="Zugehörige Sammlung")
    archival_number: Optional[str] = Field(None, description="Archivnummer")
    status: Optional[str] = Field(None, description="Status")
    
    # Digitale Publikationsdetails
    digital_published: Optional[str] = Field(None, description="Erstveröffentlichung online (ISO 8601)")
    digital_modified: Optional[str] = Field(None, description="Letzte Online-Aktualisierung (ISO 8601)")
    digital_version: Optional[str] = Field(None, description="Versionsnummer/Stand")
    digital_status: Optional[str] = Field(None, description="Publikationsstatus")

class TechnicalMetadata(CustomModel):
    """Technische Metadaten für Mediendateien."""
    
    # Datei-Informationen
    file_size: int = Field(description="Dateigröße in Bytes")
    file_mime: str = Field(description="Dateityp (MIME)")
    file_extension: str = Field(description="Dateiendung")
    
    # Medienspezifische Details
    media_duration: Optional[float] = Field(None, description="Länge des Mediums in Sekunden")
    media_bitrate: Optional[int] = Field(None, description="Bitrate in kbps")
    media_codec: Optional[str] = Field(None, description="Verwendeter Codec")
    media_resolution: Optional[str] = Field(None, description="Auflösung (z.B. 1920x1080)")
    media_format: Optional[str] = Field(None, description="Medienformat")
    media_channels: Optional[int] = Field(None, description="Anzahl der Audiokanäle")
    media_samplerate: Optional[int] = Field(None, description="Abtastrate in Hz")
    
    # Bildspezifische Details
    image_width: Optional[int] = Field(None, description="Bildbreite in Pixeln")
    image_height: Optional[int] = Field(None, description="Bildhöhe in Pixeln")
    image_colorspace: Optional[str] = Field(None, description="Farbraum")
    image_dpi: Optional[int] = Field(None, description="Auflösung in DPI")
    
    # Dokumentspezifische Details
    doc_pages: Optional[int] = Field(None, description="Anzahl der Seiten")
    doc_wordcount: Optional[int] = Field(None, description="Anzahl der Wörter")
    doc_software: Optional[str] = Field(None, description="Erstellungssoftware")
    doc_encrypted: Optional[bool] = Field(None, description="Verschlüsselungsstatus")

class CompleteMetadata(CustomModel):
    """Vollständige Metadaten, die technische und inhaltliche Metadaten kombinieren."""
    
    content: ContentMetadata
    technical: TechnicalMetadata 

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Modell in ein Dictionary für die API-Antwort."""
        return {
            'content': self.content.model_dump(),
            'technical': self.technical.model_dump()
        } 