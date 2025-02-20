# Typ-Migration Analyse

## Aktuelle Struktur

### 1. Core Models (`src/core/models/`)
Neue, native Dataclass-basierte Implementierungen:
- `base.py`: Basis-Dataclass und Konvertierungsfunktionen
- `enums.py`: Zentrale Enum-Definitionen
- `llm.py`: LLM-spezifische Modelle
- `audio.py`: Audio-Verarbeitungsmodelle
- `metadata.py`: Metadaten-Modelle

### 2. Utils Types (`src/utils/`)
Alte, Pydantic-basierte Implementierungen:
- `types.py`: Allgemeine Typdefinitionen (zu migrieren/löschen)
- `openai_types.py`: OpenAI-spezifische Typen (behalten)

## Überschneidungsanalyse

### Bereits migrierte Typen (können aus types.py gelöscht werden)

1. **Basis-Modelle**
   - ✓ `BaseModel` → migriert zu `core/models/base.py`
   - ✓ `SerializableDict` → ersetzt durch native Dict-Typen
   - ✓ `CustomModel` → ersetzt durch `BaseModel` in `core/models/base.py`

2. **LLM-Modelle**
   - ✓ `LLModel` → migriert zu `core/models/llm.py`
   - ✓ `LLMRequest` → migriert zu `core/models/llm.py`
   - ✓ `LLMInfo` → migriert zu `core/models/llm.py`
   - ✓ `TranscriptionSegment` → migriert zu `core/models/llm.py`
   - ✓ `TranscriptionResult` → migriert zu `core/models/llm.py`

3. **Audio-Modelle**
   - ✓ `AudioSegmentInfo` → migriert zu `core/models/audio.py`
   - ✓ `Chapter` → migriert zu `core/models/audio.py`
   - ✓ `AudioMetadata` → migriert zu `core/models/audio.py`
   - ✓ `AudioProcessingResult` → migriert zu `core/models/audio.py`
   - ✓ `ChapterInfo` → migriert zu `core/models/audio.py`

4. **Enums**
   - ✓ `EventFormat` → migriert zu `core/models/enums.py`
   - ✓ `PublicationStatus` → migriert zu `core/models/enums.py`
   - ✓ `ProcessingStatus` → migriert zu `core/models/enums.py`
   - ✓ `ProcessorType` → migriert zu `core/models/enums.py`
   - ✓ `OutputFormat` → migriert zu `core/models/enums.py`

### Zu migrierende Typen

1. **API Response Modelle** (nach `api/models/responses.py`)
   - `BaseResponse`
   - `CompleteMetadata`
   - `TransformerResponse`
   - `ErrorInfo`
   - `RequestInfo`
   - `ProcessInfo`

2. **Transformer Modelle** (nach `core/models/transformer.py`)
   - `TransformerData`
   - `TransformerInput`
   - `TransformerOutput`

3. **YouTube Modelle** (nach `core/models/youtube.py`)
   - `YoutubeMetadata`
   - `YoutubeProcessingResult`

### Beizubehaltende Typen

1. **OpenAI Types** (`src/utils/openai_types.py`)
   - Alle OpenAI-spezifischen Typen bleiben
   - Dient als Adapter zwischen OpenAI API und unseren Modellen
   - Enthält Pydantic-Modelle für API-Validierung

## Migrationsplan

1. **Phase 1: API Response Modelle**
   - Erstelle `api/models/responses.py`
   - Migriere Response-Modelle
   - Aktualisiere API-Endpunkte

2. **Phase 2: Transformer & YouTube**
   - Erstelle neue Modelldateien
   - Migriere Modelle
   - Aktualisiere abhängige Code-Stellen

3. **Phase 3: Cleanup**
   - Lösche migrierte Typen aus `types.py`
   - Aktualisiere Imports
   - Entferne Pydantic-Abhängigkeiten

## Zu löschende Dateien

Nach Abschluss der Migration:
- `src/utils/types.py` (vollständig)
- `src/utils/types/openai_types.py` (leere Datei, kann sofort gelöscht werden)
- Pydantic-spezifische Konfigurationen

## Beizubehaltende Dateien

- `src/utils/openai_types.py`: OpenAI API Integration (aktuelle Version)
  - Enthält Pydantic-Modelle für OpenAI API
  - Dient als Adapter zwischen OpenAI API und unseren Modellen
  - Bleibt als einzige Pydantic-Implementierung bestehen
- `src/core/models/*`: Neue Dataclass-Implementierungen
- `src/api/models/*`: Neue API-Modelle

## Nächste Schritte

1. Erstelle `api/models/responses.py`
2. Migriere API Response Modelle
3. Erstelle `core/models/transformer.py`
4. Migriere Transformer Modelle
5. Erstelle `core/models/youtube.py`
6. Migriere YouTube Modelle
7. Cleanup `types.py`

# Analyse der Modell-Tests

## Vorhandene Modelle in tests/test_types.py

### Response Models
1. `BaseResponse`
   - Basis-Antwortmodell für alle API Responses
   - Enthält: status, request, process, data, error
   - Unterstützt LLM-Request Tracking
   - Tests für: Erfolg, Fehler, Validierung, Defaults

2. `TransformerResponse`
   - Erweitert BaseResponse für Transformer-spezifische Antworten
   - Enthält: input_text, output_text, model, task, duration, token_count
   - Unterstützt Templates mit Variablen
   - Tests für: Template-Verarbeitung, Fehler, Teilweise Daten

3. `YoutubeMetadata`
   - Metadaten für YouTube Videos
   - Pflichtfelder: title, url, video_id, duration, duration_formatted, process_dir
   - Tests für: Erstellung, Validierung (leere/ungültige Werte)

