"""
Konfigurationsmanagement für die Anwendung.
"""
from typing import Dict, Any, Optional, TypedDict, cast, Union
from pathlib import Path
import os
import yaml
import logging
from logging import Logger, StreamHandler, Formatter
from .config_utils import replace_env_vars, load_dotenv

# .env-Datei laden
load_dotenv()

class ServerConfig(TypedDict):
    """Server-Konfiguration."""
    host: str
    port: int
    debug: bool
    api_port: int

class YoutubeConfig(TypedDict):
    """YouTube-Prozessor Konfiguration."""
    max_file_size: int
    max_duration: int
    temp_dir: str
    cache_dir: str
    ydl_opts: Dict[str, Any]

class AudioConfig(TypedDict):
    """Audio-Prozessor Konfiguration."""
    max_file_size: int
    segment_duration: int
    temp_dir: str
    cache_dir: str
    export_format: str

class ProcessorsConfig(TypedDict):
    """Prozessor-Konfigurationen."""
    youtube: YoutubeConfig
    audio: AudioConfig

class RateLimitingConfig(TypedDict):
    """Rate-Limiting Konfiguration."""
    enabled: bool
    requests_per_minute: int

class LoggingConfig(TypedDict):
    """Logging-Konfiguration."""
    level: str
    file: str
    max_size: int
    backup_count: int

class CacheConfig(TypedDict):
    """Cache-Konfiguration."""
    base_dir: str
    max_age_days: int
    cleanup_interval: int

class ApplicationConfig(TypedDict):
    """Gesamte Anwendungskonfiguration."""
    server: ServerConfig
    processors: Dict[str, Union[YoutubeConfig, AudioConfig]]
    rate_limiting: RateLimitingConfig
    logging: LoggingConfig
    cache: CacheConfig

class Config:
    """
    Zentrale Konfigurationsverwaltung.
    Lädt Konfiguration aus config.yaml.
    Sensitive Daten wie API-Keys werden NICHT hier verwaltet.
    """
    _instance: Optional['Config'] = None
    _logger: Optional[Logger] = None
    _config_path: Optional[Path] = None
    
    # Standard-Konfiguration
    DEFAULT_CONFIG: ApplicationConfig = {
        'server': {
            'host': '0.0.0.0',
            'port': 5000,
            'debug': False,
            'api_port': 5001
        },
        'cache': {
            'base_dir': './cache',  # Basis-Verzeichnis für alle Caches
            'max_age_days': 7,      # Standard-Aufbewahrungszeit
            'cleanup_interval': 24   # Cleanup-Intervall in Stunden
        },
        'processors': {
            'youtube': {
                'max_file_size': 120000000,  # 120 MB
                'max_duration': 3600,        # 1 Stunde
                'temp_dir': 'cache/video/temp',  # Neuer Pfad
                'cache_dir': 'cache/video/processed',  # Neuer Cache-Pfad
                'ydl_opts': {
                    'format': 'bestaudio/best'
                }
            },
            'audio': {
                'max_file_size': 120000000,  # 120 MB
                'segment_duration': 300,      # 5 Minuten
                'temp_dir': 'cache/audio/temp',  # Neuer Pfad
                'cache_dir': 'cache/audio/processed',  # Neuer Cache-Pfad
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
    
    def __new__(cls) -> 'Config':
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Initialisiert die Konfiguration und setzt den Logger auf."""
        if self._logger is None:
            self._setup_basic_logger()
            self._config_path = Path(os.path.dirname(__file__)) / '..' / '..' / 'config' / 'config.yaml'
            if self._logger:  # Expliziter Check nach dem Setup
                self._logger.info("Config Manager initialisiert")
    
    def _setup_basic_logger(self) -> None:
        """Initialisiert einen einfachen Logger für die Konfiguration."""
        if self._logger is None:
            self._logger = logging.getLogger('config')
            self._logger.setLevel(logging.INFO)
            
            console_handler = StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            console_handler.setFormatter(formatter)
            
            self._logger.addHandler(console_handler)
    
    def _read_config(self) -> ApplicationConfig:
        """
        Liest die aktuelle Konfiguration aus der YAML-Datei.
        Ersetzt Umgebungsvariablen in der Konfiguration.
        
        Returns:
            ApplicationConfig: Die geladene Konfiguration
        """
        try:
            if not self._config_path:
                raise ValueError("Config path not initialized")
                
            with open(self._config_path, 'r', encoding='utf-8') as f:
                yaml_content = yaml.safe_load(f)
            
            # Stelle sicher, dass wir ein Dictionary haben
            if not isinstance(yaml_content, dict):
                yaml_content = {}
                
            # Explizite Typisierung für den Linter
            loaded_config: Dict[str, Any] = yaml_content
                
            # Ersetze Umgebungsvariablen in der Konfiguration
            config_with_env_vars = replace_env_vars(loaded_config)
            
            # Explizites Casting für den Typchecker
            processed_config: Dict[str, Any] = cast(Dict[str, Any], config_with_env_vars)
            
            # Kombiniere mit Standard-Konfiguration
            return cast(ApplicationConfig, {**self.DEFAULT_CONFIG, **processed_config})
        except Exception as e:
            if self._logger:
                self._logger.error(f"Fehler beim Laden der Konfiguration: {str(e)}")
            return self.DEFAULT_CONFIG.copy()

    def _write_config(self, config: ApplicationConfig) -> None:
        """
        Schreibt die Konfiguration in die YAML-Datei.
        
        Args:
            config: Die zu speichernde Konfiguration
        """
        try:
            if not self._config_path:
                raise ValueError("Config path not initialized")
                
            with open(self._config_path, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)
        except Exception as e:
            if self._logger:
                self._logger.error(f"Fehler beim Speichern der Konfiguration: {str(e)}")
    
    def get_all(self) -> ApplicationConfig:
        """
        Gibt die gesamte Konfiguration zurück.
        
        Returns:
            ApplicationConfig: Die komplette Konfiguration
        """
        return self._read_config()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        Gibt einen spezifischen Konfigurationswert zurück.
        
        Unterstützt Punkt-Notation für verschachtelte Werte, z.B.:
        config.get('processors.audio.max_file_size')
        
        Args:
            key: Der Schlüssel als String, kann Punkt-Notation enthalten
            default: Standardwert falls der Schlüssel nicht existiert
            
        Returns:
            Den Konfigurationswert oder den default-Wert
        """
        config: ApplicationConfig = self._read_config()
        try:
            value: Any = config
            for k in key.split('.'):
                value = value[k]
            return value
        except (KeyError, TypeError):
            if self._logger:
                self._logger.warning(f"Konfigurationsschlüssel '{key}' nicht gefunden, verwende Standardwert: {default}")
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        Setzt einen Konfigurationswert und speichert die Änderung.
        
        Args:
            key: Der Schlüssel als String, kann Punkt-Notation enthalten
            value: Der zu setzende Wert
        """
        config: ApplicationConfig = self._read_config()
        keys = key.split('.')
        # Explizite Konvertierung zu Dict
        current_dict: Dict[str, Any] = cast(Dict[str, Any], config)
        
        # Navigiere zur richtigen Stelle in der verschachtelten Struktur
        for k in keys[:-1]:
            if k not in current_dict:
                current_dict[k] = {}
            current_dict = current_dict[k]
        
        # Setze den Wert
        current_dict[keys[-1]] = value
        if self._logger:
            self._logger.info(f"Konfigurationswert gesetzt: {key}")
        
        # Speichere die Änderung
        self._write_config(config)

# Ende der Datei 