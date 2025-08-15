# Optimierung der Prozess-Klassen mit BaseProcessor und BaseResponse

## Grundprinzipien

Die Optimierung der Prozess-Klassen basiert auf folgenden Grundprinzipien:

1. **Vererbung und Wiederverwendung**
   - Nutzung der Basis-Funktionalität von `BaseProcessor` und `BaseResponse`
   - Vermeidung von Code-Duplikation
   - Klare Trennung von Basis- und spezifischer Funktionalität

2. **Typsicherheit**
   - Strikte Typ-Annotationen mit Generics
   - Verwendung von `Optional` für optionale Felder
   - Validierung in `__post_init__`

3. **Immutability**
   - Verwendung von `frozen=True` für Responses
   - Sichere Initialisierung mit `object.__setattr__`
   - Unveränderliche Datenstrukturen

4. **Prozess-Tracking**
   - Hierarchisches LLM-Tracking
   - Performance-Messung
   - Cache-Management

## Implementierungsmuster

### 1. Basis-Klassen

#### BaseProcessor
```python
class BaseProcessor(Generic[T]):
    def __init__(self, resource_calculator: ResourceCalculator, 
                 process_id: Optional[str] = None, 
                 parent_process_info: Optional[ProcessInfo] = None):
        self.process_id = process_id or str(uuid.uuid4())
        self.resource_calculator = resource_calculator
        self.logger = self.init_logger()
        
        if parent_process_info:
            self.process_info = parent_process_info
            if self.__class__.__name__ not in self.process_info.sub_processors:
                self.process_info.sub_processors.append(self.__class__.__name__)
        else:
            self.process_info = ProcessInfo(
                id=self.process_id,
                main_processor=self.__class__.__name__,
                started=datetime.now().isoformat(),
                sub_processors=[],
                llm_info=LLMInfo()
            )
            
    def create_response(
        self,
        processor_name: str,
        result: Optional[T],
        request_info: Dict[str, Any],
        response_class: Type[ResponseType],
        from_cache: bool = False,
        cache_key: str = "",
        error: Optional[ErrorInfo] = None
    ) -> ResponseType:
        """
        Erstellt eine standardisierte Response mit den BaseProcessor-Informationen.
        
        Args:
            processor_name: Name des Prozessors
            result: Verarbeitungsergebnis
            request_info: Anfrage-Informationen
            response_class: Response-Klasse
            from_cache: Ob das Ergebnis aus dem Cache stammt
            cache_key: Cache-Schlüssel, falls verwendet
            error: Optionale Fehlerinformationen
            
        Returns:
            Eine Response des angegebenen Typs mit allen erforderlichen Informationen
        """
        # Request-Informationen erstellen
        request = RequestInfo(
            processor=processor_name,
            timestamp=datetime.now().isoformat(),
            parameters=request_info
        )
        
        # Prozess-Status festlegen
        status = ProcessingStatus.ERROR if error else ProcessingStatus.SUCCESS
        
        # Response erstellen
        return response_class(
            status=status,
            request=request,
            process=self.process_info,
            data=result,
            error=error
        )
```

#### BaseResponse
```python
@dataclass(frozen=True)
class BaseResponse:
    request: RequestInfo = field(default_factory=lambda: RequestInfo(
        processor="base",
        timestamp=datetime.now().isoformat()
    ))
    process: ProcessInfo = field(default_factory=lambda: ProcessInfo(
        id="",
        main_processor="base",
        started=datetime.now().isoformat()
    ))
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None
    data: Any = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Response-Objekt in ein Dictionary."""
        return {
            "status": self.status.value,
            "request": self.request.to_dict(),
            "process": self.process.to_dict(),
            "data": self.data.to_dict() if hasattr(self.data, "to_dict") else self.data,
            "error": self.error.to_dict() if self.error else None
        }
```

### 2. Spezifische Implementierung (YouTubeProcessor)

```python
class YoutubeProcessor(CacheableProcessor[YoutubeProcessingResult]):
    """
    Prozessor für die Verarbeitung von YouTube-Videos.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der YoutubeProcessor erbt von CacheableProcessor, um MongoDB-Caching zu nutzen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "youtube_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, 
                 process_id: Optional[str] = None, 
                 parent_process_info: Optional[ProcessInfo] = None):
        """Initialisiert den YoutubeProcessor."""
        # Zeit für Gesamtinitialisierung starten
        init_start = time.time()
        
        # Superklasse-Initialisierung
        super().__init__(resource_calculator=resource_calculator, 
                        process_id=process_id, 
                        parent_process_info=parent_process_info)
        
        # Initialisierung von Sub-Prozessoren, Konfiguration, etc.
        self.audio_processor = AudioProcessor(
            resource_calculator, 
            process_id,
            parent_process_info=self.process_info
        )
        
        # Performance-Logging
        init_end = time.time()
        self.logger.info(f"Gesamte Initialisierungszeit: {(init_end - init_start) * 1000:.2f} ms")

    async def process(
        self, 
        url: str, 
        target_language: str = 'de',
        source_language: str = 'auto',
        template: Optional[str] = None,
        use_cache: bool = True
    ) -> YoutubeResponse:
        """Verarbeitet ein YouTube-Video."""
        try:
            # Verarbeitungslogik...
            
            # Bei Cache-Hit
            if cache_hit and cached_result:
                return self.create_response(
                    processor_name="youtube",
                    result=cached_result,
                    request_info={
                        'url': url,
                        'source_language': source_language,
                        'target_language': target_language,
                        'template': template,
                        'use_cache': use_cache
                    },
                    response_class=YoutubeResponse,
                    from_cache=True,
                    cache_key=cache_key
                )
            
            # Normale Verarbeitung...
            
            # Response erstellen
            return self.create_response(
                processor_name="youtube",
                result=result,
                request_info={
                    'url': url,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=YoutubeResponse,
                from_cache=False,
                cache_key=cache_key
            )
            
        except Exception as e:
            # Fehler-Response
            return self.create_response(
                processor_name="youtube",
                result=error_result,
                request_info={
                    'url': url,
                    'source_language': source_language,
                    'target_language': target_language,
                    'template': template,
                    'use_cache': use_cache
                },
                response_class=YoutubeResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="VIDEO_PROCESSING_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )
```

