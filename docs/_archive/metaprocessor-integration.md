# MetadataProcessor Integration Analyse

## 1. Vergleich mit AudioProcessor

### 1.1 Konstruktor und Konfiguration

#### Gemeinsamkeiten
- Beide erben von `BaseProcessor`
- Beide verwenden `Config()` für Konfigurationsmanagement
- Beide initialisieren einen Logger
- Beide haben temporäre Verzeichnisse

#### Unterschiede und Optimierungspotenzial

| Aspekt | AudioProcessor | MetadataProcessor | Empfehlung |
|--------|---------------|-------------------|------------|
| Resource Calculator | Wird aktiv genutzt | Wird übergeben aber nicht genutzt | Resource Calculator für Dateigrößen und LLM-Nutzung implementieren |
| Konfigurationsstruktur | Flache Struktur | Verschachtelte Struktur mit extraction.technical/content | Flachere Struktur für bessere Wartbarkeit |
| Komponenten | Mehrere (Transcriber, Transformer) | Nur Transcriber | Transformer für Content-Analyse hinzufügen |
| Validierung | Validiert segment_duration | Validiert nur Dateigrößen | Weitere Validierungen für MIME-Types hinzufügen |

### 1.2 Fehlerbehandlung

#### Gemeinsamkeiten
- Beide nutzen `ProcessingError`
- Beide haben detailliertes Logging
- Beide haben Cleanup-Mechanismen

#### Unterschiede und Optimierungspotenzial

| Aspekt | AudioProcessor | MetadataProcessor | Empfehlung |
|--------|---------------|-------------------|------------|
| Granularität | Spezifische Fehler pro Phase | Generische Fehler | Spezifischere Fehlertypen einführen |
| Cleanup | Automatisch nach Segmentierung | Nur für temp_file | Erweiterte Cleanup-Strategie |
| Retry-Mechanismus | Vorhanden | Fehlt | Retry für LLM-Aufrufe implementieren |

### 1.3 Logging

#### Gemeinsamkeiten
- Beide nutzen strukturiertes Logging
- Beide haben verschiedene Log-Level
- Beide loggen Start/Ende von Operationen

#### Unterschiede und Optimierungspotenzial

| Aspekt | AudioProcessor | MetadataProcessor | Empfehlung |
|--------|---------------|-------------------|------------|
| Metriken | Detaillierte Audio-Metriken | Basis-Metriken | Mehr Metriken für Metadaten-Extraktion |
| Performance-Logging | Vorhanden | Fehlt | Timing-Informationen hinzufügen |
| Debug-Level | Ausführlich | Minimal | Mehr Debug-Informationen für Entwicklung |

### 1.4 Konfiguration

#### Aktuelle config.yaml für MetadataProcessor
```yaml
processors:
  metadata:
    max_file_size: 104857600
    temp_dir: "temp-processing/metadata"
    llm_template: "metadata"
    supported_mime_types:
      - audio/*
      - video/*
      - image/*
      - application/pdf
    extraction:
      technical:
        enabled: true
        timeout: 30
      content:
        enabled: true
        timeout: 60
        max_content_length: 10000
```

#### Empfohlene Anpassungen
```yaml
processors:
  metadata:
    max_file_size: 104857600
    temp_dir: "temp-processing/metadata"
    llm_template: "metadata"
    supported_mime_types:
      - audio/*
      - video/*
      - image/*
      - application/pdf
    technical:
      enabled: true
      timeout: 30
      mime_type_validation: true
      retry_count: 3
    content:
      enabled: true
      timeout: 60
      max_content_length: 10000
      llm:
        model: "gpt-4"
        temperature: 0.3
        retry_count: 3
    resource_tracking:
      enabled: true
      metrics:
        - file_size
        - processing_time
        - llm_tokens
```

## 2. API Integration

### 2.1 Aktuelle Situation

#### AudioProcessor Route
- Klare Struktur
- Gute Fehlerbehandlung
- Swagger-Integration

