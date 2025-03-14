# MongoDB-Caching und Generische Typisierung für Prozessoren

Dieses Dokument beschreibt die Implementierung des MongoDB-Cachings für Prozessoren und die Einführung einer generischen Typisierung zur Verbesserung der Typsicherheit.

## Überblick

Wir haben das Caching-System für die Prozessoren von einer dateibasierten Implementierung zu einer MongoDB-basierten Implementierung migriert und gleichzeitig die Typsicherheit durch generische Typisierung verbessert.

Die Hauptänderungen umfassen:

1. **CacheableProcessor**: Eine neue generische Basisklasse für Prozessoren, die MongoDB-Caching unterstützt
2. **Generische Typisierung**: Einführung von generischen Typen für bessere Typsicherheit und IDE-Unterstützung
3. **Protocol-Definitionen**: Neue Protocol-Klassen für dynamische Attribute zur Verbesserung der Linter-Unterstützung
4. **Optimierte Vererbungshierarchie**: Klare Vererbungsstruktur für Prozessoren

## CacheableProcessor

Die `CacheableProcessor`-Klasse ist eine generische Basisklasse für alle Prozessoren, die Caching unterstützen sollen:

```python
# TypeVar für generischen Rückgabetyp
T = TypeVar('T')  # Ergebnistyp für die verschiedenen Prozessoren

class CacheableProcessor(BaseProcessor, Generic[T]):
    """
    Basisklasse für Prozessoren mit MongoDB-Caching-Unterstützung.
    
    Der generische Typ T repräsentiert das Ergebnisobjekt, das gecached werden soll
    (z.B. AudioProcessingResult, VideoProcessingResult).
    
    Attributes:
        cache_collection_name (str): Name der MongoDB-Collection für Cache-Einträge
        cache_enabled (bool): Flag, ob Caching aktiviert ist
        cache_max_age_days (int): Maximales Alter der Cache-Einträge in Tagen
    """
    
    def generate_cache_key(self, value: str) -> str:
        """Generiert einen eindeutigen Cache-Schlüssel aus einem Wert."""
        return hashlib.sha256(value.encode()).hexdigest()
    
    def is_cache_enabled(self) -> bool:
        """Prüft, ob das Caching aktiviert ist."""
        
    def get_from_cache(self, cache_key: str) -> Tuple[bool, Optional[T]]:
        """Lädt ein Ergebnis aus dem Cache."""
        
    def save_to_cache(self, cache_key: str, result: T) -> bool:
        """Speichert ein Ergebnis im Cache."""
        
    def invalidate_cache(self, cache_key: str) -> None:
        """Löscht einen Cache-Eintrag."""
        
    def cleanup_cache(self, max_age_days: Optional[int] = None) -> Dict[str, int]:
        """Löscht alte Cache-Einträge."""
        
    def serialize_for_cache(self, result: T) -> Dict[str, Any]:
        """Serialisiert das Ergebnis-Objekt für die Speicherung im Cache."""
        
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> T:
        """Deserialisiert Daten aus dem Cache."""
```

## Integration in die Prozessoren

### AudioProcessor