### 3. LLM-Tracking und Hierarchische Prozessor-Struktur

Das LLM-Tracking ist direkt in der `BaseProcessor`-Klasse implementiert und wird automatisch in jede Response integriert.

#### LLM-Tracking im BaseProcessor

Die wichtigsten Komponenten sind:

1. **ProcessInfo-Objekt in jedem Prozessor**
   - Enthält LLM-bezogene Informationen wie Token-Nutzung, Dauer, Kosten
   - Wird bei Prozessor-Initialisierung erstellt oder vom Parent-Prozessor übernommen
   - Ermöglicht hierarchisches Tracking über mehrere Prozessoren

2. **Automatische Integration in Responses**
   - Die `create_response()`-Methode des BaseProcessors fügt die ProcessInfo automatisch in jede Response ein
   - Keine manuelle Übergabe erforderlich

3. **Hierarchisches LLM-Tracking**
   - Sub-Prozessoren (z.B. AudioProcessor innerhalb des YoutubeProcessors) erhalten die ProcessInfo des Parent-Prozessors
   - LLM-Nutzung wird an allen Stellen korrekt aggregiert
   - Die Root-ProcessInfo enthält die Gesamtnutzung

#### Code für das Tracking von LLM-Requests

```python
def add_llm_request(self, llm_request: LLMRequest) -> None:
    """Fügt einen LLM-Request zur Prozess-Info hinzu."""
    if not hasattr(self, 'process_info') or not self.process_info:
        self.logger.warning("Prozess-Info nicht initialisiert, LLM-Request wird ignoriert")
        return
        
    if not self.process_info.llm_info:
        self.process_info.llm_info = LLMInfo()
        
    # LLM-Request zur Liste hinzufügen
    if not self.process_info.llm_info.requests:
        self.process_info.llm_info.requests = []
        
    self.process_info.llm_info.requests.append(llm_request)
    
    # Aggregierte Informationen aktualisieren
    self.process_info.llm_info.total_tokens += llm_request.tokens
    self.process_info.llm_info.total_requests += 1
    self.process_info.llm_info.total_duration += llm_request.duration
    self.process_info.llm_info.total_cost += llm_request.cost
```

### 4. API-Routes

Die API-Routes nutzen die standardisierte Struktur der Prozessoren und ihrer Response-Erzeugung:

```python
@youtube_ns.route('/')
class YouTubeEndpoint(Resource):
    @youtube_ns.expect(youtube_model)
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        try:
            # Request-Daten extrahieren
            data = request.json
            url = data.get('url')
            
            # Processor initialisieren
            processor = YoutubeProcessor(resource_calculator, process_id=str(uuid.uuid4()))
            
            # Verarbeitung durchführen
            result = asyncio.run(processor.process(
                url=url,
                source_language=data.get('source_language', 'auto'),
                target_language=data.get('target_language', 'de'),
                template=data.get('template'),
                use_cache=data.get('use_cache', True)
            ))
            
            # Response zurückgeben
            # Die Response wurde bereits vom Prozessor mit allen notwendigen Informationen erstellt
            return result.to_dict()
            
        except Exception as e:
            # Fehlerbehandlung
            return {
                'status': 'error',
                'error': {
                    'code': 'PROCESSING_ERROR',
                    'message': str(e)
                }
            }, 500
```

## Best Practices

1. **Prozessor-Initialisierung**
   - Nutze `super().__init__()` für Basis-Funktionalität
   - Initialisiere Sub-Prozessoren mit `parent_process_info=self.process_info`
   - Tracke Performance-Metriken

2. **Prozess-Tracking**
   - Nutze `process_info` für Prozess-Metadaten
   - Erfasse LLM-Nutzung über `add_llm_request`
   - Sub-Prozessoren erben die LLM-Tracking-Funktionalität automatisch

3. **Response-Erstellung**
   - Verwende immer `self.create_response()` für standardisierte Responses
   - Übergebe vollständige `request_info` mit allen relevanten Parametern
   - Setze `from_cache` und `cache_key` für Cache-Transparenz

4. **Fehlerbehandlung**
   - Verwende `try-except`-Blöcke für Robustheit
   - Erstelle standardisierte Error-Responses mit `self.create_response()` und `error`-Parameter
   - Logge Fehler mit Kontext und Stack-Trace

5. **Response-Modelle**
   - Definiere strikte Typen für Response-Daten
   - Implementiere `to_dict()` für Serialisierung
   - Benutze `frozen=True` für Unveränderlichkeit

## Fazit

Die Optimierung der Prozess-Klassen mit `BaseProcessor` und `BaseResponse` führt zu:
- Besserer Code-Qualität durch Wiederverwendung
- Höherer Wartbarkeit durch Standardisierung
- Stärkerer Typsicherheit durch Generics
- Einheitlicher Konsistenz in Responses
- Effizientem Prozess-Tracking
- Optimiertem Cache-Management

Diese Muster sollten bei der Implementierung neuer Prozess-Klassen befolgt werden. 