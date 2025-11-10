"""
@fileoverview Processor Cache - Generic cache class for processor results

@description
Generic cache class for processors. This class provides a simple interface for
storing and loading processing results from various processors.

Main functionality:
- Store processor results with metadata
- Load cached results by cache key
- Cache file management (JSON + associated files)
- Automatic cache cleanup (TTL-based)
- Cache key generation from input parameters

Features:
- Generic type support (TypeVar)
- File-based caching (JSON + files)
- TTL-based cache expiration
- Automatic cleanup of expired entries
- Configurable cache directories per processor
- Cache metadata tracking

@module utils.processor_cache

@exports
- ProcessorCache: Generic class - Generic cache class for processor results
- CacheableResult: Protocol - Protocol for cacheable result classes

@usedIn
- Can be used by processors for file-based caching
- Alternative to MongoDB caching for simple use cases

@dependencies
- Standard: json - JSON serialization
- Standard: pathlib - File path handling
- Standard: hashlib - Cache key generation
- Standard: datetime - Timestamp handling
- Internal: src.core.config - Config for cache configuration
"""

import json
import shutil
import time
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generic, Optional, Tuple, TypeVar, Protocol, cast

from src.core.config import Config

# Protokoll für Ergebnisklassen mit to_dict und from_dict Methoden
class CacheableResult(Protocol):
    """Protokoll für Klassen, die im Cache gespeichert werden können."""
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheableResult': ...
    def to_dict(self) -> Dict[str, Any]: ...

# Typ-Variable für generische Ergebnistypen
T = TypeVar('T', bound=CacheableResult)

