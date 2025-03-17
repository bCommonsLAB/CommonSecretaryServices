"""
Erweiterter Prozessor mit MongoDB-Caching-Funktionalität.
"""
import hashlib
from datetime import datetime, UTC, timedelta
from typing import Any, Dict, List, Optional, Tuple, cast, TypeVar, Generic, TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pymongo.collection import Collection
    from pymongo.database import Database
    from src.core.resource_tracking import ResourceCalculator
else:
    from pymongo.collection import Collection
    from pymongo.database import Database
    from src.core.resource_tracking import ResourceCalculator

from pymongo.results import DeleteResult

from core.config import ApplicationConfig
from src.core.config import Config
from src.core.models.enums import ProcessingStatus
from src.core.models.base import ProcessInfo
# Direkten Import entfernen, um zirkuläre Abhängigkeit zu vermeiden
# from src.core.mongodb.connection import get_mongodb_database
from .base_processor import BaseProcessor

# Protocol hier direkt definieren, um zyklische Imports zu vermeiden
@runtime_checkable
class CacheableResult(Protocol):
    """Protokoll für Cache-fähige Ergebnisse."""
    @property
    def status(self) -> ProcessingStatus:
        """Status des Ergebnisses."""
        ...

T = TypeVar('T', bound=CacheableResult)  # Ergebnistyp für die verschiedenen Prozessoren

# Verzögerter Import der MongoDB-Funktionen, um zirkuläre Importe zu vermeiden
def _get_mongodb_database() -> Database[Any]:
    """Verzögerter Import der MongoDB-Datenbankfunktion, um zirkuläre Importe zu vermeiden."""
    from src.core.mongodb.connection import get_mongodb_database
    return get_mongodb_database()

