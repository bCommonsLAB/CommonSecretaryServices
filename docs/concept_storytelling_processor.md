# Konzept: StoryProcessor für thematisches Storytelling

## Überblick

Der `StoryProcessor` ist ein neuer Prozessor zur Erstellung thematischer Geschichten aus einer Sammlung von Sessions. Im Gegensatz zum `TrackProcessor`, der Sessions nach vordefinierten Tracks gruppiert, ermöglicht der `StoryProcessor` die Erstellung von Stories basierend auf thematischen Zusammenhängen. Die Konfiguration der Themen erfolgt zentral in einer MongoDB-Collection.

Die wichtigsten Funktionen des `StoryProcessor` sind:

1. **Verwaltung von thematischen Stories** auf Basis einer konfigurierbaren Themen-Tabelle in MongoDB
2. **Filterung von Sessions** nach Themen und Relevanzwerten
3. **Generierung thematischer Geschichten** durch Zusammenführung ausgewählter Sessions
4. **Anwendung von Templates** für zielgruppenspezifische Darstellung
5. **Mehrsprachige Ausgabe** mit einer einheitlichen Ausgabestruktur
6. **Gruppierung nach Zielgruppen** für maßgeschneiderte Inhalte

## MongoDB-Integration für Topic-Konfiguration

Die Topics werden in einer dedizierten MongoDB-Collection verwaltet, die folgende vereinfachte Struktur hat:

```json
{
  "_id": ObjectId("..."),
  "topic_id": "energy_transition",
  "display_name": {
    "de": "Energiewende",
    "en": "Energy Transition"
  },
  "description": {
    "de": "Beschleunigung des Übergangs durch Open Source",
    "en": "Accelerating the transition through open source"
  },
  "target_groups": ["ecosocial", "developer", "general"],
  "primary_target_group": "ecosocial",
  "template": "ecosocial",  // Verweist direkt auf ein Template im templates-Verzeichnis
  "languages": ["de", "en"],
  "primary_language": "de",
  "relevance_threshold": 0.7,
  "keywords": ["energy", "renewable", "sustainability", "transition"],
  "status": "active"
}
```

Dieser Ansatz bietet mehrere Vorteile:
- Zentrale Verwaltung aller Themen mit ihren Metadaten
- Einfache Zuordnung von Templates (direkter Verweis auf vorhandene Templates)
- Unterstützung für mehrere Sprachen und Zielgruppen
- Flexibilität bei der Konfiguration von Relevanz-Schwellenwerten

## Einbettung in die bestehende Architektur

Der `StoryProcessor` erweitert die bestehende Prozessorhierarchie und nutzt die im Cache gespeicherten Session-Daten:

```
BaseProcessor
├── CacheableProcessor
│   ├── SessionProcessor
│   ├── TrackProcessor
│   └── StoryProcessor (NEU)
```

### Datenfluss

1. Der `SessionProcessor` verarbeitet einzelne Sessions, klassifiziert sie nach Themen und speichert sie im Cache
2. Der `StoryProcessor` greift auf die Topic-Konfiguration in MongoDB zu
3. Basierend auf der Konfiguration werden relevante Sessions aus dem Cache gefiltert
4. Die ausgewählten Sessions werden zu einer thematischen Geschichte zusammengeführt
5. Die Geschichte wird über ein Template transformiert und im vorgegebenen Verzeichnisformat gespeichert

## Ausgabestruktur

Die Ausgabe wird in einer klar definierten Verzeichnisstruktur organisiert:

```
stories/
├── [event]_[target_group]/
│   ├── eventstory_[language].md
│   ├── [topic1]/
│   │   ├── [topic1]_[language].md
│   │   └── [session1]/ (Link zum existierenden Session-Ordner)
│   │       ├── assets/
│   │       └── session1_[language].md
│   └── [topic2]/
│       ├── [topic2]_[language].md
│       └── [session2]/
│           └── ...
└── [event]_[another_target_group]/
    └── ...
```

Diese Struktur ermöglicht eine klare Organisation und einfache Navigation in Obsidian:
- Events
- Zielgruppen
- Themen
- Sprachen
- Verknüpfungen zu den zugehörigen Sessions

