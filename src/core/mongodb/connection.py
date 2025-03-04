"""
MongoDB-Verbindungsmodul.
Stellt eine Verbindung zur MongoDB her und verwaltet diese.
"""

from pymongo import MongoClient
from pymongo.database import Database
from typing import Optional, Any
import logging

# Logger initialisieren
logger = logging.getLogger(__name__)

# Globale Variablen für Singleton-Pattern
_mongo_client: Optional[MongoClient[Any]] = None
_mongo_db: Optional[Database[Any]] = None

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
        max_pool_size = mongodb_config.get('max_pool_size', 50)
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

def close_mongodb_connection() -> None:
    """
    Schließt die MongoDB-Verbindung.
    """
    global _mongo_client, _mongo_db
    
    if _mongo_client is not None:
        logger.info("MongoDB-Verbindung wird geschlossen")
        _mongo_client.close()
        _mongo_client = None
        _mongo_db = None 