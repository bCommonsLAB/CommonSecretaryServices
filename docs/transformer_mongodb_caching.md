# TransformerProcessor - MongoDB-Caching und Typisierung

Dieses Dokument beschreibt den Implementierungsplan für die Optimierung des TransformerProcessor durch MongoDB-Caching und verbesserte Typisierung.

## Aktuelle Struktur

Der `TransformerProcessor` ist verantwortlich für die Textverarbeitung mittels LLM-Modellen. Er bietet Funktionen wie:
- Transformation und Übersetzung von Texten
- Template-basierte Verarbeitung
- HTML-Tabellen-Extraktion und -Verarbeitung

Aktuell erbt der Prozessor von `BaseProcessor` und implementiert kein explizites Caching, was zu wiederholter Verarbeitung identischer Texte führt.

## Ziel der Optimierung

1. **MongoDB-Caching implementieren**
   - Wiederverwendung von Transformationsergebnissen für identische Eingaben
   - Reduzierung von LLM-Kosten und Verarbeitungszeit

2. **Typsicherheit verbessern**
   - Generische Typisierung für bessere IDE-Unterstützung
   - Protocol-Definitionen für dynamische Attribute
   - Verbesserte Response-Typisierung

## Implementierungsplan

### 1. CacheableProcessor-Integration

Der TransformerProcessor soll von `CacheableProcessor[TransformationResult]` erben:

```python
class TransformerProcessor(CacheableProcessor[TransformationResult]):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    
    Verwendet MongoDB-Caching zur effizienten Wiederverwendung von Transformationsergebnissen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "transformer_cache"
```

### 2. Cache-Schlüssel-Generierung

Die `_create_cache_key`-Methode muss basierend auf Eingabetext, Sprachen, Modell und Template implementiert werden:

```python
def _create_cache_key(self, 
                     source_text: str, 
                     source_language: str, 
                     target_language: str, 
                     template: Optional[str] = None) -> str:
    """
    Erstellt einen Cache-Schlüssel basierend auf den Eingabeparametern.
    
    Args:
        source_text: Der Quelltext
        source_language: Die Quellsprache
        target_language: Die Zielsprache
        template: Optional, das verwendete Template
        
    Returns:
        str: Der generierte Cache-Schlüssel
    """
    # Für längere Texte nur die ersten 1000 Zeichen und einen Hash verwenden
    if len(source_text) > 1000:
        text_for_key = source_text[:1000] + hashlib.md5(source_text.encode()).hexdigest()
    else:
        text_for_key = source_text
        
    # Basis-Schlüssel aus Text, Sprachen und Modell generieren
    base_key = f"{text_for_key}_{source_language}_{target_language}_{self.model}"
    
    # Template hinzufügen, wenn vorhanden
    if template:
        template_key = hashlib.md5(template.encode()).hexdigest()
        base_key = f"{base_key}_{template_key}"
        
    # Hash generieren
    return self.generate_cache_key(base_key)
```

### 3. Serialisierung und Deserialisierung

```python
def serialize_for_cache(self, result: TransformationResult) -> Dict[str, Any]:
    """
    Serialisiert das TransformationResult für die Speicherung im Cache.
    
    Args:
        result: Das TransformationResult
        
    Returns:
        Dict[str, Any]: Die serialisierten Daten
    """
    # Hauptdaten speichern
    cache_data = {
        "result": result.to_dict(),
        "processed_at": datetime.now().isoformat(),
        "model": self.model,
        "target_language": result.target_language
    }
    
    return cache_data
    
def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> TransformationResult:
    """
    Deserialisiert die Cache-Daten zurück in ein TransformationResult.
    
    Args:
        cached_data: Die Daten aus dem Cache
        
    Returns:
        TransformationResult: Das deserialisierte TransformationResult
    """
    # Result-Objekt aus den Daten erstellen
    result_data = cached_data.get('result', {})
    
    # TransformationResult erstellen
    result = TransformationResult(
        text=result_data.get('text', ''),
        target_language=result_data.get('target_language', 'unknown'),
        structured_data=result_data.get('structured_data'),
        requests=result_data.get('requests', []),
        llms=result_data.get('llms', [])
    )
    
    # Metadaten hinzufügen
    result.is_from_cache = True
    
    return result
```

### 4. Spezialisierte Indizes

```python
def _create_specialized_indexes(self, collection: Any) -> None:
    """
    Erstellt spezialisierte Indizes für die Collection.
    
    Args:
        collection: Die MongoDB-Collection
    """
    # Index für Zielsprache
    collection.create_index("target_language")
    
    # Index für das verwendete Modell
    collection.create_index("model")
    
    # Index für das Erstellungsdatum
    collection.create_index("processed_at")
```

### 5. Integration in die transform-Methode