## Dataclass-Struktur

### Eingabedaten

```python
@dataclass
class StoryProcessorInput:
    """Eingabedaten für den StoryProcessor."""
    event: str
    topic_id: str
    target_group: str = "general"
    languages: List[str] = field(default_factory=lambda: ["de"])
    session_ids: Optional[List[str]] = None  # Optional, wenn aus MongoDB abgerufen werden soll
    detail_level: int = 3  # 1-5, wobei 5 der detaillierteste ist
    
    def __post_init__(self):
        """Validiert die Eingabedaten."""
        if not self.event:
            raise ValueError("event darf nicht leer sein")
        if not self.topic_id:
            raise ValueError("topic_id darf nicht leer sein")
        if not self.languages:
            raise ValueError("mindestens eine Sprache muss angegeben werden")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Eingabedaten in ein Dictionary."""
        return {
            "event": self.event,
            "topic_id": self.topic_id,
            "target_group": self.target_group,
            "languages": self.languages,
            "session_ids": self.session_ids,
            "detail_level": self.detail_level
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryProcessorInput':
        """Erstellt StoryProcessorInput aus einem Dictionary."""
        return cls(
            event=data.get("event", ""),
            topic_id=data.get("topic_id", ""),
            target_group=data.get("target_group", "general"),
            languages=data.get("languages", ["de"]),
            session_ids=data.get("session_ids"),
            detail_level=data.get("detail_level", 3)
        )
```

### Ausgabedaten

```python
@dataclass
class StoryProcessorOutput:
    """Ausgabedaten des StoryProcessors."""
    topic_id: str
    event: str
    target_group: str
    markdown_files: Dict[str, str]  # Sprache -> Dateipfad
    markdown_contents: Dict[str, str]  # Sprache -> Inhalt
    session_count: int
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Ausgabedaten in ein Dictionary."""
        return {
            "topic_id": self.topic_id,
            "event": self.event,
            "target_group": self.target_group,
            "markdown_files": self.markdown_files,
            "markdown_contents": self.markdown_contents,
            "session_count": self.session_count,
            "metadata": self.metadata
        }
```

### Verarbeitungsdaten

```python
@dataclass
class StoryData:
    """Daten für die Story-Verarbeitung."""
    input: StoryProcessorInput
    output: StoryProcessorOutput
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Verarbeitungsdaten in ein Dictionary."""
        return {
            "input": self.input.to_dict(),
            "output": self.output.to_dict()
        }
```

### Response

```python
@dataclass(frozen=True)
class StoryResponse(BaseResponse):
    """Antwort des StoryProcessors."""
    data: Optional[StoryData] = None
```

### Verarbeitungsergebnis für Cache

```python
class StoryProcessingResult:
    """
    Ergebnisstruktur für die Story-Verarbeitung.
    Wird für Caching verwendet.
    """
    
    def __init__(
        self,
        topic_id: str,
        event: str,
        target_group: str,
        session_ids: List[str],
        markdown_files: Dict[str, str],
        markdown_contents: Dict[str, str],
        metadata: Dict[str, Any],
        process_id: Optional[str] = None,
        input_data: Optional[StoryProcessorInput] = None
    ):
        self.topic_id = topic_id
        self.event = event
        self.target_group = target_group
        self.session_ids = session_ids
        self.markdown_files = markdown_files
        self.markdown_contents = markdown_contents
        self.metadata = metadata
        self.process_id = process_id
        self.input_data = input_data
        
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        return ProcessingStatus.SUCCESS if self.markdown_contents else ProcessingStatus.ERROR
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "topic_id": self.topic_id,
            "event": self.event,
            "target_group": self.target_group,
            "session_ids": self.session_ids,
            "markdown_files": self.markdown_files,
            "markdown_contents": self.markdown_contents,
            "metadata": self.metadata,
            "process_id": self.process_id,
            "input_data": self.input_data.to_dict() if self.input_data else {}
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StoryProcessingResult':
        """Erstellt ein StoryProcessingResult aus einem Dictionary."""
        return cls(
            topic_id=data.get("topic_id", ""),
            event=data.get("event", ""),
            target_group=data.get("target_group", ""),
            session_ids=data.get("session_ids", []),
            markdown_files=data.get("markdown_files", {}),
            markdown_contents=data.get("markdown_contents", {}),
            metadata=data.get("metadata", {}),
            process_id=data.get("process_id"),
            input_data=StoryProcessorInput.from_dict(data.get("input_data", {}))
        )
```

