#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Topic-Erstellung aus Session-Cache
-----------------------------------
Dieses Skript liest Session-Cache-Einträge aus der MongoDB-Datenbank
und erstellt daraus Topic-Einträge in der topics-Collection.
"""

import os
import sys
import logging
from datetime import datetime
import yaml
from typing import Dict, List, Optional, Any, Union
from bson import ObjectId
from pymongo import MongoClient
from pymongo.database import Database
from pymongo.collection import Collection
from dotenv import load_dotenv

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Ecosocial Themen als Referenzdaten
ECOSOCIAL_TOPICS = {
  "Energie": {
    "display_name": {"de": "Energie: Beschleunigung des Übergangs durch Open Source", "en": "Energy: Accelerating Transition Through Open Source"},
    "description": {
      "de": "Diskussionen über den Einsatz von Open-Source-Technologien zur Förderung erneuerbarer Energien und zur Unterstützung der Energiewende.",
      "en": "Discussions about using open source technologies to promote renewable energy and support the energy transition."
    },
    "keywords": ["Energie", "Erneuerbare", "Open Source", "Nachhaltigkeit", "Transition"]
  },
  "Regierungskollaboration": {
    "display_name": {"de": "Regierungskollaboration durch Open Source", "en": "Government Collaboration Through Open Source"},
    "description": {
      "de": "Erörterung der Zusammenarbeit zwischen Regierungen und Open-Source-Communities zur Förderung transparenter und partizipativer Regierungsführung.",
      "en": "Discussion of collaboration between governments and open source communities to promote transparent and participatory governance."
    },
    "keywords": ["Regierung", "Kollaboration", "Transparenz", "Partizipation", "Open Source"]
  },
  "Inklusives Web": {
    "display_name": {"de": "Inklusives Web für alle", "en": "Inclusive Web for Everyone"},
    "description": {
      "de": "Fokus auf die Entwicklung von Web-Technologien, die für alle zugänglich sind, einschließlich Menschen mit Behinderungen, um digitale Inklusion zu fördern.",
      "en": "Focus on developing web technologies accessible to everyone, including people with disabilities, to promote digital inclusion."
    },
    "keywords": ["Inklusion", "Barrierefreiheit", "Web", "Accessibility", "Digitale Teilhabe"]
  },
  "Open-Source-Design": {
    "display_name": {"de": "Open-Source-Design für nachhaltige Lösungen", "en": "Open Source Design for Sustainable Solutions"},
    "description": {
      "de": "Förderung von Designpraktiken, die auf offenen Prinzipien basieren, um benutzerzentrierte und nachhaltige Lösungen zu entwickeln.",
      "en": "Promotion of design practices based on open principles to develop user-centered and sustainable solutions."
    },
    "keywords": ["Design", "Open Source", "Nachhaltigkeit", "UX", "Benutzerzentriert"]
  },
  "offenes Design": {
    "display_name": {"de": "Offenes Design für nachhaltige Lösungen", "en": "Open Design for Sustainable Solutions"},
    "description": {
      "de": "Förderung von Designpraktiken, die auf offenen Prinzipien basieren, um benutzerzentrierte und nachhaltige Lösungen zu entwickeln.",
      "en": "Promotion of design practices based on open principles to develop user-centered and sustainable solutions."
    },
    "keywords": ["Design", "Open Source", "Nachhaltigkeit", "UX", "Benutzerzentriert"]
  },
  "Open-Source-Hardware": {
    "display_name": {"de": "Open-Source-Hardware und nachhaltige Produktion", "en": "Open Source Hardware and Sustainable Production"},
    "description": {
      "de": "Diskussionen über die Entwicklung und Verbreitung von Open-Source-Hardwarelösungen, die nachhaltige Produktion und Reparatur fördern.",
      "en": "Discussions about the development and dissemination of open source hardware solutions that promote sustainable production and repair."
    },
    "keywords": ["Hardware", "Open Source", "Nachhaltigkeit", "Produktion", "Reparierbarkeit"]
  }
}

# Zielgruppen-Definition
TARGET_GROUPS = [
  {
    "target_id": "technical",
    "display_name": {
      "de": "Technische Zielgruppe",
      "en": "Technical Audience"
    },
    "description": {
      "de": "Entwickler, Technikexperten und technisch versierte Personen",
      "en": "Developers, technical experts, and technically skilled individuals"
    },
    "status": "active"
  },
  {
    "target_id": "non_technical",
    "display_name": {
      "de": "Nicht-technische Zielgruppe",
      "en": "Non-Technical Audience"
    },
    "description": {
      "de": "Entscheidungsträger, Manager und nicht-technische Stakeholder",
      "en": "Decision makers, managers, and non-technical stakeholders"
    },
    "status": "active"
  }
]


def load_config() -> Dict[str, Any]:
    """
    Lädt die Konfiguration aus der config.yaml-Datei.
    
    Returns:
        Dict[str, Any]: Konfigurationsdaten
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


