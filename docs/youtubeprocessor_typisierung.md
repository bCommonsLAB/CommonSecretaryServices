# YoutubeProcessor Typisierung

## Überblick

Der YoutubeProcessor ist eine spezialisierte Komponente für das Herunterladen, Verarbeiten und Transkribieren von YouTube-Videos. Die bestehende Implementierung soll durch strikte Typisierung, bessere Integration mit dem TransformerProcessor und dem AudioProcessor sowie ein verbessertes Response-System optimiert werden.

## Analyse der bestehenden Struktur

### Basis-Komponenten
Die folgenden Komponenten sind bereits vorhanden:

```python
@dataclass(frozen=True, slots=True)
class YoutubeMetadata:
    """Metadaten eines YouTube-Videos."""
    title: str
    url: str
    video_id: str
    duration: int
    duration_formatted: str
    process_dir: str
    file_size: Optional[int] = None
    audio_file: Optional[str] = None
    source_type: str = field(default="youtube")
    availability: Optional[str] = None
    categories: List[str] = field(default_factory=list)
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    thumbnail: Optional[str] = None
    upload_date: Optional[str] = None
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    dislike_count: Optional[int] = None
    average_rating: Optional[float] = None
    age_limit: Optional[int] = None
    webpage_url: Optional[str] = None

@dataclass(frozen=True, slots=True)
class YoutubeProcessingResult:
    """Ergebnis der YouTube-Verarbeitung."""
    metadata: YoutubeMetadata
    process_id: str
    audio_result: Optional[AudioProcessingResult] = None
```

### Identifizierte Probleme
1. Fehlende Typisierung für yt-dlp Rückgabewerte
2. Unvollständige Integration mit TransformerProcessor
3. Inkonsistente Fehlerbehandlung
4. Fehlende Protocol-Definitionen
5. Untypisierte Konfigurationsoptionen

## Notwendige Anpassungen

### 1. YoutubeDL Type Definitions

```python
from typing import TypedDict, Union, Literal

class YoutubeDLInfo(TypedDict):
    """Typisierte Struktur für yt-dlp Informationen"""
    id: str
    title: str
    duration: int
    view_count: Optional[int]
    like_count: Optional[int]
    dislike_count: Optional[int]
    average_rating: Optional[float]
    age_limit: Optional[int]
    categories: List[str]
    tags: List[str]
    description: Optional[str]
    thumbnail: Optional[str]
    upload_date: Optional[str]
    uploader: Optional[str]
    uploader_id: Optional[str]
    webpage_url: Optional[str]
    availability: Optional[str]
    chapters: List[Dict[str, Any]]

class YoutubeDLOptions(TypedDict, total=False):
    """Typisierte Konfigurationsoptionen für yt-dlp"""
    format: str
    outtmpl: str
    quiet: bool
    no_warnings: bool
    extract_audio: bool
    postprocessors: List[Dict[str, str]]
    download_archive: Optional[str]
    writesubtitles: bool
    subtitleslangs: List[str]
```

### 2. YoutubeProcessor Protocol-Definitionen

```python
class YoutubeProcessorProtocol(Protocol):
    """Protocol für die YouTube-Verarbeitung"""
    async def process(
        self,
        url: str,
        target_language: str = 'de',
        extract_audio: bool = True,
        template: Optional[str] = None
    ) -> YoutubeProcessingResult: ...

    def _extract_video_id(self, url: str) -> str: ...
    
    def create_process_dir(self, video_id: str) -> Path: ...
    
    def _format_duration(self, seconds: int) -> str: ...
```

### 3. Fehlerbehandlung

```python
class YoutubeProcessingError(ProcessingError):
    """Spezifische Fehler bei der YouTube-Verarbeitung"""
    
    class ErrorCode(str, Enum):
        INVALID_URL = "INVALID_URL"
        DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
        CONVERSION_FAILED = "CONVERSION_FAILED"
        VIDEO_TOO_LONG = "VIDEO_TOO_LONG"
        PROCESSING_FAILED = "PROCESSING_FAILED"
    
    def __init__(
        self,
        message: str,
        error_code: ErrorCode,
        details: Optional[Dict[str, Any]] = None,
        stage: Optional[str] = None
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}
        self.stage = stage
```

### 4. Konfigurationstypen

```python
@dataclass(frozen=True)
class YoutubeProcessorConfig:
    """Typisierte Konfiguration für den YoutubeProcessor"""
    max_duration: int = 3600
    output_format: str = "mp3"
    download_subtitles: bool = False
    subtitle_languages: List[str] = field(default_factory=lambda: ["en", "de"])
    temp_dir: Path = field(default_factory=lambda: Path("./temp"))
    archive_path: Optional[str] = None
    ffmpeg_location: Optional[str] = None
```