## MongoDB-Schemas

### topics_collection

```javascript
{
  topic_id: { type: String, required: true, unique: true },
  display_name: {
    de: { type: String, required: true },
    en: { type: String, required: true }
  },
  description: {
    de: { type: String },
    en: { type: String }
  },
  target_groups: [{ type: String }],
  primary_target_group: { type: String },
  template: { type: String }, // Direkter Verweis auf ein Template im templates-Ordner
  languages: [{ type: String }],
  primary_language: { type: String },
  relevance_threshold: { type: Number, default: 0.7 },
  keywords: [{ type: String }],
  status: { type: String, enum: ['active', 'inactive'], default: 'active' }
}
```

### target_groups_collection

```javascript
{
  target_id: { type: String, required: true, unique: true },
  display_name: {
    de: { type: String, required: true },
    en: { type: String, required: true }
  },
  description: {
    de: { type: String },
    en: { type: String }
  },
  status: { type: String, enum: ['active', 'inactive'], default: 'active' }
}
```

## Templates

Templates für den `StoryProcessor` liegen direkt im Verzeichnis `templates/` und werden in der Topics-Collection referenziert. Die Template-Verwaltung ist bewusst einfach gehalten: Der Topic-Datensatz enthält einen direkten Verweis auf das zu verwendende Template (z.B. "ecosocial" für die Datei "templates/ecosocial.md").

Die Templates unterstützen folgende Platzhalter:

- `{{topic_id}}`: Die ID des Themas
- `{{topic_display_name}}`: Der anzeigefreundliche Name des Themas in der aktuellen Sprache
- `{{description}}`: Die Beschreibung des Themas in der aktuellen Sprache
- `{{event}}`: Der Name des Events
- `{{target_group}}`: Die ID der Zielgruppe
- `{{session_count}}`: Die Anzahl der verarbeiteten Sessions
- `{{sessions}}`: Eine Liste aller verarbeiteten Sessions
- `{{detail_level}}`: Der Detailgrad (1-5)

## API-Endpunkte

Die folgenden API-Endpunkte werden für den `StoryProcessor` benötigt:

### 1. Topic-Übersicht

```
GET /api/stories/topics
```

Gibt eine Liste aller verfügbaren Themen mit ihren Konfigurationen aus MongoDB zurück.

### 2. Zielgruppen-Übersicht

```
GET /api/stories/target-groups
```

Gibt eine Liste aller verfügbaren Zielgruppen aus MongoDB zurück.

### 3. Sessions nach Thema und Zielgruppe

```
GET /api/stories/sessions?topic={topic_id}&event={event}&target_group={target_group}
```

Gibt alle Sessions für ein bestimmtes Thema, Event und Zielgruppe zurück, sortiert nach Relevanz.

### 4. Story-Verarbeitung

```
POST /api/stories/generate
```

Verarbeitet ein Thema und erzeugt eine thematische Geschichte.

Anfragedaten:
```json
{
    "event": "fosdem_2023",
    "topic_id": "energy_transition",
    "target_group": "ecosocial",
    "languages": ["de", "en"],
    "session_ids": ["session1", "session2", "session3"],
    "detail_level": 3
}
```

## Frontend-Komponente: StoryDashboard

Das StoryDashboard ist eine einfache Verwaltungsoberfläche für die Erstellung thematischer Geschichten:

1. **Event-Auswahl**: Dropdown zur Auswahl eines Events
2. **Zielgruppen-Auswahl**: Dropdown zur Auswahl einer Zielgruppe
3. **Topic-Auswahl**: Dropdown mit verfügbaren Themen für die gewählte Zielgruppe
4. **Sprach-Auswahl**: Mehrfachauswahl der zu generierenden Sprachen
5. **Session-Tabelle**: Einfache Tabelle mit Checkbox für die Auswahl von Sessions
   - Zeigt nur die wichtigsten Informationen an: Titel, Sprecher, Event, Track, Relevanz
   - Einfache Sortierung und Filterung