4. `YoutubeProcessingResult`
   - Ergebnis der YouTube-Verarbeitung
   - Enthält: process_id, metadata (YoutubeMetadata), status
   - Tests für: Erstellung, Validierung, Dictionary-Konvertierung

### Utility Models
1. `LLModel`
   - Modell für LLM-Nutzung
   - Enthält: model, duration, tokens
   - Nur minimale Tests vorhanden

## Fehlende/Zu Migrierende Modelle

1. `ErrorInfo`
   - Fehlerinformationen (code, message)
   - Wird in BaseResponse verwendet
   - Benötigt eigene Tests

2. `RequestInfo`
   - Request-Metadaten (processor, timestamp)
   - Wird in BaseResponse verwendet
   - Benötigt eigene Tests

3. `ProcessInfo`
   - Prozess-Informationen (id, processors, duration)
   - Wird in BaseResponse verwendet
   - Benötigt eigene Tests

## Vorgeschlagene Änderungen

1. Umbenennung:
   - `tests/test_types.py` -> `tests/test_models.py`
   - Bessere Reflektion des Inhalts (Modell-Tests statt Typ-Tests)

2. Strukturierung:
   - Tests nach Modell-Kategorien gruppieren
   - Gemeinsame Fixtures für wiederverwendbare Testdaten
   - Dokumentation der Test-Abdeckung

3. Ergänzungen:
   - Vollständige Tests für ErrorInfo, RequestInfo, ProcessInfo
   - Erweiterte Tests für LLModel
   - Edge Cases und Fehlerszenarien

4. Clean-Up:
   - Entfernen des nicht verwendeten LLModel-Objekts
   - Konsistente Formatierung
   - Klare Trennung zwischen Modell-Kategorien

## Nächste Schritte

1. Implementierung der fehlenden Modelle in `src/utils/types/`
2. Umbenennung der Testdatei
3. Ergänzung der fehlenden Tests
4. Überprüfung der Testabdeckung
5. Dokumentation der Modell-Struktur und Beziehungen

# Test-Struktur und Implementierung

## Neue Test-Struktur

### 1. Basis-Modelle (BaseModel)
```python
@pytest.fixture
def base_test_data():
    """Gemeinsame Testdaten für Basis-Modelle."""
    return {
        "timestamp": datetime.now(timezone.utc),
        "id": "test-123",
        "processor": "test"
    }

class TestBaseModels:
    """Tests für die Basis-Modelle."""
    
    def test_error_info(self, base_test_data):
        """Test ErrorInfo Modell."""
        pass
        
    def test_request_info(self, base_test_data):
        """Test RequestInfo Modell."""
        pass
        
    def test_process_info(self, base_test_data):
        """Test ProcessInfo Modell."""
        pass
```

### 2. Response-Modelle
```python
@pytest.fixture
def response_test_data(base_test_data):
    """Gemeinsame Testdaten für Response-Modelle."""
    return {
        **base_test_data,
        "status": "success",
        "data": {"test": "data"}
    }

class TestResponseModels:
    """Tests für die Response-Modelle."""
    
    def test_base_response(self, response_test_data):
        """Test BaseResponse Modell."""
        pass
        
    def test_transformer_response(self, response_test_data):
        """Test TransformerResponse Modell."""
        pass
```

### 3. Prozessor-spezifische Modelle
```python
class TestYoutubeModels:
    """Tests für die YouTube-spezifischen Modelle."""
    
    def test_youtube_metadata(self):
        """Test YoutubeMetadata Modell."""
        pass
        
    def test_youtube_processing_result(self):
        """Test YoutubeProcessingResult Modell."""
        pass
```

## Neue Testroutinen

### 1. ErrorInfo Tests
- Validierung von Code-Formaten (HTTP, Custom)
- Nachrichtenformatierung
- Lokalisierung von Fehlermeldungen
- Edge Cases (leere Nachrichten, ungültige Codes)

### 2. RequestInfo Tests
- Zeitstempel-Validierung
- Processor-Name-Validierung
- Parameter-Validierung
- Serialisierung/Deserialisierung

### 3. ProcessInfo Tests
- ID-Generierung und Validierung
- Processor-Liste Validierung
- Dauer-Berechnung
- Status-Übergänge

### 4. LLModel Tests
- Token-Zählung
- Dauer-Berechnung
- Modell-Validierung
- Kostenberechnung

## Implementierungsplan

1. Basis-Modelle
   - [ ] ErrorInfo Implementation
   - [ ] RequestInfo Implementation
   - [ ] ProcessInfo Implementation
   - [ ] LLModel Implementation

2. Response-Modelle
   - [ ] BaseResponse Erweiterung
   - [ ] TransformerResponse Anpassung
   - [ ] Gemeinsame Fixtures

3. Prozessor-Modelle
   - [ ] YoutubeMetadata Optimierung
   - [ ] YoutubeProcessingResult Erweiterung
   - [ ] Prozessor-spezifische Fixtures

4. Test Coverage
   - [ ] Edge Cases
   - [ ] Fehlerszenarien
   - [ ] Integrationstests
   - [ ] Performance-Tests

## Nächste Schritte

1. [ ] Implementierung der ErrorInfo Tests
2. [ ] Implementierung der RequestInfo Tests
3. [ ] Implementierung der ProcessInfo Tests
4. [ ] Erweiterung der LLModel Tests
5. [ ] Restrukturierung der bestehenden Tests
6. [ ] Dokumentation der Testabdeckung 