class ProcessorCache(Generic[T]):
    """
    Generische Cache-Klasse für Prozessoren.
    
    Diese Klasse ermöglicht das Speichern und Laden von Verarbeitungsergebnissen
    und zugehörigen Dateien für verschiedene Prozessoren.
    
    Attributes:
        processor_name: Name des Prozessors (bestimmt das Cache-Verzeichnis)
        cache_dir: Pfad zum Cache-Verzeichnis
        max_age_days: Maximales Alter der Cache-Einträge in Tagen
    """
    
    def __init__(self, processor_name: str) -> None:
        """
        Initialisiert die Cache-Klasse für einen bestimmten Prozessor.
        
        Args:
            processor_name: Name des Prozessors (z.B. 'audio', 'video')
        """
        config = Config()
        # Verwende das Cache-Verzeichnis aus der Konfiguration
        cache_base = Path(config.get('cache', {}).get('base_dir', './cache'))
        self.processor_name = processor_name
        self.cache_dir = cache_base / processor_name / "processed"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Lade Cache-Konfiguration
        self.max_age_days = config.get('cache', {}).get('max_age_days', 7)
    
    @staticmethod
    def generate_simple_key(url_or_filename: str, file_size: Optional[int] = None) -> str:
        """
        Generiert einen einfachen Cache-Schlüssel aus URL/Dateiname und optional Dateigröße.
        
        Args:
            url_or_filename: URL oder Dateiname
            file_size: Optionale Dateigröße in Bytes
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Basis-Hash aus URL oder Dateiname
        base_hash = hashlib.md5(url_or_filename.encode()).hexdigest()
        
        # Wenn Dateigröße vorhanden, in den Hash einbeziehen
        if file_size is not None:
            return hashlib.sha256(f"{base_hash}_{file_size}".encode()).hexdigest()
        
        return base_hash
        
    def _get_cache_dir(self, cache_key: str) -> Path:
        """
        Gibt das Cache-Verzeichnis für einen Schlüssel zurück.
        
        Args:
            cache_key: Der Cache-Schlüssel
            
        Returns:
            Path: Pfad zum Cache-Verzeichnis
        """
        return self.cache_dir / cache_key
        
    def _safe_delete_dir(self, dir_path: Path) -> None:
        """
        Löscht ein Verzeichnis sicher und rekursiv.
        
        Args:
            dir_path: Pfad zum zu löschenden Verzeichnis
        """
        try:
            if dir_path.exists():
                shutil.rmtree(str(dir_path))
        except Exception as e:
            print(f"Fehler beim Löschen von {dir_path}: {str(e)}")
            
    def cleanup_old_cache(self) -> None:
        """
        Löscht alte Cache-Einträge basierend auf der Konfiguration.
        """
        try:
            now = time.time()
            for cache_entry in self.cache_dir.glob("*"):
                if cache_entry.is_dir():
                    # Prüfe das Alter des Cache-Eintrags
                    entry_age = now - cache_entry.stat().st_mtime
                    max_age = self.max_age_days * 24 * 60 * 60  # Konvertiere Tage in Sekunden
                    
                    if entry_age > max_age:
                        self._safe_delete_dir(cache_entry)
        except Exception as e:
            print(f"Fehler beim Cache-Cleanup: {str(e)}")
            
    def has_cache_with_key(self, cache_key: str, required_files: Optional[list[str]] = None) -> bool:
        """
        Prüft, ob ein gültiger Cache-Eintrag für den angegebenen Schlüssel existiert.
        
        Args:
            cache_key: Der Cache-Schlüssel
            required_files: Liste der erforderlichen Dateien, die existieren müssen
            
        Returns:
            bool: True wenn ein gültiger Cache-Eintrag existiert, sonst False
        """
        cache_dir = self._get_cache_dir(cache_key)
        
        if not cache_dir.exists():
            return False
            
        # Wenn keine Dateien angegeben sind, prüfe nur, ob das Verzeichnis existiert
        if not required_files:
            return True
            
        # Prüfe, ob alle erforderlichen Dateien existieren
        return all((cache_dir / file).exists() for file in required_files)
        
    def save_cache_with_key(
        self, 
        cache_key: str,
        result: T,
        metadata: Dict[str, Any],
    ) -> None:
        """
        Speichert ein Verarbeitungsergebnis im Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            result: Das zu speichernde Ergebnis (muss to_dict() Methode haben)
            metadata: Metadaten zum Cache-Eintrag
            files: Dict mit Dateinamen und Pfaden/Bytes der zu speichernden Dateien
        """
        cache_dir = self._get_cache_dir(cache_key)
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Speichere Metadaten
        metadata.update({
            'cache_key': cache_key,
            'processor': self.processor_name,
            'created_at': datetime.now().isoformat(),
            'cache_version': '1.0.0'  # Für Cache-Invalidierung
        })
        
        with open(cache_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)
            
        # 2. Speichere Ergebnis
        with open(cache_dir / "result.json", "w", encoding="utf-8") as f:
            # Ergebnis muss to_dict() Methode haben
            json.dump(result.to_dict(), f, indent=2)
            
    def load_cache_with_key(
        self, 
        cache_key: str,
        result_class: type[T],
        required_files: Optional[list[str]] = None
    ) -> Optional[Tuple[T, Dict[str, Any]]]:
        """
        Lädt ein Verarbeitungsergebnis aus dem Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            result_class: Die Klasse des Ergebnisses (muss from_dict() Methode haben)
            required_files: Liste der erforderlichen Dateien
            
        Returns:
            Optional[Tuple[T, Dict[str, Any], Dict[str, Path]]]: 
            Tupel aus (Ergebnis, Metadaten, Dict mit Dateipfaden) oder None wenn kein Cache
        """
        if not self.has_cache_with_key(cache_key, required_files):
            return None
            
        cache_dir = self._get_cache_dir(cache_key)
        
        # 1. Lade Metadaten
        with open(cache_dir / "metadata.json", "r", encoding="utf-8") as f:
            metadata = json.load(f)
            
        # 2. Lade Ergebnis
        with open(cache_dir / "result.json", "r", encoding="utf-8") as f:
            # Klasse muss from_dict() Methode haben
            result_data = json.load(f)
            result = cast(T, result_class.from_dict(result_data))
            
        return result, metadata
        
    def invalidate_cache(self, cache_key: str) -> None:
        """
        Löscht einen Cache-Eintrag.
        
        Args:
            cache_key: Der Cache-Schlüssel
        """
        cache_dir = self._get_cache_dir(cache_key)
        
        if cache_dir.exists():
            self._safe_delete_dir(cache_dir) 