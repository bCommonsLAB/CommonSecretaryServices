"""
Cache-Management für Video-Verarbeitungsergebnisse. hallo 
Ermöglicht das Speichern und Laden von Video-Verarbeitungsergebnissen und zugehörigen Dateien.
"""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict

from src.core.models.video import VideoProcessingResult, VideoSource
from src.core.config import Config

@dataclass
class CacheMetadata:
    """Metadaten für Cache-Einträge"""
    video_id: str
    source_hash: str  # Hash der Quelle (URL oder Datei)
    target_language: str
    template: Optional[str]
    created_at: str
    cache_version: str = "1.0.0"  # Für Cache-Invalidierung
    is_from_cache: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert Metadaten in Dict"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'CacheMetadata':
        """Erstellt Metadaten aus Dict"""
        return cls(**data)

class VideoCache:
    """Cache-Manager für Video-Verarbeitungsergebnisse"""
    
    def __init__(self):
        config = Config()
        self.cache_dir = Path(config.get('temp_dir', '/tmp')) / "video_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
    def _generate_cache_key(self, source: VideoSource, target_language: str, template: Optional[str]) -> str:
        """Generiert einen eindeutigen Cache-Schlüssel"""
        # Hash aus URL oder Datei erstellen
        if source.url:
            source_hash = hashlib.sha256(source.url.encode()).hexdigest()
        else:
            # Bei Datei-Upload den Inhalt hashen
            source_hash = hashlib.sha256(source.file).hexdigest() if isinstance(source.file, bytes) else ""
            
        # Parameter in Hash einbeziehen
        param_str = f"{target_language}_{template or ''}"
        return hashlib.sha256(f"{source_hash}_{param_str}".encode()).hexdigest()

    def _get_cache_dir(self, cache_key: str) -> Path:
        """Gibt das Cache-Verzeichnis für einen Schlüssel zurück"""
        return self.cache_dir / cache_key

    def has_valid_cache(self, source: VideoSource, target_language: str, template: Optional[str]) -> bool:
        """Prüft ob ein gültiger Cache-Eintrag existiert"""
        cache_key = self._generate_cache_key(source, target_language, template)
        cache_dir = self._get_cache_dir(cache_key)
        
        if not cache_dir.exists():
            return False
            
        # Prüfe ob alle erforderlichen Dateien existieren
        required_files = ['metadata.json', 'result.json', 'audio.mp3']
        return all((cache_dir / file).exists() for file in required_files)

    def save(self, 
            result: VideoProcessingResult,
            source: VideoSource,
            target_language: str,
            template: Optional[str],
            audio_path: Optional[Path]) -> None:
        """Speichert Verarbeitungsergebnis im Cache"""
        cache_key = self._generate_cache_key(source, target_language, template)
        cache_dir = self._get_cache_dir(cache_key)
        cache_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Speichere Metadaten
        metadata = CacheMetadata(
            video_id=result.metadata.video_id or hashlib.md5(str(datetime.now()).encode()).hexdigest(),
            source_hash=cache_key,
            target_language=target_language,
            template=template,
            created_at=datetime.now().isoformat()
        )
        
        with open(cache_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata.to_dict(), f, indent=2)
            
        # 2. Speichere Ergebnis
        with open(cache_dir / "result.json", "w", encoding="utf-8") as f:
            # Hier müsste eine to_dict() Methode für VideoProcessingResult implementiert sein
            json.dump(result.to_dict(), f, indent=2)
            
        # 3. Kopiere Audio-Datei wenn vorhanden
        if audio_path and audio_path.exists():
            with open(cache_dir / "audio.mp3", "wb") as f:
                f.write(audio_path.read_bytes())

    def load(self, 
             source: VideoSource,
             target_language: str,
             template: Optional[str]) -> Optional[Tuple[VideoProcessingResult, Path, CacheMetadata]]:
        """
        Lädt Verarbeitungsergebnis aus dem Cache
        
        Returns:
            Optional[Tuple[VideoProcessingResult, Path, CacheMetadata]]: 
            Tupel aus Ergebnis, Audio-Pfad und Metadaten oder None wenn kein Cache
        """
        if not self.has_valid_cache(source, target_language, template):
            return None
            
        cache_key = self._generate_cache_key(source, target_language, template)
        cache_dir = self._get_cache_dir(cache_key)
        
        # 1. Lade Metadaten
        with open(cache_dir / "metadata.json", "r", encoding="utf-8") as f:
            metadata = CacheMetadata.from_dict(json.load(f))
            
        # 2. Lade Ergebnis
        with open(cache_dir / "result.json", "r", encoding="utf-8") as f:
            # Hier müsste eine from_dict() Methode für VideoProcessingResult implementiert sein
            result: VideoProcessingResult = VideoProcessingResult.from_dict(json.load(f))
            
        # 3. Audio-Pfad
        audio_path = cache_dir / "audio.mp3"
        
        return result, audio_path, metadata

    def invalidate(self, source: VideoSource, target_language: str, template: Optional[str]) -> None:
        """Löscht einen Cache-Eintrag"""
        cache_key = self._generate_cache_key(source, target_language, template)
        cache_dir = self._get_cache_dir(cache_key)
        
        if cache_dir.exists():
            for file in cache_dir.glob("*"):
                file.unlink()
            cache_dir.rmdir() 