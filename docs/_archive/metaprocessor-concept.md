# MetadataProcessor Konzept

## Übersicht

Der MetadataProcessor ist eine zentrale Komponente für die Extraktion und Verarbeitung von Metadaten aus verschiedenen Medientypen. Er unterstützt sowohl technische als auch inhaltliche Metadaten und bietet eine flexible Schnittstelle für verschiedene Eingabeformate.

## Hauptkomponenten

### 1. TechnicalMetadata
- Extrahiert technische Eigenschaften aus Mediendateien
- Unterstützt verschiedene Eingabeformate (bytes, file-like objects, Pfade)
- Erkennt automatisch MIME-Types und Dateiformate
- Spezifische Extraktion für:
  - Audio/Video (Dauer, Bitrate, Kanäle)
  - Bilder (Dimensionen, Farbraum)
  - PDFs (Seitenanzahl, Verschlüsselung)

### 2. ContentMetadata
- Analysiert inhaltliche Aspekte mittels LLM
- Verwendet Template-basierte Transformation
- Extrahiert strukturierte Metadaten wie:
  - Bibliographische Daten
  - Räumliche/zeitliche Einordnung
  - Plattform-spezifische Details
  - Event-Informationen
  - Social Media Metriken

### 3. CompleteMetadata
- Kombiniert technische und inhaltliche Metadaten
- Bietet ganzheitliche Sicht auf Medienobjekte

## Implementierungsdetails

### Methoden

1. `extract_technical_metadata`
```python
async def extract_technical_metadata(
    binary_data: Union[bytes, BinaryIO, Path],
    mime_type: str = None,
    file_extension: str = None,
    logger: ProcessingLogger = None
) -> TechnicalMetadata
```
- Verarbeitet verschiedene Eingabeformate
- Erstellt temporäre Dateien bei Bedarf
- Extrahiert formatspezifische Details
- Bereinigt temporäre Ressourcen

2. `extract_content_metadata`
```python
async def extract_content_metadata(
    content: str,
    context: Dict[str, Any] = None,
    logger: ProcessingLogger = None
) -> ContentMetadata
```
- Nutzt LLM für Inhaltsanalyse
- Verarbeitet Kontext-Informationen
- Verwendet Template-System
- Validiert Ausgabe gegen ContentMetadata-Schema

3. `extract_metadata`
```python
async def extract_metadata(
    binary_data: Union[bytes, BinaryIO, Path],
    content: str = None,
    context: Dict[str, Any] = None,
    logger: ProcessingLogger = None
) -> CompleteMetadata
```
- Kombiniert technische und inhaltliche Analyse
- Erweitert Kontext mit technischen Metadaten
- Liefert vollständiges Metadaten-Objekt

## Anwendungsbeispiele

### 1. YouTube-Prozessor Integration

```python
# Im YouTubeProcessor
async def process(self, url: str, ...) -> YoutubeProcessingResult:
    # Video-Informationen abrufen
    info = await self._get_video_info(url)
    
    # Technische Metadaten aus Audio-Datei
    technical_metadata = await self.metadata_processor.extract_technical_metadata(
        binary_data=audio_path,
        mime_type='audio/mp3'
    )
    
    # Inhaltliche Metadaten aus Video-Beschreibung und Kontext
    content_metadata = await self.metadata_processor.extract_content_metadata(
        content=info.get('description', ''),
        context={
            'type': 'youtube',
            'platform_data': {
                'title': info.get('title'),
                'uploader': info.get('uploader'),
                'view_count': info.get('view_count'),
                'tags': info.get('tags', [])
            },
            'transcription': transcription_result.text,
            'transcription_confidence': transcription_result.confidence
        }
    )
    
    # Kombinierte Metadaten
    complete_metadata = CompleteMetadata(
        technical=technical_metadata,
        content=content_metadata
    )
```

### 2. Audio-Prozessor Integration

```python
# Im AudioProcessor
async def process(self, audio_source: Union[str, Path, bytes], ...) -> AudioProcessingResult:
    # Technische Metadaten extrahieren
    technical_metadata = await self.metadata_processor.extract_technical_metadata(
        binary_data=audio_source
    )
    
    # Audio verarbeiten und transkribieren
    transcription_result = await self.transcribe(audio_source)
    
    # Inhaltliche Metadaten aus Transkription
    content_metadata = await self.metadata_processor.extract_content_metadata(
        content=transcription_result.text,
        context={
            'type': 'audio',
            'file_info': technical_metadata.dict(),
            'transcription': transcription_result.text,
            'transcription_confidence': transcription_result.confidence
        }
    )
    
    # Ergebnis zusammenstellen
    return AudioProcessingResult(
        metadata=CompleteMetadata(
            technical=technical_metadata,
            content=content_metadata
        ),
        transcription=transcription_result
    )
```

## Vorteile

1. **Modularität**
   - Klare Trennung zwischen technischen und inhaltlichen Metadaten
   - Wiederverwendbare Komponenten für verschiedene Prozessoren

2. **Flexibilität**
   - Unterstützung verschiedener Eingabeformate
   - Erweiterbare Metadaten-Schemata
   - Anpassbare LLM-Templates

3. **Robustheit**
   - Fehlerbehandlung für verschiedene Medientypen
   - Ressourcen-Management (temporäre Dateien)
   - Validierung der Ausgaben

4. **Integration**
   - Nahtlose Einbindung in bestehende Prozessoren
   - Konsistente Logging-Unterstützung
   - Asynchrone Verarbeitung

## Nächste Schritte

1. **Implementierung in Prozessoren**
   - Integration in YouTubeProcessor
   - Integration in AudioProcessor
   - Anpassung der Rückgabetypen

2. **Template-Optimierung**
   - Entwicklung spezifischer Templates für verschiedene Medientypen
   - Verfeinerung der LLM-Prompts

3. **Erweiterungen**
   - Unterstützung weiterer Medienformate
   - Caching-Mechanismen für Metadaten
   - Batch-Verarbeitung 