# Konzept: Refaktorierung MetaProcessor

## Gemeinsamkeiten mit TransformerProcessor

### Grundstruktur
- Vererbung von BaseProcessor
- Ähnliche Initialisierung (resource_calculator, process_id)
- Logging-System
- Fehlerbehandlung und Validierung
- Response-Struktur mit Request/Process/Data/Status

### Wiederverwendbare Komponenten
- Basis-Validierungsmethoden
- Error-Handling Mechanismen
- Debug-Output System
- Resource Tracking
- LLM-Info Tracking

## Spezifische Anpassungen

### MetaProcessor Response-Struktur
```python
class MetaProcessorResponse:
    request: RequestInfo
    process: ProcessInfo
    data: MetaProcessorData
    llm_info: Optional[LLMInfo]
    status: ProcessingStatus
    error: Optional[ErrorInfo]

class MetaProcessorData:
    input: MetaProcessorInput
    output: MetaProcessorOutput
    processors: List[ProcessorInfo]  # Liste der verwendeten Prozessoren

class ProcessorInfo:
    name: str
    status: ProcessingStatus
    start_time: datetime
    end_time: Optional[datetime]
    error: Optional[ErrorInfo]
```

### Hauptfunktionalitäten

1. **Prozessor-Orchestrierung**
- Dynamische Prozessor-Auswahl basierend auf Input
- Parallele Ausführung wo möglich
- Abhängigkeitsmanagement zwischen Prozessoren
- Fortschrittsverfolgung

2. **Zustandsmanagement**
- Tracking des Gesamtfortschritts
- Zwischenergebnisse speichern
- Wiederaufnahme nach Fehlern
- Cleanup nach Abschluss

3. **Ressourcenmanagement**
- Lastverteilung zwischen Prozessoren
- Priorisierung von Aufgaben
- Ressourcenlimits pro Prozessor

## Implementierungsschritte

1. **Basisstruktur**
```python
class MetaProcessor(BaseProcessor):
    def __init__(self, resource_calculator, process_id=None):
        super().__init__(resource_calculator, process_id)
        self.processors = {}  # Verfügbare Prozessoren
        self.active_processes = {}  # Laufende Prozesse
        self.results_cache = {}  # Zwischenergebnisse
```

2. **Hauptmethoden**
```python
def process(self, input_data: MetaProcessorInput) -> MetaProcessorResponse:
    # Hauptverarbeitungslogik
    
def select_processors(self, input_data: MetaProcessorInput) -> List[str]:
    # Prozessorauswahl basierend auf Input
    
def execute_processor(self, processor_name: str, data: Any) -> Any:
    # Einzelprozessorausführung
    
def manage_dependencies(self, processors: List[str]) -> Dict[str, List[str]]:
    # Abhängigkeitsmanagement
```

## Validierung und Tests

1. **Eingabevalidierung**
- Validierung der MetaProcessorInput Struktur
- Prüfung der Prozessor-Verfügbarkeit
- Validierung der Prozessor-Konfigurationen

2. **Testszenarien**
- Einzelprozessor-Tests
- Multi-Prozessor-Tests
- Fehlerszenarien
- Ressourcenlimits
- Wiederaufnahmetests

## Unterschiede zum TransformerProcessor

1. **Komplexität**
- Mehrere Prozessoren statt einem
- Abhängigkeitsmanagement
- Zustandsverwaltung
- Ressourcenverteilung

2. **Fehlerbehandlung**
- Granularere Fehlerbehandlung pro Prozessor
- Teilweise Erfolge möglich
- Wiederaufnahmemöglichkeiten

3. **Konfiguration**
- Komplexere Konfigurationsstruktur
- Prozessor-spezifische Einstellungen
- Globale Metaprozessor-Einstellungen

## Nächste Schritte

1. **Vorbereitungsphase**
- Aktuelle Implementierung analysieren
- Abhängigkeiten identifizieren
- Testfälle dokumentieren

2. **Implementierung**
- Basisstruktur aufsetzen
- Prozessor-Management implementieren
- Response-Struktur anpassen
- Tests erstellen

3. **Integration**
- Bestehende Prozessoren anpassen
- API-Endpunkte aktualisieren
- Dokumentation erweitern

4. **Validierung**
- Umfangreiche Tests durchführen
- Performance-Messungen
- Fehlerszenarien testen

