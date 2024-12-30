from pathlib import Path
from dotenv import load_dotenv
import os
import yaml
from typing import Any, Optional

class Config:
    """Zentrale Konfigurationsklasse für die Anwendung.
    
    Lädt Umgebungsvariablen aus der .env Datei und Konfigurationen aus der config.yaml.
    """
    
    def __init__(self):
        # Lade .env Datei aus dem Root-Verzeichnis
        env_path = Path(__file__).parents[2] / '.env'
        load_dotenv(env_path)
        
        # OpenAI Konfiguration
        self.openai_api_key = os.getenv('OPENAI_API_KEY')
        if not self.openai_api_key:
            raise ValueError("OPENAI_API_KEY muss in der .env Datei gesetzt sein")
            
        # Lade YAML Konfiguration
        config_path = Path(__file__).parents[2] / 'config' / 'config.yaml'
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f)
        except Exception as e:
            print(f"Warnung: Konnte config.yaml nicht laden: {e}")
            self._config = {}
            
    def get(self, key: str, default: Any = None) -> Any:
        """Holt einen Wert aus der Konfiguration.
        
        Args:
            key: Der Konfigurationsschlüssel in Dot-Notation (z.B. 'processors.youtube.max_file_size')
            default: Standardwert, falls der Schlüssel nicht existiert
            
        Returns:
            Den Konfigurationswert oder den Standardwert
        """
        try:
            value = self._config
            for k in key.split('.'):
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default 