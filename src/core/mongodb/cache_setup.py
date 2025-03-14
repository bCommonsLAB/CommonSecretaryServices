"""
Setup-Skript für MongoDB-Cache-Collections und -Indizes.
"""
from typing import Dict, List, Optional
from pymongo import IndexModel, ASCENDING
from pymongo.errors import CollectionInvalid

from src.core.config import Config
from src.core.mongodb.connection import get_mongodb_database
from src.utils.logger import get_logger

# Logger initialisieren
logger = get_logger(process_id="cache-setup")

def setup_cache_collections(force_recreate: bool = False) -> Dict[str, List[str]]:
    """
    Richtet die Cache-Collections und deren Indizes in MongoDB ein.
    
    Args:
        force_recreate: Ob bestehende Collections gelöscht und neu erstellt werden sollen
        
    Returns:
        Dictionary mit Collection-Namen und erstellten Indizes
    """
    logger.info("=== CACHE SETUP: Starte Einrichtung der Cache-Collections ===")
    logger.info(f"Force Recreate: {force_recreate}")
    
    try:
        db = get_mongodb_database()
        logger.info("MongoDB-Verbindung hergestellt")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Konnte keine Verbindung zur MongoDB herstellen: {str(e)}")
        return {}
    
    # Konfiguration laden
    try:
        config = Config()
        cache_config = config.get('cache', {})
        mongodb_cache_config = cache_config.get('mongodb', {})
        logger.info(f"Cache-Konfiguration geladen: {mongodb_cache_config}")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Fehler beim Laden der Konfiguration: {str(e)}")
        return {}
    
    # Prüfen, ob MongoDB-Caching aktiviert ist
    if not mongodb_cache_config.get('enabled', True):
        logger.info("MongoDB-Caching ist deaktiviert, überspringe Collection-Setup")
        return {}
    
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
        "event_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("event_id", ASCENDING)])
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
    
    logger.info(f"Einzurichtende Collections: {list(collections_config.keys())}")
    
    # Ergebnisse speichern
    results: Dict[str, List[str]] = {}
    
    # Collections erstellen und Indizes einrichten
    for coll_name, indices in collections_config.items():
        logger.info(f"=== Verarbeite Collection: {coll_name} ===")
        # Collection erstellen, wenn sie nicht existiert
        try:
            existing_collections = db.list_collection_names()
            logger.info(f"Vorhandene Collections: {existing_collections}")
            
            if force_recreate and coll_name in existing_collections:
                logger.info(f"Lösche bestehende Collection '{coll_name}'")
                db.drop_collection(coll_name)
                
            if coll_name not in db.list_collection_names():
                logger.info(f"Erstelle Collection '{coll_name}'")
                db.create_collection(coll_name)
            else:
                logger.info(f"Collection '{coll_name}' existiert bereits")
        except CollectionInvalid as e:
            logger.info(f"Collection '{coll_name}' existiert bereits (CollectionInvalid): {str(e)}")
        except Exception as e:
            logger.error(f"CACHE SETUP ERROR: Unerwarteter Fehler bei Collection '{coll_name}': {str(e)}")
            continue
        
        # Erstelle Indizes
        try:
            collection = db[coll_name]
            logger.info(f"Collection-Objekt erhalten: {collection}")
            
            # Erstelle last_accessed Index separat
            try:
                logger.info(f"Erstelle last_accessed Index für '{coll_name}'")
                last_accessed_index = collection.create_index([("last_accessed", ASCENDING)])
                logger.info(f"last_accessed Index '{last_accessed_index}' für '{coll_name}' erstellt")
            except Exception as e:
                logger.warning(f"Fehler beim Erstellen des last_accessed Index für '{coll_name}': {str(e)}")
            
            # Erstelle die definierten Indizes
            index_names: List[str] = []
            for i, index in enumerate(indices):
                try:
                    logger.info(f"Erstelle Index {i+1}/{len(indices)} für '{coll_name}'")
                    index_result = collection.create_index(
                        index.document["key"], 
                        unique=index.document.get("unique", False)
                    )
                    index_names.append(index_result)
                    logger.info(f"Index '{index_result}' für '{coll_name}' erfolgreich erstellt")
                except Exception as e:
                    logger.error(f"CACHE SETUP ERROR: Fehler beim Erstellen von Index für '{coll_name}': {str(e)}")
            
            results[coll_name] = index_names
            logger.info(f"Indizes für '{coll_name}' erstellt: {index_names}")
        except Exception as e:
            logger.error(f"CACHE SETUP ERROR: Fehler beim Zugriff auf Collection '{coll_name}': {str(e)}")
    
    logger.info(f"=== CACHE SETUP: Cache-Collections-Setup abgeschlossen: {len(results)} Collections eingerichtet ===")
    return results