# Analyse: MetadataProcessor Implementierung vs. Konzept

## Aktuelle Implementierung

### Stärken
1. **Grundstruktur**
   - Erbt korrekt von BaseProcessor
   - Implementiert Logger und Konfigurationsmanagement
   - Unterstützt verschiedene Eingabeformate (bytes, file-like objects, Pfade)

2. **Technische Metadaten**
   - Robuste MIME-Type Erkennung mit Fallbacks
   - Unterstützung für verschiedene Medientypen (Audio, Video, PDF, etc.)
   - Validierung von Dateigröße und MIME-Types
   - Detaillierte Extraktion von Medien-spezifischen Metadaten

3. **Fehlerbehandlung**
   - Granulare Fehlertypen (ProcessingError, UnsupportedMimeTypeError, etc.)
   - Ausführliches Logging
   - Sauberes Exception Handling

### Abweichungen vom Konzept

1. **Content Metadata**
   - Konzept sieht tiefere LLM-Integration vor
   - Aktuelle Implementierung verwendet Dummy-Daten
   - Template-System nicht vollständig implementiert

2. **Response-Struktur**
   - Einfachere Struktur als im Konzept vorgesehen
   - Fehlendes strukturiertes Tracking von LLM-Nutzung
   - Keine vollständige Integration der ProcessInfo

3. **Integration**
   - Weniger tiefe Integration mit anderen Prozessoren
   - Fehlendes Caching-System
   - Keine Batch-Verarbeitung

## Empfohlene Anpassungen

### 1. Response-Struktur modernisieren
```python
class MetadataResponse:
    request: RequestInfo
    process: ProcessInfo
    data: MetadataData
    llm_info: Optional[LLMInfo]
    status: ProcessingStatus
    error: Optional[ErrorInfo]

class MetadataData:
    technical: Optional[TechnicalMetadata]
    content: Optional[ContentMetadata]
    processing_info: ProcessingInfo
```

### 2. Content Metadata vervollständigen
- LLM-Integration für Inhaltsanalyse implementieren
- Template-System für verschiedene Medientypen einführen
- Strukturierte Extraktion von inhaltlichen Metadaten

### 3. Prozessor-Integration verbessern
- Tiefere Integration mit TransformerProcessor
- Bessere Nutzung des Template-Systems
- Implementierung von Caching-Mechanismen

### 4. Ressourcen-Management
- Tracking von LLM-Nutzung
- Besseres Cleanup von temporären Dateien
- Implementierung von Batch-Verarbeitung

## Implementierungsplan

1. **Phase 1: Response-Struktur**
   - Neue Datenmodelle implementieren
   - Response-Klassen anpassen
   - Tests aktualisieren

2. **Phase 2: Content Metadata**
   - LLM-Integration implementieren
   - Template-System entwickeln
   - Validierungssystem erweitern

3. **Phase 3: Prozessor-Integration**
   - TransformerProcessor-Integration
   - Caching-System implementieren
   - Batch-Verarbeitung hinzufügen

4. **Phase 4: Tests & Dokumentation**
   - Unit-Tests erweitern
   - Integrationstests erstellen
   - Dokumentation aktualisieren

## Technische Schulden

1. **Content Metadata**
   - Dummy-Implementierung durch echte LLM-Integration ersetzen
   - Template-System vollständig implementieren
   - Validierung der extrahierten Metadaten verbessern

2. **Ressourcen-Management**
   - Besseres Tracking von Ressourcenverbrauch
   - Optimierung der temporären Dateiverwaltung
   - Implementierung von Batch-Verarbeitung

3. **Tests**
   - Mehr Unit-Tests für Metadaten-Extraktion
   - Integrationstests mit anderen Prozessoren
   - Performance-Tests für große Dateien

## Nächste Schritte

1. **Kurzfristig**
   - Response-Struktur modernisieren
   - LLM-Integration implementieren
   - Basic Template-System einführen

2. **Mittelfristig**
   - Caching-System implementieren
   - Prozessor-Integration verbessern
   - Test-Coverage erhöhen

3. **Langfristig**
   - Batch-Verarbeitung implementieren
   - Performance-Optimierungen
   - Erweiterte Medientyp-Unterstützung 

## Detaillierte Response-Struktur