```python
class AudioProcessor(CacheableProcessor[AudioProcessingResult]):
    """
    Audio Processor für die Verarbeitung von Audio-Dateien.
    
    Der Processor erbt von CacheableProcessor und spezifiziert AudioProcessingResult
    als generischen Typ für das Caching.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "audio_cache"
    
    def _create_cache_key(self, audio_path: str, source_info: Optional[Dict[str, Any]] = None) -> str:
        """Erstellt einen Cache-Schlüssel basierend auf der Audio-Quelle."""
        # Bestimme die Basis für den Cache-Key
        if source_info:
            video_id = source_info.get('video_id')
            original_filename = source_info.get('original_filename')
            
            if video_id:
                # Bei Video-ID diese als Basis verwenden
                return self.generate_cache_key(video_id)
            elif original_filename:
                # Bei Original-Dateinamen diesen als Basis verwenden
                return self.generate_cache_key(original_filename)
        
        # Sonst den Pfad als Basis verwenden
        file_size = None
        try:
            file_size = Path(audio_path).stat().st_size
        except:
            pass
            
        # Wenn Dateigröße verfügbar, diese mit in den Schlüssel einbeziehen
        if file_size:
            return self.generate_cache_key(f"{audio_path}_{file_size}")
        
        return self.generate_cache_key(audio_path)
    
    def serialize_for_cache(self, result: AudioProcessingResult) -> Dict[str, Any]:
        """Serialisiert das AudioProcessingResult für die Speicherung im Cache."""
        cache_data = {
            "result": result.to_dict(),
            "source_path": getattr(result.metadata, "source_path", None),
            "processed_at": datetime.now().isoformat(),
            "source_language": getattr(result.metadata, "source_language", None),
            "target_language": getattr(result.metadata, "target_language", None),
            "template": getattr(result.metadata, "template", None),
            "original_filename": getattr(result.metadata, "original_filename", None),
            "video_id": getattr(result.metadata, "video_id", None)
        }
        
        return cache_data
    
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> AudioProcessingResult:
        """Deserialisiert die Cache-Daten zurück in ein AudioProcessingResult."""
        # Result-Objekt aus den Daten erstellen
        result_data = cached_data.get('result', {})
        result = AudioProcessingResult.from_dict(result_data)
        
        # Setze is_from_cache auf True
        result.is_from_cache = True
        
        # Dynamisch zusätzliche Metadaten aus dem Cache hinzufügen
        metadata_attrs = {
            'source_path': cached_data.get('source_path'),
            'source_language': cached_data.get('source_language'),
            'target_language': cached_data.get('target_language'),
            'template': cached_data.get('template'),
            'original_filename': cached_data.get('original_filename'),
            'video_id': cached_data.get('video_id')
        }
        
        # Füge die zusätzlichen Attribute zum Metadata-Objekt hinzu
        for attr_name, attr_value in metadata_attrs.items():
            if attr_value is not None:
                setattr(result.metadata, attr_name, attr_value)
        
        return result
    
    def _create_specialized_indexes(self, collection: Any) -> None:
        """Erstellt spezialisierte Indizes für die Collection."""
        collection.create_index("source_path")
```

### VideoProcessor

```python
class VideoProcessor(CacheableProcessor[VideoProcessingResult]):
    """
    Prozessor für die Verarbeitung von Video-Dateien.
    Lädt Videos herunter, extrahiert Audio und transkribiert sie.
    
    Der VideoProcessor erbt von CacheableProcessor und spezifiziert VideoProcessingResult
    als generischen Typ für das Caching.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "video_cache"
    
    def _create_cache_key(self, source: Union[str, VideoSource]) -> str:
        """Erstellt einen Cache-Schlüssel basierend auf der Video-Quelle."""
        if isinstance(source, VideoSource):
            url = source.url
            if not url:
                return self.generate_cache_key(f"video_{uuid.uuid4()}")
            source = url
            
        # Wenn eine URL angegeben wurde, den Dateinamen extrahieren
        if isinstance(source, str) and source.startswith(('http://', 'https://')):
            # Basis-URL als Cache-Key verwenden (ohne Query-Parameter)
            parsed_url = urlparse(source)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path}"
            return self.generate_cache_key(base_url)
            
        # Sonst den Pfad als Basis verwenden
        return self.generate_cache_key(source)
```

## Protokoll-Definitionen für Metadaten

Um die Typsicherheit zu verbessern und den Linter bei der Erkennung dynamischer Attribute zu unterstützen, haben wir Protocol-Klassen für die Metadaten definiert:

```python
class AudioMetadataProtocol(Protocol):
    """Protocol für die AudioMetadata-Klasse und ihre dynamischen Attribute."""
    duration: float
    duration_formatted: str
    file_size: int
    sample_rate: int
    channels: int
    bits_per_sample: int
    format: str
    codec: str
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_path: Optional[str]
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]
    original_filename: Optional[str]
    video_id: Optional[str]
    filename: Optional[str]

class VideoMetadataProtocol(Protocol):
    """Protocol für die VideoMetadata-Klasse und ihre dynamischen Attribute."""
    title: str
    duration: int
    duration_formatted: str
    file_size: Optional[int]
    process_dir: Optional[str]
    audio_file: Optional[str]
    source: 'VideoSource'
    
    # Dynamische Attribute, die zur Laufzeit hinzugefügt werden können
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]
```

