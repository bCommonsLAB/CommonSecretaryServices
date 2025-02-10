# Typisierung MetadataProcessor

## Vergleich mit TransformerProcessor

### Hauptunterschiede
1. Constructor-Struktur und Fehlerbehandlung
2. Validierungsfunktionen
3. Prozess-Tracking und Logging

## Notwendige Änderungen

### 1. Constructor verbessern
```python
def __init__(
    self,
    resource_calculator: ResourceCalculator,  # Nicht mehr Optional
    process_id: Optional[str] = None,
    max_file_size: int = 100 * 1024 * 1024,
    supported_mime_types: Optional[List[str]] = None,
    features: Optional[Dict[str, bool]] = None
) -> None:
    """Initialisiert den MetadataProcessor."""
    super().__init__(resource_calculator=resource_calculator, process_id=process_id)
    
    try:
        # Konfiguration laden
        metadata_config = self.load_processor_config('metadata')
        
        # Logger initialisieren
        self.logger = self.init_logger("MetadataProcessor")
        
        # Basis-Konfiguration
        self.max_file_size = max_file_size
        
        # MIME-Type Konfiguration
        self.supported_mime_types = supported_mime_types or [
            "audio/*", "video/*", "image/*", "application/pdf",
            "text/markdown", "text/plain", "text/*"
        ]
        
        # Features initialisieren
        self.features = MetadataFeatures(**(features or {
            "technical_enabled": True,
            "content_enabled": True
        }))
        
        # Transformer für Content-Analyse
        self.transformer = TransformerProcessor(resource_calculator, process_id)
        
        if self.logger:
            self.logger.info(
                "MetadataProcessor initialisiert",
                extra={
                    "args": {
                        "max_file_size": self.max_file_size,
                        "supported_mime_types": self.supported_mime_types,
                        "features": asdict(self.features)
                    }
                }
            )
    except Exception as e:
        if self.logger:
            self.logger.error("Fehler bei der Initialisierung des MetadataProcessors",
                            error=e)
        raise ProcessingError(f"Initialisierungsfehler: {str(e)}")
```

### 2. Validierungsfunktionen hinzufügen
```python
def validate_binary_data(self, data: Optional[Union[str, Path, BinaryIO]], param_name: str) -> Optional[Union[str, Path, BinaryIO]]:
    """Validiert die Binärdaten."""
    if data is None:
        return None
        
    if isinstance(data, (str, Path)):
        path = Path(data)
        if not path.exists():
            raise ValueError(f"{param_name}: Datei existiert nicht: {path}")
        if not path.is_file():
            raise ValueError(f"{param_name}: Ist kein File: {path}")
            
    return data

def validate_mime_type(self, mime_type: Optional[str]) -> bool:
    """Validiert den MIME-Type."""
    if not mime_type:
        return False
    return any(fnmatch.fnmatch(mime_type, pattern) for pattern in self.supported_mime_types)
```

### 3. Prozess-Tracking verbessern
```python
def track_processing_step(
    self,
    step_name: str,
    status: ProcessingStatus,
    error: Optional[Dict[str, Any]] = None
) -> ProcessingStep:
    """Erstellt einen neuen Verarbeitungsschritt mit Zeitstempel."""
    now = datetime.now(timezone.utc)
    return ProcessingStep(
        name=step_name,
        status=status,
        started_at=now,
        completed_at=now,
        error=error
    )
```

## Vorteile der Änderungen

1. **Verbesserte Fehlerbehandlung**
   - Strukturierte Fehler im Constructor
   - Validierung von Binärdaten und MIME-Types
   - Besseres Logging

2. **Prozess-Tracking**
   - Detaillierte Verarbeitungsschritte
   - Zeitstempel für Performance-Analyse
   - Strukturierte Fehlerinformationen

3. **Bessere Wartbarkeit**
   - Klare Validierungsregeln
   - Verbesserte Logging-Struktur
   - Einheitliche Fehlerbehandlung

## Implementierungsschritte

1. Constructor-Logik aktualisieren
2. Validierungsfunktionen implementieren
3. Prozess-Tracking einbauen
4. Tests anpassen

## Migrations-Hinweise

1. ResourceCalculator ist nicht mehr optional
2. Validierungsfehler werden jetzt strukturiert zurückgegeben
3. Prozess-Tracking muss in bestehende Verarbeitung integriert werden 

## API-Routen Vergleich

### TransformerProcessor Route
```python
@api.route('/transform-template')
class TemplateTransformEndpoint(Resource):
    def post(self) -> Union[Dict[str, Any], tuple[Dict[str, Any], int]]:
        data: Any = request.get_json()
        tracker: PerformanceTracker | None = get_performance_tracker()
        
        try:
            # Zeitmessung für Gesamtprozess starten
            process_start = time.time()
            
            transformer_processor: TransformerProcessor = get_transformer_processor(tracker.process_id if tracker else None)
            result: TransformerResponse = transformer_processor.transformByTemplate(
                source_text=data['text'],
                source_language=data.get('source_language', 'de'),
                target_language=data.get('target_language', 'de'),
                template=data['template'],
                context=data.get('context', {})
            )

            # Response erstellen mit:
            # - Fehlerbehandlung
            # - Status-Tracking
            # - LLM-Informationen
            # - Strukturierte Daten
            response = {
                'status': 'error' if result.error else 'success',
                'request': {...},
                'process': {...},
                'data': {...}
            }

            if result.error:
                response['error'] = {
                    'code': result.error.code,
                    'message': result.error.message,
                    'details': result.error.details
                }
                return response, 400
            
            return response
            
        except Exception as error:
            # Strukturierte Fehlerbehandlung
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError",
                    "message": str(error),
                    "details": {}
                }
            }, 400
```

### Notwendige Änderungen für MetadataProcessor Route

