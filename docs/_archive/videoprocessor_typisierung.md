# Video-Prozessor Konzept

## Übersicht

Der Video-Prozessor soll als eigenständige Komponente implementiert werden, die sich auf die reine Video-zu-Audio-Konvertierung und Transkription konzentriert. Die Entscheidung für eine separate Implementierung basiert auf folgenden Überlegungen:

### Gründe für separate Implementierung

1. **Single Responsibility Principle**: 
   - YouTube-Prozessor: Fokus auf YouTube-spezifische Funktionen (Metadaten, Kapitel etc.)
   - Video-Prozessor: Fokus auf generische Video-Verarbeitung
   
2. **Wartbarkeit**:
   - Klare Trennung der Zuständigkeiten
   - Einfachere Fehlerbehebung
   - Reduzierte Komplexität pro Komponente

3. **Erweiterbarkeit**:
   - Leichtere Integration weiterer Video-Quellen
   - Unabhängige Weiterentwicklung der Prozessoren

## Technische Spezifikation

### Modell-Integration

Der Video-Prozessor nutzt die folgenden bestehenden Modelle:

1. **Basis-Modelle** (aus `core.models.base`):
   - `RequestInfo`
   - `ProcessInfo`
   - `ErrorInfo`
   - `ProcessingStatus`

2. **Audio-Modelle** (aus `core.models.audio`):
   - `TranscriptionResult`
   - `AudioMetadata`
   - `AudioProcessingResult`
   - `AudioResponse`

3. **LLM-Modelle** (aus `core.models.llm`):
   - `LLMInfo`
   - `LLMRequest`
   - `LLModel`

4. **Transformer-Modelle** (aus `core.models.transformer`):
   - `TransformationResult`
   - `TransformerResponse`

### Neue Modelle

```python
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Union
from pathlib import Path

@dataclass(frozen=True)
class VideoSource:
    """Quelle des zu verarbeitenden Videos."""
    url: Optional[str] = None
    file: Optional[Union[Path, bytes]] = None
    file_name: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Quelle."""
        if not self.url and not self.file:
            raise ValueError("Entweder URL oder File muss angegeben werden")
        if self.file and not self.file_name:
            raise ValueError("Bei File-Upload muss ein Dateiname angegeben werden")

@dataclass(frozen=True)
class VideoMetadata:
    """Metadaten des verarbeiteten Videos."""
    title: str
    source: VideoSource
    duration: int
    duration_formatted: str
    file_size: Optional[int] = None
    process_dir: str
    audio_file: Optional[str] = None

    def __post_init__(self) -> None:
        """Validiert die Metadaten."""
        if not self.title.strip():
            raise ValueError("title darf nicht leer sein")
        if self.duration < 0:
            raise ValueError("duration muss positiv sein")
        if not self.duration_formatted.strip():
            raise ValueError("duration_formatted darf nicht leer sein")
        if not self.process_dir.strip():
            raise ValueError("process_dir darf nicht leer sein")

@dataclass(frozen=True)
class VideoProcessingResult:
    """Ergebnis der Video-Verarbeitung."""
    metadata: VideoMetadata
    transcription: Optional[TranscriptionResult]
    process_id: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "metadata": self.metadata.__dict__,
            "transcription": self.transcription.to_dict() if self.transcription else None,
            "process_id": self.process_id
        }

@dataclass(frozen=True)
class VideoResponse(BaseResponse):
    """Standardisierte API-Response für Video-Verarbeitung."""
    data: VideoProcessingResult
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None

    @classmethod
    def create(cls, request: RequestInfo, process: ProcessInfo, data: VideoProcessingResult,
               llm_info: Optional[LLMInfo] = None) -> 'VideoResponse':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            request=request,
            process=process,
            data=data,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error: ErrorInfo) -> 'VideoResponse':
        """Erstellt eine Fehler-Response."""
        dummy_source = VideoSource(url="")
        dummy_metadata = VideoMetadata(
            title="",
            source=dummy_source,
            duration=0,
            duration_formatted="00:00:00",
            process_dir=""
        )
        dummy_result = VideoProcessingResult(
            metadata=dummy_metadata,
            transcription=None,
            process_id=""
        )
        return cls(
            request=request,
            process=process,
            data=dummy_result,
            error=error,
            status=ProcessingStatus.ERROR
        )
```

### Prozessor-Implementierung