#### MetadataProcessor (Fehlt)
- Keine API-Route
- Keine Swagger-Modelle
- Keine Request/Response-Validierung

### 2.2 Empfohlene API-Route

```python
@api.route('/metadata/extract')
@api.response(200, 'Erfolg', metadata_result_model)
@api.response(400, 'Ungültige Anfrage')
@api.response(500, 'Server Fehler')
class MetadataExtractionResource(Resource):
    @api.expect(metadata_upload_parser)
    @api.doc(
        description='Extrahiert Metadaten aus einer Datei',
        params={
            'file': 'Die zu analysierende Datei',
            'content': 'Optionaler zusätzlicher Text für die Analyse',
            'context': 'Optionaler JSON-Kontext'
        }
    )
    async def post(self):
        """Extrahiert Metadaten aus einer Datei."""
        try:
            args = metadata_upload_parser.parse_args()
            
            # Validiere MIME-Type
            file = args['file']
            mime_type = magic.from_buffer(file.read(1024), mime=True)
            file.seek(0)
            
            # Validiere Dateigröße
            if file.content_length > MAX_FILE_SIZE:
                api.abort(400, f"Datei zu groß: {file.content_length} Bytes")
                
            # Parse optionalen Kontext
            context = {}
            if args.get('context'):
                try:
                    context = json.loads(args['context'])
                except json.JSONDecodeError:
                    api.abort(400, "Ungültiger JSON-Kontext")
            
            # Verarbeite Datei
            processor = MetadataProcessor(resource_calculator)
            result = await processor.extract_metadata(
                binary_data=file,
                content=args.get('content'),
                context=context
            )
            
            return result.to_dict()
            
        except ProcessingError as e:
            api.abort(400, str(e))
        except Exception as e:
            api.abort(500, f"Server Fehler: {str(e)}")
```

## 3. Optimierungspotenzial

### 3.1 Kurzfristige Optimierungen
1. Resource Calculator Integration
   - Tracking von Dateigrößen
   - Monitoring von LLM-Nutzung
   - Performance-Metriken

2. Fehlerbehandlung
   - Spezifischere Fehlertypen
   - Retry-Mechanismen
   - Bessere Validierung

3. Logging
   - Performance-Metriken
   - Detailliertere Debug-Informationen
   - Resource-Tracking

### 3.2 Mittelfristige Verbesserungen
1. Architektur
   - Transformer für Content-Analyse
   - Caching-Mechanismus
   - Async Batch-Verarbeitung

2. Konfiguration
   - Vereinfachte Struktur
   - Mehr Validierung
   - Flexiblere MIME-Type-Regeln

3. Tests
   - Unit Tests für alle Komponenten
   - Integration Tests
   - Performance Tests

## 4. Nächste Schritte

1. **Sofort**
   - Resource Calculator implementieren
   - API-Route erstellen
   - Logging erweitern

2. **Diese Woche**
   - Fehlertypen spezifizieren
   - Tests schreiben
   - Konfiguration anpassen

3. **Nächste Woche**
   - Integration in bestehende Prozessoren
   - Performance-Optimierung
   - Dokumentation aktualisieren

# MetadataProcessor Refactoring Analyse

## 1. Hauptänderungen

### 1.1 Transformer-Integration
- MetadataProcessor soll TransformerProcessor für LLM-Operationen nutzen
- Keine eigene OpenAI-Implementierung
- Nutzung der bestehenden Template-Logik

### 1.2 Schlüsselkomponenten

| Komponente | Ist-Zustand | Soll-Zustand |
|------------|-------------|--------------|
| LLM-Verarbeitung | Eigene OpenAI-Integration | Nutzung des TransformerProcessors |
| Template-System | Fehlt | Integration des Transformer-Templates |
| Validierung | Basis-Validierung | Erweiterte Validierung wie im Transformer |
| Error Handling | Einfach | Detailliert wie im Transformer |

## 2. Konkrete Code-Änderungen

