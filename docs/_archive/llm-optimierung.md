# LLM-Tracking Optimierung

## Aktuelles Problem

Die aktuelle Implementierung des LLM-Trackings weist folgende Schwachstellen auf:

1. **Redundante Konvertierung**: In verschiedenen Prozessoren (YouTube, Video, Audio) wird die gleiche Konvertierungslogik für LLM-Requests implementiert.
2. **Inkonsistente Handhabung**: Die Verarbeitung von LLM-Informationen ist nicht einheitlich zwischen den Prozessoren.
3. **Fehlende Zentralisierung**: Response-Erstellung und LLM-Tracking sind nicht zentral organisiert.
4. **Typ-Unsicherheit**: Durch Dictionary-basierte Konvertierungen entstehen potenzielle Typ-Unsicherheiten.

## Lösungsansatz

### 1. Zentralisierung in BaseResponse

Die `BaseResponse` Klasse in `core/models/base.py` wird erweitert, um standardisierte LLM-Tracking Funktionalität bereitzustellen:

```python
@dataclass(frozen=True)
class BaseResponse:
    request: RequestInfo
    process: ProcessInfo
    status: ProcessingStatus = ProcessingStatus.PENDING
    error: Optional[ErrorInfo] = None
    llm_info: Optional[LLMInfo] = None  # Neu: Zentrale LLM-Info

    def add_llm_requests(self, requests: Union[List[LLMRequest], LLMInfo]) -> None:
        """Fügt LLM-Requests zentral hinzu und aktualisiert Process-Info."""
        if not self.llm_info:
            object.__setattr__(self, 'llm_info', LLMInfo(
                model="multi-model",
                purpose="multi-purpose"
            ))
        
        if isinstance(requests, LLMInfo):
            self.llm_info.add_request(requests.requests)
        else:
            self.llm_info.add_request(requests)
            
        # Aktualisiere Process-Info
        object.__setattr__(self.process, 'llm_info', self.llm_info.to_dict())
```

### 2. Erweiterung der LLMInfo Klasse

Die `LLMInfo` Klasse in `core/models/llm.py` wird optimiert:

```python
@dataclass(frozen=True)
class LLMInfo:
    model: str
    purpose: str
    requests: List[LLMRequest] = field(default_factory=list)
    
    @property
    def requests_count(self) -> int:
        return len(self.requests)
        
    @property
    def total_tokens(self) -> int:
        return sum(r.tokens for r in self.requests)
        
    @property
    def total_duration(self) -> float:
        return sum(r.duration for r in self.requests)

    def merge(self, other: 'LLMInfo') -> 'LLMInfo':
        """Kombiniert zwei LLMInfo Objekte."""
        return LLMInfo(
            model=f"{self.model}+{other.model}",
            purpose=f"{self.purpose}+{other.purpose}",
            requests=[*self.requests, *other.requests]
        )
```

### 3. Standardisierte Response-Erstellung

Ein neues Response-Factory-Modul in `core/models/response_factory.py`:

```python
class ResponseFactory:
    @staticmethod
    def create_response(
        processor_name: str,
        result: Any,
        request_info: Dict[str, Any],
        llm_info: Optional[LLMInfo] = None,
        error: Optional[ErrorInfo] = None
    ) -> BaseResponse:
        """Erstellt eine standardisierte Response mit LLM-Tracking."""
        response = BaseResponse(
            request=RequestInfo(
                processor=processor_name,
                timestamp=datetime.now().isoformat(),
                parameters=request_info
            ),
            process=ProcessInfo(
                id=str(uuid.uuid4()),
                main_processor=processor_name,
                started=datetime.now().isoformat()
            ),
            status=ProcessingStatus.ERROR if error else ProcessingStatus.SUCCESS,
            error=error
        )
        
        if llm_info:
            response.add_llm_requests(llm_info)
            
        return response
```

## Implementierungsplan

1. **Phase 1: Core-Modelle**
   - Erweitern der BaseResponse
   - Optimieren der LLMInfo
   - Erstellen der ResponseFactory

2. **Phase 2: Prozessor-Anpassungen**
   - Refactoring YouTube-Processor
   - Refactoring Video-Processor
   - Refactoring Audio-Processor
   - Entfernen redundanter Konvertierungslogik

3. **Phase 3: Tests & Validierung**
   - Unit-Tests für neue Funktionalität
   - Integration-Tests für Prozessoren
   - Performance-Tests für LLM-Tracking

## Vorteile

1. **Typ-Sicherheit**: Durch strikte Typisierung und zentrale Validierung
2. **Wartbarkeit**: Zentrale Logik statt Redundanz
3. **Konsistenz**: Einheitliche Handhabung in allen Prozessoren
4. **Erweiterbarkeit**: Einfache Integration neuer LLM-Tracking Funktionen

## Risiken & Mitigationen

1. **Breaking Changes**
   - Schrittweise Migration
   - Temporäre Kompatibilitätsschicht

