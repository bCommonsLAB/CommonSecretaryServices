# Video-Transkript Parameter

## Überblick

Ab sofort kann ein bereits vorhandenes Video-Transkript direkt an die Session-Verarbeitung übergeben werden. Dies ermöglicht es, die zeitintensive Video-Verarbeitung zu überspringen, wenn das Transkript bereits aus einer vorherigen Verarbeitung vorliegt.

## Neuer Parameter

### `video_transcript` (optional)

- **Typ**: String
- **Beschreibung**: Vorhandenes Video-Transkript (überspringt Video-Verarbeitung wenn gesetzt)
- **Verhalten**: 
  - Wenn `video_transcript` gesetzt ist, wird dieser Text direkt verwendet
  - Die Video-URL (`video_url`) wird in diesem Fall ignoriert
  - Die Video-Verarbeitung wird komplett übersprungen
  - Das Transkript fließt wie gewohnt in die Markdown-Generierung ein

## Verwendung

### Szenario 1: Ohne Transkript (bisheriges Verhalten)

```bash
curl -X POST http://localhost:5000/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "FOSDEM 2025",
    "session": "Welcome Talk",
    "url": "https://fosdem.org/2025/schedule/event/welcome/",
    "filename": "welcome.md",
    "track": "keynotes",
    "video_url": "https://video.fosdem.org/2025/welcome.webm",
    "source_language": "en",
    "target_language": "de"
  }'
```

**Ergebnis**: Video wird verarbeitet, Transkript extrahiert (dauert mehrere Minuten)

### Szenario 2: Mit vorhandenem Transkript (NEU)

```bash
curl -X POST http://localhost:5000/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "FOSDEM 2025",
    "session": "Welcome Talk",
    "url": "https://fosdem.org/2025/schedule/event/welcome/",
    "filename": "welcome.md",
    "track": "keynotes",
    "video_transcript": "Hello everyone, welcome to FOSDEM 2025. Today we have an exciting program...",
    "source_language": "en",
    "target_language": "de"
  }'
```

**Ergebnis**: Video-Verarbeitung wird übersprungen, vorhandenes Transkript wird direkt verwendet (schnell)

### Szenario 3: Beide Parameter gesetzt

```bash
curl -X POST http://localhost:5000/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "FOSDEM 2025",
    "session": "Welcome Talk",
    "url": "https://fosdem.org/2025/schedule/event/welcome/",
    "filename": "welcome.md",
    "track": "keynotes",
    "video_url": "https://video.fosdem.org/2025/welcome.webm",
    "video_transcript": "Hello everyone, welcome to FOSDEM 2025...",
    "source_language": "en",
    "target_language": "de"
  }'
```

**Ergebnis**: `video_transcript` hat Vorrang, Video-URL wird ignoriert

## Anwendungsfälle

### 1. Wiederverarbeitung mit verschiedenen Templates
Wenn eine Session bereits verarbeitet wurde und das Transkript vorliegt, kann die Session mit einem anderen Template neu verarbeitet werden, ohne erneut das Video zu transkribieren.

### 2. Manuelle Transkript-Korrektur
Das automatisch generierte Transkript kann manuell korrigiert und dann zur Verarbeitung verwendet werden.

### 3. Batch-Verarbeitung mit vorverarbeiteten Videos
Videos können in einem separaten Schritt transkribiert werden, die Transkripte zwischengespeichert und dann effizient in Batch-Verarbeitung genutzt werden.

## Cache-Verhalten

Der Cache-Key berücksichtigt das Video-Transkript:
- Wenn `video_transcript` gesetzt ist, wird ein Hash des Transkripts im Cache-Key verwendet
- Unterschiedliche Transkripte führen zu unterschiedlichen Cache-Einträgen
- Dies verhindert falsche Cache-Hits bei unterschiedlichen Transkript-Versionen

## Rückwärtskompatibilität

Die Änderung ist vollständig rückwärtskompatibel:
- Bestehende API-Aufrufe funktionieren unverändert
- Der Parameter `video_transcript` ist optional
- Wenn nicht gesetzt, verhält sich die API wie bisher

## Implementierungsdetails

### Geänderte Dateien
1. `src/api/routes/session_routes.py` - API Input Model erweitert
2. `src/core/models/session.py` - SessionInput Dataclass erweitert
3. `src/processors/session_processor.py` - Prozessor-Logik angepasst

### Logik im SessionProcessor

```python
# 2. Video verarbeiten falls vorhanden, oder vorhandenes Transkript verwenden
video_transcript_text = ""
if video_transcript:
    # Verwende das bereits vorhandene Transkript
    video_transcript_text = video_transcript
    self.logger.info("Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)")
elif video_url:
    # Verarbeite die Video-URL wie bisher
    video_transcript_text = await self._process_video(
        video_url=video_url,
        source_language=source_language,
        target_language=source_language,
        use_cache=use_cache
    )
```

## Performance-Vorteile

- **Zeitersparnis**: Video-Verarbeitung dauert typischerweise 2-5 Minuten pro Video
- **Ressourcen**: Keine Video-Downloads, keine Transkriptions-API-Aufrufe
- **Cache-Effizienz**: Vorverarbeitete Transkripte können mehrfach verwendet werden

## Beispiel: Workflow mit separater Video-Verarbeitung

```python
# Schritt 1: Video separat verarbeiten (einmalig)
video_response = await video_processor.process_video(
    video_url="https://video.fosdem.org/2025/welcome.webm",
    source_language="en"
)
transcript = video_response.data.transcript

# Schritt 2: Session mit verschiedenen Templates verarbeiten (mehrfach, schnell)
for language in ["de", "fr", "es", "it"]:
    session_response = await session_processor.process_session(
        event="FOSDEM 2025",
        session="Welcome Talk",
        url="https://fosdem.org/2025/schedule/event/welcome/",
        filename="welcome.md",
        track="keynotes",
        video_transcript=transcript,  # Wiederverwendung!
        source_language="en",
        target_language=language
    )
```

