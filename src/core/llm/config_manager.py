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

from typing import Dict, Optional, Tuple, Any
from ..config import Config
from ..exceptions import ProcessingError
from ..models.llm_config import ProviderConfig, UseCaseConfig, LLMConfig
from ..models.llm_models import LLMModel
from .provider_manager import ProviderManager
from .protocols import LLMProvider
from .use_cases import UseCase
import logging

logger = logging.getLogger(__name__)


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
            cls._instance._config: Optional[LLMConfig] = None
            cls._instance._provider_manager = ProviderManager()
            cls._instance._model_repo: Optional[Any] = None
            cls._instance._use_case_config_repo: Optional[Any] = None
        return cls._instance
    
    def __init__(self) -> None:
        """Initialisiert den Config Manager."""
        if self._config is None:
            self._load_config()
    
    def _get_model_repository(self) -> Any:
        """Gibt das Model-Repository zurück (lazy loading)."""
        if self._model_repo is None:
            try:
                from ..mongodb.llm_model_repository import LLMModelRepository
                self._model_repo = LLMModelRepository()
            except Exception as e:
                logger.warning(f"Konnte Model-Repository nicht laden: {str(e)}")
                return None
        return self._model_repo
    
    def _get_use_case_config_repository(self) -> Any:
        """Gibt das Use-Case-Config-Repository zurück (lazy loading)."""
        if self._use_case_config_repo is None:
            try:
                from ..mongodb.llm_model_repository import LLMUseCaseConfigRepository
                self._use_case_config_repo = LLMUseCaseConfigRepository()
            except Exception as e:
                logger.warning(f"Konnte Use-Case-Config-Repository nicht laden: {str(e)}")
                return None
        return self._use_case_config_repo
    
    def _load_models_from_mongodb(self) -> Dict[str, LLMModel]:
        """
        Lädt Modelle aus MongoDB.
        
        Returns:
            Dict[str, LLMModel]: Dictionary mit model_id -> LLMModel
        """
        model_repo = self._get_model_repository()
        if not model_repo:
            return {}
        
        try:
            models = model_repo.get_all_models()
            return {model.model_id: model for model in models}
        except Exception as e:
            logger.warning(f"Fehler beim Laden der Modelle aus MongoDB: {str(e)}")
            return {}
    
    def _load_config(self) -> None:
        """Lädt die Konfiguration aus config.yaml und MongoDB."""
        config = Config()
        config_data = config.get_all()
        
        # Lade LLM-Provider-Konfigurationen (immer aus config.yaml)
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
        
        # Lade Use-Case-Konfigurationen (zuerst aus MongoDB, dann Fallback auf config.yaml)
        use_cases: Dict[str, UseCaseConfig] = {}
        
        # Versuche MongoDB zu laden
        use_case_config_repo = self._get_use_case_config_repository()
        mongodb_configs: Dict[str, str] = {}
        
        if use_case_config_repo:
            try:
                mongodb_configs = use_case_config_repo.get_all_use_case_configs()
                logger.debug(f"Geladene Use-Case-Konfigurationen aus MongoDB: {list(mongodb_configs.keys())}")
            except Exception as e:
                logger.warning(f"Fehler beim Laden der Use-Case-Konfigurationen aus MongoDB: {str(e)}")
        
        # Wenn MongoDB-Konfigurationen vorhanden, verwende diese
        if mongodb_configs:
            # Lade Modelle aus MongoDB für Validierung
            mongodb_models = self._load_models_from_mongodb()
            
            for use_case_name, model_id in mongodb_configs.items():
                # Extrahiere Provider und Modell-Name aus model_id
                if '/' in model_id:
                    provider, model_name = model_id.split('/', 1)
                    
                    # Validiere dass Modell existiert
                    if model_id in mongodb_models:
                        use_cases[use_case_name] = UseCaseConfig(
                            use_case=use_case_name,
                            provider=provider,
                            model=model_name
                        )
                        logger.debug(f"Use-Case {use_case_name} aus MongoDB geladen: {model_id}")
                    else:
                        logger.warning(
                            f"Modell {model_id} für Use-Case {use_case_name} existiert nicht in MongoDB, "
                            f"verwende Fallback auf config.yaml"
                        )
        
        # Fallback auf config.yaml wenn MongoDB leer ist
        if not use_cases:
            llm_config_data = config_data.get('llm_config', {})
            use_cases_config = llm_config_data.get('use_cases', {})
            
            for use_case_name, use_case_data in use_cases_config.items():
                if isinstance(use_case_data, dict):
                    use_cases[use_case_name] = UseCaseConfig(
                        use_case=use_case_name,
                        provider=use_case_data.get('provider', ''),
                        model=use_case_data.get('model', '')
                    )
            logger.debug("Use-Case-Konfigurationen aus config.yaml geladen (Fallback)")
        
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
    
    def get_model_for_use_case(
        self,
        use_case: UseCase | str,
        prefer_best: bool = False,
        test_size: str = "medium"
    ) -> Optional[str]:
        """
        Gibt das konfigurierte Modell für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case oder Use-Case-Name
            prefer_best: Wenn True, verwende das beste Modell basierend auf Tests
            test_size: Test-Größe für Best-Model-Auswahl (nur wenn prefer_best=True)
            
        Returns:
            Optional[str]: Modell-Name oder None wenn nicht konfiguriert
        """
        if not self._config:
            return None
        
        use_case_str = use_case.value if isinstance(use_case, UseCase) else str(use_case)
        
        # Wenn prefer_best=True, versuche bestes Modell zu finden
        if prefer_best:
            try:
                from .model_selector import LLMModelSelector
                selector = LLMModelSelector()
                best_model_id = selector.get_best_model_for_use_case(use_case_str, test_size)
                
                if best_model_id:
                    # Extrahiere Modell-Name aus model_id (Format: provider/model_name)
                    if '/' in best_model_id:
                        _, model_name = best_model_id.split('/', 1)
                        logger.debug(f"Bestes Modell für {use_case_str} ({test_size}): {model_name}")
                        return model_name
            except Exception as e:
                logger.warning(f"Fehler bei Best-Model-Auswahl: {str(e)}, verwende aktuelles Modell")
        
        # Standard: Verwende aktuelles Modell
        use_case_config = self._config.get_use_case_config(use_case_str)
        return use_case_config.model if use_case_config else None
    
    def get_model_from_mongodb(self, model_id: str) -> Optional[LLMModel]:
        """
        Gibt ein Modell aus MongoDB zurück.
        
        Args:
            model_id: Die Modell-ID
            
        Returns:
            Optional[LLMModel]: Das Modell oder None
        """
        model_repo = self._get_model_repository()
        if not model_repo:
            return None
        
        try:
            return model_repo.get_model(model_id)
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Modells {model_id} aus MongoDB: {str(e)}")
            return None
    
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

    def get_embedding_defaults(self) -> Tuple[Optional[str], Optional[str], Optional[int]]:
        """
        Gibt die Standardkonfiguration für Embeddings zurück.
        
        Returns:
            Tuple aus (modell_name, provider_name, dimensionen) – jeder Wert kann None sein,
            falls in der Konfiguration nicht gesetzt.
        """
        if not self._config:
            return None, None, None
        
        use_case_config = self.get_use_case_config(UseCase.EMBEDDING)
        model_name = use_case_config.model if use_case_config else None
        provider_name = use_case_config.provider if use_case_config else None
        
        # Dimensionen sind optional und werden direkt aus der rohen Konfiguration gelesen
        config = Config()
        raw_config = config.get_all()
        dimensions: Optional[int] = None
        try:
            llm_cfg = raw_config.get("llm_config", {})
            use_cases_cfg = llm_cfg.get("use_cases", {})
            embedding_cfg = use_cases_cfg.get("embedding", {})
            raw_dims = embedding_cfg.get("dimensions")
            if isinstance(raw_dims, int) and raw_dims > 0:
                dimensions = raw_dims
        except Exception:
            # Im Fehlerfall Dimensions-Angabe einfach weglassen, Fallback erfolgt später
            dimensions = None
        
        return model_name, provider_name, dimensions
    
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


