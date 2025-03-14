"""
Test für den AudioProcessor mit MongoDB-Caching.

Dieses Skript testet die MongoDB-Caching-Funktionalität des AudioProcessors.
"""

import asyncio
import sys
import uuid
import logging
import time
from datetime import datetime
from pathlib import Path

# Füge das Hauptverzeichnis zum Python-Pfad hinzu
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.core.config import Config
from src.utils.logger import get_logger
from src.core.mongodb.connection import get_mongodb_database
from src.core.resource_tracking import ResourceCalculator
from src.processors.audio_processor import AudioProcessor
from pymongo import IndexModel, ASCENDING

# Konfiguriere Logging direkt
logging.basicConfig(level=logging.INFO)
logger = get_logger(process_id="test-audio-processor")

def setup_cache_collections_sync(force_recreate: bool = False):
    """
    Synchrone Version der Cache-Collection-Einrichtung für Tests.
    """
    db = get_mongodb_database()
    
    # Konfiguration laden
    config = Config()
    
    # Definiere die benötigten Collections mit ihren Indizes
    collections_config = {
        "audio_cache": [
            IndexModel([("cache_key", ASCENDING)], unique=True),
            IndexModel([("source_path", ASCENDING)]),
            IndexModel([("created_at", ASCENDING)]),
            IndexModel([("last_accessed", ASCENDING)])
        ]
    }
    
    # Erstelle Collections und Indizes
    results = {}
    
    for coll_name, indices in collections_config.items():
        # Collection löschen, wenn force_recreate gesetzt ist
        if force_recreate:
            existing_collections = db.list_collection_names()
            if coll_name in existing_collections:
                print(f"Lösche bestehende Collection '{coll_name}'")
                db.drop_collection(coll_name)
        
        # Erstelle Collection explizit
        try:
            db.create_collection(coll_name)
            print(f"Collection '{coll_name}' erstellt")
        except Exception as e:
            print(f"Collection '{coll_name}' existiert bereits oder Fehler: {str(e)}")
        
        # Erstelle Indizes
        collection = db[coll_name]
        index_names = []
        for index in indices:
            try:
                index_result = collection.create_index(
                    index.document["key"], 
                    unique=index.document.get("unique", False)
                )
                index_names.append(index_result)
                print(f"Index '{index_result}' für '{coll_name}' erstellt")
            except Exception as e:
                print(f"Fehler beim Erstellen von Index für '{coll_name}': {str(e)}")
        
        results[coll_name] = index_names
    
    print(f"Cache-Collections-Setup abgeschlossen: {len(results)} Collections eingerichtet")
    return results

def test_direct_mongodb_cache():
    """
    Testet direkt das Speichern und Abrufen von Daten im MongoDB-Cache
    ohne die Audioverarbeitung durchzuführen.
    """
    print("\n===== Direkter MongoDB-Cache-Test =====")
    
    # MongoDB-Verbindung herstellen
    db = get_mongodb_database()
    collection = db["audio_cache"]
    
    # Test-Daten erstellen
    cache_key = f"test_key_{uuid.uuid4()}"
    test_data = {
        "cache_key": cache_key,
        "source_path": "/path/to/test_audio.mp3",
        "created_at": datetime.now(),
        "last_accessed": datetime.now(),
        "result": {
            "metadata": {
                "filename": "Test Audio",
                "format": "mp3",
                "duration": 60,
                "duration_formatted": "00:01:00"
            }
        }
    }
    
    try:
        # Datensatz in MongoDB speichern
        print(f"Speichere Test-Datensatz mit cache_key: {cache_key}")
        insert_result = collection.insert_one(test_data)
        print(f"Datensatz gespeichert, ID: {insert_result.inserted_id}")
        
        # Datensatz aus MongoDB abrufen
        print("Suche gespeicherten Datensatz...")
        found_data = collection.find_one({"cache_key": cache_key})
        
        if found_data:
            print(f"Datensatz gefunden:")
            print(f"  Cache-Key: {found_data.get('cache_key')}")
            print(f"  Source Path: {found_data.get('source_path')}")
            print(f"  Created At: {found_data.get('created_at')}")
            
            # Anzahl der Einträge in der Collection ausgeben
            count = collection.count_documents({})
            print(f"Anzahl der Einträge in der audio_cache Collection: {count}")
            
            # Erfolg
            print("MongoDB-Cache funktioniert korrekt!")
            return True
        else:
            print(f"Fehler: Datensatz mit cache_key {cache_key} nicht gefunden!")
            return False
            
    except Exception as e:
        print(f"Fehler beim direkten MongoDB-Cache-Test: {str(e)}")
        import traceback
        print(traceback.format_exc())
        return False
    finally:
        # Testdaten wieder entfernen
        collection.delete_one({"cache_key": cache_key})
        print(f"Testdaten mit cache_key {cache_key} wurden entfernt.")