6. **Generieren-Button**: Startet die Generierung der Story

Die Komponente verzichtet bewusst auf eine integrierte Vorschau, da der Benutzer Obsidian für die Betrachtung der generierten Markdown-Dateien verwendet.

## Implementierungsplan

Die Implementierung des `StoryProcessor` erfolgt in mehreren Phasen:

### Phase A: Grundstruktur und MongoDB (2 Wochen)

1. **MongoDB-Schemas einrichten**
   - Topics-Collection und Indizes definieren
   - Target-Groups-Collection und Indizes definieren
   - Testdaten anlegen

2. **StoryProcessor-Klasse implementieren**
   - Dataclass-Strukturen
   - MongoDB-Anbindung
   - Cache-Mechanismen
   - Grundlegende Verarbeitungslogik

3. **Session-Verarbeitung implementieren**
   - Methoden zur Extraktion relevanter Sessions aus dem Cache
   - Kombinierung von Session-Inhalten

### Phase B: Templates und Story-Generierung (2 Wochen)

1. **Template-Integration**
   - Template-Lademechanismen
   - Platzhalter-Ersetzungslogik
   - Mehrsprachige Ausgabe

2. **Story-Generierung**
   - Aufbau des Transformer-Prompts
   - Markdown-Generierung
   - Speicherung in der definierten Verzeichnisstruktur

3. **Symbolische Links zu Sessions**
   - Integration mit bestehenden Session-Ordnern
   - Korrektes Setzen der Links für Obsidian-Navigation

### Phase C: API und Frontend (2 Wochen)

1. **API-Endpunkte implementieren**
   - GET und POST Methoden
   - Request-Validierung
   - Fehlerbehandlung

2. **StoryDashboard implementieren**
   - Event- und Zielgruppenauswahl
   - Session-Tabelle mit Auswahlmöglichkeit
   - Generierungsfunktion mit Statusanzeige

### Phase D: Tests und Finalisierung (1 Woche)

1. **Tests**
   - Unit-Tests für Kernfunktionen
   - Integrationstests für den vollständigen Workflow

2. **Dokumentation und Feinschliff**
   - Erstellen der Anwenderdokumentation
   - Letzte Optimierungen und Fehlerbehebungen

## Best Practices für die Implementierung

### 1. Einfachheit bevorzugen

- Einfache, direkte Template-Verwaltung über MongoDB-Felder
- Klare, verständliche API-Endpunkte
- Minimalistisches, funktionales Dashboard

### 2. Mehrsprachigkeit

- Konsistente Handhabung von Sprachcodes (ISO 639-1)
- Einfache Unterstützung mehrerer Ausgabesprachen
- Fallback-Mechanismen für fehlende Übersetzungen

### 3. Effizienz

- Optimale Nutzung des Caches für schnelle Verarbeitung
- Asynchrone Verarbeitung für große Datenmengen
- Effiziente MongoDB-Abfragen

### 4. Robustheit

- Gründliche Validierung aller Eingaben
- Fehlertoleranz bei fehlenden oder ungültigen Daten
- Klare Fehlerbehandlung und -meldungen

## Fazit

Der `StoryProcessor` erweitert das bestehende System um eine pragmatische, benutzerfreundliche Lösung für die Erstellung thematischer Geschichten aus vorhandenen Sessions. Die Integration mit MongoDB für die Themenkonfiguration und die Unterstützung mehrerer Zielgruppen und Sprachen bietet eine flexible Grundlage. Die einfache Verwaltung von Templates und die klare Ausgabestruktur machen die Lösung sowohl für Entwickler als auch für Endanwender zugänglich und wartbar.

Die gezielte Implementierung in klar definierten Phasen ermöglicht eine systematische Entwicklung mit früher Funktionalität und kontinuierlicher Verbesserung. 