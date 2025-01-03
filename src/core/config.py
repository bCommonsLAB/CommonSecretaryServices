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
    _logger = None
    _config_path = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if self._logger is None:
            self._setup_basic_logger()
            self._config_path = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'config.yaml')
            self._logger.info("Config Manager initialisiert")
    
    def _setup_basic_logger(self):
        """Initialisiert einen einfachen Logger für die Konfiguration."""
        if self._logger is None:
            self._logger = logging.getLogger('config')
            self._logger.setLevel(logging.INFO)
            
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            
            self._logger.addHandler(console_handler)
    
    def _read_config(self):
        """Liest die aktuelle Konfiguration aus der YAML-Datei."""
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f) or {}
            return {**self.DEFAULT_CONFIG, **config}
        except Exception as e:
            self._logger.error(f"Fehler beim Laden der Konfiguration: {str(e)}")
            return self.DEFAULT_CONFIG.copy()

    def _write_config(self, config):
        """Schreibt die Konfiguration in die YAML-Datei."""
        try:
            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            self._logger.error(f"Fehler beim Speichern der Konfiguration: {str(e)}")
    
    def get_all(self):
        """Gibt die gesamte Konfiguration zurück"""
        return self._read_config()
    
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
        config = self._read_config()
        try:
            value = config
            for k in key.split('.'):
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value):
        """Setzt einen Konfigurationswert und speichert die Änderung.
        
        Args:
            key: Der Schlüssel als String, kann Punkt-Notation enthalten
            value: Der zu setzende Wert
        """
        config = self._read_config()
        keys = key.split('.')
        current = config
        
        # Navigiere zur richtigen Stelle in der verschachtelten Struktur
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        
        # Setze den Wert
        current[keys[-1]] = value
        self._logger.info(f"Konfigurationswert gesetzt: {key}")
        
        # Speichere die Änderung
        self._write_config(config)
    
    # Standard-Konfiguration
    DEFAULT_CONFIG = {
        'server': {
            'host': '0.0.0.0',
            'port': 5000,
            'debug': False,
            'api_port': 5001  # API Port für interne Kommunikation
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

# Ende der Datei 