# Konzept: Native Python Dataclasses Migration

## Aktueller Stand

### Implementierte Basis-Komponenten

1. **Core Models (core/models/base.py)**
   - BaseModel Dataclass mit frozen=True und slots=True
   - JSON Serialisierung/Deserialisierung
   - Typ-Konvertierung und Validierung
   - Dict Konvertierung

2. **Validierung (core/models/validation.py)**
   - Validierungs-Dekoratoren
   - Typ-Checks
   - Post-Init Validierung

### Neue Dateistruktur

```
core/
  models/
    base.py         # Basis-Dataclass und Konvertierung
    validation.py   # Validierungs-Utilities
    enums.py        # Enum-Definitionen
    llm.py         # LLM-spezifische Modelle
    audio.py       # Audio-Verarbeitungs-Modelle
    metadata.py    # Metadaten-Modelle
api/
  models/
    responses.py   # API Response-Modelle
    requests.py    # API Request-Modelle
```

## Nächste Schritte

1. **Modell-Migration**
   - [ ] LLM-Modelle in core/models/llm.py
   - [ ] Audio-Modelle in core/models/audio.py
   - [ ] Metadaten-Modelle in core/models/metadata.py
   - [ ] Response-Modelle in api/models/responses.py

2. **Validierungs-Optimierung**
   - [ ] Implementierung spezifischer Validatoren
   - [ ] Type-Checking Verbesserungen
   - [ ] Custom Error Messages

3. **Tests**
   - [ ] Unit-Tests für Basis-Modelle
   - [ ] Validierungs-Tests
   - [ ] Integration-Tests

## Validierungs-Strategie

```python
@dataclass(frozen=True, slots=True)
class ValidatedModel(BaseModel):
    field: str
    
    def __post_init__(self):
        if not self.field.strip():
            raise ValueError("Field must not be empty")
```

## Type Hints und Annotationen

```python
from typing import Annotated, TypeVar, TypeAlias

# Typ-Aliase
ISO639_1: TypeAlias = Annotated[str, Field(
    min_length=2,
    max_length=2,
    pattern=r"^[a-z]{2}$"
)]

# Generische Typen
T = TypeVar('T', bound='BaseModel')
```

## Performance-Optimierungen

1. **Slots und Frozen**
   - Nutzung von slots=True für Speicheroptimierung
   - frozen=True für Immutability

2. **Caching**
   - Caching von häufig genutzten Konvertierungen
   - Lazy Loading wo sinnvoll

3. **Validierung**
   - Effiziente Validierung in __post_init__
   - Typ-Checks nur wo nötig

## API Response Format

```python
@dataclass(frozen=True, slots=True)
class ApiResponse(BaseModel):
    status: str  # success/error
    data: Optional[Dict[str, Any]]
    error: Optional[ErrorInfo]
    
    def __post_init__(self):
        if self.status == "error" and not self.error:
            raise ValueError("Error info required for error status")
```

## Migration Checkliste

- [x] Basis-Modell implementiert
- [x] JSON Serialisierung
- [x] Typ-Konvertierung
- [ ] Enum-Migration
- [ ] LLM-Modelle
- [ ] Audio-Modelle
- [ ] API Response-Modelle
- [ ] Tests angepasst