### 5. Response-Typen

```python
@dataclass(frozen=True)
class YoutubeResponse(BaseResponse):
    """Response für die YouTube-Verarbeitung"""
    data: YoutubeProcessingResult
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert Response in Dict"""
        base_dict = {
            'status': self.status.value,
            'request': asdict(self.request),
            'process': asdict(self.process),
            'error': asdict(self.error) if self.error else None
        }
        return {
            **base_dict,
            'data': self.data.to_dict()
        }
```

### 6. Überarbeiteter YoutubeProcessor

```python
class YoutubeProcessor(BaseProcessor):
    """Prozessor für die Verarbeitung von YouTube-Videos"""
    
    def __init__(
        self,
        resource_calculator: ResourceCalculator,
        config: Optional[YoutubeProcessorConfig] = None,
        process_id: Optional[str] = None
    ) -> None:
        super().__init__(resource_calculator, process_id)
        self.config = config or YoutubeProcessorConfig()
        self.logger = get_logger(process_id, self.__class__.__name__)
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
        # Initialisiere yt-dlp Optionen
        self.ydl_opts: YoutubeDLOptions = {
            'quiet': True,
            'no_warnings': True,
            'extract_audio': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': self.config.output_format,
            }]
        }
```

## Integration mit anderen Prozessoren

### 1. TransformerProcessor Integration

```python
class YoutubeProcessor(BaseProcessor):
    async def _process_audio(
        self,
        audio_path: Path,
        target_language: str,
        template: Optional[str]
    ) -> TransformationResult:
        """Verarbeitet die Audio-Datei mit dem TransformerProcessor"""
        return await self.transformer.transform(
            source_text=str(audio_path),
            source_language="auto",
            target_language=target_language,
            context={"type": "audio", "template": template}
        )
```

### 2. Template-Integration

```python
class YoutubeProcessor(BaseProcessor):
    async def _apply_template(
        self,
        info: YoutubeDLInfo,
        transcription: str,
        template: str,
        target_language: str
    ) -> str:
        """Wendet Template auf die Transkription an"""
        return await self.transformer.transformByTemplate(
            source_text=transcription,
            source_language="auto",
            target_language=target_language,
            template=template,
            context={
                "video_id": info["id"],
                "title": info["title"],
                "uploader": info["uploader"],
                "upload_date": info["upload_date"],
                "categories": info["categories"],
                "tags": info["tags"],
                "chapters": info["chapters"]
            }
        )
```

## API Route Anpassungen

```python
@api.route('/process-youtube')
class YoutubeEndpoint(Resource):
    @api.expect(youtube_parser)
    @api.response(200, 'Erfolg', youtube_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet ein YouTube-Video')
    async def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        try:
            url = request.form.get('url')
            if not url:
                raise ValidationError("URL ist erforderlich")
                
            result = await youtube_processor.process(
                url=url,
                target_language=request.form.get('target_language', 'de'),
                extract_audio=request.form.get('extract_audio', True),
                template=request.form.get('template')
            )
            return result.to_dict()
            
        except YoutubeProcessingError as e:
            return {
                'error': str(e),
                'error_code': e.error_code.value,
                'stage': e.stage,
                'details': e.details
            }, 400
```

## Implementierungsschritte

1. Type Definitions
   - YoutubeDL Types implementieren
   - Response-Typen erstellen
   - Konfigurationstypen einführen

2. Fehlerbehandlung
   - YoutubeProcessingError implementieren
   - Error Codes definieren
   - Stage-basierte Fehlerbehandlung

3. Prozessor aktualisieren
   - Constructor überarbeiten
   - Methoden typisieren
   - Protocol-Integration

4. Tests erweitern
   - Response-Validierung
   - Fehlerszenarien
   - Template-Integration

## Vorteile der Anpassungen

1. **Typsicherheit**
   - Vollständige Typisierung aller Komponenten
   - Frühe Fehlererkennung
   - Bessere IDE-Unterstützung

2. **Wartbarkeit**
   - Klare Schnittstellen
   - Standardisierte Fehlerbehandlung
   - Dokumentierte Konfiguration

3. **Testbarkeit**
   - Mocking durch Protocols
   - Definierte Testfälle
   - Validierbare Responses

4. **Performance**
   - Optimierte Dateiverarbeitung
   - Effizientes Caching
   - Verbesserte Fehlerbehandlung

## Nächste Schritte

1. Implementiere YoutubeDL Type Definitions
2. Aktualisiere YoutubeProcessor mit neuer Typisierung
3. Erweitere Tests für neue Typen
4. Dokumentiere API-Änderungen
5. Führe Integrationstests durch 