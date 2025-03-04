# Cache-Implementierung

Dieses Dokument beschreibt die generische Cache-Implementierung für die verschiedenen Prozessoren im System.

## Überblick

Die Cache-Implementierung ermöglicht es, Verarbeitungsergebnisse verschiedener Prozessoren (Audio, Video, etc.) zu speichern und wiederzuverwenden, um Ressourcen zu sparen und die Verarbeitungszeit zu reduzieren.

Die Hauptkomponenten sind:

1. `ProcessorCache` - Eine generische Klasse, die das Speichern und Laden von Verarbeitungsergebnissen verwaltet
2. Prozessor-spezifische Cache-Implementierungen in den jeweiligen Prozessor-Klassen

## ProcessorCache

Die `ProcessorCache`-Klasse ist eine generische Klasse, die für verschiedene Ergebnistypen verwendet werden kann. Sie bietet folgende Funktionalitäten:

- Speichern von Verarbeitungsergebnissen mit Metadaten und zugehörigen Dateien
- Laden von Verarbeitungsergebnissen basierend auf einem Cache-Schlüssel
- Überprüfen, ob ein gültiger Cache-Eintrag existiert
- Löschen alter Cache-Einträge
- Invalidieren von Cache-Einträgen

### Verwendung

```python
# Initialisierung
cache = ProcessorCache[AudioProcessingResult]("audio")

# Cache-Schlüssel generieren
cache_key = ProcessorCache.generate_simple_key(url_or_filename, file_size)

# Prüfen, ob Cache-Eintrag existiert
if cache.has_cache_with_key(cache_key, required_files=["audio.mp3"]):
    # Cache-Eintrag laden
    result, metadata, files = cache.load_cache_with_key(
        cache_key=cache_key,
        result_class=AudioProcessingResult,
        required_files=["audio.mp3"]
    )
    
    # Cache-Eintrag verwenden
    # ...

# Cache-Eintrag speichern
cache.save_cache_with_key(
    cache_key=cache_key,
    result=result,
    metadata=metadata,
    files={"audio.mp3": audio_file_path}
)

# Alte Cache-Einträge löschen
cache.cleanup_old_cache()

# Cache-Eintrag invalidieren
cache.invalidate_cache(cache_key)
```

## Cache-Schlüssel

Die Cache-Schlüssel werden verwendet, um eindeutige Identifikatoren für Cache-Einträge zu generieren. Die Schlüssel werden basierend auf verschiedenen Parametern generiert:

1. **Basis-Schlüssel**: URL, Dateiname oder Video-ID
2. **Verarbeitungsparameter**: Quellsprache, Zielsprache, Template, etc.

Die `ProcessorCache`-Klasse bietet eine statische Methode `generate_simple_key`, um einfache Schlüssel aus URL oder Dateiname und optional Dateigröße zu generieren:

```python
# Einfachen Schlüssel aus URL generieren
key = ProcessorCache.generate_simple_key("https://example.com/video.mp4")

# Schlüssel aus Dateiname und Größe generieren
key = ProcessorCache.generate_simple_key("video.mp4", file_size=1024)
```

## Prozessor-spezifische Implementierungen

### AudioProcessor

Der `AudioProcessor` verwendet den `ProcessorCache` für Audio-Verarbeitungsergebnisse. Die Cache-Schlüssel werden basierend auf folgenden Parametern generiert:

- Audio-Pfad oder Original-Dateiname oder Video-ID
- Quellsprache
- Zielsprache
- Template (optional)

### VideoProcessor

Der `VideoProcessor` verwendet den `ProcessorCache` für Video-Verarbeitungsergebnisse. Die Cache-Schlüssel werden basierend auf folgenden Parametern generiert:

- Video-URL oder Dateiname
- Quellsprache
- Zielsprache
- Template (optional)

## Cache-Verzeichnisstruktur

Die Cache-Einträge werden in einer hierarchischen Verzeichnisstruktur gespeichert:

```
cache/
  ├── audio/
  │   └── processed/
  │       ├── [cache_key_1]/
  │       │   ├── metadata.json
  │       │   ├── result.json
  │       │   └── audio.mp3
  │       └── [cache_key_2]/
  │           ├── metadata.json
  │           ├── result.json
  │           └── audio.mp3
  └── video/
      └── processed/
          ├── [cache_key_1]/
          │   ├── metadata.json
          │   ├── result.json
          │   └── audio.mp3
          └── [cache_key_2]/
              ├── metadata.json
              ├── result.json
              └── audio.mp3
```

Jeder Cache-Eintrag besteht aus:

- `metadata.json`: Metadaten zum Cache-Eintrag (Erstellungsdatum, Prozessor, etc.)
- `result.json`: Das serialisierte Verarbeitungsergebnis
- Zusätzliche Dateien (z.B. `audio.mp3`): Dateien, die zum Verarbeitungsergebnis gehören

## Cache-Konfiguration

Die Cache-Konfiguration wird aus der Anwendungskonfiguration geladen:

```json
{
  "cache": {
    "base_dir": "./cache",
    "max_age_days": 7
  }
}
```

- `base_dir`: Basis-Verzeichnis für alle Cache-Einträge
- `max_age_days`: Maximales Alter der Cache-Einträge in Tagen, bevor sie automatisch gelöscht werden 