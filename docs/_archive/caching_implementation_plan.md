# MongoDB-Caching für den AudioProcessor - Implementierungsplan

## Problembeschreibung

Bei dem Versuch, das MongoDB-Caching für den AudioProcessor zu implementieren, sind wir auf zirkuläre Importe gestoßen. Die Codebase hat eine komplexe Abhängigkeitsstruktur, die bei der Einführung von `CacheableProcessor` als Basisklasse für `AudioProcessor` zu Problemen führt.

## Abhängigkeitsstruktur

Die identifizierten zirkulären Abhängigkeiten umfassen:

1. `VideoProcessor` importiert `AudioProcessor`
2. `EventProcessor` importiert `VideoProcessor`
3. `worker_manager.py` importiert `EventProcessor`
4. `CacheableProcessor` importiert `mongodb.connection`, welches `worker_manager` importiert

Diese Abhängigkeitskette führt zu einem zirkulären Import, wenn wir versuchen, `CacheableProcessor` in `AudioProcessor` zu importieren.

## Lösungsansatz

Um das MongoDB-Caching für den `AudioProcessor` zu implementieren, gibt es mehrere mögliche Ansätze:

### Option 1: Umstrukturierung der Importe

- Verschiebe die Definition von `CacheableProcessor` in ein separates Modul außerhalb der zirkulären Abhängigkeitskette
- Passe die Importe in allen betroffenen Dateien an
- Vorteil: Saubere Lösung
- Nachteil: Erfordert größere Änderungen an der Codebase

### Option 2: Verzögertes Importieren (Lazy Loading)

- Importiere `CacheableProcessor` innerhalb von Methoden statt auf Modulebene
- Implementiere eine Factory-Methode, die den korrekten Processor-Typ zurückgibt
- Vorteil: Minimale Änderungen an der Codebase
- Nachteil: Kann zu Laufzeitfehlern führen

### Option 3: Komposition statt Vererbung

- Statt von `CacheableProcessor` zu erben, implementiere Caching-Funktionalität durch ein Composition-Pattern
- Erstelle eine `AudioProcessorCache`-Klasse, die von `AudioProcessor` verwendet wird
- Vorteil: Vermeidet zirkuläre Importe
- Nachteil: Erfordert Anpassung des Caching-Konzepts

## Empfohlene Implementierung

Wir empfehlen Option 3 (Komposition statt Vererbung) für die Implementierung des MongoDB-Cachings im AudioProcessor:

1. Erstelle eine neue Klasse `AudioProcessorCache`, die das Caching für den AudioProcessor übernimmt
2. Implementiere die Methoden `save_to_cache`, `load_from_cache` und `has_cache` in dieser Klasse
3. Integriere die Cache-Klasse in den AudioProcessor durch Komposition
4. Passe den `process`-Methode des AudioProcessors an, um die Cache-Funktionalität zu nutzen

## Code-Beispiel (Pseudocode)

```python
# In einer neuen Datei audio_processor_cache.py
class AudioProcessorCache:
    def __init__(self, config):
        self.collection_name = "audio_cache"
        # MongoDB-Verbindung initialisieren
        
    def generate_cache_key(self, audio_path, source_info=None):
        # Cache-Key generieren
        
    def has_cache(self, cache_key):
        # Prüfen, ob ein Cache-Eintrag existiert
        
    def save_to_cache(self, cache_key, result, metadata):
        # Ergebnis im Cache speichern
        
    def load_from_cache(self, cache_key):
        # Ergebnis aus dem Cache laden

# In audio_processor.py
class AudioProcessor(BaseProcessor):
    def __init__(self, resource_calculator, process_id=None):
        super().__init__(resource_calculator, process_id)
        self.cache = AudioProcessorCache(self.config)
        
    def process(self, audio_source, source_info=None, use_cache=True, ...):
        # Cache-Key generieren
        cache_key = self.cache.generate_cache_key(audio_path, source_info)
        
        # Cache-Hit prüfen
        if use_cache and self.cache.has_cache(cache_key):
            cached_result = self.cache.load_from_cache(cache_key)
            # Response mit Cache-Ergebnis erstellen
            
        # Normal processing
        # ...
        
        # Ergebnis cachen
        if use_cache:
            self.cache.save_to_cache(cache_key, result, metadata)
```

## Nächste Schritte

1. Implementiere `AudioProcessorCache` als separate Klasse
2. Integriere diese in den `AudioProcessor`
3. Passe die `process`-Methode an, um das Caching zu nutzen
4. Schreibe Tests für die Cache-Funktionalität

## Hinweise für die Zukunft

Bei der Implementierung neuer Prozessoren sollte darauf geachtet werden, dass Caching durch Komposition statt Vererbung implementiert wird, um zirkuläre Importe zu vermeiden und die Codebase flexibler zu gestalten. 