```python
from src.core.models.enums import ProcessorType

class VideoProcessor(BaseProcessor):
    """Prozessor für die Verarbeitung von Videos."""
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None):
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        # Initialisiere Prozessoren
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        self.transcriber = WhisperTranscriber({"process_id": process_id})
        self.audio_processor = AudioProcessor(resource_calculator, process_id)
        
        # Konfiguration
        config = Config()
        self.max_duration = config.get('processors.video.max_duration', 3600)
        
        # Download-Optionen
        self.ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
            }]
        }

    async def process(
        self, 
        source: Union[str, VideoSource],
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None
    ) -> VideoResponse:
        """
        Verarbeitet ein Video.
        
        Args:
            source: URL oder VideoSource-Objekt mit Video-Datei
            target_language: Zielsprache für die Transkription
            source_language: Quellsprache (auto für automatische Erkennung)
            template: Optional Template für die Verarbeitung
            
        Returns:
            VideoResponse: Die standardisierte Response mit Transkription und Metadaten
        """
        llm_info = LLMInfo(model="video-processing", purpose="video-processing")
        
        try:
            # Verarbeitung implementieren...
            pass
            
        except Exception as e:
            error_info = ErrorInfo(
                code="VIDEO_PROCESSING_ERROR",
                message=str(e),
                details={}
            )
            return VideoResponse.create_error(
                request=RequestInfo(
                    processor=ProcessorType.VIDEO.value,
                    timestamp=datetime.now().isoformat(),
                    parameters={
                        'source': str(source),
                        'target_language': target_language,
                        'source_language': source_language,
                        'template': template
                    }
                ),
                process=ProcessInfo(
                    id=self.process_id or str(uuid.uuid4()),
                    main_processor=ProcessorType.VIDEO.value,
                    started=datetime.now().isoformat()
                ),
                error=error_info
            )
```

## Prozessablauf

1. **Eingabe-Validierung**:
   - Prüfung der Video-Quelle (URL oder Datei)
   - Validierung des Formats
   - Größenbeschränkungen

2. **Video-Verarbeitung**:
   - Download bei URL
   - Extraktion der Audio-Spur
   - MP3-Konvertierung

3. **Sprachverarbeitung**:
   - Automatische Spracherkennung durch AudioProcessor
   - Transkription mit Whisper API
   - Übersetzung bei unterschiedlichen Sprachen
   - Template-Transformation wenn Template angegeben

4. **Ergebnisaufbereitung**:
   - Metadaten-Sammlung
   - Response-Erstellung
   - Ressourcen-Bereinigung

## Integration

### API-Route

```python
@router.post("/video", response_model=VideoResponse)
async def process_video(
    request: VideoRequest,
    background_tasks: BackgroundTasks
) -> VideoResponse:
    """
    Endpunkt für Video-Verarbeitung.
    Unterstützt URLs und Datei-Uploads.
    """
```

### Beispiel-Requests

```json
// URL-basierte Anfrage
{
    "source": {
        "url": "https://example.com/video.mp4"
    },
    "target_language": "de",
    "source_language": "auto",
    "template": "default"
}

// Datei-basierte Anfrage
{
    "source": {
        "file": "<base64-encoded-file>",
        "file_name": "video.mp4"
    },
    "target_language": "de",
    "source_language": "auto"
}
```

## Nächste Schritte

1. **Implementierung**:
   - Basis-Klasse erstellen
   - Input-Validierung implementieren
   - Sprachverarbeitung integrieren
   - API-Route hinzufügen

2. **Tests**:
   - Unit-Tests für Kernfunktionen
   - Integrationstests
   - Sprachverarbeitungs-Tests

3. **Dokumentation**:
   - API-Dokumentation
   - Beispiel-Implementierungen
   - Fehlerbehandlung

4. **Optimierung**:
   - Performance-Tuning
   - Caching-Strategien
   - Ressourcen-Management

## Fazit

Der Video-Prozessor bietet eine flexible Lösung für die Verarbeitung verschiedener Video-Quellen mit Fokus auf Sprachverarbeitung. Durch die Integration mit dem AudioProcessor und TransformerProcessor sowie die Wiederverwendung bestehender Modelle wird eine effiziente und wartbare Implementierung erreicht. Die automatische Spracherkennung und optionale Template-Transformation ermöglichen eine vielseitige Nutzung für verschiedene Anwendungsfälle. 