class CacheableProcessor(BaseProcessor[T], Generic[T]):
    """
    Basisklasse für Prozessoren mit MongoDB-Caching-Unterstützung.
    
    Der generische Typ T repräsentiert das Ergebnisobjekt, das gecached werden soll
    (z.B. AudioProcessingResult, VideoProcessingResult).
    
    Attributes:
        cache_collection_name (str): Name der MongoDB-Collection für Cache-Einträge
        cache_enabled (bool): Flag, ob Caching aktiviert ist
        cache_max_age_days (int): Maximales Alter der Cache-Einträge in Tagen
        _cache_collection (Optional[Collection[Any]]): Die MongoDB-Collection für den Cache
    """
    
    # Klassenvariable für den Collection-Namen mit Typannotation
    cache_collection_name: Optional[str] = None
    
    # Typannotationen für Instanzvariablen
    __annotations__ = {
        "_cache_collection": Optional[Collection[Any]]
    }
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den CacheableProcessor.
        
        Args:
            resource_calculator: ResourceCalculator-Instanz für Performance-Tracking
            process_id: Optional, ID für den Prozess
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        
        # Cache-Konfiguration
        config = Config()
        self.config: ApplicationConfig = config.get_all()
        
        # Standardwerte
        self.is_cache_enabled_flag = self.config.get('caching', {}).get('enabled', True)
        self.cache_max_age_days = self.config.get('caching', {}).get('max_age_days', 7)
        
        # Cache-Collection-Name nur setzen, wenn nicht bereits in der Klasse definiert
        if not hasattr(self.__class__, 'cache_collection_name') or self.__class__.cache_collection_name is None:
            self.cache_collection_name = None
        
        # Collection für Cache
        object.__setattr__(self, "_cache_collection", None)
        
        # Indizes für die Cache-Collection einrichten
        self._setup_cache_indices()
        
    def _setup_cache_indices(self) -> None:
        """
        Richtet die Indizes für die Cache-Collection ein.
        Diese Methode wurde optimiert, um die zentrale Initialisierung zu nutzen.
        """
        if not self.is_cache_enabled():
            return
            
        # Prüfen, ob ein Collection-Name definiert ist
        if not self.cache_collection_name:
            self.logger.warning("Kein Cache-Collection-Name definiert, Cache wird nicht initialisiert")
            return
        
        # Import der MongoDB-Verbindungsfunktionen
        from src.core.mongodb.connection import get_mongodb_database, is_collection_initialized
        
        # Prüfen, ob die Collection bereits initialisiert wurde
        if is_collection_initialized(self.cache_collection_name):
            self.logger.debug(f"Collection {self.cache_collection_name} bereits zentral initialisiert, überspringe Setup")
            # Nur die Collection für die Verwendung speichern
            self._cache_collection = get_mongodb_database()[self.cache_collection_name]
            return
            
        # Wenn die Collection noch nicht initialisiert ist, den alten Prozess durchführen
        try:
            # Datenbank abrufen
            db = get_mongodb_database()
            
            # Collection abrufen oder erstellen
            collection = db[self.cache_collection_name]
            
            # Standardwert für index_info, falls die Abfrage fehlschlägt
            index_info = {}
            
            # Vorhandene Indizes abrufen
            try:
                index_info = collection.index_information()
                self.logger.debug(f"Vorhandene Indizes für {self.cache_collection_name}: {list(index_info.keys())}")
                
                # Cache-Collection speichern
                self._cache_collection = collection
                
                # Wenn bereits Indizes existieren, nicht erneut erstellen
                if len(index_info) > 1:  # Mehr als nur der Standard-_id-Index
                    self.logger.debug(f"Indizes für {self.cache_collection_name} existieren bereits, überspringe Erstellung")
                    return
                    
            except Exception as e:
                self.logger.error(f"Fehler beim Abrufen der Index-Informationen für '{self.cache_collection_name}': {str(e)}")
            
            # Wenn keine Indizes vorhanden sind, erstelle sie
            try:
                # Standardindizes erstellen
                collection.create_index("cache_key")
                collection.create_index("last_accessed")
                
                # Prozessor-spezifische Indizes erstellen
                if hasattr(self, '_create_specialized_indexes') and callable(getattr(self, '_create_specialized_indexes')):
                    self._create_specialized_indexes(collection)
                
                self.logger.info(f"Indizes für {self.cache_collection_name} erstellt")
                self._cache_collection = collection
                
            except Exception as e:
                self.logger.error(f"Fehler beim Erstellen der Indizes für '{self.cache_collection_name}': {str(e)}")
        except Exception as e:
            self.logger.error(f"Fehler beim Einrichten der Cache-Collections: {str(e)}")
        
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezialisierte Indizes für den jeweiligen Prozessor-Typ.
        Diese Methode sollte von abgeleiteten Klassen überschrieben werden.
        
        Args:
            collection: Die MongoDB-Collection
        """
        pass
        
    def is_cache_enabled(self) -> bool:
        """
        Prüft, ob das Caching aktiviert ist.
        
        Returns:
            bool: True wenn Caching aktiviert ist, sonst False
        """
        return self.is_cache_enabled_flag and self.cache_collection_name is not None
        
    def generate_cache_key(self, data: str) -> str:
        """
        Generiert einen eindeutigen Cache-Schlüssel aus den Daten.
        
        Args:
            data: Die Daten, aus denen der Schlüssel generiert werden soll.
                Kann z.B. eine URL, ein Dateiname oder ein Suchbegriff sein.
        
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # SHA-256 Hash für eindeutigen Schlüssel erzeugen
        sha256 = hashlib.sha256()
        sha256.update(data.encode('utf-8'))
        return sha256.hexdigest()
        
    def get_from_cache(self, cache_key: str) -> Tuple[bool, Optional[T]]:
        """
        Lädt ein Ergebnis aus dem Cache.
        
        Args:
            cache_key: Der Cache-Schlüssel
            
        Returns:
            Tuple[bool, Optional[T]]: Tupel aus (Cache-Hit, Ergebnis oder None)
        """
        if not self.is_cache_enabled():
            return False, None
            
        if not self.cache_collection_name:
            return False, None
            
        try:
            # Datenbank abrufen
            db: Database[Any] = _get_mongodb_database()
            
            # Collection abrufen
            collection: Collection[Any] = db[self.cache_collection_name]
            
            # Cache-Eintrag abfragen
            cache_entry: Any | None = collection.find_one({"cache_key": cache_key})
            
            if cache_entry:
                # Aktualisiere letzten Zugriff
                collection.update_one(
                    {"_id": cache_entry["_id"]},
                    {"$set": {"last_accessed": datetime.now(UTC)}}
                )
                
                # Deserialisiere die Daten
                try:
                    if "data" in cache_entry:
                        cached_data = cache_entry["data"]
                        result = self.deserialize_cached_data(cached_data)
                        return True, result
                except Exception as e:
                    self.logger.error(f"Fehler beim Deserialisieren der Cache-Daten: {str(e)}")
                    # Cache-Eintrag löschen, da er nicht deserialisiert werden konnte
                    collection.delete_one({"_id": cache_entry["_id"]})
        except Exception as e:
            self.logger.error(f"Fehler beim Laden aus dem Cache: {str(e)}")
            
        return False, None
        
    def save_to_cache(self, cache_key: str, result: T) -> None:
        """
        Speichert ein Ergebnis im Cache, nur wenn es erfolgreich war.
        
        Args:
            cache_key: Der Cache-Schlüssel
            result: Das zu speichernde Ergebnis
        """
        if not self.is_cache_enabled():
            return
            
        if not self.cache_collection_name:
            return
            
        # Prüfe auf ProcessingStatus
        status: ProcessingStatus = result.status
        if status != ProcessingStatus.SUCCESS:
            self.logger.warning(f"Versuch, Ergebnis mit Status {status} zu cachen wurde verhindert")
            return
            
        try:
            # Datenbank abrufen
            db: Database[Any] = _get_mongodb_database()
            
            # Collection abrufen
            collection: Collection[Any] = db[self.cache_collection_name]
            
            # Serialisiere das Ergebnis
            serialized_data: Dict[str, Any] = self.serialize_for_cache(result)
            
            # Aktueller Zeitpunkt
            now: datetime = datetime.now(UTC)
            
            # Cache-Eintrag vorbereiten
            cache_entry: Dict[str, str | datetime | Dict[str, Any]] = {
                "cache_key": cache_key,
                "created_at": now,
                "last_accessed": now,
                "data": serialized_data,
                "status": "success"  # Expliziter Status für Cache-Einträge
            }
            
            # Cache-Eintrag speichern oder aktualisieren (Upsert)
            collection.replace_one(
                {"cache_key": cache_key},
                cache_entry,
                upsert=True
            )
            
            self.logger.debug(f"Erfolgreiches Ergebnis im Cache gespeichert: {cache_key}")
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern im Cache: {str(e)}")
            
    def invalidate_cache(self, cache_key: str) -> None:
        """
        Löscht einen Cache-Eintrag.
        
        Args:
            cache_key: Der Cache-Schlüssel
        """
        if not self.is_cache_enabled():
            return
            
        if not self.cache_collection_name:
            return
            
        try:
            # Datenbank abrufen
            db: Database[Any] = _get_mongodb_database()
            
            # Collection abrufen
            collection: Collection[Any] = db[self.cache_collection_name]
            
            # Cache-Eintrag löschen
            result: DeleteResult = collection.delete_one({"cache_key": cache_key})
            
            if result.deleted_count > 0:
                self.logger.debug(f"Cache-Eintrag gelöscht: {cache_key}")
            else:
                self.logger.debug(f"Kein Cache-Eintrag gefunden für: {cache_key}")
        except Exception as e:
            self.logger.error(f"Fehler beim Löschen aus dem Cache: {str(e)}")
    
    def cleanup_cache(self, max_age_days: Optional[int] = None) -> Dict[str, int]:
        """
        Bereinigt den Cache von alten Einträgen.
        
        Args:
            max_age_days: Optional, maximales Alter der Einträge in Tagen
            
        Returns:
            Dict[str, int]: Statistik über gelöschte Einträge
        """
        if not self.is_cache_enabled():
            return {"deleted": 0, "total": 0}
            
        if not self.cache_collection_name:
            return {"deleted": 0, "total": 0}
            
        # Verwende Standardwert, wenn nicht angegeben
        if max_age_days is None:
            max_age_days = self.cache_max_age_days
            
        # Stelle sicher, dass max_age_days nicht None ist
        if max_age_days is None:
            max_age_days = 7  # Fallback-Wert
            
        # Vor diesem Zeitpunkt erstellte Einträge werden gelöscht
        cutoff_date: datetime = datetime.now(UTC) - timedelta(days=max_age_days)
        
        try:
            # Datenbank abrufen
            db: Database[Any] = _get_mongodb_database()
            
            # Collection abrufen
            collection: Collection[Any] = db[self.cache_collection_name]
            
            # Gesamtzahl der Einträge
            total: int = collection.count_documents({})
            
            # Alte Einträge löschen
            result: DeleteResult = collection.delete_many({
                "created_at": {"$lt": cutoff_date}
            })
            
            deleted = result.deleted_count
            
            self.logger.info(
                f"Cache bereinigt: {deleted} von {total} Einträgen gelöscht "
                f"(älter als {max_age_days} Tage)"
            )
            
            return {"deleted": deleted, "total": total}
        except Exception as e:
            self.logger.error(f"Fehler bei der Cache-Bereinigung: {str(e)}")
            return {"deleted": 0, "total": 0}
    
    def serialize_for_cache(self, result: T) -> Dict[str, Any]:
        """
        Serialisiert das Ergebnis-Objekt für die Speicherung im Cache.
        Diese Methode muss von abgeleiteten Klassen überschrieben werden.
        
        Args:
            result: Das zu serialisierende Ergebnis
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        raise NotImplementedError("serialize_for_cache muss von abgeleiteten Klassen implementiert werden")
        
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> T:
        """
        Deserialisiert Daten aus dem Cache.
        Diese Methode muss von abgeleiteten Klassen überschrieben werden.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            T: Das deserialisierte Ergebnis
        """
        raise NotImplementedError("deserialize_cached_data muss von abgeleiteten Klassen implementiert werden")

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        Gibt Statistiken über den Cache für diesen Prozessor zurück.
        
        Returns:
            Dict mit Statistiken: Anzahl der Einträge, Gesamtgröße, etc.
        """
        if not self.is_cache_enabled():
            return {"enabled": False}
            
        if not self.cache_collection_name:
            return {"enabled": True, "collection": None, "entries": 0}
            
        try:
            db = _get_mongodb_database()
            collection = db[self.cache_collection_name]
            
            # Basis-Statistiken
            stats: Dict[str, Any] = {
                "collection": self.cache_collection_name,
                "processor": self.__class__.__name__,
                "enabled": self.is_cache_enabled(),
                "ttl_days": self.cache_max_age_days,
                "total_entries": collection.count_documents({}),
                "last_updated": datetime.now(UTC).isoformat()
            }
            
            # Aggregation für erweiterte Statistiken
            pipeline = [
                {
                    "$group": {
                        "_id": None,
                        "total_size": {"$sum": {"$ifNull": ["$size_bytes", 0]}},
                        "avg_size": {"$avg": {"$ifNull": ["$size_bytes", 0]}},
                        "oldest_entry": {"$min": {"$ifNull": ["$created_at", None]}},
                        "newest_entry": {"$max": {"$ifNull": ["$created_at", None]}},
                        "total_accesses": {"$sum": {"$ifNull": ["$access_count", 0]}}
                    }
                }
            ]
            
            # Aggregation ausführen
            agg_cursor = collection.aggregate(pipeline)
            agg_results: List[Dict[str, Any]] = []
            for doc in agg_cursor:
                agg_results.append(cast(Dict[str, Any], doc))
            
            # Wenn Ergebnisse vorhanden sind, zu Stats hinzufügen
            if agg_results:
                agg_data = agg_results[0]
                stats.update({
                    "total_size_bytes": agg_data.get("total_size", 0),
                    "avg_size_bytes": round(agg_data.get("avg_size", 0), 2),
                    "oldest_entry": agg_data.get("oldest_entry"),
                    "newest_entry": agg_data.get("newest_entry"),
                    "total_accesses": agg_data.get("total_accesses", 0)
                })
            
            return stats
            
        except Exception as e:
            # Bei Fehlern einfache Statistiken zurückgeben
            self.logger.error(f"Fehler beim Abrufen von Cache-Statistiken: {str(e)}")
            return {
                "collection": self.cache_collection_name,
                "processor": self.__class__.__name__,
                "enabled": self.is_cache_enabled(),
                "error": str(e)
            } 