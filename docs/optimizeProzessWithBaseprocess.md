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
```

### 2. Spezifische Implementierung (TransformerProcessor)

```python
class TransformerProcessor(CacheableProcessor[TransformationResult]):
    def __init__(self, resource_calculator: ResourceCalculator, 
                 process_id: Optional[str] = None, 
                 parent_process_info: Optional[ProcessInfo] = None):
        # Zeit für Gesamtinitialisierung starten
        init_start = time.time()
        
        # Superklasse-Initialisierung
        super().__init__(resource_calculator=resource_calculator, 
                        process_id=process_id, 
                        parent_process_info=parent_process_info)
        
        # Konfiguration laden
        config = Config()
        processor_config = config.get('processors', {}).get('transformer', {})
        
        # Konfigurationswerte laden
        self.model = processor_config.get('model', 'gpt-4')
        self.temperature = processor_config.get('temperature', 0.7)
        self.max_tokens = processor_config.get('max_tokens', 4000)
        
        # OpenAI Client initialisieren
        self.client = OpenAI(api_key=config_keys.openai_api_key)
        
        # Performance-Logging
        init_end = time.time()
        self.logger.info(f"Gesamte Initialisierungszeit: {(init_end - init_start) * 1000:.2f} ms")

    def transform(self, source_text: str, source_language: str, 
                 target_language: str, summarize: bool = False,
                 target_format: Optional[OutputFormat] = None,
                 context: Optional[Dict[str, Any]] = None,
                 use_cache: bool = True) -> TransformerResponse:
        process_start = time.time()
        
        try:
            # Validierung
            source_text = self.validate_text(source_text)
            
            # Cache prüfen
            if use_cache and self.is_cache_enabled():
                cache_hit, cached_result = self.get_from_cache(cache_key)
                if cache_hit and cached_result:
                    return self._create_response_from_cached_result(
                        cached_result=cached_result,
                        source_text=source_text,
                        source_language=source_language,
                        target_language=target_language,
                        summarize=summarize,
                        target_format=target_format,
                        cache_key=cache_key
                    )
            
            # Text transformieren
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": source_text}
                ],
                temperature=0.7,
            )
            
            # LLM-Nutzung tracken
            usage = completion.usage
            if usage:
                self.add_llm_requests(LLMRequest(
                    purpose="text_transformation",
                    tokens=usage.total_tokens,
                    duration=time.time() - process_start,
                    model=self.model
                ))
            
            # Response erstellen
            return TransformerResponse.create(
                data=TransformerData(
                    text=transformed_text,
                    language=target_language,
                    format=target_format
                )
            )
            
        except Exception as e:
            return TransformerResponse.create_error(
                error=ErrorInfo(
                    code="TRANSFORMATION_ERROR",
                    message=str(e),
                    details={"error_type": type(e).__name__}
                )
            )
```

### 3. Response-Modelle und LLM-Tracking

Die Response-Modelle und das LLM-Tracking wurden in die `transformer.py` ausgelagert, um eine bessere Trennung der Zuständigkeiten zu erreichen.

#### Response-Modelle

```python
@dataclass(frozen=True)
class TransformerData:
    """Ausgabedaten des Transformers"""
    text: str
    language: str
    format: OutputFormat
    summarized: bool = False
    structured_data: Optional[Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "language": self.language,
            "format": self.format.value,
            "summarized": self.summarized,
            "structured_data": self.structured_data
        }

@dataclass(frozen=True, init=False)
class TransformerResponse(BaseResponse):
    """Response des Transformer-Prozessors"""
    data: Optional[TransformerData] = field(default=None)
    translation: Optional[TranslationResult] = field(default=None)

    def __init__(
        self,
        data: TransformerData,
        translation: Optional[TranslationResult] = None,
        **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'translation', translation)

    @classmethod
    def create(
        cls,
        data: Optional[TransformerData] = None,
        translation: Optional[TranslationResult] = None,
        process: Optional[ProcessInfo] = None,
        **kwargs: Any
    ) -> 'TransformerResponse':
        """Erstellt eine erfolgreiche Response."""
        if data is None:
            raise ValueError("data must not be None")
        response = cls(data=data, translation=translation, process=process, **kwargs)
        object.__setattr__(response, 'status', ProcessingStatus.SUCCESS)
        return response

    @classmethod
    def create_error(
        cls,
        error: ErrorInfo,
        **kwargs: Any
    ) -> 'TransformerResponse':
        """Erstellt eine Error-Response."""
        response = cls(
            data=TransformerData(
                text="",
                language="",
                format=OutputFormat.TEXT
            ),
            **kwargs
        )
        object.__setattr__(response, 'status', ProcessingStatus.ERROR)
        object.__setattr__(response, 'error', error)
        return response
