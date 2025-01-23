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