def get_mongodb_connection() -> Database:
    """
    Stellt eine Verbindung zur MongoDB her.
    Verwendet die MONGODB_URI aus der .env-Datei und den Datenbanknamen aus config.yaml.
    
    Returns:
        Database: MongoDB-Datenbankinstanz
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


def find_cache_entry(db: Database, entry_id: Optional[str] = None) -> Optional[Dict]:
    """
    Sucht nach einem bestimmten Cache-Eintrag.
    
    Args:
        db: MongoDB-Datenbankinstanz
        entry_id: ID des gesuchten Eintrags (optional)
    
    Returns:
        Optional[Dict]: Gefundener Cache-Eintrag oder None
    """
    session_cache = db.session_cache
    
    # Versuche, anhand der ID zu suchen
    if entry_id:
        try:
            object_id = ObjectId(entry_id)
            logger.info(f"Suche nach Cache-Eintrag mit _id: {entry_id}")
            entry = session_cache.find_one({"_id": object_id})
            if entry:
                return entry
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der ObjectId: {e}")
    
    # Suche nach Einträgen mit dem korrekten Pfad 'data.topic'
    logger.info("Suche nach Einträgen mit 'data.topic'...")
    entry = session_cache.find_one({"data.topic": {"$exists": True, "$ne": None}})
    if entry:
        logger.info(f"Eintrag mit Topic '{entry.get('data', {}).get('topic')}' gefunden.")
        return entry
    
    # Versuche alternative Pfade für Topics
    logger.info("Versuche alternative Pfade für Topics...")
    for path in ["data.result.topic", "result.topic"]:
        logger.info(f"Suche nach Topics unter Pfad: {path}")
        entry = session_cache.find_one({path: {"$exists": True, "$ne": None}})
        if entry:
            logger.info(f"Eintrag gefunden unter Pfad: {path}")
            return entry
    
    return None


def extract_unique_topics(db: Database) -> tuple[List[str], str]:
    """
    Extrahiert einzigartige Topics aus dem Session-Cache.
    
    Args:
        db: MongoDB-Datenbankinstanz
    
    Returns:
        tuple[List[str], str]: Liste der einzigartigen Topics und der gefundene Pfad
    """
    session_cache = db.session_cache
    
    # Direkt nach dem korrekten Pfad 'data.topic' suchen
    logger.info("Suche nach Topics unter Pfad: data.topic")
    entries = list(session_cache.find({"data.topic": {"$exists": True, "$ne": None}}))
    
    if entries:
        logger.info(f"{len(entries)} Einträge mit Topics unter 'data.topic' gefunden.")
        entries_list = entries
        found_path = "data.topic"
    else:
        # Fallback zu anderen möglichen Pfaden
        logger.warning("Keine Einträge mit Topics unter 'data.topic' gefunden. Versuche alternative Pfade...")
        alternative_paths = ["data.result.topic", "result.topic"]
        found_path = None
        
        for path in alternative_paths:
            logger.info(f"Suche nach Topics unter Pfad: {path}")
            entries = list(session_cache.find({path: {"$exists": True, "$ne": None}}))
            if entries:
                logger.info(f"{len(entries)} Einträge gefunden unter Pfad: {path}")
                entries_list = entries
                found_path = path
                break
        
        if not found_path:
            logger.warning("Keine Einträge mit Topics unter den bekannten Pfaden gefunden.")
            return [], ""  # Leere Liste und leerer Pfad zurückgeben
    
    logger.info(f"{len(entries_list)} Session-Cache-Einträge mit Topics unter '{found_path}' gefunden.")
    
    # Extrahiere einzigartige Topics
    unique_topics: List[str] = []
    topic_mapping: Dict[str, bool] = {}
    
    # Trenne den Pfad für die korrekte Extraktion
    path_parts = found_path.split(".")
    
    for entry in entries_list:
        # Navigiere durch den Pfad
        value: Any = entry
        for part in path_parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                value = None
                break
        
        # Wenn ein Wert gefunden wurde, füge ihn hinzu
        if value and isinstance(value, str) and value not in topic_mapping:
            unique_topics.append(value)
            topic_mapping[value] = True
    
    logger.info(f"{len(unique_topics)} einzigartige Topics extrahiert: {', '.join(unique_topics[:10])}...")
    if len(unique_topics) > 10:
        logger.info(f"... und {len(unique_topics) - 10} weitere.")
    
    return unique_topics, found_path


def create_topics(db: Database, unique_topics: List[str], session_cache_entries: List[Dict], topic_path: str) -> int:
    """
    Erstellt Topic-Einträge in der topics-Collection.
    
    Args:
        db: MongoDB-Datenbankinstanz
        unique_topics: Liste der einzigartigen Topics
        session_cache_entries: Liste der Session-Cache-Einträge
        topic_path: Pfad zum Topic-Attribut in den Session-Cache-Einträgen
    
    Returns:
        int: Anzahl der erstellten Topics
    """
    topics_collection = db.topics
    created_count = 0
    
    for topic_name in unique_topics:
        # Prüfen, ob Topic bereits existiert
        existing_topic = topics_collection.find_one({"topic_id": topic_name})
        if existing_topic:
            logger.info(f"Topic '{topic_name}' existiert bereits.")
            continue
        
        # Topic-Daten erstellen
        topic_data = ECOSOCIAL_TOPICS.get(topic_name, {
            "display_name": {"de": topic_name, "en": topic_name},
            "description": {
                "de": f"Ein Thema über {topic_name} im Kontext von Open Source und Nachhaltigkeit.",
                "en": f"A topic about {topic_name} in the context of open source and sustainability."
            },
            "keywords": [topic_name, "Open Source", "Nachhaltigkeit"]
        })
        
        # Event aus der Session extrahieren
        event = "FOSDEM 2025"  # Standard-Event
        
        # Trenne den Pfad für die korrekte Extraktion
        path_parts = topic_path.split(".")
        
        # Extrahiere das Event aus der Session
        for entry in session_cache_entries:
            # Navigiere durch den Pfad zum Topic
            value = entry
            for part in path_parts:
                if part in value:
                    value = value[part]
                else:
                    value = None
                    break
            
            # Wenn das Topic übereinstimmt, versuche das Event zu extrahieren
            if value == topic_name:
                # Versuche verschiedene mögliche Pfade für das Event
                for event_path in ["data.event", "data.result.event", "result.event", "event"]:
                    event_value = entry
                    for part in event_path.split("."):
                        if part in event_value:
                            event_value = event_value[part]
                        else:
                            event_value = None
                            break
                    
                    if event_value and isinstance(event_value, str):
                        event = event_value
                        break
                
                break
        
        # Topic-Dokument erstellen
        topic_document = {
            "topic_id": topic_name,
            "event": event,
            "display_name": topic_data["display_name"],
            "description": topic_data["description"],
            "keywords": topic_data["keywords"],
            "primary_target_group": "technical",
            "relevance_threshold": 0.6,
            "status": "active",
            "template": "ecosocial",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        # In die Datenbank einfügen
        topics_collection.insert_one(topic_document)
        created_count += 1
        logger.info(f"Topic '{topic_name}' erfolgreich erstellt.")
    
    return created_count


def create_target_groups(db: Database) -> int:
    """
    Erstellt Zielgruppen in der target_groups-Collection, falls nicht vorhanden.
    
    Args:
        db: MongoDB-Datenbankinstanz
    
    Returns:
        int: Anzahl der erstellten Zielgruppen
    """
    target_groups_collection = db.target_groups
    created_count = 0
    
    for tg in TARGET_GROUPS:
        existing_target_group = target_groups_collection.find_one({"target_id": tg["target_id"]})
        if not existing_target_group:
            tg["created_at"] = datetime.now()
            tg["updated_at"] = datetime.now()
            target_groups_collection.insert_one(tg)
            created_count += 1
            logger.info(f"Zielgruppe '{tg['target_id']}' erstellt.")
        else:
            logger.info(f"Zielgruppe '{tg['target_id']}' existiert bereits.")
    
    return created_count


def test_topic_creation(db: Database) -> None:
    """
    Testet, ob ein Topic erfolgreich erstellt wurde.
    
    Args:
        db: MongoDB-Datenbankinstanz
    """
    test_topic = "offenes Design"
    topic = db.topics.find_one({"topic_id": test_topic})
    
    if topic:
        logger.info(f"Test erfolgreich: Topic '{test_topic}' gefunden.")
        logger.info(f"Topic-Details: {topic}")
    else:
        logger.warning(f"Test fehlgeschlagen: Topic '{test_topic}' nicht gefunden.")


def main() -> None:
    """
    Hauptfunktion zur Ausführung des Skripts.
    """
    logger.info("Starte Topic-Erstellung aus Session-Cache in der bestehenden Datenbank...")
    
    # Datenbankverbindung herstellen
    db = get_mongodb_connection()
    
    # Beispiel-Cache-Eintrag finden
    example_id = "67d4dcf84b21761a934fad69"  # Beispiel-ID aus dem Screenshot
    example_entry = find_cache_entry(db, example_id)
    
    if example_entry:
        logger.info("Cache-Eintrag gefunden:")
        for key, value in example_entry.items():
            if key != "data" and not isinstance(value, dict) and not isinstance(value, list):
                logger.info(f"  {key}: {value}")
        
        # Versuche topic und event zu finden
        if "data" in example_entry:
            if "topic" in example_entry["data"]:
                logger.info(f"  data.topic: {example_entry['data']['topic']}")
            elif "result" in example_entry["data"] and "topic" in example_entry["data"]["result"]:
                logger.info(f"  data.result.topic: {example_entry['data']['result']['topic']}")
        
            if "event" in example_entry["data"]:
                logger.info(f"  data.event: {example_entry['data']['event']}")
            elif "result" in example_entry["data"] and "event" in example_entry["data"]["result"]:
                logger.info(f"  data.result.event: {example_entry['data']['result']['event']}")
    else:
        logger.info("Kein passender Cache-Eintrag gefunden. Suche nach allen Einträgen mit Topics...")
    
    # Einzigartige Topics extrahieren
    unique_topics, topic_path = extract_unique_topics(db)
    
    if not unique_topics:
        logger.warning("Keine Topics gefunden. Beende Skript.")
        return
    
    # Session-Cache auslesen für den gefundenen Pfad
    session_cache_entries = list(db.session_cache.find({topic_path: {"$exists": True, "$ne": None}}))
    logger.info(f"{len(session_cache_entries)} Session-Cache-Einträge mit Topics unter '{topic_path}' für die Verarbeitung bereit.")
    
    # Topics erstellen
    created_topics = create_topics(db, unique_topics, session_cache_entries, topic_path)
    logger.info(f"{created_topics} neue Topics erstellt.")
    
    # Zielgruppen erstellen
    created_target_groups = create_target_groups(db)
    logger.info(f"{created_target_groups} neue Zielgruppen erstellt.")
    
    # Test durchführen
    if unique_topics:
        test_topic = unique_topics[0]
        topic = db.topics.find_one({"topic_id": test_topic})
        if topic:
            logger.info(f"Test erfolgreich: Topic '{test_topic}' gefunden.")
            logger.info(f"Topic-Details: {topic}")
        else:
            logger.warning(f"Test fehlgeschlagen: Topic '{test_topic}' nicht gefunden.")
    
    logger.info("Topic- und Zielgruppen-Erstellung abgeschlossen.")


if __name__ == "__main__":
    main() 