# Konzeption: TrackProzessor

## Überblick

Der TrackProzessor ist eine neue Komponente, die die Zusammenfassung von Event-Tracks ermöglicht. Er nutzt die bereits verarbeiteten Event-Daten aus der MongoDB und erstellt eine strukturierte Gesamtzusammenfassung basierend auf einem Template.

## Architektur

### Basis-Komponenten

Der TrackProzessor erbt von `BaseProcessor` und nutzt die folgenden bestehenden Komponenten:

1. **ResponseFactory**
   - Standardisierte Response-Erstellung
   - LLM-Tracking Integration
   - Fehlerbehandlung

2. **ResourceCalculator**
   - Ressourcenverbrauch-Tracking
   - Performance-Monitoring

3. **ProcessingLogger**
   - Strukturiertes Logging
   - Fehler-Tracking

4. **MongoDB Integration**
   - Event-Datenbank-Zugriff
   - Event-Datenstrukturen

### Datenmodelle

```python
@dataclass(frozen=True)
class TrackResponse(BaseResponse):
    """Response des Track-Prozessors"""
    data: TrackData
    llm_info: Optional[LLMInfo] = None

@dataclass(frozen=True)
class TrackData:
    """Datenstruktur für Track-Verarbeitung"""
    input: TrackInput
    output: TrackOutput
    events: List[EventData]  # Wiederverwendung der EventData-Struktur

@dataclass(frozen=True)
class TrackInput:
    """Eingabedaten für Track-Verarbeitung"""
    track_name: str
    template: str
    target_language: str

@dataclass(frozen=True)
class TrackOutput:
    """Ausgabedaten der Track-Verarbeitung"""
    summary: str
    metadata: Dict[str, Any]
    structured_data: Dict[str, Any]
```

## Hauptfunktionalitäten

### 1. Event-Datenbank-Zugriff
- Liest Events eines Tracks aus der MongoDB
- Extrahiert Markdown-Dateien und Metadaten
- Sammelt alle relevanten Event-Informationen

### 2. Template-Verarbeitung
- Nutzt den TransformerProcessor für die Template-Verarbeitung
- Verwendet das `track-eco-social-summary.md` Template
- Fügt Kontextinformationen aus allen Events hinzu

### 3. Zusammenfassung
- Erstellt eine strukturierte Gesamtzusammenfassung
- Extrahiert Schlüsselinformationen aus allen Events
- Generiert Metadaten für den gesamten Track

## API-Endpoint

```python
@router.post("/tracks/{track_name}/summary")
async def create_track_summary(
    track_name: str,
    template: str = "track-eco-social-summary",
    target_language: str = "de"
) -> TrackResponse:
    """
    Erstellt eine Zusammenfassung für einen Track.
    
    Args:
        track_name: Name des Tracks
        template: Name des Templates für die Zusammenfassung
        target_language: Zielsprache für die Zusammenfassung
        
    Returns:
        TrackResponse: Die Zusammenfassung des Tracks
    """
```

## Verarbeitungsablauf

1. **Initialisierung**
   - Validiere Eingabeparameter
   - Initialisiere LLM-Tracking
   - Erstelle temporäre Verzeichnisse

2. **Event-Datenbank-Zugriff**
   - Query MongoDB nach Events des Tracks
   - Extrahiere EventData-Objekte
   - Sammle Markdown-Dateien und Metadaten

3. **Template-Verarbeitung**
   - Erstelle Kontext aus allen Events
   - Nutze TransformerProcessor
   - Verarbeite Template-Variablen

4. **Response-Erstellung**
   - Strukturiere Ergebnis
   - Füge LLM-Informationen hinzu
   - Erstelle standardisierte Response

## Fehlerbehandlung

- Validierung der Track-Parameter
- Fehlerbehandlung bei Datenbank-Zugriff
- Fehlerbehandlung bei Template-Verarbeitung
- Graceful Degradation bei fehlenden Daten
- Detaillierte Fehlerprotokolle

## Wiederverwendete Komponenten

1. **EventProcessor**
   - Event-Datenstrukturen
   - MongoDB-Integration
   - Markdown-Generierung

2. **TransformerProcessor**
   - Template-Verarbeitung
   - LLM-Integration
   - Response-Struktur

3. **BaseProcessor**
   - Grundlegende Funktionalität
   - Logging
   - Ressourcen-Tracking

4. **ResponseFactory**
   - Standardisierte Responses
   - LLM-Tracking
   - Fehlerbehandlung

## Nächste Schritte

1. Implementierung der Datenmodelle
2. Entwicklung des TrackProzessors
3. Integration des API-Endpoints
4. Erstellung von Tests
5. Dokumentation der API 