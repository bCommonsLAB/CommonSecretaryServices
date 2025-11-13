"""
@fileoverview LLM Configuration Models - Dataclasses for LLM provider and use case configuration

@description
Dataclasses for LLM provider and use case configuration management.
Defines the structure for provider settings and use case mappings.

@module core.models.llm_config

@exports
- ProviderConfig: Dataclass - Provider configuration
- UseCaseConfig: Dataclass - Use case configuration
- LLMConfig: Dataclass - Complete LLM configuration
- ModelInfo: Dataclass - Model information
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from ..validation import is_non_empty_str


@dataclass(frozen=True)
class ProviderConfig:
    """
    Konfiguration für einen LLM-Provider.
    
    Attributes:
        name: Name des Providers (z.B. 'openai', 'mistral', 'openrouter')
        api_key: API-Key für den Provider (aus Umgebungsvariablen)
        enabled: Ob der Provider aktiviert ist
        base_url: Optional, benutzerdefinierte Base-URL für den Provider
        additional_config: Optional, zusätzliche Provider-spezifische Konfiguration
        available_models: Optional, Dictionary mit Use-Case -> Liste von Modell-Namen
    """
    name: str
    api_key: str
    enabled: bool = True
    base_url: Optional[str] = None
    additional_config: Dict[str, Any] = field(default_factory=dict)
    available_models: Dict[str, List[str]] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.name):
            raise ValueError("Provider name darf nicht leer sein")
        # API-Key-Validierung ist optional - erlaubt 'not-configured' als Placeholder
        # Die tatsächliche Validierung erfolgt beim Provider-Zugriff
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Konfiguration in ein Dictionary."""
        result: Dict[str, Any] = {
            "name": self.name,
            "enabled": self.enabled
        }
        if self.base_url:
            result["base_url"] = self.base_url
        if self.additional_config:
            result["additional_config"] = self.additional_config
        return result


@dataclass(frozen=True)
class UseCaseConfig:
    """
    Konfiguration für einen Use-Case.
    
    Attributes:
        use_case: Name des Use-Cases (z.B. 'transcription', 'image2text')
        provider: Name des zu verwendenden Providers
        model: Name des zu verwendenden Modells
    """
    use_case: str
    provider: str
    model: str
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.use_case):
            raise ValueError("Use-Case darf nicht leer sein")
        if not is_non_empty_str(self.provider):
            raise ValueError("Provider darf nicht leer sein")
        if not is_non_empty_str(self.model):
            raise ValueError("Model darf nicht leer sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Konfiguration in ein Dictionary."""
        return {
            "use_case": self.use_case,
            "provider": self.provider,
            "model": self.model
        }


@dataclass(frozen=True)
class ModelInfo:
    """
    Informationen über ein verfügbares Modell.
    
    Attributes:
        name: Name des Modells
        provider: Provider des Modells
        use_cases: Liste der unterstützten Use-Cases
        description: Optional, Beschreibung des Modells
    """
    name: str
    provider: str
    use_cases: List[str] = field(default_factory=list)
    description: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validiert die Felder nach der Initialisierung."""
        if not is_non_empty_str(self.name):
            raise ValueError("Model name darf nicht leer sein")
        if not is_non_empty_str(self.provider):
            raise ValueError("Provider darf nicht leer sein")
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Informationen in ein Dictionary."""
        result: Dict[str, Any] = {
            "name": self.name,
            "provider": self.provider,
            "use_cases": self.use_cases
        }
        if self.description:
            result["description"] = self.description
        return result


@dataclass(frozen=True)
class LLMConfig:
    """
    Komplette LLM-Konfiguration.
    
    Attributes:
        providers: Dictionary der Provider-Konfigurationen (key: provider name)
        use_cases: Dictionary der Use-Case-Konfigurationen (key: use case name)
    """
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)
    use_cases: Dict[str, UseCaseConfig] = field(default_factory=dict)
    
    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """
        Gibt die Konfiguration für einen Provider zurück.
        
        Args:
            provider_name: Name des Providers
            
        Returns:
            Optional[ProviderConfig]: Provider-Konfiguration oder None
        """
        return self.providers.get(provider_name)
    
    def get_use_case_config(self, use_case: str) -> Optional[UseCaseConfig]:
        """
        Gibt die Konfiguration für einen Use-Case zurück.
        
        Args:
            use_case: Name des Use-Cases
            
        Returns:
            Optional[UseCaseConfig]: Use-Case-Konfiguration oder None
        """
        return self.use_cases.get(use_case)
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert die Konfiguration in ein Dictionary."""
        return {
            "providers": {
                name: config.to_dict() 
                for name, config in self.providers.items()
            },
            "use_cases": {
                name: config.to_dict() 
                for name, config in self.use_cases.items()
            }
        }


