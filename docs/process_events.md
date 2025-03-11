# EventProcessor: Verarbeitung von Events

Der `EventProcessor` ist eine zentrale Komponente zur Verarbeitung von Event-Informationen und zugehörigen Medien. Diese Dokumentation erklärt die Funktionsweise der beiden Hauptmethoden `process_event` und `process_many_events` sowie die zugrundeliegende Architektur.

## Inhaltsverzeichnis

1. [Überblick](#überblick)
2. [Architektur](#architektur)
3. [process_event](#process_event)
4. [process_many_events](#process_many_events)
5. [Asynchrone Verarbeitung](#asynchrone-verarbeitung)
6. [Caching](#caching)
7. [Anwendungsfall: Mehrsprachige Verarbeitung](#anwendungsfall-mehrsprachige-verarbeitung)
8. [Implementierungsplan für MongoDB-Caching](#implementierungsplan-für-mongodb-caching)
9. [Logging](#logging)
10. [MongoDB-Integration](#mongodb-integration)
11. [Performance-Tracking](#performance-tracking)

## Überblick

Der `EventProcessor` verarbeitet Event-Informationen und zugehörige Medien (Videos, Anhänge) und generiert strukturierte Markdown-Dateien. Die Hauptfunktionalitäten umfassen:

- Extraktion von Event-Informationen von Webseiten
- Verarbeitung von Videos und Extraktion von Transkriptionen
- Verarbeitung von PDF-Anhängen und Extraktion von Vorschaubildern
- Generierung von Markdown-Dateien mit allen Informationen
- Asynchrone Verarbeitung mit Webhook-Callbacks
- Batch-Verarbeitung mehrerer Events
- Mehrsprachige Verarbeitung mit optimiertem Caching

## Architektur

Der `EventProcessor` ist nach dem Prozessor-Pattern aufgebaut und erbt von `BaseProcessor`. Er nutzt verschiedene Subprozessoren für spezifische Aufgaben:

- `VideoProcessor`: Verarbeitet Videos und extrahiert Transkriptionen
- `TransformerProcessor`: Transformiert Texte und generiert Markdown
- `PDFProcessor`: Verarbeitet PDF-Dateien und extrahiert Vorschaubilder

Die Datenmodellierung erfolgt über typisierte Dataclasses:
- `EventInput`: Eingabeparameter für die Event-Verarbeitung
- `EventOutput`: Ausgabedaten der Event-Verarbeitung
- `EventData`: Kombiniert Input und Output
- `EventResponse`: Standardisierte API-Antwort

### Verbesserte Prozessor-Architektur

Der neue Ansatz verwendet eine verteilte Caching-Verantwortung, bei der jeder Prozessor für sein eigenes Caching zuständig ist:

```
┌─────────────────────────────────────────────────────┐
│                   EventProcessor                     │
│            (Koordination & Orchestrierung)           │
└───────────┬────────────┬────────────┬───────────────┘
            │            │            │
┌───────────▼─┐  ┌───────▼────┐  ┌────▼─────┐  ┌───────▼───────┐
│ Video-      │  │ Audio-     │  │ PDF-     │  │ Transformer-  │
│ Processor   │  │ Processor  │  │ Processor│  │ Processor     │
└───────┬─────┘  └─────┬──────┘  └────┬─────┘  └───────┬───────┘
        │              │              │                │
┌───────▼─────┐  ┌─────▼──────┐  ┌────▼─────┐  ┌───────▼───────┐
│ video_cache │  │ audio_cache│  │ pdf_cache│  │transformer_cache│
└─────────────┘  └────────────┘  └──────────┘  └───────────────┘
                     MongoDB
```

## process_event

Die Methode `process_event` verarbeitet ein einzelnes Event mit allen zugehörigen Medien.

### Signatur

```python
async def process_event(
    self,
    event: str,
    session: str,
    url: str,
    filename: str,
    track: str,
    day: Optional[str] = None,
    starttime: Optional[str] = None,
    endtime: Optional[str] = None,
    speakers: Optional[List[str]] = None,
    video_url: Optional[str] = None,
    attachments_url: Optional[str] = None,
    language: str = "en",  # Geändert: Ein einziger Sprachparameter statt source_language und target_language
    use_cache: bool = True
) -> EventResponse:
```

### Parameter

- `event`: Name der Veranstaltung
- `session`: Name der Session
- `url`: URL zur Event-Seite
- `filename`: Zieldateiname für die Markdown-Datei
- `track`: Track/Kategorie der Session
- `day`: Veranstaltungstag im Format YYYY-MM-DD (optional)
- `starttime`: Startzeit im Format HH:MM (optional)
- `endtime`: Endzeit im Format HH:MM (optional)
- `speakers`: Liste der Vortragenden (optional)
- `video_url`: URL zum Video (optional)
- `attachments_url`: URL zu Anhängen (optional)
- `language`: Zielsprache für das Markdown (Standard: "en")
- `use_cache`: Ob die Ergebnisse zwischengespeichert werden sollen (Standard: True)

### Ablauf

1. **Validierung der Eingabeparameter**:
   - Konvertierung in `EventInput`-Dataclass
   - Initialisierung des LLM-Trackings

2. **Verzeichnisstruktur erstellen**:
   - Zielverzeichnis: `events/[event]/[track]/[session_dir]`

3. **Event-Seite abrufen**:
   - Abrufen der HTML-Seite mit `_fetch_event_page`
   - Extraktion des Textes mit BeautifulSoup

4. **Video verarbeiten** (falls vorhanden):
   - Aufruf des `VideoProcessor` zur Transkription
   - **Optimierung**: Caching basiert nur auf der Video-URL, nicht auf der Sprache
   - Transkription erfolgt immer in der Originalsprache des Videos
   - Video-Prozessor ist für sein eigenes Caching in MongoDB verantwortlich

5. **Anhänge verarbeiten** (falls vorhanden):
   - Aufruf des `PDFProcessor` für Vorschaubilder und Textextraktion
   - **Optimierung**: Caching basiert auf file_path und extraction_method
   - PDF-Prozessor ist für sein eigenes Caching in MongoDB verantwortlich
   - Extraktion der Bilder in ein Assets-Verzeichnis 

6. **Markdown generieren**:
   - Aufruf des `TransformerProcessor` mit Template "Event"
   - **Optimierung**: Sprachabhängiger Prozess, Caching berücksichtigt Quell- und Zielsprache
   - TransformerProcessor ist für sein eigenes Caching in MongoDB verantwortlich
   - Hinzufügen von Links zu Anhängen und Transkription (keine Einbettung)
   - Speichern der Markdown-Datei im Zielverzeichnis

7. **Response erstellen**:
   - Erstellung einer standardisierten `EventResponse`
   - Einbindung von Metadaten und Performance-Informationen

### Rückgabewert

Eine `EventResponse` mit folgender Struktur:
- `status`: Verarbeitungsstatus (success/error)
- `request`: Kontext der Anfrage
- `process`: Verarbeitungsdetails (inkl. LLM-Nutzung)
- `data`: Ergebnisdaten (EventData mit Input/Output)
- `error`: Fehlerinformationen (falls aufgetreten)

## process_many_events

Die Methode `process_many_events` verarbeitet mehrere Events sequentiell.

### Signatur

```python
async def process_many_events(
    self,
    events: List[Dict[str, Any]]
) -> BatchEventResponse:
```

### Parameter

- `events`: Liste von Event-Daten mit denselben Parametern wie `process_event`

### Ablauf

1. **Initialisierung**:
   - Listen für erfolgreiche Outputs und Fehler
   - Tracking der Gesamtverarbeitungszeit

2. **Sequentielle Verarbeitung**:
   - Iteration über alle Events
   - Aufruf von `process_event` für jedes Event
   - **Optimierung**: Jeder Prozessor nutzt sein eigenes Caching, wodurch wiederholte Medienverarbeitung vermieden wird
   - Sammlung erfolgreicher Ergebnisse und Fehler

3. **Batch-Output erstellen**:
   - Erstellung eines `BatchEventOutput` mit Zusammenfassung
   - Kombination aller LLM-Infos

4. **Response erstellen**:
   - Erstellung einer standardisierten `BatchEventResponse`

### Rückgabewert

Eine `BatchEventResponse` mit folgender Struktur:
- `status`: Verarbeitungsstatus (success/error)
- `request`: Kontext der Anfrage
- `process`: Verarbeitungsdetails (inkl. LLM-Nutzung)
- `data`: Ergebnisdaten (BatchEventData mit Input/Output)
- `error`: Fehlerinformationen (falls aufgetreten)

## Asynchrone Verarbeitung

Der `EventProcessor` unterstützt auch asynchrone Verarbeitung mit Webhook-Callbacks:

### process_event_async

```python
async def process_event_async(
    self,
    event: str,
    session: str,
    url: str,
    filename: str,
    track: str,
    webhook_url: str,
    # weitere Parameter wie bei process_event
    webhook_headers: Optional[Dict[str, str]] = None,
    include_markdown: bool = True,
    include_metadata: bool = True,
    event_id: Optional[str] = None,
    language: str = "en",  # Geändert: Ein einziger Sprachparameter
    use_cache: bool = True
) -> EventResponse:
```

Diese Methode startet die Verarbeitung in einem separaten Task und gibt sofort eine Antwort zurück. Nach Abschluss der Verarbeitung wird ein Webhook-Callback an die angegebene URL gesendet.

### process_many_events_async

```python
async def process_many_events_async(
    self,
    events: List[Dict[str, Any]],
    webhook_url: str,
    webhook_headers: Optional[Dict[str, str]] = None,
    include_markdown: bool = True,
    include_metadata: bool = True,
    batch_id: Optional[str] = None
) -> BatchEventResponse:
```

Diese Methode verwendet die MongoDB-basierte Job-Verwaltung für die asynchrone Verarbeitung mehrerer Events. Die Jobs werden in der MongoDB gespeichert und von einem Worker-Manager verarbeitet.

## Caching

Der `EventProcessor` verwendet ein verbessertes, MongoDB-basiertes Caching-System:

### Prozessor-spezifisches Caching

- **VideoProcessor**: Cached Ergebnisse basierend auf der Video-URL
- **AudioProcessor**: Cached Ergebnisse basierend auf der Audio-URL
- **PDFProcessor**: Cached Ergebnisse basierend auf Dateipfad und Extraktionsmethode
- **TransformerProcessor**: Cached Ergebnisse basierend auf Quelltext, Quell-/Zielsprache und Template

### MongoDB Collections

Jeder Prozessor verwaltet seine eigene Cache-Collection:

```
mongodb
├── video_cache
├── audio_cache
├── pdf_cache
├── transformer_cache
└── event_metadata (für Verlinkung und Referenzierung)
```

### Cache-Schlüssel

- **Medien-Prozessoren**: Verwenden nur die URL/Dateipfad als Schlüssel, unabhängig von der Sprache
- **TransformerProcessor**: Verwendet komplexeren Schlüssel mit Quell-/Zielsprache

### Vorteile des neuen Caching-Systems

1. **Effizienz**: Ressourcenintensive Medienverarbeitung erfolgt nur einmal
2. **Mehrsprachigkeit**: Nur sprachabhängige Komponenten werden pro Sprache neu generiert
3. **Flexibilität**: Jeder Prozessor kann seinen Cache unabhängig verwalten
4. **Skalierbarkeit**: MongoDB bietet bessere Skalierbarkeit als Dateisystem-basiertes Caching

## Anwendungsfall: Mehrsprachige Verarbeitung

Ein häufiger Anwendungsfall ist die Erstellung von Markdown-Dateien für ein Event in verschiedenen Sprachen. Das optimierte Caching-System erleichtert diesen Prozess erheblich.

### Mehrfache Aufrufe mit verschiedenen Zielsprachen

```python
# Erstellen der englischen Version
response_en = await event_processor.process_event(
    event="Conference 2023",
    session="AI Keynote",
    url="https://example.com/conference/ai-keynote",
    filename="ai-keynote.md",
    track="AI Track",
    video_url="https://example.com/videos/ai-keynote.mp4",
    attachments_url="https://example.com/slides/ai-keynote.pdf",
    language="en",
    use_cache=True
)

# Erstellen der deutschen Version
response_de = await event_processor.process_event(
    event="Conference 2023",
    session="AI Keynote",
    url="https://example.com/conference/ai-keynote",
    filename="ai-keynote.md",  # wird automatisch zu ai-keynote_de.md
    track="AI Track",
    video_url="https://example.com/videos/ai-keynote.mp4",
    attachments_url="https://example.com/slides/ai-keynote.pdf",
    language="de",
    use_cache=True
)

# Erstellen der französischen Version
response_fr = await event_processor.process_event(
    event="Conference 2023",
    session="AI Keynote",
    url="https://example.com/conference/ai-keynote",
    filename="ai-keynote.md",  # wird automatisch zu ai-keynote_fr.md
    track="AI Track",
    video_url="https://example.com/videos/ai-keynote.mp4",
    attachments_url="https://example.com/slides/ai-keynote.pdf",
    language="fr",
    use_cache=True
)
```

### Ablauf der mehrsprachigen Verarbeitung

#### Erster Aufruf (Englisch)

1. **Alle Prozessoren führen vollständige Verarbeitung durch:**
   - VideoProcessor verarbeitet das Video und extrahiert die Transkription
   - PDFProcessor verarbeitet das PDF und extrahiert Vorschaubilder
   - TransformerProcessor generiert englisches Markdown

2. **Caching in MongoDB:**
   - `video_cache`: Speichert Transkription mit Schlüssel basierend auf `video_url`
   - `pdf_cache`: Speichert Extrakte mit Schlüssel basierend auf `file_path` und `extraction_method`
   - `transformer_cache`: Speichert Template mit Schlüssel basierend auf `source_text`, `en`, `en` und `template`

3. **Dateisystem:**
   - Markdown-Datei: `events/Conference 2023/AI Track/ai-keynote/ai-keynote.md`
   - Assets-Verzeichnis: `events/Conference 2023/AI Track/ai-keynote/assets/`

#### Zweiter Aufruf (Deutsch)

1. **Selektive Verarbeitung:**
   - VideoProcessor: Verwendet gecachte Transkription (keine Neuverarbeitung)
   - PDFProcessor: Verwendet gecachte Extrakte (keine Neuverarbeitung)
   - TransformerProcessor: Führt neue Verarbeitung mit `target_language="de"` durch

2. **Caching in MongoDB:**
   - Neuer Eintrag nur in `transformer_cache` mit Schlüssel basierend auf `source_text`, `en`, `de` und `template`

3. **Dateisystem:**
   - Neue Markdown-Datei: `events/Conference 2023/AI Track/ai-keynote/ai-keynote_de.md`
   - Wiederverwendung des Assets-Verzeichnisses

#### Dritter Aufruf (Französisch)

1. **Selektive Verarbeitung:**
   - VideoProcessor: Verwendet gecachte Transkription (keine Neuverarbeitung)
   - PDFProcessor: Verwendet gecachte Extrakte (keine Neuverarbeitung)
   - TransformerProcessor: Führt neue Verarbeitung mit `target_language="fr"` durch

2. **Caching in MongoDB:**
   - Neuer Eintrag nur in `transformer_cache` mit Schlüssel basierend auf `source_text`, `en`, `fr` und `template`

3. **Dateisystem:**
   - Neue Markdown-Datei: `events/Conference 2023/AI Track/ai-keynote/ai-keynote_fr.md`
   - Wiederverwendung des Assets-Verzeichnisses

### Speicherstruktur

#### Dateisystem

Die verschiedenen Sprachversionen werden organisiert als:

```
events/
└── Conference 2023/
    └── AI Track/
        └── ai-keynote/
            ├── ai-keynote.md      # Englische Version (Standardsprache)
            ├── ai-keynote_de.md   # Deutsche Version
            ├── ai-keynote_fr.md   # Französische Version
            └── assets/            # Gemeinsam genutzte Assets für alle Sprachversionen
                ├── slide01.png
                ├── slide02.png
                └── ...
```

#### MongoDB

Die Cache-Einträge in MongoDB:

```
video_cache:
{
  "cache_key": "VideoProcessor:abc123",
  "source_url": "https://example.com/videos/ai-keynote.mp4",
  "response": {...}  # Enthält Transkription in Originalsprache
}

pdf_cache:
{
  "cache_key": "PDFProcessor:def456",
  "file_path": "https://example.com/slides/ai-keynote.pdf",
  "extraction_method": "preview",
  "response": {...}  # Enthält Vorschaubilder
}

transformer_cache:
[
  {
    "cache_key": "TransformerProcessor:ghi789",
    "template": "Event",
    "source_language": "en",
    "target_language": "en",
    "response": {...}  # Enthält englisches Markdown
  },
  {
    "cache_key": "TransformerProcessor:jkl012",
    "template": "Event",
    "source_language": "en",
    "target_language": "de",
    "response": {...}  # Enthält deutsches Markdown
  },
  {
    "cache_key": "TransformerProcessor:mno345",
    "template": "Event",
    "source_language": "en",
    "target_language": "fr",
    "response": {...}  # Enthält französisches Markdown
  }
]
```

### Performance-Vorteile

Bei diesem Ansatz werden die zeitaufwändigen Schritte (Video- und PDF-Verarbeitung) nur einmal ausgeführt, unabhängig von der Anzahl der gewünschten Sprachen. Für jede weitere Sprache wird nur der relativ schnelle Transformationsschritt durchgeführt.

Bei einem typischen Event mit:
- 60-minütigem Video (Transkription: ~5 Minuten)
- PDF-Präsentation (Verarbeitung: ~2 Minuten)
- Markdown-Generierung (pro Sprache: ~10 Sekunden)

Ergibt sich folgende Zeitersparnis:
- Erste Sprache: 7:10 Minuten
- Jede weitere Sprache: 10 Sekunden (statt 7:10 Minuten)

Bei 10 Sprachen wird die Gesamtverarbeitungszeit von 71:40 Minuten auf 8:30 Minuten reduziert - eine Einsparung von 88%.

## Implementierungsplan für MongoDB-Caching

Die Implementierung des MongoDB-basierten Caching-Systems erfolgt in mehreren strukturierten Phasen, um einen reibungslosen Übergang vom filebasierten zum datenbankbasierten Caching zu gewährleisten.

### Phase 1: Infrastruktur und Basisklassen

1. **Einrichtung der MongoDB-Collections**
   - Erstellung der Collections `video_cache`, `audio_cache`, `pdf_cache`, `transformer_cache`
   - Implementierung optimierter Indizes für effiziente Abfragen
   ```python
   async def setup_mongodb_caching():
       db = get_mongodb_database()
       # Indizes erstellen für alle Cache-Collections
       await db.video_cache.create_index([("cache_key", 1)], unique=True)
       await db.video_cache.create_index([("source_url", 1)])
       # [...weitere Indizes...]
   ```

2. **Implementierung der `CacheableProcessor`-Basisklasse**
   - Entwicklung einer gemeinsamen Basisklasse für alle Prozessoren mit Caching-Funktionalität
   - Standardisierung der Cache-Schlüssel-Generierung
   ```python
   class CacheableProcessor(BaseProcessor):
       def __init__(self, resource_calculator: Any, process_id: Optional[str] = None):
           super().__init__(resource_calculator, process_id)
           self.cache_collection_name = f"{self.__class__.__name__.lower()}_cache"
           
       async def _generate_cache_key(self, *args, **kwargs) -> str:
           # Prozessorspezifische Cache-Schlüssel-Generierung
           # ...
   ```

### Phase 2: Prozessorspezifische Implementierungen

3. **Anpassung des VideoProcessors**
   - Integration der Caching-Funktionalität in die `process`-Methode
   - Spezialisierte Behandlung von Video-URLs als Cache-Schlüssel
   - Entfernung der Sprachabhängigkeit vom Caching

4. **Anpassung des AudioProcessors**
   - Analog zum VideoProcessor mit Fokus auf Audio-spezifische Metadaten
   - Effizienter Umgang mit Transkriptionen

5. **Anpassung des PDFProcessors**
   - Spezielle Behandlung von Binärdaten für Vorschaubilder
   - Integration von GridFS für große Dateien
   - Optimierung der Extraktion und des Cachings von Metadaten

6. **Anpassung des TransformerProcessors**
   - Sprachabhängiges Caching für unterschiedliche Zielsprachen
   - Effiziente Speicherung und Abruf von generierten Templates

### Phase 3: EventProcessor-Integration

7. **Anpassung der API-Schnittstelle**
   - Übergang von getrennten `source_language` und `target_language` Parametern zu einem einzigen `language`-Parameter
   - Optimierung der Dateinamen-Generierung für mehrsprachige Dateien

8. **Implementierung sprachbasierter Logik**
   - Anpassung des Markdown-Generators für Verlinkung statt Einbettung
   - Intelligente Wiederverwendung von Assets zwischen Sprachversionen

### Phase 4: Testing und Validierung

9. **Unit-Tests**
   - Entwicklung spezifischer Tests für jede Prozessorklasse
   - Validierung der Cache-Schlüssel und Cache-Trefferquoten

10. **Integrationstests**
    - End-to-End-Tests mit verschiedenen Sprachen
    - Performance-Vergleiche zwischen altem und neuem System

11. **Last- und Belastungstests**
    - Überprüfung der MongoDB-Skalierbarkeit
    - Optimierung der Indizes basierend auf realen Lastszenarien

### Phase 5: Überwachung und Wartung

12. **Cache-Management-Tools**
    - Entwicklung von Werkzeugen zur Cache-Verwaltung
    - Implementierung von TTL-Indexen für automatische Cache-Bereinigung

13. **Monitoring**
    - Dashboard für Cache-Statistiken
    - Automatische Benachrichtigungen bei Cache-Problemen

14. **Cache-Hygiene**
    - Regelmäßige Bereinigung alter oder selten verwendeter Cache-Einträge
    - Optimierung des Speicherbedarfs

### Migrations- und Rollout-Strategie

15. **Parallelbetrieb**
    - Gleichzeitiger Betrieb des alten und neuen Caching-Systems
    - Schrittweise Aktivierung pro Prozessortyp

16. **Feature-Flag-Steuerung**
    - Konfigurierbare Aktivierung des MongoDB-Cachings 
    - A/B-Testing zur Validierung der Performance-Gewinne

17. **Vollständige Umstellung**
    - Deaktivierung des filebasierten Cachings nach erfolgreicher Validierung
    - Dokumentation der neuen Implementierung

## Logging

Der `EventProcessor` verwendet strukturiertes Logging mit verschiedenen Ebenen:

- `info`: Allgemeine Informationen zum Verarbeitungsablauf
- `debug`: Detaillierte Informationen für die Fehlersuche
- `error`: Fehler und Ausnahmen
- `warning`: Warnungen bei nicht kritischen Problemen

Besonders bei der asynchronen Verarbeitung wird ausführliches Logging verwendet, um den Ablauf nachvollziehen zu können.

## MongoDB-Integration

Der `EventProcessor` nutzt MongoDB für zwei Hauptzwecke:

### 1. Asynchrone Job-Verwaltung

- `EventJobRepository`: Verwaltet Jobs und Batches in der MongoDB
- `Job`: Dataclass für einen einzelnen Verarbeitungsjob
- `Batch`: Dataclass für einen Batch von Jobs
- `JobStatus`: Enum für den Status eines Jobs (pending, processing, completed, failed)

### 2. Prozessor-spezifisches Caching

- Jeder Prozessor (Video, Audio, PDF, Transformer) verwaltet seine eigene Cache-Collection
- Standardisierte Indizes für effiziente Abfragen:
  ```js
  db.collection.createIndex({ "cache_key": 1 }, { unique: true })
  db.collection.createIndex({ "processed_at": 1 })
  ```
- Spezifische Indizes je nach Prozessortyp, z.B.:
  ```js
  db.video_cache.createIndex({ "source_url": 1 })
  db.transformer_cache.createIndex({ "template": 1, "source_language": 1, "target_language": 1 })
  ```

## Performance-Tracking

Der `EventProcessor` verwendet einen Performance-Tracker, um die Verarbeitungszeit verschiedener Operationen zu messen:

- `measure_operation`: Misst die Zeit für eine Operation
- `set_event_metadata`: Setzt Metadaten für das Event-Monitoring

Die Performance-Daten werden in der Response zurückgegeben und können für Monitoring und Optimierung verwendet werden.

### Cache-Statistiken

Zusätzlich werden Cache-Statistiken erfasst:
- Cache-Hits und -Misses
- Speicherverbrauch pro Cache-Collection
- Durchschnittliche Zugriffsrate 