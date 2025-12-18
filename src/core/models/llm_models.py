"""
@fileoverview LLM Model Models - Dataclasses for LLM model management in MongoDB

@description
Dataclasses for LLM model management. Defines the structure of models, test results,
and use case configurations stored in MongoDB.

@module core.models.llm_models

@exports
- LLMModel: Dataclass - Model definition
- LLMTestResult: Dataclass - Test result
- LLMUseCaseConfig: Dataclass - Use case configuration
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, UTC
from ..validation import is_non_empty_str


@dataclass(frozen=True)
class LLMModel:
    """
    Definition eines LLM-Modells.
    
    Attributes:
        model_id: Eindeutige ID im Format "{provider}/{model_name}"
        provider: Name des Providers (z.B. "openrouter", "openai")
        model_name: Name des Modells (z.B. "mistralai/mistral-medium-3.1")
        use_cases: Liste der unterstützten Use-Cases
        enabled: Ob das Modell aktiviert ist
        description: Optional, Beschreibung des Modells
        metadata: Optional, zusätzliche Metadaten (z.B. context_length, pricing)
        created_at: Erstellungszeitpunkt
        updated_at: Letzter Aktualisierungszeitpunkt
    """
    model_id: str
    provider: str
    model_name: str
    use_cases: List[str] = field(default_factory=list)
    enabled: bool = True
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.model_id):
            raise ValueError("model_id darf nicht leer sein")
        if not is_non_empty_str(self.provider):
            raise ValueError("provider darf nicht leer sein")
        if not is_non_empty_str(self.model_name):
            raise ValueError("model_name darf nicht leer sein")
        
        # Validiere model_id Format
        expected_id = f"{self.provider}/{self.model_name}"
        if self.model_id != expected_id:
            raise ValueError(
                f"model_id '{self.model_id}' entspricht nicht dem erwarteten Format "
                f"'{expected_id}' (provider/model_name)"
            )
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Modell in ein Dictionary."""
        result: Dict[str, Any] = {
            "model_id": self.model_id,
            "provider": self.provider,
            "model_name": self.model_name,
            "use_cases": self.use_cases,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
        if self.description:
            result["description"] = self.description
        if self.metadata:
            result["metadata"] = self.metadata
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMModel":
        """Erstellt ein LLMModel aus einem Dictionary."""
        # Konvertiere ISO-Format Strings zu datetime
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        elif created_at is None:
            created_at = datetime.now(UTC)
        
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        elif updated_at is None:
            updated_at = datetime.now(UTC)
        
        return cls(
            model_id=data["model_id"],
            provider=data["provider"],
            model_name=data["model_name"],
            use_cases=data.get("use_cases", []),
            enabled=data.get("enabled", True),
            description=data.get("description"),
            metadata=data.get("metadata", {}),
            created_at=created_at,
            updated_at=updated_at
        )


@dataclass(frozen=True)
class LLMTestResult:
    """
    Ergebnis eines LLM-Tests.
    
    Attributes:
        model_id: Referenz auf das getestete Modell
        use_case: Use-Case für den Test
        test_size: Größe des Tests ("small", "medium", "large")
        status: Status des Tests ("success", "error")
        duration_ms: Dauer des Tests in Millisekunden
        tokens: Optional, Anzahl der verwendeten Tokens
        error_message: Optional, Fehlermeldung bei Fehler
        error_code: Optional, Fehlercode bei Fehler
        validation_status: Status der Validierung ("success", "error")
        tested_at: Zeitpunkt des Tests
        test_result_data: Vollständige Test-Result-Daten für Details
        quality_score: Optional, Cosinus-Similarity zwischen Input- und Output-Embeddings (0.0-1.0)
        input_embedding: Optional, Embedding des Input-Texts (für spätere Analyse)
        output_embedding: Optional, Embedding des Output-Texts (für spätere Analyse)
    """
    model_id: str
    use_case: str
    test_size: str
    status: str
    duration_ms: int
    tokens: Optional[int] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    validation_status: str = "success"
    tested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    test_result_data: Dict[str, Any] = field(default_factory=dict)
    quality_score: Optional[float] = None
    input_embedding: Optional[List[float]] = None
    output_embedding: Optional[List[float]] = None
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.model_id):
            raise ValueError("model_id darf nicht leer sein")
        if not is_non_empty_str(self.use_case):
            raise ValueError("use_case darf nicht leer sein")
        if self.test_size not in ["small", "medium", "large"]:
            raise ValueError(f"test_size muss 'small', 'medium' oder 'large' sein, nicht '{self.test_size}'")
        if self.status not in ["success", "error"]:
            raise ValueError(f"status muss 'success' oder 'error' sein, nicht '{self.status}'")
        if self.validation_status not in ["success", "error"]:
            raise ValueError(
                f"validation_status muss 'success' oder 'error' sein, nicht '{self.validation_status}'"
            )
        if self.duration_ms < 0:
            raise ValueError(f"duration_ms muss >= 0 sein, nicht {self.duration_ms}")
        if self.quality_score is not None and (self.quality_score < 0.0 or self.quality_score > 1.0):
            raise ValueError(f"quality_score muss zwischen 0.0 und 1.0 liegen, nicht {self.quality_score}")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Test-Ergebnis in ein Dictionary."""
        result: Dict[str, Any] = {
            "model_id": self.model_id,
            "use_case": self.use_case,
            "test_size": self.test_size,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "validation_status": self.validation_status,
            "tested_at": self.tested_at.isoformat(),
            "test_result_data": self.test_result_data
        }
        if self.tokens is not None:
            result["tokens"] = self.tokens
        if self.error_message:
            result["error_message"] = self.error_message
        if self.error_code:
            result["error_code"] = self.error_code
        if self.quality_score is not None:
            result["quality_score"] = self.quality_score
        if self.input_embedding is not None:
            result["input_embedding"] = self.input_embedding
        if self.output_embedding is not None:
            result["output_embedding"] = self.output_embedding
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMTestResult":
        """Erstellt ein LLMTestResult aus einem Dictionary."""
        # Konvertiere ISO-Format String zu datetime
        tested_at = data.get("tested_at")
        if isinstance(tested_at, str):
            tested_at = datetime.fromisoformat(tested_at.replace('Z', '+00:00'))
        elif tested_at is None:
            tested_at = datetime.now(UTC)
        
        return cls(
            model_id=data["model_id"],
            use_case=data["use_case"],
            test_size=data["test_size"],
            status=data["status"],
            duration_ms=data["duration_ms"],
            tokens=data.get("tokens"),
            error_message=data.get("error_message"),
            error_code=data.get("error_code"),
            validation_status=data.get("validation_status", "success"),
            tested_at=tested_at,
            test_result_data=data.get("test_result_data", {}),
            quality_score=data.get("quality_score"),
            input_embedding=data.get("input_embedding"),
            output_embedding=data.get("output_embedding")
        )


@dataclass(frozen=True)
class LLMUseCaseConfig:
    """
    Konfiguration für einen Use-Case.
    
    Attributes:
        use_case: Name des Use-Cases
        current_model_id: ID des aktuell verwendeten Modells
        updated_at: Letzter Aktualisierungszeitpunkt
        updated_by: Optional, User-ID falls Authentifizierung vorhanden
    """
    use_case: str
    current_model_id: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_by: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.use_case):
            raise ValueError("use_case darf nicht leer sein")
        if not is_non_empty_str(self.current_model_id):
            raise ValueError("current_model_id darf nicht leer sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Konfiguration in ein Dictionary."""
        result: Dict[str, Any] = {
            "use_case": self.use_case,
            "current_model_id": self.current_model_id,
            "updated_at": self.updated_at.isoformat()
        }
        if self.updated_by:
            result["updated_by"] = self.updated_by
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LLMUseCaseConfig":
        """Erstellt ein LLMUseCaseConfig aus einem Dictionary."""
        # Konvertiere ISO-Format String zu datetime
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
        elif updated_at is None:
            updated_at = datetime.now(UTC)
        
        return cls(
            use_case=data["use_case"],
            current_model_id=data["current_model_id"],
            updated_at=updated_at,
            updated_by=data.get("updated_by")
        )