### 2.1 Konstruktor Anpassung
```python
def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
    super().__init__(resource_calculator, process_id)
    
    # Konfiguration laden
    metadata_config = self.load_processor_config('metadata')
    
    # Logger initialisieren
    self.logger = self.init_logger("MetadataProcessor")
    
    # Transformer für Content-Analyse
    self.transformer = TransformerProcessor(resource_calculator, process_id)
    
    # Rest der Initialisierung...
```

### 2.2 Content-Extraktion via Transformer
```python
async def extract_content_metadata(
    self, 
    content: str,
    context: Dict[str, Any]
) -> ContentMetadata:
    """Extrahiert Content-Metadaten mittels Transformer."""
    try:
        # Transformer für Template-Transformation nutzen
        result = await self.transformer.transformByTemplate(
            source_text=content,
            source_language="auto",  # oder aus context
            target_language="de",    # oder aus config
            template="Metadata",     # Template aus templates/Metadata.md
            context=context
        )
        
        # Konvertiere Transformer-Ergebnis in ContentMetadata
        return ContentMetadata(**result.data.output.structured_data)
        
    except Exception as e:
        if self.logger:
            self.logger.error(f"Fehler bei Content-Extraktion: {str(e)}")
        raise
```

## 3. Vorteile der Integration

1. **Code-Wiederverwendung**
   - Nutzung der bewährten Transformer-Logik
   - Einheitliche Template-Verarbeitung
   - Konsistentes Error-Handling

2. **Wartbarkeit**
   - Weniger doppelter Code
   - Zentrale LLM-Logik
   - Einfachere Updates

3. **Funktionalität**
   - Bessere Typ-Validierung
   - Strukturierte Ausgaben
   - Konsistentes Logging

## 4. Implementierungsschritte

1. **Phase 1: Basis-Integration**
   - TransformerProcessor als Dependency einbinden
   - Template-System integrieren
   - Basis-Funktionalität testen

2. **Phase 2: Datenmodell-Anpassung**
   - Response-Struktur vereinheitlichen
   - Typ-Validierung erweitern
   - Error-Handling verbessern

3. **Phase 3: Optimierung**
   - Performance-Monitoring
   - Caching implementieren
   - Tests erweitern

## 5. Code-Beispiele

### 5.1 Template-Integration
```python
# In metadata_processor.py
async def process_with_template(
    self,
    content: str,
    template_name: str = "Metadata",
    context: Optional[Dict[str, Any]] = None
) -> MetadataResponse:
    """Verarbeitet Content mit einem Template."""
    try:
        transformer_result = await self.transformer.transformByTemplate(
            source_text=content,
            source_language="auto",
            target_language="de",
            template=template_name,
            context=context
        )
        
        return MetadataResponse(
            request=self.create_request_info(),
            process=self.create_process_info(),
            data=MetadataData(
                content=ContentMetadata(**transformer_result.data.output.structured_data),
                technical=None
            ),
            llm_info=transformer_result.llm_info
        )
    except Exception as e:
        return self.create_error_response(str(e))
```

### 5.2 Error-Handling
```python
def create_error_response(self, error_message: str) -> MetadataResponse:
    """Erstellt eine Error-Response im Transformer-Stil."""
    return MetadataResponse(
        request=self.create_request_info(),
        process=self.create_process_info(),
        data=MetadataData(technical=None, content=None),
        status=ProcessingStatus.ERROR,
        error=ErrorInfo(
            code="PROCESSING_ERROR",
            message=error_message,
            details={
                "processor": "metadata",
                "timestamp": datetime.now().isoformat()
            }
        )
    )
```

## 6. Nächste Schritte

1. **Sofort**
   - TransformerProcessor in MetadataProcessor integrieren
   - Template-System einbinden
   - Error-Handling anpassen

2. **Kurzfristig**
   - Tests für neue Integration schreiben
   - Dokumentation aktualisieren
   - Performance-Monitoring implementieren

3. **Mittelfristig**
   - Caching-Strategie entwickeln
   - Batch-Verarbeitung implementieren
   - Monitoring erweitern 