def create_ttl_indexes(ttl_days: Optional[int] = None) -> None:
    """
    Erstellt TTL-Indizes für die Cache-Collections.
    
    Args:
        ttl_days: Optional, Anzahl der Tage, nach denen Dokumente automatisch gelöscht werden sollen
    """
    logger.info("=== CACHE SETUP: Starte Einrichtung der TTL-Indizes ===")
    
    try:
        db = get_mongodb_database()
        logger.info("MongoDB-Verbindung für TTL-Indizes hergestellt")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Konnte keine Verbindung zur MongoDB herstellen: {str(e)}")
        return
    
    # Konfiguration laden
    try:
        config = Config()
        cache_config = config.get('cache', {})
        mongodb_cache_config = cache_config.get('mongodb', {})
        logger.info(f"Cache-Konfiguration für TTL geladen: {mongodb_cache_config}")
    except Exception as e:
        logger.error(f"CACHE SETUP ERROR: Fehler beim Laden der Konfiguration für TTL: {str(e)}")
        return
    
    # Prüfen, ob MongoDB-Caching aktiviert ist
    if not mongodb_cache_config.get('enabled', True):
        logger.info("MongoDB-Caching ist deaktiviert, überspringe TTL-Index-Setup")
        return
    
    # TTL-Tage aus Konfiguration oder Parameter
    if ttl_days is None:
        ttl_days = mongodb_cache_config.get('ttl_days', 30)
    
    # Sicherstellen, dass ttl_days nicht None ist
    if ttl_days is None:
        ttl_days = 30  # Standardwert, falls in der Konfiguration nicht gesetzt
    
    logger.info(f"TTL-Tage: {ttl_days}")
    
    # TTL in Sekunden umrechnen
    ttl_seconds = ttl_days * 24 * 60 * 60
    logger.info(f"TTL in Sekunden: {ttl_seconds}")
    
    # Liste der Cache-Collections
    cache_collections = [
        "video_cache",
        "audio_cache",
        "transformer_cache",
        "event_cache",
        "track_cache",
        "notion_cache",
        "metadata_cache",
        "imageocr_cache",
        "pdf_cache"
    ]
    
    logger.info(f"TTL-Indizes werden für folgende Collections erstellt: {cache_collections}")
    
    # TTL-Indizes erstellen
    for coll_name in cache_collections:
        logger.info(f"Verarbeite TTL-Index für Collection: {coll_name}")
        try:
            existing_collections = db.list_collection_names()
            if coll_name in existing_collections:
                collection = db[coll_name]
                
                # Prüfen, ob bereits ein TTL-Index existiert und diesen löschen
                try:
                    index_info = collection.index_information()
                    logger.info(f"Vorhandene Indizes für '{coll_name}': {list(index_info.keys())}")
                    
                    # Lösche alle TTL-Indizes und den created_at-Index
                    for idx_name in list(index_info.keys()):
                        if idx_name.startswith("ttl_") or idx_name == "created_at_1":
                            try:
                                logger.info(f"Lösche Index '{idx_name}' für '{coll_name}'")
                                collection.drop_index(idx_name)
                                logger.info(f"Index '{idx_name}' für '{coll_name}' erfolgreich gelöscht")
                            except Exception as e:
                                logger.warning(f"Fehler beim Löschen des Index '{idx_name}' für '{coll_name}': {str(e)}")
                except Exception as e:
                    logger.warning(f"Fehler beim Abrufen der Index-Informationen für '{coll_name}': {str(e)}")
                
                try:
                    # TTL-Index auf created_at erstellen mit eindeutigem Namen
                    ttl_index_name = f"ttl_created_at_{ttl_days}d"
                    logger.info(f"Erstelle TTL-Index '{ttl_index_name}' für '{coll_name}' mit {ttl_days} Tagen")
                    collection.create_index(
                        [("created_at", ASCENDING)],
                        expireAfterSeconds=ttl_seconds,
                        name=ttl_index_name
                    )
                    logger.info(f"TTL-Index '{ttl_index_name}' für '{coll_name}' erfolgreich erstellt (TTL: {ttl_days} Tage)")
                except Exception as e:
                    logger.error(f"CACHE SETUP ERROR: Fehler beim Erstellen des TTL-Index für '{coll_name}': {str(e)}")
            else:
                logger.warning(f"Collection '{coll_name}' existiert nicht, überspringe TTL-Index")
        except Exception as e:
            logger.error(f"CACHE SETUP ERROR: Unerwarteter Fehler bei TTL-Index für '{coll_name}': {str(e)}")

    logger.info("=== CACHE SETUP: TTL-Indizes-Setup abgeschlossen ===")

