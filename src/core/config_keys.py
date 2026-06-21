"""
@fileoverview API Key Management - Manages sensitive configuration values from environment variables

@description
Management of sensitive configuration values such as API keys. This class provides
secure access to API keys that are loaded exclusively from environment variables or
the .env file.

WICHTIG (Sicherheit):
- API-Keys werden AUSSCHLIESSLICH aus Umgebungsvariablen gelesen (z. B. via
  Docker Compose oder .env). Sie werden NICHT in config.yaml gepflegt und NICHT
  über das Dashboard-Frontend gesetzt oder angezeigt.
- Es gibt bewusst KEINE set_*-Methoden mehr: Keys dürfen zur Laufzeit nicht aus
  dem Frontend geändert werden.

The class uses the singleton pattern to ensure that API keys are only loaded once.

@module core.config_keys

@exports
- ConfigKeys: Class - Singleton for read-only API key access

@usedIn
- src.core.llm.config_manager: Lädt Provider-API-Keys aus Umgebungsvariablen
- src.processors.rag_processor: Lädt Voyage-API-Key

@dependencies
- External: dotenv - Loading .env file
- System: os.environ - Environment variable access
"""
import os
from typing import Dict, Optional

from dotenv import load_dotenv  # type: ignore


class ConfigKeys:
    """
    Verwaltet sensitive Konfigurationswerte (nur lesend).
    Lädt Werte ausschließlich aus Umgebungsvariablen oder .env Datei.
    """
    _instance = None

    # Zentrales Mapping: Provider-Name -> Name der Umgebungsvariable.
    # Achtung: 'voyageai' nutzt VOYAGE_API_KEY (nicht VOYAGEAI_API_KEY).
    # Provider ohne Eintrag (z. B. 'ollama') benötigen keinen echten Key.
    PROVIDER_ENV_VARS: Dict[str, str] = {
        'openai': 'OPENAI_API_KEY',
        'mistral': 'MISTRAL_API_KEY',
        'openrouter': 'OPENROUTER_API_KEY',
        'voyageai': 'VOYAGE_API_KEY',
    }

    # Provider, die einen lokalen/offenen Endpunkt nutzen und nur einen
    # nicht-leeren Dummy-Key brauchen (OpenAI-kompatible Clients verlangen das).
    _LOCAL_PROVIDER_DUMMY_KEYS: Dict[str, str] = {
        'ollama': 'ollama',
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigKeys, cls).__new__(cls)
            cls._instance._load_env()
        return cls._instance

    def _load_env(self):
        """Lädt Umgebungsvariablen aus .env Datei"""
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        load_dotenv(env_path, override=True)

    def get_api_key_for_provider(self, provider_name: str) -> Optional[str]:
        """
        Gibt den API-Key für einen Provider zurück.

        Der Key wird ausschließlich aus der zum Provider gehörenden
        Umgebungsvariable gelesen (siehe PROVIDER_ENV_VARS).

        Args:
            provider_name: Name des Providers (z. B. 'openai', 'voyageai')

        Returns:
            Optional[str]: Der API-Key, ein Dummy-Key für lokale Provider
            (z. B. 'ollama') oder None, falls keine Variable gesetzt ist.
        """
        # Lokale Provider brauchen keinen echten Key, nur einen Dummy.
        if provider_name in self._LOCAL_PROVIDER_DUMMY_KEYS:
            return self._LOCAL_PROVIDER_DUMMY_KEYS[provider_name]

        env_var = self.PROVIDER_ENV_VARS.get(provider_name)
        if not env_var:
            return None
        return os.getenv(env_var)

    @property
    def openai_api_key(self) -> str:
        """
        Gibt den OpenAI API Key zurück.
        Wird ausschließlich aus der Umgebungsvariable OPENAI_API_KEY geladen.
        """
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            raise ValueError("OpenAI API Key nicht gefunden. Bitte setzen Sie die OPENAI_API_KEY Umgebungsvariable.")
        return api_key

    @property
    def mistral_api_key(self) -> str:
        """
        Gibt den Mistral API Key zurück.
        Wird ausschließlich aus der Umgebungsvariable MISTRAL_API_KEY geladen.
        """
        api_key = os.getenv('MISTRAL_API_KEY')
        if not api_key:
            raise ValueError("Mistral API Key nicht gefunden. Bitte setzen Sie die MISTRAL_API_KEY Umgebungsvariable.")
        return api_key

    @property
    def openrouter_api_key(self) -> str:
        """
        Gibt den OpenRouter API Key zurück.
        Wird ausschließlich aus der Umgebungsvariable OPENROUTER_API_KEY geladen.
        """
        api_key = os.getenv('OPENROUTER_API_KEY')
        if not api_key:
            raise ValueError("OpenRouter API Key nicht gefunden. Bitte setzen Sie die OPENROUTER_API_KEY Umgebungsvariable.")
        return api_key

    @property
    def voyage_api_key(self) -> str:
        """
        Gibt den Voyage API Key zurück.
        Wird ausschließlich aus der Umgebungsvariable VOYAGE_API_KEY geladen.
        """
        api_key = os.getenv('VOYAGE_API_KEY')
        if not api_key:
            raise ValueError("Voyage API Key nicht gefunden. Bitte setzen Sie die VOYAGE_API_KEY Umgebungsvariable.")
        return api_key