### Basis-Struktur
```python
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

@dataclass
class MetadataResponse:
    """Hauptresponse-Klasse für den MetadataProcessor."""
    request: RequestInfo
    process: ProcessInfo
    data: MetadataData
    llm_info: Optional[LLMInfo] = None
    status: ProcessingStatus = ProcessingStatus.SUCCESS
    error: Optional[ErrorInfo] = None

@dataclass
class MetadataData:
    """Container für alle Metadaten-Informationen."""
    technical: Optional[TechnicalMetadata] = None
    content: Optional[ContentMetadata] = None
    processing_info: ProcessingInfo
    source_info: Optional[Dict[str, Any]] = None

@dataclass
class ProcessingInfo:
    """Informationen über den Verarbeitungsprozess."""
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    steps: List[ProcessingStep] = field(default_factory=list)
    resource_usage: Optional[ResourceUsage] = None

@dataclass
class ProcessingStep:
    """Einzelner Verarbeitungsschritt."""
    name: str
    status: ProcessingStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    error: Optional[ErrorInfo] = None
```

### Technische Metadaten
```python
@dataclass
class TechnicalMetadata:
    """Technische Metadaten einer Datei."""
    file_name: str
    file_mime: str
    file_size: int
    file_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    modified_at: Optional[datetime] = None
    
    # Medienspezifische Informationen
    media_duration: Optional[float] = None
    media_bitrate: Optional[int] = None
    media_codec: Optional[str] = None
    media_channels: Optional[int] = None
    media_sample_rate: Optional[int] = None
    
    # Dokumentspezifische Informationen
    doc_pages: Optional[int] = None
    doc_encrypted: Optional[bool] = None
    
    # Bildspezifische Informationen
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    image_format: Optional[str] = None
    image_color_space: Optional[str] = None
```

### Inhaltliche Metadaten
```python
@dataclass
class ContentMetadata:
    """Inhaltliche Metadaten, extrahiert durch LLM."""
    # Basis-Informationen
    title: str
    abstract: str
    language: str
    content_type: str
    keywords: List[str]
    
    # Zeitliche Informationen
    created: Optional[datetime] = None
    time_period: Optional[str] = None
    temporal_coverage: Optional[List[str]] = None
    
    # Räumliche Informationen
    locations: Optional[List[str]] = None
    spatial_coverage: Optional[str] = None
    
    # Inhaltliche Klassifikation
    topics: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    
    # Personen und Organisationen
    persons: Optional[List[str]] = None
    organizations: Optional[List[str]] = None
    
    # Plattform-spezifische Informationen
    platform_data: Optional[Dict[str, Any]] = None
    
    # Strukturierte Extrakte
    structured_data: Optional[Dict[str, Any]] = None
```

### LLM-Informationen
```python
@dataclass
class LLMInfo:
    """Informationen über LLM-Nutzung."""
    model: str
    purpose: str
    requests: List[LLMRequest] = field(default_factory=list)
    total_tokens: int = 0
    total_duration_ms: float = 0
    
@dataclass
class LLMRequest:
    """Details eines einzelnen LLM-Requests."""
    timestamp: datetime
    operation: str
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    model_params: Dict[str, Any]
```

### Vorteile der neuen Struktur

1. **Vollständigkeit**
   - Umfassende Erfassung aller relevanten Metadaten
   - Klare Trennung zwischen technischen und inhaltlichen Daten
   - Detailliertes Prozess-Tracking

2. **Flexibilität**
   - Optionale Felder für verschiedene Medientypen
   - Erweiterbare Struktur für neue Metadaten
   - Anpassbare Plattform-spezifische Informationen

3. **Nachverfolgbarkeit**
   - Detailliertes Tracking von Verarbeitungsschritten
   - Vollständige LLM-Nutzungsinformationen
   - Ressourcenverbrauch-Monitoring

4. **Integration**
   - Kompatibel mit anderen Prozessoren
   - Standardisierte Fehlerbehandlung
   - Einheitliche Zeitstempel und Dauer-Tracking

## Analyse der vorhandenen Typen

### Vorhandene Basistypen (@base.py)
```python
# Können 1:1 übernommen werden:
- RequestInfo
- ProcessInfo
- ErrorInfo
- BaseResponse
```

