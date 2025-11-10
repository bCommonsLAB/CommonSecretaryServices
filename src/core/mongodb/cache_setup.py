"""
@fileoverview MongoDB Cache Setup - Setup script for MongoDB cache collections and indexes

@description
Setup script for MongoDB cache collections and indexes. This module provides functions
to initialize and configure MongoDB cache collections for all processors that support
caching. Creates necessary indexes for performance optimization.

Main functionality:
- Creates cache collections for all processors
- Sets up TTL indexes for automatic cache expiration
- Creates performance indexes (cache_key, created_at)
- Configurable index creation (can be disabled)
- Supports force recreation of indexes

Features:
- Automatic collection creation
- TTL-based cache expiration
- Performance-optimized indexes
- Configurable via config.yaml
- Error handling and logging

@module core.mongodb.cache_setup

@exports
- setup_cache_collections(): Dict[str, List[str]] - Sets up all cache collections
- setup_mongodb_caching(): None - Main setup function for MongoDB caching

@usedIn
- src.dashboard.app: Calls setup_mongodb_caching on app initialization
- Cache initialization: Used during application startup

@dependencies
- External: pymongo - MongoDB driver for Python
- Internal: src.core.config - Config for cache configuration
- Internal: src.core.mongodb.connection - get_mongodb_database
- Internal: src.utils.logger - Logging system
"""
from typing import Dict, List, Optional, Any
from pymongo import IndexModel, ASCENDING
from pymongo.errors import CollectionInvalid
from pymongo.collection import Collection
from pymongo.database import Database

from src.core.config import Config
from src.core.mongodb.connection import get_mongodb_database
from src.utils.logger import get_logger

# Logger initialisieren
logger = get_logger(process_id="cache-setup")