def setup_mongodb_caching(force_recreate: bool = False) -> None:
    """
    Führt alle notwendigen Setup-Schritte für das MongoDB-Caching durch.
    
    Args:
        force_recreate: Ob bestehende Collections gelöscht und neu erstellt werden sollen
    """
    logger.info("=== CACHE SETUP: Starte vollständiges MongoDB-Cache-Setup ===")
    logger.info(f"Force Recreate: {force_recreate}")
    
    setup_success = True
    
    # Zuerst Collections erstellen
    try:
        logger.info("Starte Einrichtung der Collections...")
        setup_cache_collections(force_recreate)
        logger.info("Einrichtung der Collections abgeschlossen")
    except Exception as e:
        setup_success = False
        logger.error(f"=== CACHE SETUP ERROR: Fehler beim Einrichten der Collections: {str(e)} ===")
        import traceback
        logger.error(f"Stacktrace: {traceback.format_exc()}")
    
    # Dann TTL-Indizes erstellen
    try:
        logger.info("Starte Einrichtung der TTL-Indizes...")
        create_ttl_indexes()
        logger.info("Einrichtung der TTL-Indizes abgeschlossen")
    except Exception as e:
        setup_success = False
        logger.error(f"=== CACHE SETUP ERROR: Fehler beim Einrichten der TTL-Indizes: {str(e)} ===")
        import traceback
        logger.error(f"Stacktrace: {traceback.format_exc()}")
    
    if setup_success:
        logger.info("=== CACHE SETUP: MongoDB-Cache-Setup erfolgreich abgeschlossen ===")
    else:
        logger.warning("=== CACHE SETUP: MongoDB-Cache-Setup mit Fehlern abgeschlossen, Server wird trotzdem gestartet ===")

if __name__ == "__main__":
    # Für Standalone-Ausführung
    import argparse
    
    parser = argparse.ArgumentParser(description="MongoDB-Cache-Collections einrichten")
    parser.add_argument("--force", action="store_true", help="Collections neu erstellen")
    
    args = parser.parse_args()
    
    # Führe Setup aus
    logger.info("Starte Cache-Setup als Standalone-Skript")
    setup_mongodb_caching(args.force) 