### Vorhandene Metadaten-Typen (@metadata.py)
```python
# Können übernommen werden:
@dataclass(frozen=True, slots=True)
class ContentMetadata:
    # Bereits sehr umfangreich mit:
    - Bibliographischen Grunddaten
    - Wissenschaftlicher Klassifikation
    - Räumlicher/zeitlicher Einordnung
    - Rechten und Lizenzen
    
@dataclass(frozen=True, slots=True)
class TechnicalMetadata:
    # Bereits gut strukturiert mit:
    - Basis-Dateiinformationen
    - Medienspezifischen Details
    - Dokumentspezifischen Informationen
```

### Vorhandene LLM-Typen (@llm.py)
```python
# Können direkt verwendet werden:
- LLModel
- LLMRequest
- LLMInfo
- TranscriptionSegment
- TranscriptionResult
```

### Vorhandene Enums (@enums.py)
```python
# Passen perfekt:
- ProcessorType
- ProcessingStatus
- OutputFormat
```

## Anpassung der Response-Struktur

### Was wir behalten können
1. **Basis-Struktur**
   - Alle `BaseResponse`-Komponenten
   - Vorhandene Validierungslogik
   - Frozen Dataclasses mit Slots

2. **Metadaten-Modelle**
   - Existierende `ContentMetadata`
   - Existierende `TechnicalMetadata`
   - Vorhandene Post-Init Validierungen

3. **LLM-Tracking**
   - Komplettes `LLMInfo`-System
   - Request-Tracking
   - Performance-Metriken

### Notwendige Ergänzungen

1. **MetadataResponse erweitern**
```python
@dataclass(frozen=True, slots=True)
class MetadataResponse(BaseResponse):
    """Erweitert BaseResponse um Metadaten-spezifische Felder."""
    data: MetadataData
    
@dataclass(frozen=True, slots=True)
class MetadataData:
    """Neu: Kombiniert vorhandene Metadaten-Typen."""
    technical: Optional[TechnicalMetadata] = None
    content: Optional[ContentMetadata] = None
    source_info: Optional[Dict[str, Any]] = None
```

2. **ProcessingInfo erweitern**
```python
@dataclass(frozen=True, slots=True)
class ProcessingStep:
    """Neu: Tracking einzelner Verarbeitungsschritte."""
    name: str
    status: ProcessingStatus
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    error: Optional[ErrorInfo] = None
```

## Vorteile dieser Anpassung

1. **Kompatibilität**
   - Nutzung bewährter Strukturen
   - Keine Breaking Changes
   - Beibehaltung der Validierungslogik

2. **Erweiterbarkeit**
   - Neue Komponenten ergänzen bestehende
   - Keine Redundanz
   - Klare Trennung der Zuständigkeiten

3. **Konsistenz**
   - Einheitliche Validierung
   - Durchgängige Nutzung von frozen=True und slots=True
   - Konsistente Fehlerbehandlung

## Implementierungsschritte

1. **Phase 1: MetadataResponse**
   - Neue Response-Klasse erstellen
   - Vorhandene Typen integrieren
   - Tests anpassen

2. **Phase 2: ProcessingInfo**
   - ProcessingStep implementieren
   - In ProcessInfo integrieren
   - Tracking-Logik hinzufügen

3. **Phase 3: Integration**
   - Processor-Code anpassen
   - Validierungen erweitern
   - Tests aktualisieren

## Technische Überlegungen

1. **Frozen Dataclasses**
   - Alle neuen Klassen als `@dataclass(frozen=True, slots=True)`
   - Konsistent mit vorhandenen Strukturen
   - Performance-Vorteile beibehalten

2. **Validierung**
   - Bestehende `__post_init__` Methoden nutzen
   - Validierungslogik aus base.py übernehmen
   - Typ-Checks beibehalten

3. **Error Handling**
   - Vorhandene ErrorInfo-Struktur nutzen
   - Granulare Fehlertypen beibehalten
   - Konsistente Exception-Hierarchie

## Fazit
Die vorhandenen Typen sind sehr gut strukturiert und können größtenteils 1:1 übernommen werden. Wir müssen nur wenige neue Strukturen (MetadataResponse, ProcessingStep) hinzufügen, die sich nahtlos in das bestehende System einfügen. Die Verwendung von frozen=True und slots=True sowie die vorhandene Validierungslogik sind optimal und sollten beibehalten werden.