def setup_cache_collections(force_recreate: bool = False) -> Dict[str, List[str]]:
    """
    Richtet alle notwendigen Cache-Collections mit Indizes ein.
    
    Args:
        force_recreate: Wenn True, werden Indizes neu erstellt, selbst wenn sie bereits existieren
        
    Returns:
        Dict[str, List[str]]: Dictionary mit Collection-Namen als Schlüssel und Liste der erstellten Indizes als Werte
    """
    logger.debug("=== CACHE SETUP: Starte Cache-Collections-Setup ===")
    
    # Ergebnis-Objekt
    results: Dict[str, List[str]] = {}
    
    try:
        # Konfiguration laden
        config = Config()
        cache_config = config.get('cache', {})
        mongodb_config = cache_config.get('mongodb', {})
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Fehler beim Laden der Konfiguration: {str(e)}")
        return results
        
    # Prüfen, ob MongoDB-Caching aktiviert ist
    if not mongodb_config.get('enabled', False):
        logger.debug("MongoDB-Caching ist deaktiviert, überspringe Cache-Collections-Setup")
        return results
        
    # Prüfen, ob Index-Erstellung aktiviert ist
    if not mongodb_config.get('create_indexes', True):
        logger.debug("MongoDB-Index-Erstellung ist deaktiviert, überspringe Cache-Collections-Setup")
        return results
    
    # Versuche, die Datenbank zu verbinden
    try:
        db: Database[Dict[str, Any]] = get_mongodb_database()
        logger.debug("MongoDB-Verbindung hergestellt")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Konnte keine Verbindung zur MongoDB herstellen: {str(e)}")
        return results
    
    # Konfiguration laden
    try:
        config = Config()
        cache_config = config.get('cache', {})
        mongodb_cache_config = cache_config.get('mongodb', {})
        logger.debug(f"Cache-Konfiguration geladen: {mongodb_cache_config}")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Fehler beim Laden der Konfiguration: {str(e)}")
        return results
    
    # Prüfen, ob MongoDB-Caching aktiviert ist
    if not mongodb_cache_config.get('enabled', True):
        logger.debug("MongoDB-Caching ist deaktiviert, überspringe Collection-Setup")
        return results
    
    # Definiere die benötigten Collections mit ihren Indizes
    collections_config = {
        "video_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("source_url", ASCENDING)])
            # created_at wird als TTL-Index erstellt
            # last_accessed wird als normaler Index erstellt
        ],
        "audio_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("source_url", ASCENDING)])
        ],
        "transformer_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("target_language", ASCENDING)])
        ],
        "track_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("track_id", ASCENDING)])
        ],
        "notion_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("page_id", ASCENDING)])
        ],
        "metadata_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("url", ASCENDING)])
        ],
        "imageocr_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("image_url", ASCENDING)])
        ],
        "pdf_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("pdf_url", ASCENDING)])
        ]
    }
    
    logger.debug(f"Einzurichtende Collections: {list(collections_config.keys())}")
    
    # Collections erstellen und Indizes einrichten
    for coll_name, indices in collections_config.items():
        logger.debug(f"=== Verarbeite Collection: {coll_name} ===")
        # Collection erstellen, wenn sie nicht existiert
        try:
            existing_collections = db.list_collection_names()
            logger.debug(f"Vorhandene Collections: {existing_collections}")
            
            if force_recreate and coll_name in existing_collections:
                logger.debug(f"Lösche bestehende Collection '{coll_name}'")
                db.drop_collection(coll_name)
                
            if coll_name not in db.list_collection_names():
                logger.debug(f"Erstelle Collection '{coll_name}'")
                db.create_collection(coll_name)
            else:
                logger.debug(f"Collection '{coll_name}' existiert bereits")
        except CollectionInvalid as e:
            logger.debug(f"Collection '{coll_name}' existiert bereits (CollectionInvalid): {str(e)}")
        except Exception as e:
            logger.error(f"CACHE SETUP ERROR: Unerwarteter Fehler bei Collection '{coll_name}': {str(e)}")
            continue
        
        # Erstelle Indizes
        try:
            collection = db[coll_name]
            logger.debug(f"Collection-Objekt erhalten: {collection}")
            
            # Erstelle last_accessed Index separat
            try:
                logger.debug(f"Erstelle last_accessed Index für '{coll_name}'")
                last_accessed_index = collection.create_index([("last_accessed", ASCENDING)])
                logger.debug(f"last_accessed Index '{last_accessed_index}' für '{coll_name}' erstellt")
            except Exception as e:
                logger.warning(f"Fehler beim Erstellen des last_accessed Index für '{coll_name}': {str(e)}")
            
            # Erstelle die definierten Indizes
            index_names: List[str] = []
            for i, index in enumerate(indices):
                try:
                    logger.debug(f"Erstelle Index {i+1}/{len(indices)} für '{coll_name}'")
                    index_result = collection.create_index(
                        index.document["key"], 
                        unique=index.document.get("unique", False)
                    )
                    index_names.append(index_result)
                    logger.debug(f"Index '{index_result}' für '{coll_name}' erfolgreich erstellt")
                except Exception as e:
                    logger.error(f"CACHE SETUP ERROR: Fehler beim Erstellen von Index für '{coll_name}': {str(e)}")
            
            results[coll_name] = index_names
            logger.debug(f"Indizes für '{coll_name}' erstellt: {index_names}")
        except Exception as e:
            logger.error(f"CACHE SETUP ERROR: Fehler beim Zugriff auf Collection '{coll_name}': {str(e)}")
    
    logger.debug(f"=== CACHE SETUP: Cache-Collections-Setup abgeschlossen: {len(results)} Collections eingerichtet ===")
    return results

