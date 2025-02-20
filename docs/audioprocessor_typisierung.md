# AudioProcessor Typisierung

## Überblick

Der AudioProcessor ist eine zentrale Komponente für die Verarbeitung von Audiodateien. Die bestehende Implementierung soll durch strikte Typisierung und bessere Integration mit dem vorhandenen Response-System verbessert werden.

## Analyse der bestehenden Struktur

### Basis-Komponenten
Die folgenden Komponenten sind bereits vorhanden und werden in anderen Prozessoren erfolgreich eingesetzt:

```python
@dataclass
class RequestInfo:
    processor: str
    timestamp: str
    parameters: Dict[str, Any]

@dataclass
class ProcessInfo:
    id: str
    main_processor: str
    started: str
    sub_processors: List[str] = field(default_factory=list)
    completed: Optional[str] = None
    duration: Optional[float] = None
    llm_info: Optional[Dict[str, Any]] = None

@dataclass(frozen=True)
class BaseResponse:
    request: RequestInfo
    process: ProcessInfo
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None
```

### Vorteile der bestehenden Struktur
1. Einheitliches Response-Handling über alle Prozessoren
2. Integrierte LLM-Informationen
3. Standardisierte Fehlerbehandlung
4. Frozen Dataclasses für Unveränderlichkeit

## Notwendige Anpassungen

### 1. AudioResponse Definition
Die AudioResponse muss als spezialisierte Version der BaseResponse implementiert werden:

```python
@dataclass(frozen=True)
class AudioResponse(BaseResponse):
    """Response für Audio-Verarbeitung"""
    data: AudioProcessingResult
    metadata: AudioMetadata
    transcription: TranscriptionResult

    def to_dict(self) -> Dict[str, Any]:
        """
        Konvertiert Response in Dict.
        Erweitert die Basis-Serialisierung um Audio-spezifische Felder.
        """
        base_dict = {
            'status': self.status.value,
            'request': asdict(self.request),
            'process': asdict(self.process),
            'error': asdict(self.error) if self.error else None
        }
        return {
            **base_dict,
            'data': self.data.to_dict(),
            'metadata': self.metadata.to_dict(),
            'transcription': self.transcription.to_dict()
        }
```

Begründung:
- Erweitert BaseResponse um Audio-spezifische Felder
- Behält Unveränderlichkeit durch frozen=True
- Implementiert standardisierte Serialisierung
- Ermöglicht typsichere Verarbeitung

### 2. Fehlerbehandlung

```python
class AudioProcessingError(ProcessingError):
    """Spezifische Fehler bei der Audio-Verarbeitung"""
    def __init__(
        self,
        message: str,
        error_code: str = 'AUDIO_PROCESSING_ERROR',
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}
```

Begründung:
- Spezifische Fehlercodes für Audio-Verarbeitung
- Konsistente Fehlerbehandlung mit anderen Prozessoren
- Detaillierte Fehlerinformationen für Debugging
- Typsichere Fehlerdetails

### 3. Protocol-Definitionen für externe Prozessoren

```python
class TransformerProtocol(Protocol):
    """Protocol für die Transformer-Integration"""
    async def transform(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None
    ) -> TransformationResult: ...

    async def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        template: str,
        context: Optional[Dict[str, Any]] = None
    ) -> TransformationResult: ...

class MetadataProtocol(Protocol):
    """Protocol für die Metadata-Integration"""
    async def extract_metadata(
        self,
        binary_data: Union[str, Path, bytes],
        content: str,
        context: Optional[Dict[str, Any]] = None
    ) -> MetadataResult: ...
```

Begründung:
- Klare Schnittstellen-Definition
- Ermöglicht Mocking in Tests
- Verbesserte IDE-Unterstützung
- Typsichere Integration externer Prozessoren

### 4. AudioProcessor Methoden-Typisierung

```python
class AudioProcessor(BaseProcessor):
    async def process(
        self,
        audio_source: Union[str, Path, bytes],
        source_info: Optional[Dict[str, Any]] = None,
        chapters: Optional[List[Dict[str, Any]]] = None,
        target_language: Optional[str] = None,
        template: Optional[str] = None
    ) -> AudioResponse:
        """
        Verarbeitet eine Audio-Datei.
        
        Args:
            audio_source: Audio-Datei als Pfad oder Bytes
            source_info: Zusätzliche Quellinformationen
            chapters: Kapitelinformationen
            target_language: Zielsprache (ISO 639-1)
            template: Optional Template für Transformation
            
        Returns:
            AudioResponse: Typisiertes Verarbeitungsergebnis
            
        Raises:
            AudioProcessingError: Bei Verarbeitungsfehlern
        """
```

Begründung:
- Klare Parameter-Typisierung
- Dokumentierte Rückgabewerte
- Spezifische Fehlertypen
- Optionale Parameter mit sinnvollen Defaults

## API Route Anpassungen

```python
@api.route('/process-audio')
class AudioEndpoint(Resource):
    @api.expect(upload_parser)
    @api.response(200, 'Erfolg', audio_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet eine Audio-Datei')
    async def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        try:
            result = await audio_processor.process(file)
            return result.to_dict()
        except AudioProcessingError as e:
            return {
                'error': str(e),
                'error_code': e.error_code,
                'details': e.details
            }, 400
```

Begründung:
- Konsistente API-Responses
- Standardisierte Fehler-Responses
- Automatische OpenAPI-Dokumentation
- Typsichere Serialisierung

## Implementierungsschritte

1. Response-Typen implementieren
   - AudioResponse
   - AudioProcessingResult
   - TranscriptionResult

2. Fehlerbehandlung einführen
   - AudioProcessingError
   - Spezifische Fehlercodes
   - Error-Mapping

3. Prozessor aktualisieren
   - Protocol-Integration
   - Methoden-Typisierung
   - Response-Handling

4. Tests erweitern
   - Response-Validierung
   - Fehlerszenarien
   - Protocol-Conformance

## Vorteile der Anpassungen

1. **Typsicherheit**
   - Strikte Typisierung aller Komponenten
   - Frühe Fehlererkennung
   - Bessere IDE-Unterstützung

2. **Wartbarkeit**
   - Klare Schnittstellen
   - Standardisierte Strukturen
   - Dokumentierte Fehlerszenarien

3. **Testbarkeit**
   - Mocking durch Protocols
   - Definierte Testfälle
   - Validierbare Responses

4. **Performance**
   - Optimierte Serialisierung
   - Effiziente Fehlerbehandlung
   - Reduzierte Laufzeit-Checks

## Nächste Schritte

1. Implementiere AudioResponse und zugehörige Typen
2. Aktualisiere AudioProcessor mit neuer Typisierung
3. Erweitere Tests für neue Typen
4. Dokumentiere API-Änderungen
5. Führe Integrationstests durch 