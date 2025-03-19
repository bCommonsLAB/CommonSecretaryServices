#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
MongoDB-Dokument-Analyse
------------------------
Dieses Skript untersucht die Struktur von Dokumenten in der MongoDB-Datenbank,
um zu verstehen, wo die Topic-Informationen gespeichert sind.
"""

import os
import sys
import logging
import yaml
import json
from bson import ObjectId, json_util
from pymongo import MongoClient
from dotenv import load_dotenv

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config():
    """
    Lädt die Konfiguration aus der config.yaml-Datei.
    """
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.yaml')
        logger.info(f"Lade Konfiguration aus: {config_path}")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            logger.info("Konfiguration erfolgreich geladen.")
            return config
    except Exception as e:
        logger.error(f"Fehler beim Laden der Konfiguration: {e}")
        return {}


def get_mongodb_connection():
    """
    Stellt eine Verbindung zur MongoDB her.
    Verwendet die MONGODB_URI aus der .env-Datei und den Datenbanknamen aus config.yaml.
    """
    # Lade Umgebungsvariablen aus .env-Datei
    load_dotenv()
    
    # Lade Konfiguration
    config = load_config()
    
    # Hole MONGODB_URI aus Umgebungsvariablen
    mongodb_uri = os.getenv("MONGODB_URI")
    
    if not mongodb_uri:
        mongodb_uri = "mongodb://localhost:27017"
        logger.warning(f"MONGODB_URI nicht gefunden. Verwende Standard-URI: {mongodb_uri}")
    else:
        logger.info("MONGODB_URI aus .env-Datei geladen.")
    
    # Hole Datenbanknamen aus der Konfiguration
    db_name = config.get("mongodb", {}).get("db_name", "common-secretary-service")
    logger.info(f"Verwende Datenbanknamen aus config.yaml: {db_name}")
    
    # Verbindung zur MongoDB herstellen
    client = MongoClient(mongodb_uri)
    
    logger.info(f"Verbindung zur Datenbank '{db_name}' hergestellt.")
    
    return client[db_name]


def examine_document(db, collection_name, document_id=None):
    """
    Untersucht ein Dokument in der angegebenen Collection.
    
    Args:
        db: MongoDB-Datenbankinstanz
        collection_name: Name der Collection
        document_id: ID des zu untersuchenden Dokuments (optional)
    """
    collection = db[collection_name]
    
    # Mit ID nach einem Dokument suchen
    if document_id:
        try:
            object_id = ObjectId(document_id)
            document = collection.find_one({"_id": object_id})
            if document:
                logger.info(f"Dokument mit ID {document_id} gefunden.")
                return document
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der ObjectId: {e}")
    
    # Beliebiges Dokument mit topic Feld in verschiedenen Pfaden suchen
    for path in ["data.topic", "data.result.topic", "result.topic"]:
        logger.info(f"Suche nach Dokument mit Feld: {path}")
        document = collection.find_one({path: {"$exists": True, "$ne": None}})
        if document:
            logger.info(f"Dokument mit Pfad {path} gefunden.")
            return document
    
    # Wenn kein Dokument mit topic gefunden wurde, einfach irgendein Dokument zurückgeben
    document = collection.find_one()
    if document:
        logger.info("Ein Dokument ohne topic gefunden.")
        return document
    
    logger.warning(f"Keine Dokumente in der Collection '{collection_name}' gefunden.")
    return None


def show_document_structure(document, max_level=3, current_level=0, path=""):
    """
    Zeigt die Struktur eines Dokuments rekursiv an.
    
    Args:
        document: Das zu untersuchende Dokument
        max_level: Maximale Tiefe der Rekursion
        current_level: Aktuelle Tiefe der Rekursion
        path: Aktueller Pfad im Dokument
    """
    if current_level >= max_level:
        return
    
    if isinstance(document, dict):
        for key, value in document.items():
            current_path = f"{path}.{key}" if path else key
            
            if isinstance(value, (dict, list)):
                if isinstance(value, dict) and len(value) > 0:
                    print(f"{'  ' * current_level}{current_path}: <dict> mit {len(value)} Elementen")
                    show_document_structure(value, max_level, current_level + 1, current_path)
                elif isinstance(value, list) and len(value) > 0:
                    print(f"{'  ' * current_level}{current_path}: <list> mit {len(value)} Elementen")
                    if len(value) > 0 and isinstance(value[0], (dict, list)):
                        show_document_structure(value[0], max_level, current_level + 1, f"{current_path}[0]")
            else:
                # Bei Strings nur einen Teil anzeigen, wenn sie zu lang sind
                if isinstance(value, str) and len(value) > 50:
                    print(f"{'  ' * current_level}{current_path}: '{value[:50]}...' (Typ: {type(value).__name__})")
                else:
                    print(f"{'  ' * current_level}{current_path}: {value} (Typ: {type(value).__name__})")
    elif isinstance(document, list) and len(document) > 0:
        for i, item in enumerate(document[:3]):  # Nur die ersten 3 Elemente
            if i >= 3:
                print(f"{'  ' * current_level}... und {len(document) - 3} weitere Elemente")
                break
            
            if isinstance(item, (dict, list)):
                show_document_structure(item, max_level, current_level + 1, f"{path}[{i}]")
            else:
                # Bei Strings nur einen Teil anzeigen, wenn sie zu lang sind
                if isinstance(item, str) and len(item) > 50:
                    print(f"{'  ' * current_level}{path}[{i}]: '{item[:50]}...' (Typ: {type(item).__name__})")
                else:
                    print(f"{'  ' * current_level}{path}[{i}]: {item} (Typ: {type(item).__name__})")


def search_path(document, target_key, current_path=""):
    """
    Sucht rekursiv nach einem Schlüssel im Dokument und gibt dessen Pfad zurück.
    
    Args:
        document: Das zu durchsuchende Dokument
        target_key: Der gesuchte Schlüssel
        current_path: Der aktuelle Pfad im Dokument
    
    Returns:
        list: Liste der gefundenen Pfade
    """
    paths = []
    
    if isinstance(document, dict):
        for key, value in document.items():
            new_path = f"{current_path}.{key}" if current_path else key
            
            # Prüfen, ob der aktuelle Schlüssel der gesuchte ist
            if key == target_key:
                paths.append(new_path)
            
            # Rekursiv weitersuchem, falls Wert ein dict oder eine Liste ist
            if isinstance(value, (dict, list)):
                paths.extend(search_path(value, target_key, new_path))
                
    elif isinstance(document, list):
        for i, item in enumerate(document):
            new_path = f"{current_path}[{i}]"
            
            if isinstance(item, (dict, list)):
                paths.extend(search_path(item, target_key, new_path))
    
    return paths


def count_documents_with_path(db, collection_name, path, display_stats=True):
    """
    Zählt die Anzahl der Dokumente mit einem bestimmten Pfad.
    
    Args:
        db: MongoDB-Datenbankinstanz
        collection_name: Name der Collection
        path: Der zu prüfende Pfad
        display_stats: True, wenn Statistiken angezeigt werden sollen
    
    Returns:
        int: Anzahl der gefundenen Dokumente
    """
    collection = db[collection_name]
    count = collection.count_documents({path: {"$exists": True, "$ne": None}})
    
    if display_stats:
        total = collection.count_documents({})
        logger.info(f"Dokumente mit {path}: {count} von {total} ({round(count/total*100 if total > 0 else 0, 2)}%)")
    
    return count


def main():
    """
    Hauptfunktion zur Ausführung des Skripts.
    """
    logger.info("Starte MongoDB-Dokument-Analyse...")
    
    # Datenbankverbindung herstellen
    db = get_mongodb_connection()
    
    # Optionale ID für ein spezifisches Dokument
    document_id = None
    if len(sys.argv) > 1:
        document_id = sys.argv[1]
        logger.info(f"Verwende übergebene ID: {document_id}")
    
    # Document aus session_cache untersuchen
    document = examine_document(db, "session_cache", document_id)
    
    if not document:
        logger.error("Kein Dokument gefunden. Beende Skript.")
        return
    
    # Dokument-ID anzeigen
    doc_id = str(document.get("_id", "Keine ID"))
    logger.info(f"Dokument-ID: {doc_id}")
    
    # Struktur des Dokuments anzeigen
    print("\n--- Dokument-Struktur ---")
    show_document_structure(document)
    
    # Nach dem "topic"-Schlüssel suchen
    print("\n--- Suche nach 'topic' ---")
    topic_paths = search_path(document, "topic")
    
    if topic_paths:
        logger.info(f"Topic-Schlüssel gefunden unter folgenden Pfaden:")
        for path in topic_paths:
            logger.info(f"  - {path}")
    else:
        logger.warning("Kein 'topic' Schlüssel im Dokument gefunden.")
    
    # Statistiken zu den Dokumenten anzeigen
    print("\n--- Collection-Statistiken ---")
    
    # Prüfen häufig vorkommende Pfade
    common_paths = ["data.topic", "data.result.topic", "result.topic"]
    found_paths = []
    
    for path in common_paths:
        count = count_documents_with_path(db, "session_cache", path)
        if count > 0:
            found_paths.append((path, count))
    
    # Sortieren nach Anzahl
    found_paths.sort(key=lambda x: x[1], reverse=True)
    
    if found_paths:
        logger.info("Häufigste Pfade für 'topic':")
        for path, count in found_paths:
            logger.info(f"  - {path}: {count} Dokumente")
    
    # Wenn das Dokument einen topic-Wert enthält, diesen anzeigen
    for path, _ in found_paths:
        # Den Pfad in Teile aufteilen
        parts = path.split(".")
        value = document
        
        # Durch den Pfad navigieren
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
        
        if value:
            logger.info(f"Beispiel-Topic in Pfad '{path}': {value}")
            break
    
    logger.info("MongoDB-Dokument-Analyse abgeschlossen.")


if __name__ == "__main__":
    main() 