```python
def transform(self, 
              source_text: str, 
              source_language: str, 
              target_language: str, 
              summarize: bool = False, 
              target_format: Optional[OutputFormat] = None,
              context: Optional[Dict[str, Any]] = None,
              use_cache: bool = True) -> TransformerResponse:
    """
    Transformiert einen Text.
    
    Args:
        source_text: Der zu transformierende Text
        source_language: Die Quellsprache
        target_language: Die Zielsprache
        summarize: Ob der Text zusammengefasst werden soll
        target_format: Das Zielformat
        context: Optionaler Kontext für die Transformation
        use_cache: Ob der Cache verwendet werden soll
        
    Returns:
        TransformerResponse: Die Response mit dem transformierten Text
    """
    # Cache-Schlüssel generieren
    if use_cache and self.is_cache_enabled():
        cache_key = self._create_cache_key(
            source_text=source_text,
            source_language=source_language,
            target_language=target_language
        )
        
        # Prüfen, ob im Cache vorhanden
        cache_hit, cached_result = self.get_from_cache(cache_key)
        
        if cache_hit and cached_result:
            self.logger.info(f"Cache-Hit für Transformation: {cache_key[:8]}...")
            
            # Response aus dem Cache erstellen
            return self._create_response_from_result(
                result=cached_result,
                source_text=source_text,
                source_language=source_language,
                target_language=target_language
            )
    
    # Normale Verarbeitung durchführen...
    # [Bestehender Code]
    
    # Ergebnis im Cache speichern
    if use_cache and self.is_cache_enabled():
        self.save_to_cache(cache_key, result)
        
    return response
```

### 6. Integration in die transformByTemplate-Methode

Ähnliche Änderungen wie bei der `transform`-Methode, aber mit zusätzlicher Berücksichtigung des Templates für den Cache-Schlüssel.

### 7. Protocol für TransformerMetadata

```python
class TransformerMetadataProtocol(Protocol):
    """Protocol für die Metadaten des TransformerProcessor."""
    # Basis-Attribute
    model: str
    target_format: OutputFormat
    
    # Dynamische Attribute
    source_language: Optional[str]
    target_language: Optional[str]
    template: Optional[str]
    template_name: Optional[str]
    summarize: Optional[bool]
```

### 8. Verbesserte TransformationResult-Klasse

```python
@dataclass
class TransformationResult:
    """
    Ergebnis einer Transformation.
    
    Attributes:
        text: Der transformierte Text
        target_language: Die Zielsprache
        structured_data: Optionale strukturierte Daten
        requests: Liste der LLM-Requests
        llms: Liste der verwendeten LLM-Modelle
        is_from_cache: Ob das Ergebnis aus dem Cache stammt
    """
    text: str
    target_language: str
    structured_data: Optional[Any] = None
    requests: Optional[List[LLMRequest]] = None
    llms: List[LLModel] = field(default_factory=list)
    is_from_cache: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Ergebnis in ein Dictionary."""
        return {
            "text": self.text,
            "target_language": self.target_language,
            "structured_data": self.structured_data,
            "requests": [r.to_dict() for r in self.requests] if self.requests else [],
            "llms": [l.to_dict() for l in self.llms] if self.llms else [],
            "is_from_cache": self.is_from_cache
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransformationResult':
        """Erstellt ein TransformationResult aus einem Dictionary."""
        return cls(
            text=data.get("text", ""),
            target_language=data.get("target_language", "unknown"),
            structured_data=data.get("structured_data"),
            requests=[LLMRequest.from_dict(r) for r in data.get("requests", [])],
            llms=[LLModel.from_dict(l) for l in data.get("llms", [])],
            is_from_cache=data.get("is_from_cache", False)
        )
```

## Vorteile der Optimierung

1. **Reduzierte LLM-Kosten**
   - Wiederverwendung von Transformationsergebnissen
   - Weniger API-Aufrufe für identische Anfragen

2. **Verbesserte Performance**
   - Schnellere Antwortzeiten für bereits verarbeitete Texte
   - Reduzierte Serverlast

3. **Bessere Typsicherheit**
   - Frühzeitiges Erkennen von Programmierfehlern
   - Verbesserte IDE-Unterstützung und Dokumentation

4. **Einheitliches Caching-System**
   - Konsistente Handhabung über alle Prozessoren hinweg
   - Einfachere Wartung und Weiterentwicklung

## Implementierungsschritte

1. Anpassung der TransformationResult-Klasse
2. Definition des TransformerMetadataProtocol
3. Erweiterung des TransformerProcessor für MongoDB-Caching
4. Integration der Cache-Funktionalität in die Transformationsmethoden
5. Tests für die Cache-Funktionalität
6. Performance-Messungen

## Tests

Für die Validierung der Implementierung sollten folgende Tests durchgeführt werden:

1. **Funktionstest**: Überprüfen, ob identische Transformation aus dem Cache bedient wird
2. **Performance-Test**: Messung der Verarbeitungszeit mit und ohne Cache
3. **Konsistenz-Test**: Überprüfen, ob Cache-Ergebnisse identisch mit direkten Transformationen sind
4. **Invalidierung-Test**: Testen der Cache-Bereinigungsfunktionen

## Nächste Schritte

Nach erfolgreicher Implementierung und Testung des MongoDB-Cachings für den TransformerProcessor können wir mit der Optimierung des PDFProcessor und ImageOCRProcessor fortfahren. 