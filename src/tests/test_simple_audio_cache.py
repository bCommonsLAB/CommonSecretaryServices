"""
Test für die direkte MongoDB-Zugriffe ohne Abhängigkeit von einem vollständigen Processor.
"""
import sys
import os
import uuid
import logging
import time
from datetime import datetime
from typing import Dict, Any, List, Optional

import pymongo
from pymongo.collection import Collection

from src.core.config import Config
from src.core.mongodb.connection import get_mongodb_database

# Logger einrichten
logger = logging.getLogger("test_simple_audio_cache")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def setup_cache_collection() -> Collection:
    """
    Richtet die MongoDB-Collection für den Test ein.
    
    Returns:
        Collection: Die MongoDB-Collection
    """
    # Konfiguration laden
    config = Config()
    config_data = config.get_all()
    
    # MongoDB-Verbindung herstellen
    mongodb_uri = config_data.get('mongodb', {}).get('connection_string', 'mongodb://localhost:27017')
    logger.info(f"MongoDB-Verbindungsstring gefunden: {mongodb_uri}")
    
    # Datenbank abrufen
    db = get_mongodb_database()
    
    # Collection für Audio-Cache
    collection_name = "audio_cache"
    
    # Collection erstellen oder abrufen
    try:
        db.create_collection(collection_name)
        logger.info(f"Collection '{collection_name}' erstellt")
    except pymongo.errors.CollectionInvalid:
        logger.info(f"Collection '{collection_name}' existiert bereits")
    
    collection = db[collection_name]
    
    # Index für Cache-Key erstellen
    collection.create_index([("cache_key", pymongo.ASCENDING)], unique=True, name="cache_key_1")
    logger.info(f"Index 'cache_key_1' für '{collection_name}' erstellt")
    
    # Index für Quellpfad erstellen
    collection.create_index([("source_path", pymongo.ASCENDING)], name="source_path_1")
    logger.info(f"Index 'source_path_1' für '{collection_name}' erstellt")
    
    # Index für Erstellungsdatum erstellen
    collection.create_index([("created_at", pymongo.ASCENDING)], name="created_at_1")
    logger.info(f"Index 'created_at_1' für '{collection_name}' erstellt")
    
    # Index für letzten Zugriff erstellen
    collection.create_index([("last_accessed", pymongo.ASCENDING)], name="last_accessed_1")
    logger.info(f"Index 'last_accessed_1' für '{collection_name}' erstellt")
    
    return collection

def test_direct_mongodb_audio_cache() -> None:
    """
    Testet das direkte Speichern und Abrufen von Daten im MongoDB-Cache.
    """
    logger.info("Starte direkten MongoDB-Cache-Test...")
    
    # Cache-Collection einrichten
    collection = setup_cache_collection()
    
    # Testdaten erstellen
    test_key = f"test_audio_key_{uuid.uuid4()}"
    test_data = {
        "cache_key": test_key,
        "source_path": "https://example.com/test_audio.mp3",
        "created_at": datetime.now(),
        "last_accessed": datetime.now(),
        "data": {
            "metadata": {
                "title": "Test-Audio",
                "duration": 120,
                "format": "mp3",
                "sample_rate": 44100,
                "channels": 2
            },
            "segments": [
                {
                    "start": 0,
                    "end": 60,
                    "text": "Das ist ein Test-Segment."
                },
                {
                    "start": 60,
                    "end": 120,
                    "text": "Das ist ein weiteres Test-Segment."
                }
            ],
            "is_from_cache": True
        }
    }
    
    # Daten in die Collection einfügen
    try:
        result = collection.insert_one(test_data)
        logger.info(f"Speichere Test-Datensatz mit cache_key: {test_key}")
        logger.info(f"Datensatz gespeichert, ID: {result.inserted_id}")
    except Exception as e:
        logger.error(f"Fehler beim Speichern: {e}")
        return
    
    # Gespeicherten Datensatz suchen
    logger.info("Suche gespeicherten Datensatz...")
    found_data = collection.find_one({"cache_key": test_key})
    
    if found_data:
        logger.info("Datensatz gefunden:")
        logger.info(f"  Cache-Key: {found_data['cache_key']}")
        logger.info(f"  Source URL: {found_data['source_path']}")
        logger.info(f"  Created At: {found_data['created_at']}")
        
        # Prüfen, ob die Daten korrekt sind
        if found_data['data']['metadata']['title'] == "Test-Audio":
            logger.info("Daten wurden korrekt gespeichert und abgerufen.")
        else:
            logger.error("Daten stimmen nicht überein!")
    else:
        logger.error("Datensatz nicht gefunden!")
        return
    
    # Anzahl der Einträge in der Collection zählen
    count = collection.count_documents({})
    logger.info(f"Anzahl der Einträge in der {collection.name} Collection: {count}")
    
    # Erfolgsmeldung
    logger.info("MongoDB-Cache funktioniert korrekt!")
    
    # Testdaten aufräumen
    collection.delete_one({"cache_key": test_key})
    logger.info(f"Testdaten mit cache_key {test_key} wurden entfernt.")
    
    logger.info("Direkter MongoDB-Cache-Test erfolgreich.")

if __name__ == "__main__":
    logger.info("Starte Test...")
    test_direct_mongodb_audio_cache()
    logger.info("Test erfolgreich abgeschlossen") 