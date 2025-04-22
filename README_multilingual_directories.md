# Mehrsprachige Verzeichnisstruktur für Obsidian

Die Implementierung löst das Problem der mehrsprachigen Verzeichnisstruktur für Obsidian, indem sie:

1. Eine wiederverwendbare Übersetzungsdatenbank erstellt
2. Übersetzungen von Track-, Session- und Dateinamen speichert
3. Die übersetzten Namen für die Verzeichnisstruktur verwendet

## Komponenten

### 1. Datenmodell (`src/core/models/translation.py`)
Eine Dataclass, die Übersetzungen von Begriffen speichert:
- `entity_type` - Typ des zu übersetzenden Elements (track, session, etc.)
- `entity_id` - Eindeutige ID des Elements
- `original_text` - Originaltext
- `original_language` - Quellsprache
- `translations` - Wörterbuch mit Übersetzungen in verschiedene Sprachen

### 2. MongoDB-Repository (`src/core/mongodb/translation_repository.py`)
Verwaltet das Speichern und Abrufen von Übersetzungen:
- `get_translation()` - Holt eine Übersetzung aus der Datenbank
- `save_translation()` - Speichert eine Übersetzung
- `get_or_create_translation()` - Holt oder erstellt eine Übersetzung

### 3. Übersetzer-Service (`src/core/services/translator_service.py`)
Service, der die Übersetzungsfunktionalität bereitstellt:
- `translate_text()` - Übersetzt einen allgemeinen Text
- `translate_entity()` - Übersetzt einen benannten Entity-Text (Track, Session, etc.)
- Singleton-Implementierung über `get_translator_service()`

### 4. Integration im Session-Processor (`src/processors/session_processor.py`)
Anpassung der `process_session`-Methode:
- Übersetzung von Track- und Session-Namen vor der Verzeichniserstellung
- Verwendung der übersetzten Namen für die Zielverzeichnisse
- Erstellung einheitlicher Verzeichnisstrukturen für jede Sprache

## Verzeichnisstruktur

Die implementierte Lösung erzeugt folgende Struktur:

```
event
  > assets
     > Original_Session_Name (als directory)
         assets
  > DE (target language)
     > Übersetzter_Track_Name (track Übersetzung targetlanguage)
         Track_Summary.md (Übersetzung targetlanguage)
         Übersetzter_Session_Name.md (Übersetzung targetlanguage)
  > FR (weitere target languages)
     > Nom_de_piste_traduit (track Übersetzung targetlanguage)
         ...
```

## Verwendung

Bei der Verarbeitung einer Session mit dem Session-Processor werden die Verzeichnis- und Dateinamen automatisch übersetzt und gecacht:

```python
response = await session_processor.process_session(
    event="my_event",
    session="My Session",
    track="Development Track",
    target_language="de",
    # weitere Parameter...
)
```

Die Übersetzungen werden in der MongoDB gespeichert und bei erneuter Verwendung wiederverwendet, um Konsistenz zu gewährleisten. 