2. **Performance**
   - Lazy Loading für LLM-Informationen
   - Caching von aggregierten Werten

3. **Komplexität**
   - Klare Dokumentation
   - Beispiel-Implementierungen

## Nächste Schritte

1. Review des Konzepts
2. Implementierung der Core-Änderungen
3. Schrittweise Migration der Prozessoren
4. Umfangreiche Tests
5. Dokumentation & Beispiele

## Detaillierter Implementierungsplan

### Phase 1: Core-Modelle (bereits definiert)

### Phase 2: Utility-Klassen

#### transcription_utils.py

1. Refactoring der LLMRequest-Erstellung:
```python
def create_llm_request(
    self,
    purpose: str,
    tokens: int,
    duration: float,
    model: Optional[str] = None
) -> LLMRequest:
    """Zentrale Methode für LLMRequest-Erstellung."""
    return LLMRequest(
        model=model or self.model,
        purpose=purpose,
        tokens=tokens,
        duration=duration
    )
```

2. Anpassung der Methoden:
- `translate_text`: Verwendung von create_llm_request
- `summarize_text`: Verwendung von create_llm_request
- `transform_by_template`: Integration mit ResponseFactory
- `transcribe_segment`: Verwendung von create_llm_request

#### transformer_processor.py

1. Integration der ResponseFactory:
```python
from src.core.models.response_factory import ResponseFactory

def create_transformer_response(
    self,
    result: Any,
    request_info: Dict[str, Any],
    llm_info: Optional[LLMInfo] = None,
    error: Optional[ErrorInfo] = None
) -> TransformerResponse:
    """Zentrale Response-Erstellung für Transformer."""
    return ResponseFactory.create_response(
        processor_name=ProcessorType.TRANSFORMER.value,
        result=result,
        request_info=request_info,
        llm_info=llm_info,
        error=error
    )
```

2. Refactoring der Methoden:
- `transform`: Verwendung von create_transformer_response
- `transformByTemplate`: Verwendung von create_transformer_response
- `transformHtmlTable`: Verwendung von create_transformer_response

#### metadata_processor.py

1. Integration der ResponseFactory:
```python
def create_metadata_response(
    self,
    result: Any,
    request_info: Dict[str, Any],
    llm_info: Optional[LLMInfo] = None,
    error: Optional[ErrorInfo] = None
) -> MetadataResponse:
    """Zentrale Response-Erstellung für Metadata."""
    return ResponseFactory.create_response(
        processor_name="metadata",
        result=result,
        request_info=request_info,
        llm_info=llm_info,
        error=error
    )
```

2. Refactoring der Methoden:
- `process`: Verwendung von create_metadata_response
- `extract_content_metadata`: Integration mit LLMInfo

### Phase 3: Tests & Validierung

#### Neue Unit-Tests

1. transcription_utils_test.py:
```python
def test_llm_request_creation():
    """Test der zentralen LLMRequest-Erstellung."""
    
def test_translation_llm_tracking():
    """Test des LLM-Trackings bei Übersetzungen."""
    
def test_template_transform_llm_tracking():
    """Test des LLM-Trackings bei Template-Transformationen."""
```

2. transformer_processor_test.py:
```python
def test_response_factory_integration():
    """Test der ResponseFactory-Integration."""
    
def test_llm_info_aggregation():
    """Test der LLMInfo-Aggregation über mehrere Operationen."""
```

3. metadata_processor_test.py:
```python
def test_metadata_llm_tracking():
    """Test des LLM-Trackings bei Metadaten-Extraktion."""
    
def test_content_metadata_llm_info():
    """Test der LLMInfo bei Content-Metadaten."""
```

### Phase 4: Migration & Deployment

1. Schrittweise Migration:
   - Implementierung der Core-Änderungen
   - Einführung der neuen Utility-Methoden
   - Parallelbetrieb mit alter Implementierung
   - Schrittweise Umstellung der Prozessoren
   - Entfernung der alten Implementierung

2. Deployment-Strategie:
   - Feature-Flags für neue Implementierung
   - A/B-Testing der Performance
   - Monitoring der LLM-Tracking Genauigkeit
   - Rollback-Plan bei Problemen

### Phase 5: Dokumentation

1. Neue Dokumentation:
   - Zentrale LLM-Tracking Architektur
   - Best Practices für Prozessor-Implementierungen
   - Beispiele für ResponseFactory-Nutzung
   - Troubleshooting-Guide

2. Code-Beispiele:
   - Minimale Prozessor-Implementierung
   - LLM-Tracking Integration
   - Response-Erstellung
   - Error-Handling

## Timeline

1. Woche 1: Core-Modelle & Utility-Klassen
2. Woche 2: Prozessor-Anpassungen
3. Woche 3: Tests & Validierung
4. Woche 4: Migration & Deployment
5. Woche 5: Dokumentation & Finalisierung 