def create_ttl_index(collection: Collection[Dict[str, Any]], field: str, expire_after_seconds: int, max_retries: int = 3) -> bool:
    """
    Erstellt einen TTL-Index mit Retry-Logik.
    
    Args:
        collection: MongoDB Collection
        field: Feld für den TTL-Index
        expire_after_seconds: TTL in Sekunden
        max_retries: Maximale Anzahl von Versuchen
        
    Returns:
        bool: True wenn erfolgreich, False wenn fehlgeschlagen
    """
    import time
    from pymongo.errors import OperationFailure
    
    for attempt in range(max_retries):
        try:
            # Prüfe ob Collection existiert
            database: Database[Dict[str, Any]] = collection.database  # Explizite Typ-Annotation hinzufügen
            if collection.name not in database.list_collection_names():
                logger.warning(f"Collection {collection.name} existiert nicht")
                return False
                
            # Hole existierende Indizes
            index_info = collection.index_information()
            
            # Lösche existierende TTL-Indizes
            for idx_name in list(index_info.keys()):
                if idx_name.startswith("ttl_") or idx_name == f"{field}_1":
                    try:
                        logger.debug(f"Lösche existierenden Index {idx_name}")
                        collection.drop_index(idx_name)
                    except Exception as e:
                        logger.warning(f"Fehler beim Löschen von Index {idx_name}: {str(e)}")
            
            # Warte kurz zwischen Versuchen
            if attempt > 0:
                time.sleep(1)
            
            # Erstelle neuen TTL-Index
            index_name = f"ttl_{field}_{expire_after_seconds}s"
            logger.debug(f"Erstelle TTL-Index {index_name} (Versuch {attempt + 1}/{max_retries})")
            
            collection.create_index(
                [(field, ASCENDING)],
                expireAfterSeconds=expire_after_seconds,
                name=index_name,
                background=True  # Erlaubt andere Operationen während des Index-Builds
            )
            
            # Verifiziere Index-Erstellung
            new_indexes = collection.index_information()
            if index_name in new_indexes:
                logger.debug(f"TTL-Index {index_name} erfolgreich erstellt")
                return True
            else:
                logger.warning(f"Index {index_name} wurde nicht erstellt")
                
        except OperationFailure as e:
            logger.warning(f"OperationFailure beim Versuch {attempt + 1}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(1)
                continue
            else:
                logger.error(f"TTL-Index-Erstellung nach {max_retries} Versuchen fehlgeschlagen")
                return False
                
        except Exception as e:
            logger.error(f"Unerwarteter Fehler bei TTL-Index-Erstellung: {str(e)}")
            return False
            
    return False

def create_ttl_indexes(ttl_days: Optional[int] = None) -> None:
    """
    Erstellt TTL-Indizes für die Cache-Collections.
    
    Args:
        ttl_days: Optional, Anzahl der Tage, nach denen Dokumente automatisch gelöscht werden sollen
    """
    logger.debug("=== CACHE SETUP: Starte Einrichtung der TTL-Indizes ===")
    
    try:
        db: Database[Dict[str, Any]] = get_mongodb_database()
        logger.debug("MongoDB-Verbindung für TTL-Indizes hergestellt")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Konnte keine Verbindung zur MongoDB herstellen: {str(e)}")
        return
    
    # Konfiguration laden
    try:
        config = Config()
        cache_config = config.get('cache', {})
        mongodb_cache_config = cache_config.get('mongodb', {})
        logger.debug(f"Cache-Konfiguration für TTL geladen: {mongodb_cache_config}")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Fehler beim Laden der Konfiguration für TTL: {str(e)}")
        return
    
    # Prüfen, ob MongoDB-Caching aktiviert ist
    if not mongodb_cache_config.get('enabled', False):
        logger.debug("MongoDB-Caching ist deaktiviert, überspringe TTL-Index-Setup")
        return
        
    # Prüfen, ob Index-Erstellung aktiviert ist
    if not mongodb_cache_config.get('create_indexes', True):
        logger.debug("MongoDB-Index-Erstellung ist deaktiviert, überspringe TTL-Index-Setup")
        return
    
    # TTL-Tage aus Konfiguration oder Parameter
    if ttl_days is None:
        ttl_days = mongodb_cache_config.get('ttl_days', 30)
    
    # Sicherstellen, dass ttl_days nicht None ist
    if ttl_days is None:
        ttl_days = 30  # Standardwert, falls in der Konfiguration nicht gesetzt
    
    logger.debug(f"TTL-Tage: {ttl_days}")
    
    # TTL in Sekunden umrechnen
    ttl_seconds = ttl_days * 24 * 60 * 60
    logger.debug(f"TTL in Sekunden: {ttl_seconds}")
    
    # Liste der Cache-Collections
    cache_collections = [
        "video_cache",
        "audio_cache",
        "transformer_cache",
        "track_cache",
        "notion_cache",
        "metadata_cache",
        "imageocr_cache",
        "pdf_cache"
    ]
    
    logger.debug(f"TTL-Indizes werden für folgende Collections erstellt: {cache_collections}")
    
    # TTL-Indizes erstellen
    for coll_name in cache_collections:
        logger.debug(f"Verarbeite TTL-Index für Collection: {coll_name}")
        try:
            collection: Collection[Dict[str, Any]] = db[coll_name]
            if create_ttl_index(collection, "created_at", ttl_seconds):
                logger.debug(f"TTL-Index für {coll_name} erfolgreich erstellt")
            else:
                logger.error(f"TTL-Index für {coll_name} konnte nicht erstellt werden")
        except Exception as e:
            logger.error(f"CACHE SETUP ERROR: Unerwarteter Fehler bei TTL-Index für '{coll_name}': {str(e)}")

    logger.debug("=== CACHE SETUP: TTL-Indizes-Setup abgeschlossen ===")

def setup_mongodb_caching(force_recreate: bool = False) -> None:
    """
    Führt alle notwendigen Setup-Schritte für das MongoDB-Caching durch.
    
    Args:
        force_recreate: Ob bestehende Collections gelöscht und neu erstellt werden sollen
    """
    logger.debug("=== CACHE SETUP: Starte vollständiges MongoDB-Cache-Setup ===")
    logger.debug(f"Force Recreate: {force_recreate}")
    
    setup_success = True
    
    # Zuerst Collections erstellen
    try:
        logger.debug("Starte Einrichtung der Collections...")
        setup_cache_collections(force_recreate)
        logger.debug("Einrichtung der Collections abgeschlossen")
    except Exception as e:
        setup_success = False
        logger.error(f"=== CACHE SETUP ERROR: Fehler beim Einrichten der Collections: {str(e)} ===")
        import traceback
        logger.error(f"Stacktrace: {traceback.format_exc()}")
    
    # Dann TTL-Indizes erstellen
    try:
        logger.debug("Starte Einrichtung der TTL-Indizes...")
        create_ttl_indexes()
        logger.debug("Einrichtung der TTL-Indizes abgeschlossen")
    except Exception as e:
        setup_success = False
        logger.error(f"=== CACHE SETUP ERROR: Fehler beim Einrichten der TTL-Indizes: {str(e)} ===")
        import traceback
        logger.error(f"Stacktrace: {traceback.format_exc()}")
    
    if setup_success:
        logger.debug("=== CACHE SETUP: MongoDB-Cache-Setup erfolgreich abgeschlossen ===")
    else:
        logger.warning("=== CACHE SETUP: MongoDB-Cache-Setup mit Fehlern abgeschlossen, Server wird trotzdem gestartet ===")

if __name__ == "__main__":
    # Für Standalone-Ausführung
    import argparse
    
    parser = argparse.ArgumentParser(description="MongoDB-Cache-Collections einrichten")
    parser.add_argument("--force", action="store_true", help="Collections neu erstellen")
    
    args = parser.parse_args()
    
    # Führe Setup aus
    logger.debug("Starte Cache-Setup als Standalone-Skript")
    setup_mongodb_caching(args.force) 