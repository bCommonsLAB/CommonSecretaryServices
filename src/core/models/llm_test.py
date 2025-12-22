"""
@fileoverview LLM Test Models - Dataclasses for LLM test case definitions

@description
Dataclasses for defining and managing LLM test cases. Test cases define
how to test a specific use case with different sizes (small/medium/large).

@module core.models.llm_test

@exports
- LLMTestCase: Dataclass - Test case definition
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from ..validation import is_non_empty_str


@dataclass(frozen=True)
class LLMTestCase:
    """
    Definition eines LLM-Test-Cases.
    
    Attributes:
        use_case: Name des Use-Cases (z.B. 'chat_completion', 'transcription')
        size: Größe des Tests ('small', 'medium', 'large')
        description: Beschreibung des Tests
        endpoint: API-Endpoint für den Test (z.B. '/api/transformer/template')
        method: HTTP-Methode ('POST', 'GET', etc.)
        parameters: Dictionary mit Request-Parametern
        expected_fields: Optional, Liste von erwarteten Feldern im Response (z.B. ['data.structured_data'])
        validate_json: Optional, ob JSON-Validierung durchgeführt werden soll (default: False)
    """
    use_case: str
    size: str
    description: str
    endpoint: str
    method: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    expected_fields: List[str] = field(default_factory=list)
    validate_json: bool = False
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.use_case):
            raise ValueError("use_case darf nicht leer sein")
        if self.size not in ['small', 'medium', 'large']:
            raise ValueError(f"size muss 'small', 'medium' oder 'large' sein, nicht '{self.size}'")
        if not is_non_empty_str(self.description):
            raise ValueError("description darf nicht leer sein")
        if not is_non_empty_str(self.endpoint):
            raise ValueError("endpoint darf nicht leer sein")
        if not is_non_empty_str(self.method):
            raise ValueError("method darf nicht leer sein")
        if self.method.upper() not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH']:
            raise ValueError(f"method muss eine gültige HTTP-Methode sein, nicht '{self.method}'")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert den Test-Case in ein Dictionary."""
        return {
            "use_case": self.use_case,
            "size": self.size,
            "description": self.description,
            "endpoint": self.endpoint,
            "method": self.method,
            "parameters": self.parameters,
            "expected_fields": self.expected_fields,
            "validate_json": self.validate_json
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LLMTestCase':
        """
        Erstellt einen LLMTestCase aus einem Dictionary.
        
        Args:
            data: Dictionary mit Test-Case-Daten
            
        Returns:
            LLMTestCase: Test-Case-Instanz
        """
        return cls(
            use_case=data.get('use_case', ''),
            size=data.get('size', 'small'),
            description=data.get('description', ''),
            endpoint=data.get('endpoint', ''),
            method=data.get('method', 'POST'),
            parameters=data.get('parameters', {}),
            expected_fields=data.get('expected_fields', []),
            validate_json=data.get('validate_json', False)
        )

