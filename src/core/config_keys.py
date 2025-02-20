"""
Verwaltung von sensitiven Konfigurationswerten wie API-Keys.
Diese werden ausschließlich aus Umgebungsvariablen geladen.
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