"""
Konfigurationsmanagement für die Anwendung.
"""
import os
import yaml
import logging
from pathlib import Path

class Config:
    """
    Zentrale Konfigurationsverwaltung.
    Lädt Konfiguration aus config.yaml.
    Sensitive Daten wie API-Keys werden NICHT hier verwaltet.
    """
    _instance = None
    _config = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._config is None:
            self._setup_basic_logger()
            self._load_config()
            self._logger.info("Konfiguration geladen")
    
    def _setup_basic_logger(self):
        """Initialisiert einen einfachen Logger für die Konfiguration."""
        if self._logger is None:
            self._logger = logging.getLogger('config')
            self._logger.setLevel(logging.INFO)
            
            # Konsolen-Handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            
            self._logger.addHandler(console_handler)
    
    def _load_config(self):
        """Lädt die Konfiguration aus config.yaml"""
        try:
            config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.yaml')
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
                
            # Setze Standard-Werte wenn nicht vorhanden
            self._config = {**self.DEFAULT_CONFIG, **self._config}
            
        except Exception as e:
            self._logger.error(f"Fehler beim Laden der Konfiguration: {str(e)}")
            self._config = self.DEFAULT_CONFIG.copy()
    
    def get_all(self):
        """Gibt die gesamte Konfiguration zurück"""
        return self._config
    
    def get(self, key, default=None):
        """Gibt einen spezifischen Konfigurationswert zurück.
        
        Unterstützt Punkt-Notation für verschachtelte Werte, z.B.:
        config.get('processors.audio.max_file_size')
        
        Args:
            key: Der Schlüssel als String, kann Punkt-Notation enthalten
            default: Standardwert falls der Schlüssel nicht existiert
            
        Returns:
            Den Konfigurationswert oder den default-Wert
        """
        try:
            value = self._config
            for k in key.split('.'):
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key, value):
        """Setzt einen Konfigurationswert"""
        self._config[key] = value
        self._logger.info(f"Konfigurationswert gesetzt: {key}")
    
    # Standard-Konfiguration
    DEFAULT_CONFIG = {
        'server': {
            'host': '0.0.0.0',
            'port': 5000,
            'debug': False
        },
        'processors': {
            'youtube': {
                'max_file_size': 104857600,  # 100 MB
                'max_duration': 3600,        # 1 Stunde
                'temp_dir': 'temp-processing/video',
                'ydl_opts': {
                    'format': 'bestaudio/best'
                }
            },
            'audio': {
                'max_file_size': 104857600,  # 100 MB
                'segment_duration': 300,      # 5 Minuten
                'temp_dir': 'temp-processing/audio',
                'export_format': 'mp3'
            }
        },
        'rate_limiting': {
            'enabled': True,
            'requests_per_minute': 60
        },
        'logging': {
            'level': 'INFO',
            'file': 'logs/detailed.log',
            'max_size': 10485760,  # 10 MB
            'backup_count': 5
        }
    } 