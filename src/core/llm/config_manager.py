"""
@fileoverview LLM Config Manager - Manages LLM provider and use case configuration

@description
Manages LLM provider and use case configuration. Loads configuration from
config.yaml and provides methods for accessing provider and model settings
per use case.

@module core.llm.config_manager

@exports
- LLMConfigManager: Class - LLM configuration management
"""

from typing import Dict, Optional
from ..config import Config
from ..exceptions import ProcessingError
from ..models.llm_config import ProviderConfig, UseCaseConfig, LLMConfig
from .provider_manager import ProviderManager
from .protocols import LLMProvider
from .use_cases import UseCase


class LLMConfigManager:
    """
    Verwaltet LLM-Provider- und Use-Case-Konfiguration.
    
    Lädt Konfiguration aus config.yaml und stellt Methoden für den Zugriff
    auf Provider- und Modell-Einstellungen pro Use-Case bereit.
    """
    
    _instance: Optional['LLMConfigManager'] = None
    
    def __new__(cls) -> 'LLMConfigManager':
        """Singleton-Pattern für LLMConfigManager."""
        if cls._instance is None:
            cls._instance = super(LLMConfigManager, cls).__new__(cls)
            cls._instance._config = None
            cls._instance._provider_manager = ProviderManager()
        return cls._instance
    
    def __init__(self) -> None:
        """Initialisiert den Config Manager."""
        if self._config is None:
            self._load_config()
    
    def _load_config(self) -> None:
        """Lädt die Konfiguration aus config.yaml."""
        config = Config()
        config_data = config.get_all()
        
        # Lade LLM-Provider-Konfigurationen
        providers: Dict[str, ProviderConfig] = {}
        llm_providers_config = config_data.get('llm_providers', {})
        
        for provider_name, provider_data in llm_providers_config.items():
            if isinstance(provider_data, dict):
                # API-Key aus Umgebungsvariablen laden
                api_key_env = provider_data.get('api_key', '')
                api_key = ''
                if api_key_env.startswith('${') and api_key_env.endswith('}'):
                    # Umgebungsvariable extrahieren
                    env_var = api_key_env[2:-1]
                    import os
                    api_key = os.getenv(env_var, '')
                else:
                    api_key = api_key_env
                
                # Erlaube leere API-Keys für nicht konfigurierte Provider
                # Validierung erfolgt erst beim tatsächlichen Gebrauch
                try:
                    # Lade verfügbare Modelle aus Config
                    available_models = provider_data.get('available_models', {})
                    
                    providers[provider_name] = ProviderConfig(
                        name=provider_name,
                        api_key=api_key or 'not-configured',  # Placeholder für nicht konfigurierte Provider
                        enabled=provider_data.get('enabled', True),
                        base_url=provider_data.get('base_url'),
                        additional_config=provider_data.get('additional_config', {}),
                        available_models=available_models
                    )
                except ValueError:
                    # Wenn Validierung fehlschlägt, überspringe Provider
                    continue
        
        # Lade Use-Case-Konfigurationen
        use_cases: Dict[str, UseCaseConfig] = {}
        llm_config_data = config_data.get('llm_config', {})
        use_cases_config = llm_config_data.get('use_cases', {})
        
        for use_case_name, use_case_data in use_cases_config.items():
            if isinstance(use_case_data, dict):
                use_cases[use_case_name] = UseCaseConfig(
                    use_case=use_case_name,
                    provider=use_case_data.get('provider', ''),
                    model=use_case_data.get('model', '')
                )
        
        self._config = LLMConfig(
            providers=providers,
            use_cases=use_cases
        )
    
    def get_provider_for_use_case(self, use_case: UseCase | str) -> Optional[LLMProvider]:
        """
        Gibt den konfigurierten Provider für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case oder Use-Case-Name
            
        Returns:
            Optional[LLMProvider]: Provider-Instanz oder None wenn nicht konfiguriert
            
        Raises:
            ProcessingError: Wenn der Provider nicht verfügbar ist oder API-Key fehlt
        """
        if not self._config:
            return None
        
        # Konvertiere UseCase-Enum zu String falls nötig
        use_case_str = use_case.value if isinstance(use_case, UseCase) else str(use_case)
        
        use_case_config = self._config.get_use_case_config(use_case_str)
        if not use_case_config:
            return None
        
        provider_config = self._config.get_provider_config(use_case_config.provider)
        if not provider_config:
            raise ProcessingError(
                f"Provider '{use_case_config.provider}' für Use-Case '{use_case_str}' nicht gefunden"
            )
        
        if not provider_config.enabled:
            raise ProcessingError(
                f"Provider '{use_case_config.provider}' ist deaktiviert"
            )
        
        # Prüfe ob API-Key vorhanden ist
        if not provider_config.api_key or provider_config.api_key == 'not-configured':
            raise ProcessingError(
                f"API-Key für Provider '{provider_config.name}' nicht konfiguriert. "
                f"Bitte setzen Sie die entsprechende Umgebungsvariable."
            )
        
        # Erstelle Provider-Instanz
        try:
            # Füge available_models zu additional_config hinzu, damit es an Provider übergeben wird
            provider_kwargs = provider_config.additional_config.copy()
            if provider_config.available_models:
                provider_kwargs['available_models'] = provider_config.available_models
            
            return self._provider_manager.get_provider(
                provider_name=provider_config.name,
                api_key=provider_config.api_key,
                base_url=provider_config.base_url,
                **provider_kwargs
            )
        except ImportError as e:
            # Spezielle Behandlung für fehlende Pakete (z.B. mistralai)
            raise ProcessingError(
                f"Provider '{provider_config.name}' kann nicht verwendet werden: {str(e)}. "
                f"Bitte installieren Sie das erforderliche Paket oder wählen Sie einen anderen Provider."
            ) from e
        except Exception as e:
            raise ProcessingError(
                f"Fehler beim Erstellen des Providers '{provider_config.name}': {str(e)}"
            ) from e
    
    def get_model_for_use_case(self, use_case: UseCase | str) -> Optional[str]:
        """
        Gibt das konfigurierte Modell für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case oder Use-Case-Name
            
        Returns:
            Optional[str]: Modell-Name oder None wenn nicht konfiguriert
        """
        if not self._config:
            return None
        
        use_case_str = use_case.value if isinstance(use_case, UseCase) else str(use_case)
        use_case_config = self._config.get_use_case_config(use_case_str)
        return use_case_config.model if use_case_config else None
    
    def get_provider_config(self, provider_name: str) -> Optional[ProviderConfig]:
        """
        Gibt die Konfiguration für einen Provider zurück.
        
        Args:
            provider_name: Name des Providers
            
        Returns:
            Optional[ProviderConfig]: Provider-Konfiguration oder None
        """
        if not self._config:
            return None
        return self._config.get_provider_config(provider_name)
    
    def get_use_case_config(self, use_case: UseCase | str) -> Optional[UseCaseConfig]:
        """
        Gibt die Konfiguration für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case oder Use-Case-Name
            
        Returns:
            Optional[UseCaseConfig]: Use-Case-Konfiguration oder None
        """
        if not self._config:
            return None
        use_case_str = use_case.value if isinstance(use_case, UseCase) else str(use_case)
        return self._config.get_use_case_config(use_case_str)
    
    def get_all_providers(self) -> Dict[str, ProviderConfig]:
        """
        Gibt alle Provider-Konfigurationen zurück.
        
        Returns:
            Dict[str, ProviderConfig]: Dictionary der Provider-Konfigurationen
        """
        if not self._config:
            return {}
        return self._config.providers.copy()
    
    def get_all_use_cases(self) -> Dict[str, UseCaseConfig]:
        """
        Gibt alle Use-Case-Konfigurationen zurück.
        
        Returns:
            Dict[str, UseCaseConfig]: Dictionary der Use-Case-Konfigurationen
        """
        if not self._config:
            return {}
        return self._config.use_cases.copy()
    
    def reload_config(self) -> None:
        """Lädt die Konfiguration neu."""
        # Setze _config auf None, damit _load_config() die Konfiguration neu lädt
        self._config = None
        self._load_config()
        # Cache leeren, damit neue Provider-Instanzen erstellt werden
        if hasattr(self._provider_manager, 'clear_cache'):
            self._provider_manager.clear_cache()


