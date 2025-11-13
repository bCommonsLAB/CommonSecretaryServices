"""
@fileoverview Provider Manager - Central management of LLM providers

@description
Manages LLM provider instances and provides factory methods for creating
provider instances based on configuration.

@module core.llm.provider_manager

@exports
- ProviderManager: Class - Central provider management
"""

from typing import Dict, Optional, Type, Any
from ..exceptions import ProcessingError
from .protocols import LLMProvider
from .use_cases import UseCase


class ProviderManager:
    """
    Zentrale Verwaltung von LLM-Providern.
    
    Verwaltet Provider-Instanzen und stellt Factory-Methoden für die
    Erstellung von Provider-Instanzen bereit.
    """
    
    _instance: Optional['ProviderManager'] = None
    _providers: Dict[str, LLMProvider] = {}
    _provider_classes: Dict[str, Type[LLMProvider]] = {}
    
    def __new__(cls) -> 'ProviderManager':
        """Singleton-Pattern für ProviderManager."""
        if cls._instance is None:
            cls._instance = super(ProviderManager, cls).__new__(cls)
        return cls._instance
    
    def register_provider_class(
        self,
        provider_name: str,
        provider_class: Type[LLMProvider]
    ) -> None:
        """
        Registriert eine Provider-Klasse.
        
        Args:
            provider_name: Name des Providers (z.B. 'openai', 'mistral')
            provider_class: Klasse, die das LLMProvider-Protocol implementiert
        """
        self._provider_classes[provider_name] = provider_class
    
    def create_provider(
        self,
        provider_name: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs: Any
    ) -> LLMProvider:
        """
        Erstellt eine Provider-Instanz.
        
        Args:
            provider_name: Name des Providers
            api_key: API-Key für den Provider
            base_url: Optional, benutzerdefinierte Base-URL
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            LLMProvider: Provider-Instanz
            
        Raises:
            ProcessingError: Wenn der Provider nicht registriert ist
        """
        if provider_name not in self._provider_classes:
            raise ProcessingError(
                f"Provider '{provider_name}' ist nicht registriert. "
                f"Verfügbare Provider: {', '.join(self._provider_classes.keys())}"
            )
        
        provider_class = self._provider_classes[provider_name]
        
        # Erstelle Provider-Instanz mit API-Key und optionaler Base-URL
        try:
            if base_url:
                provider = provider_class(api_key=api_key, base_url=base_url, **kwargs)
            else:
                provider = provider_class(api_key=api_key, **kwargs)
            
            return provider
        except Exception as e:
            raise ProcessingError(
                f"Fehler beim Erstellen des Providers '{provider_name}': {str(e)}"
            ) from e
    
    def get_provider(
        self,
        provider_name: str,
        api_key: str,
        base_url: Optional[str] = None,
        **kwargs: Any
    ) -> LLMProvider:
        """
        Gibt eine Provider-Instanz zurück (erstellt sie bei Bedarf).
        
        Args:
            provider_name: Name des Providers
            api_key: API-Key für den Provider
            base_url: Optional, benutzerdefinierte Base-URL
            **kwargs: Zusätzliche Provider-spezifische Parameter
            
        Returns:
            LLMProvider: Provider-Instanz
        """
        # Erstelle Cache-Key basierend auf Provider-Name und Base-URL
        cache_key = f"{provider_name}:{base_url or 'default'}"
        
        if cache_key not in self._providers:
            self._providers[cache_key] = self.create_provider(
                provider_name=provider_name,
                api_key=api_key,
                base_url=base_url,
                **kwargs
            )
        
        return self._providers[cache_key]
    
    def get_available_providers(self) -> list[str]:
        """
        Gibt die Namen aller registrierten Provider zurück.
        
        Returns:
            list[str]: Liste der Provider-Namen
        """
        return list(self._provider_classes.keys())
    
    def is_provider_registered(self, provider_name: str) -> bool:
        """
        Prüft, ob ein Provider registriert ist.
        
        Args:
            provider_name: Name des Providers
            
        Returns:
            bool: True wenn registriert, False sonst
        """
        return provider_name in self._provider_classes
    
    def clear_cache(self) -> None:
        """Löscht den Provider-Cache."""
        self._providers.clear()