## Verwendung des MongoDB-Cachings

### Grundlegende Verwendung

```python
# AudioProcessor mit MongoDB-Caching
processor = AudioProcessor(resource_calculator)

# Verarbeitung mit Cache-Überprüfung
result = await processor.process(
    audio_source="https://example.com/audio.mp3",
    source_language="de",
    target_language="en",
    use_cache=True  # Caching aktivieren
)

# Cache explizit löschen
processor.invalidate_cache(cache_key)

# Cache aufräumen (Einträge älter als 7 Tage löschen)
stats = processor.cleanup_cache()
print(f"Gelöschte Cache-Einträge: {stats['deleted']} von {stats['total']}")
```

### Konfiguration

Die Caching-Funktionalität kann über die Konfigurationsdatei gesteuert werden:

```json
{
  "cache": {
    "enabled": true,
    "max_age_days": 7
  },
  "mongodb": {
    "connection_string": "mongodb://localhost:27017",
    "database": "audio_cache_db"
  }
}
```

## Vorteile der neuen Implementierung

1. **Verbesserte Typsicherheit**
   - Generische Typen für die Prozessoren
   - Klare Vererbungshierarchie
   - Explizite Protokolle für dynamische Attribute

2. **Bessere Speichereffizienz**
   - Verwendung von MongoDB für die Speicherung der Cache-Daten
   - Indizierung für schnellere Zugriffe
   - Bessere Skalierbarkeit

3. **Vereinfachte Verwaltung**
   - Zentrale Steuerung des Cachings
   - Einfaches Aufräumen alter Cache-Einträge
   - Klare Trennung zwischen verschiedenen Prozessoren

4. **Erhöhte Performance**
   - Schnellere Zugriffe durch Indizierung
   - Optimierte Serialisierung und Deserialisierung
   - Geringerer Overhead für die Speicherverwaltung

## Bekannte Einschränkungen

1. **MongoDB erforderlich**: Die neue Implementierung erfordert eine MongoDB-Instanz
2. **Speicherplatz**: Die Cache-Daten können bei häufiger Nutzung viel Speicherplatz belegen
3. **Synchronisation**: Bei parallelen Zugriffen kann es zu Synchronisationsproblemen kommen

## Nächste Schritte

1. **Performance-Tests**: Systematisches Testen der Leistung unter Last
2. **Cache-Validierung**: Implementierung einer zusätzlichen Validierung für Cache-Einträge
3. **Lebenszyklus-Management**: Verbesserte Verwaltung des Cache-Lebenszyklus
4. **Dokumentation**: Erweiterung der Dokumentation um weitere Beispiele

## Beispiele

### AudioProcessor mit MongoDB-Caching

```python
# Erstelle einen AudioProcessor
processor = AudioProcessor(resource_calculator)

# Überprüfe, ob ein Cache-Eintrag existiert
cache_key = processor._create_cache_key(audio_path, source_info)
cache_hit, cached_result = processor.get_from_cache(cache_key)

if cache_hit and cached_result:
    # Verwende das gecachte Ergebnis
    print(f"Cache-Hit für {cache_key}")
    return create_response_from_cached_result(cached_result)

# Normale Verarbeitung durchführen
result = process_audio()

# Ergebnis im Cache speichern
processor.save_to_cache(cache_key, result)
```

### VideoProcessor mit MongoDB-Caching

```python
# Erstelle einen VideoProcessor
processor = VideoProcessor(resource_calculator)

# Überprüfe, ob ein Cache-Eintrag existiert
cache_key = processor._create_cache_key(video_url)
cache_hit, cached_result = processor.get_from_cache(cache_key)

if cache_hit and cached_result:
    # Verwende das gecachte Ergebnis
    print(f"Cache-Hit für {cache_key}")
    return create_response_from_cached_result(cached_result)

# Normale Verarbeitung durchführen
result = process_video()

# Ergebnis im Cache speichern
processor.save_to_cache(cache_key, result)
``` 