"""
MongoDB-Verbindungsmodul.
Stellt eine Verbindung zur MongoDB her und verwaltet diese.
"""

from pymongo import MongoClient
from pymongo.database import Database
from typing import Optional, Any, Set
import logging
import time

# Logger initialisieren
logger = logging.getLogger(__name__)

# Globale Variablen für Singleton-Pattern
_mongo_client: Optional[MongoClient[Any]] = None
_mongo_db: Optional[Database[Any]] = None
_initialized_collections: Set[str] = set()  # Speichert bereits initialisierte Collections

def get_mongodb_client() -> MongoClient[Any]:
    """
    Gibt eine Singleton-Instanz des MongoDB-Clients zurück.
    
    Returns:
        MongoClient: MongoDB-Client-Instanz
    """
    global _mongo_client
    
    if _mongo_client is None:
        # MongoDB-Konfiguration laden
        from src.core.config import Config
        config = Config()
        mongodb_config = config.get('mongodb', {})
        
        uri = mongodb_config.get('uri', 'mongodb://localhost:27017/')
        max_pool_size = mongodb_config.get('max_pool_size', 100)  # Erhöht für bessere Performance
        connect_timeout_ms = mongodb_config.get('connect_timeout_ms', 5000)
        
        logger.info(f"Verbindung zur MongoDB wird hergestellt: {uri}")
        
        # Client erstellen
        _mongo_client = MongoClient(
            uri,
            maxPoolSize=max_pool_size,
            connectTimeoutMS=connect_timeout_ms
        )
        
        # Verbindung testen
        try:
            # Ping-Befehl ausführen
            _mongo_client.admin.command('ping')
            logger.info("MongoDB-Verbindung erfolgreich hergestellt")
        except Exception as e:
            logger.error(f"Fehler bei der MongoDB-Verbindung: {str(e)}")
            raise
    
    return _mongo_client

def get_mongodb_database(db_name: Optional[str] = None) -> Database[Any]:
    """
    Gibt eine MongoDB-Datenbank zurück.
    
    Args:
        db_name: Optional, Name der Datenbank. Wenn nicht angegeben, wird der Name aus der Konfiguration verwendet.
        
    Returns:
        Database: MongoDB-Datenbank-Instanz
    """
    global _mongo_db
    
    if _mongo_db is None or db_name is not None:
        # Wenn keine Datenbank angegeben ist, verwende die aus der Konfiguration
        if db_name is None:
            from src.core.config import Config
            config = Config()
            mongodb_config = config.get('mongodb', {})
            db_name = mongodb_config.get('db_name', 'event_processing')
        
        # Client holen und Datenbank zurückgeben
        client = get_mongodb_client()
        
        if db_name is not None:
            _mongo_db = client[db_name]
            logger.debug(f"MongoDB-Datenbank ausgewählt: {db_name}")
        else:
            raise ValueError("Kein Datenbankname angegeben und keiner in der Konfiguration gefunden")
    
    return _mongo_db

def setup_mongodb_connection() -> None:
    """
    Initialisiert die MongoDB-Verbindung und richtet alle notwendigen Indizes für
    alle bekannten Prozessor-Cache-Collections ein.
    
    Diese Funktion sollte beim Serverstart aufgerufen werden, um sicherzustellen,
    dass die MongoDB-Verbindung und alle Indizes vor den ersten Requests initialisiert sind.
    """
    start_time = time.time()
    logger.info("Initialisiere MongoDB-Verbindung und Cache-Collections...")
    
    # MongoDB-Client und Datenbank initialisieren
    db = get_mongodb_database()
    
    # Liste aller bekannten Cache-Collections
    cache_collections = {
        "youtube_cache": {
            "cache_key": 1,
            "video_id": 1,
            "source_url": 1,
            "last_accessed": 1,
            "processed_at": 1
        },
        "audio_cache": {
            "cache_key": 1,
            "source_url": 1,
            "source_path": 1,
            "last_accessed": 1,
            "ttl_created_at_30d": {"expireAfterSeconds": 30 * 24 * 60 * 60}  # 30 Tage TTL
        },
        "transformer_cache": {
            "cache_key": 1,
            "template": 1,
            "source_language": 1,
            "target_language": 1,
            "model": 1,
            "last_accessed": 1,
            "cached_at": 1,
            "ttl_created_at_30d": {"expireAfterSeconds": 30 * 24 * 60 * 60}  # 30 Tage TTL
        },
        "video_cache": {
            "cache_key": 1,
            "source_url": 1,
            "last_accessed": 1
        },
        "pdf_cache": {
            "cache_key": 1,
            "file_hash": 1,
            "last_accessed": 1
        },
        "imageocr_cache": {
            "cache_key": 1,
            "file_hash": 1,
            "last_accessed": 1
        }
    }
    
    # Initialisiere alle Cache-Collections und deren Indizes
    for collection_name, indexes in cache_collections.items():
        collection = db[collection_name]
        _initialized_collections.add(collection_name)
        
        # Vorhandene Indizes abrufen
        try:
            existing_indexes = collection.index_information()
            logger.debug(f"Vorhandene Indizes für {collection_name}: {list(existing_indexes.keys())}")
            
            # Prüfen, ob alle benötigten Indizes vorhanden sind
            if len(existing_indexes) > 1:  # Mehr als nur der Standard-_id-Index
                logger.debug(f"Indizes für {collection_name} existieren bereits")
                continue
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Index-Informationen für '{collection_name}': {str(e)}")
            continue
        
        # Indizes erstellen
        try:
            for index_name, index_spec in indexes.items():
                if isinstance(index_spec, dict) and "expireAfterSeconds" in index_spec:
                    # TTL-Index mit expireAfterSeconds
                    expire_seconds = index_spec.pop("expireAfterSeconds")
                    collection.create_index(
                        [(index_name, 1)], 
                        expireAfterSeconds=expire_seconds
                    )
                else:
                    # Einfache Indizes
                    collection.create_index([(index_name, 1)])
            logger.info(f"Indizes für {collection_name} erstellt")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Indizes für '{collection_name}': {str(e)}")
    
    end_time = time.time()
    logger.info(f"MongoDB-Verbindung und Indizes initialisiert in {(end_time - start_time) * 1000:.2f} ms")

def is_collection_initialized(collection_name: str) -> bool:
    """
    Prüft, ob eine Collection bereits initialisiert wurde.
    
    Args:
        collection_name: Name der zu prüfenden Collection
        
    Returns:
        bool: True, wenn die Collection bereits initialisiert wurde, sonst False
    """
    return collection_name in _initialized_collections

def close_mongodb_connection() -> None:
    """
    Schließt die MongoDB-Verbindung.
    """
    global _mongo_client, _mongo_db, _initialized_collections
    
    if _mongo_client is not None:
        logger.info("MongoDB-Verbindung wird geschlossen")
        _mongo_client.close()
        _mongo_client = None
        _mongo_db = None
        _initialized_collections.clear() 