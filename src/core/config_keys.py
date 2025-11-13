"""
@fileoverview API Key Management - Manages sensitive configuration values from environment variables

@description
Management of sensitive configuration values such as API keys. This class provides
secure access to API keys that are loaded exclusively from environment variables or
the .env file.

The class uses the singleton pattern to ensure that API keys are only loaded once.
All values are read from environment variables at runtime, never from configuration files.

Features:
- Singleton pattern for global instance
- Automatic loading of .env file
- Validation of API key formats
- Secure storage in environment variables

@module core.config_keys

@exports
- ConfigKeys: Class - Singleton for API key management

@usedIn
- src.processors.transformer_processor: Loads OpenAI API key
- src.dashboard.routes.config_routes: Manages API key via web interface
- All processors using LLM APIs: Load API keys

@dependencies
- External: dotenv - Loading .env file
- System: os.environ - Environment variable access
"""
import os

from dotenv import load_dotenv  # type: ignore


class ConfigKeys:
    """
    Verwaltet sensitive Konfigurationswerte.
    Lädt Werte ausschließlich aus Umgebungsvariablen oder .env Datei.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigKeys, cls).__new__(cls)
            cls._instance._load_env()
        return cls._instance

    def _load_env(self):
        """Lädt Umgebungsvariablen aus .env Datei"""
        env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        load_dotenv(env_path, override=True)

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

    def set_openai_api_key(self, api_key: str):
        """
        Setzt den OpenAI API Key in der Umgebungsvariable.
        
        Args:
            api_key: Der zu setzende API Key
            
        Raises:
            ValueError: Wenn der API Key ein ungültiges Format hat
        """
        if not api_key.startswith('sk-'):
            raise ValueError("Ungültiger API Key Format. Muss mit 'sk-' beginnen.")
        
        os.environ['OPENAI_API_KEY'] = api_key
    
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
    
    def set_mistral_api_key(self, api_key: str):
        """
        Setzt den Mistral API Key in der Umgebungsvariable.
        
        Args:
            api_key: Der zu setzende API Key
            
        Raises:
            ValueError: Wenn der API Key ein ungültiges Format hat
        """
        if not api_key.startswith('mistral-'):
            raise ValueError("Ungültiger Mistral API Key Format. Muss mit 'mistral-' beginnen.")
        
        os.environ['MISTRAL_API_KEY'] = api_key
    
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
    
    def set_openrouter_api_key(self, api_key: str):
        """
        Setzt den OpenRouter API Key in der Umgebungsvariable.
        
        Args:
            api_key: Der zu setzende API Key
            
        Raises:
            ValueError: Wenn der API Key ein ungültiges Format hat
        """
        if not api_key.startswith('sk-or-'):
            raise ValueError("Ungültiger OpenRouter API Key Format. Muss mit 'sk-or-' beginnen.")
        
        os.environ['OPENROUTER_API_KEY'] = api_key 