1. **Request-Validierung verbessern**
```python
@api.route('/extract-metadata')
class MetadataEndpoint(Resource):
    @api.expect(metadata_upload_parser)
    @api.response(200, 'Erfolg', metadata_response)
    @api.response(400, 'Validierungsfehler', error_model)
    async def post(self) -> Dict[str, Any]:
        args = metadata_upload_parser.parse_args()
        uploaded_file = args.get('file')
        content = args.get('content')
        context = args.get('context')
        
        # Prozess-Tracking initialisieren
        process_id = str(uuid.uuid4())
        tracker = get_performance_tracker() or get_performance_tracker(process_id)
        process_start = time.time()
            
        try:
            processor: MetadataProcessor = get_metadata_processor(process_id)
            result: MetadataResponse = await processor.process(
                binary_data=uploaded_file,
                content=content,
                context=context
            )
            
            # Response erstellen
            response = {
                'status': 'error' if result.error else 'success',
                'request': {
                    'processor': 'metadata',
                    'timestamp': datetime.now().isoformat(),
                    'parameters': {
                        'has_file': uploaded_file is not None,
                        'has_content': content is not None,
                        'context': context
                    }
                },
                'process': {
                    'id': tracker.process_id if tracker else None,
                    'main_processor': 'metadata',
                    'sub_processors': ['transformer'] if result.data.content else [],
                    'started': datetime.fromtimestamp(process_start).isoformat(),
                    'completed': datetime.now().isoformat(),
                    'duration': int((time.time() - process_start) * 1000),
                    'llm_info': result.llm_info.to_dict() if result.llm_info else None
                },
                'data': {
                    'technical': result.data.technical.to_dict() if result.data.technical else None,
                    'content': result.data.content.to_dict() if result.data.content else None,
                    'steps': [step.to_dict() for step in result.data.steps]
                }
            }

            # Fehlerbehandlung
            if result.error:
                response['error'] = {
                    'code': result.error.code,
                    'message': result.error.message,
                    'details': result.error.details if hasattr(result.error, 'details') else {}
                }
                return response, 400
            
            return response
            
        except Exception as error:
            logger.error(
                "Fehler bei der Metadaten-Extraktion",
                error=error,
                traceback=traceback.format_exc()
            )
            return {
                "status": "error",
                "error": {
                    "code": "ProcessingError",
                    "message": f"Fehler bei der Metadaten-Extraktion: {str(error)}",
                    "details": {
                        "error_type": type(error).__name__,
                        "traceback": traceback.format_exc()
                    }
                }
            }, 400
```

### Hauptunterschiede und Verbesserungen

1. **Request-Handling**
   - Transformer: JSON-Payload
   - Metadata: Multipart-Form mit File-Upload
   - ➡️ Bessere Validierung für File-Uploads

2. **Response-Struktur**
   - Transformer: Fokus auf Text-Transformation
   - Metadata: Komplexere Metadaten-Struktur
   - ➡️ Einheitliche Struktur für beide

3. **Error-Handling**
   - Transformer: Detaillierte Fehler
   - Metadata: Bisher einfacher
   - ➡️ Gleiche Fehlerstruktur verwenden

4. **Performance-Tracking**
   - Transformer: Vollständiges Tracking
   - Metadata: Bisher minimal
   - ➡️ Tracking vereinheitlichen

### API-Modelle aktualisieren

```python
metadata_response = api.model('MetadataResponse', {
    'status': fields.String(description='Status der Verarbeitung (success/error)'),
    'request': fields.Nested(api.model('RequestInfo', {
        'processor': fields.String(description='Name des Prozessors'),
        'timestamp': fields.String(description='Zeitstempel der Anfrage'),
        'parameters': fields.Raw(description='Anfrageparameter')
    })),
    'process': fields.Nested(api.model('ProcessInfo', {
        'id': fields.String(description='Eindeutige Prozess-ID'),
        'main_processor': fields.String(description='Hauptprozessor'),
        'sub_processors': fields.List(fields.String, description='Unterprozessoren'),
        'started': fields.String(description='Startzeitpunkt'),
        'completed': fields.String(description='Endzeitpunkt'),
        'duration': fields.Float(description='Verarbeitungsdauer in Millisekunden'),
        'llm_info': fields.Nested(api.model('LLMInfo', {
            'requests_count': fields.Integer(description='Anzahl der LLM-Anfragen'),
            'total_tokens': fields.Integer(description='Gesamtanzahl der Tokens'),
            'total_duration': fields.Float(description='Gesamtdauer in Millisekunden')
        }))
    })),
    'data': fields.Nested(api.model('MetadataData', {
        'technical': fields.Nested(technical_metadata),
        'content': fields.Nested(content_metadata),
        'steps': fields.List(fields.Nested(processing_step))
    })),
    'error': fields.Nested(api.model('ErrorInfo', {
        'code': fields.String(description='Fehlercode'),
        'message': fields.String(description='Fehlermeldung'),
        'details': fields.Raw(description='Detaillierte Fehlerinformationen')
    }))
})
```

## Implementierungsschritte für API

1. Request-Parser aktualisieren
2. Response-Struktur vereinheitlichen
3. Error-Handling verbessern
4. Performance-Tracking einbauen
5. API-Dokumentation aktualisieren

## Vorteile

1. **Konsistente API-Struktur**
   - Gleiche Response-Formate
   - Einheitliche Fehlerbehandlung
   - Bessere Wartbarkeit

2. **Verbesserte Dokumentation**
   - Klare API-Modelle
   - Bessere Swagger/OpenAPI Docs
   - Einfachere Integration

3. **Besseres Monitoring**
   - Detailliertes Performance-Tracking
   - Strukturierte Fehler-Logs
   - Prozess-Nachverfolgung 