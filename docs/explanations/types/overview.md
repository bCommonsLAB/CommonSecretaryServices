---
status: draft
last_verified: 2025-08-15
---

# Typen & Dataclasses

Ziele: einfache, unveränderliche Modelle mit klarer Validierung, schnelle Serialisierung, mypy‑sauber.

## Grundregeln
- Native `@dataclass` statt Pydantic
- Strikte Typ‑Annotationen (keine `Any` in öffentlichen APIs)
- Validierung in `__post_init__`
- Unveränderlich, wo möglich: `frozen=True`
- Performance: `slots=True` für häufige Modelle
- Serialisierung: `to_dict()`/`from_dict()` implementieren
- Generics: `TypeVar` für wiederverwendbare Strukturen
- Typprüfung: `mypy` (siehe `mypy.ini`)

## Minimales Muster
```python
from dataclasses import dataclass
from typing import Optional, Dict, Any

@dataclass(frozen=True, slots=True)
class AudioMetadata:
    duration: float
    process_dir: str
    args: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "duration": self.duration,
            "process_dir": self.process_dir,
            "args": self.args,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "AudioMetadata":
        return AudioMetadata(
            duration=float(data["duration"]),
            process_dir=str(data["process_dir"]),
            args=dict(data.get("args", {})),
        )
```

## Validierung in `__post_init__`
```python
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class Chapter:
    title: str
    start_time: float
    end_time: float

    def __post_init__(self) -> None:
        if self.start_time < 0 or self.end_time < 0:
            raise ValueError("Timestamps dürfen nicht negativ sein")
        if self.end_time < self.start_time:
            raise ValueError("end_time < start_time")
```

## Generics (TypeVar)
```python
from dataclasses import dataclass
from typing import Generic, TypeVar, Dict, Any

T = TypeVar("T")

@dataclass(frozen=True, slots=True)
class CacheEntry(Generic[T]):
    key: str
    value: T

    def to_dict(self) -> Dict[str, Any]:
        return {"key": self.key, "value": self.value}  # value muss selbst serialisierbar sein
```

## mypy‑Hinweise
- Öffentliche Funktionen/Methoden: vollständige Signaturen
- Keine stillen Typ‑Casts; stattdessen genaue Typen
- Collections immer parametrisieren: `list[str]`, `dict[str, Any]`

## Projektbezug
- Kernmodelle unter `src/core/models/*` folgen diesem Muster (z. B. `audio.py`, `metadata.py`, `transformer.py`).
- Responses implementieren `to_dict()`; API‑Schicht verwendet diese direkt.

Weiterführende historische Dokumente wurden ins Archiv verschoben. Die obigen Regeln sind maßgeblich.