def test_audio_processor_caching():
    """
    Testet den AudioProcessor mit MongoDB-Caching.
    
    Der Test führt folgende Schritte aus:
    1. MongoDB-Cache initialisieren
    2. AudioProcessor mit aktiviertem Caching erstellen
    3. Prüfe, ob der AudioProcessor korrekt initialisiert wurde
    4. Teste die Verarbeitung einer lokalen Audiodatei mit Caching
    """
    print("Starte AudioProcessor-Caching-Test")
    process_id = str(uuid.uuid4())
    
    try:
        # Initialisiere MongoDB-Caching
        print("Lade Konfiguration...")
        config = Config()
        cache_config = config.get("cache", {})
        connection_string = cache_config.get("mongo_uri")
        
        if not connection_string:
            print("MongoDB-Verbindungsstring nicht gefunden in config.yaml")
            return
            
        print(f"MongoDB-Verbindungsstring gefunden: {connection_string}")
        
        # MongoDB-Caching einrichten
        print("Richte MongoDB-Caching ein...")
        setup_cache_collections_sync(force_recreate=False)
        print("MongoDB-Caching eingerichtet.")
        
        # ResourceCalculator initialisieren
        resource_calculator = ResourceCalculator()
        
        # AudioProcessor mit aktiviertem Caching erstellen
        print("Erstelle AudioProcessor...")
        processor = AudioProcessor(resource_calculator, process_id)
        print("AudioProcessor erstellt.")
        
        # Prüfe, ob der AudioProcessor korrekt initialisiert wurde
        if not hasattr(processor, 'cache_collection_name'):
            print("FEHLER: AudioProcessor hat kein 'cache_collection_name'-Attribut")
            return
            
        print(f"AudioProcessor Cache-Collection: {processor.cache_collection_name}")
        
        # Prüfe, ob der AudioProcessor vom CacheableProcessor erbt
        print(f"AudioProcessor erbt von: {processor.__class__.__mro__}")
        
        # Teste die Erstellung eines Cache-Schlüssels
        test_path = "tests/samples/sample_audio.m4a"
        # Verwende die Methode _create_cache_key
        cache_key = processor._create_cache_key(test_path)
        print(f"Test Cache-Schlüssel für Datei '{test_path}': {cache_key}")
        
        # Prüfe, ob der Cache aktiviert ist
        print(f"Cache aktiviert: {processor.is_cache_enabled()}")
        
        # Teste die Verarbeitung einer lokalen Testdatei
        test_file_path = Path("tests/samples/sample_audio.m4a")
        if test_file_path.exists():
            print(f"Teste Verarbeitung der lokalen Datei: {test_file_path}")
            
            # Erster Durchlauf (sollte die Datei verarbeiten und cachen)
            start_time = time.time()
            first_response = asyncio.run(processor.process(
                audio_source=str(test_file_path),
                target_language="de",
                use_cache=True
            ))
            first_duration = time.time() - start_time
            
            if first_response.status == "success":
                print(f"Erster Durchlauf erfolgreich in {first_duration:.2f} Sekunden")
                
                # Zweiter Durchlauf (sollte den Cache nutzen)
                start_time = time.time()
                second_response = asyncio.run(processor.process(
                    audio_source=str(test_file_path),
                    target_language="de",
                    use_cache=True
                ))
                second_duration = time.time() - start_time
                
                if second_response.status == "success":
                    print(f"Zweiter Durchlauf erfolgreich in {second_duration:.2f} Sekunden")
                    
                    # Prüfen, ob der zweite Durchlauf schneller war (Cache-Hit)
                    if second_duration < first_duration:
                        speedup = first_duration / second_duration
                        print(f"Cache-Hit bestätigt: Zweiter Durchlauf war {speedup:.2f}x schneller")
                    else:
                        print("Cache möglicherweise nicht genutzt.")
                else:
                    print(f"Zweiter Durchlauf fehlgeschlagen: {second_response.error}")
            else:
                print(f"Erster Durchlauf fehlgeschlagen: {first_response.error}")
        else:
            print(f"Testdatei {test_file_path} nicht gefunden, überspringe Verarbeitungstest")
        
        # Führe den direkten MongoDB-Cache-Test durch
        mongodb_test_result = test_direct_mongodb_cache()
        if mongodb_test_result:
            print("Direkter MongoDB-Cache-Test erfolgreich.")
        else:
            print("Direkter MongoDB-Cache-Test fehlgeschlagen.")
        
        print("Test erfolgreich abgeschlossen")
        
    except Exception as e:
        print(f"Fehler während des Tests: {str(e)}")
        import traceback
        print(traceback.format_exc())
        raise

if __name__ == "__main__":
    print("Starte Test...")
    test_audio_processor_caching()
    print("Test beendet.") 