```

#### LLM-Tracking in der Response

Das LLM-Tracking wurde aus dem Prozessor in die Response-Modelle verschoben. Die wichtigsten Änderungen sind:

1. **ProcessInfo in der Response**
   - Die `ProcessInfo` enthält jetzt alle LLM-bezogenen Informationen
   - Wird beim Erstellen der Response übergeben
   - Ermöglicht hierarchisches Tracking über mehrere Prozessoren

2. **Response-Erstellung**
   ```python
   # Im Prozessor
   return TransformerResponse.create(
       data=TransformerData(
           text=transformed_text,
           language=target_language,
           format=target_format
       ),
       process=self.process_info  # Übergabe der ProcessInfo mit LLM-Daten
   )
   ```

3. **Fehler-Response**
   ```python
   return TransformerResponse.create_error(
       error=ErrorInfo(
           code="TRANSFORMATION_ERROR",
           message=str(e),
           details={"error_type": type(e).__name__}
       ),
       process=self.process_info  # Auch bei Fehlern LLM-Daten mitgeben
   )
   ```

#### Vorteile der Auslagerung

1. **Bessere Trennung der Zuständigkeiten**
   - Prozessor: Fokus auf Verarbeitungslogik
   - Response-Modelle: Fokus auf Datenstruktur und LLM-Tracking
   - API-Routes: Fokus auf HTTP-Kommunikation

2. **Vereinfachte Wartung**
   - LLM-Tracking-Logik ist zentral in den Response-Modellen
   - Weniger Code-Duplikation
   - Klare Verantwortlichkeiten

3. **Verbesserte Typsicherheit**
   - Strikte Typ-Annotationen in den Response-Modellen
   - Bessere IDE-Unterstützung
   - Frühere Fehlererkennung

4. **Flexiblere Erweiterbarkeit**
   - Einfaches Hinzufügen neuer Response-Typen
   - Anpassung des LLM-Trackings ohne Prozessor-Änderungen
   - Bessere Testbarkeit

### 4. API-Routes

```python
@transformer_ns.route('/text')
class TransformTextEndpoint(Resource):
    @transformer_ns.expect(transform_model)
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        try:
            # Request-Daten extrahieren
            data = request.json
            source_text = data.get('text', '')
            source_language = data.get('source_language', 'de')
            target_language = data.get('target_language', 'de')
            
            # Processor initialisieren
            processor = get_transformer_processor()
            
            # Transformation durchführen
            result = processor.transform(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=data.get('summarize', False),
                target_format=data.get('target_format'),
                context=data.get('context'),
                use_cache=data.get('use_cache', True)
            )
            
            # Response erstellen
            return processor.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language,
                    'duration_ms': int((time.time() - start_time) * 1000)
                },
                response_class=TransformerResponse,
                from_cache=processor.process_info.is_from_cache,
                cache_key=processor.process_info.cache_key
            )
            
        except Exception as e:
            return processor.create_response(
                processor_name="transformer",
                result=None,
                request_info={
                    'text': _truncate_text(source_text),
                    'source_language': source_language,
                    'target_language': target_language
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="ProcessingError",
                    message=str(e),
                    details=traceback.format_exc()
                )
            )
```

## Best Practices

1. **Prozessor-Initialisierung**
   - Nutze `super().__init__()` für Basis-Funktionalität
   - Initialisiere Konfiguration und Clients
   - Tracke Performance-Metriken

2. **Prozess-Tracking**
   - Nutze `process_info` für Prozess-Metadaten
   - Tracke LLM-Nutzung mit `add_llm_requests`
   - Implementiere Cache-Management

3. **Fehlerbehandlung**
   - Validiere Eingaben mit Basis-Methoden
   - Erstelle standardisierte Error-Responses
   - Logge Fehler mit Kontext

4. **Response-Erstellung**
   - Nutze `create_response` für standardisierte Responses
   - Füge Performance-Metriken hinzu
   - Berücksichtige Cache-Status

5. **Response-Modelle**
   - Lagere Response-Logik in separate Modelle aus
   - Nutze `create()` und `create_error()` für standardisierte Responses
   - Übergib ProcessInfo für LLM-Tracking
   - Implementiere `to_dict()` für Serialisierung

## Fazit

Die Optimierung der Prozess-Klassen mit `BaseProcessor` und `BaseResponse` führt zu:
- Besserer Code-Qualität durch Wiederverwendung
- Höherer Wartbarkeit durch Standardisierung
- Stärkerer Typsicherheit durch Generics
- Einheitlicher Konsistenz in Responses
- Effizientem Prozess-Tracking
- Optimiertem Cache-Management

Diese Muster sollten bei der Implementierung neuer Prozess-Klassen befolgt werden. 