"""
Test-Daten für die Story-Funktionalität erstellen
-------------------------------------------------

Dieses Skript erstellt Test-Daten für die Story-Funktionalität,
einschließlich Topics und Zielgruppen in der MongoDB.
"""

import os
import sys
from datetime import datetime
from typing import Dict, Any, List, Optional, cast

# Füge das Stammverzeichnis zum Python-Pfad hinzu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pymongo.collection import Collection
from pymongo.database import Database
from pymongo import MongoClient, ASCENDING, IndexModel

# StoryRepository-Implementierung für dieses Skript
class StoryRepository:
    """Repository für die Verwaltung von Story-bezogenen Daten in MongoDB."""
    
    def __init__(self, client: MongoClient[Dict[str, Any]], db: Database[Dict[str, Any]]):
        """
        Initialisiert das StoryRepository.
        
        Args:
            client: MongoDB-Client
            db: MongoDB-Datenbank
        """
        self.client = client
        self.db = db
        # Collections definieren
        self.topics_collection: Collection[Dict[str, Any]] = self.db.topics
        self.target_groups_collection: Collection[Dict[str, Any]] = self.db.target_groups
        
        # Indizes einrichten
        self._setup_indices()
    
    def _setup_indices(self) -> None:
        """Richtet die Indizes für Story-Collections ein."""
        # Topics-Collection Indizes
        topic_indices = [
            IndexModel([("topic_id", ASCENDING)], unique=True),
            IndexModel([("primary_target_group", ASCENDING)]),
            IndexModel([("status", ASCENDING)])
        ]
        self.topics_collection.create_indexes(topic_indices)
        
        # Target-Groups-Collection Indizes
        target_group_indices = [
            IndexModel([("target_id", ASCENDING)], unique=True),
            IndexModel([("status", ASCENDING)])
        ]
        self.target_groups_collection.create_indexes(target_group_indices)
    
    # Topic-bezogene Methoden
    def get_topic_by_id(self, topic_id: str) -> Optional[Dict[str, Any]]:
        """
        Ruft ein Thema anhand seiner ID ab.
        
        Args:
            topic_id: Die ID des Themas
            
        Returns:
            Das Thema-Dokument oder None, wenn nicht gefunden
        """
        return self.topics_collection.find_one({"topic_id": topic_id})
    
    def create_topic(self, topic_data: Dict[str, Any]) -> str:
        """
        Erstellt ein neues Thema in der Datenbank.
        
        Args:
            topic_data: Die Daten des neuen Themas
            
        Returns:
            Die ID des erstellten Dokuments
        """
        result = self.topics_collection.insert_one(topic_data)
        return str(result.inserted_id)
    
    def update_topic(self, topic_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Aktualisiert ein vorhandenes Thema.
        
        Args:
            topic_id: Die ID des zu aktualisierenden Themas
            update_data: Die zu aktualisierenden Daten
            
        Returns:
            True, wenn das Thema aktualisiert wurde, sonst False
        """
        result = self.topics_collection.update_one(
            {"topic_id": topic_id}, 
            {"$set": update_data}
        )
        return result.modified_count > 0
    
    # Target-Group-bezogene Methoden
    def get_target_group_by_id(self, target_id: str) -> Optional[Dict[str, Any]]:
        """
        Ruft eine Zielgruppe anhand ihrer ID ab.
        
        Args:
            target_id: Die ID der Zielgruppe
            
        Returns:
            Das Zielgruppen-Dokument oder None, wenn nicht gefunden
        """
        return self.target_groups_collection.find_one({"target_id": target_id})
    
    def create_target_group(self, target_group_data: Dict[str, Any]) -> str:
        """
        Erstellt eine neue Zielgruppe in der Datenbank.
        
        Args:
            target_group_data: Die Daten der neuen Zielgruppe
            
        Returns:
            Die ID des erstellten Dokuments
        """
        result = self.target_groups_collection.insert_one(target_group_data)
        return str(result.inserted_id)
    
    def update_target_group(self, target_id: str, update_data: Dict[str, Any]) -> bool:
        """
        Aktualisiert eine vorhandene Zielgruppe.
        
        Args:
            target_id: Die ID der zu aktualisierenden Zielgruppe
            update_data: Die zu aktualisierenden Daten
            
        Returns:
            True, wenn die Zielgruppe aktualisiert wurde, sonst False
        """
        result = self.target_groups_collection.update_one(
            {"target_id": target_id}, 
            {"$set": update_data}
        )
        return result.modified_count > 0

# Test-Topics für verschiedene Szenarien
TEST_TOPICS = [
    {
        "topic_id": "nachhaltigkeit-2023",
        "display_name": {
            "de": "Nachhaltigkeit und Umweltschutz",
            "en": "Sustainability and Environmental Protection"
        },
        "description": {
            "de": "Themen rund um Nachhaltigkeit, Umweltschutz und Klimaschutz",
            "en": "Topics related to sustainability, environmental protection and climate action"
        },
        "keywords": ["Nachhaltigkeit", "Umweltschutz", "Klimaschutz", "Ressourcenschonung", "Kreislaufwirtschaft"],
        "primary_target_group": "politik",
        "relevance_threshold": 0.6,
        "status": "active",
        "template": "eco_social",
        "event": "forum-2023",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    },
    {
        "topic_id": "digitalisierung-2023",
        "display_name": {
            "de": "Digitale Transformation",
            "en": "Digital Transformation"
        },
        "description": {
            "de": "Die digitale Transformation von Wirtschaft und Gesellschaft",
            "en": "The digital transformation of economy and society"
        },
        "keywords": ["Digitalisierung", "KI", "Automatisierung", "Industrie 4.0", "Datenschutz"],
        "primary_target_group": "wirtschaft",
        "relevance_threshold": 0.7,
        "status": "active",
        "template": "default",
        "event": "forum-2023",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    },
    {
        "topic_id": "energie-2023",
        "display_name": {
            "de": "Energiewende und erneuerbare Energien",
            "en": "Energy Transition and Renewable Energy"
        },
        "description": {
            "de": "Die Transformation des Energiesektors und der Ausbau erneuerbarer Energien",
            "en": "The transformation of the energy sector and the expansion of renewable energy"
        },
        "keywords": ["Energiewende", "Erneuerbare Energien", "Solarenergie", "Windkraft", "Wasserstoff"],
        "primary_target_group": "wirtschaft",
        "relevance_threshold": 0.65,
        "status": "active",
        "template": "eco_social",
        "event": "forum-2023",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }
]

# Test-Zielgruppen
TEST_TARGET_GROUPS = [
    {
        "target_id": "politik",
        "display_name": {
            "de": "Politische Entscheidungsträger",
            "en": "Political Decision Makers"
        },
        "description": {
            "de": "Politiker und Entscheidungsträger auf allen Ebenen",
            "en": "Politicians and decision makers at all levels"
        },
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    },
    {
        "target_id": "wirtschaft",
        "display_name": {
            "de": "Wirtschaft und Unternehmen",
            "en": "Business and Companies"
        },
        "description": {
            "de": "Unternehmen, Wirtschaftsverbände und Entscheidungsträger in der Wirtschaft",
            "en": "Companies, business associations and decision makers in the economy"
        },
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    },
    {
        "target_id": "zivilgesellschaft",
        "display_name": {
            "de": "Zivilgesellschaft",
            "en": "Civil Society"
        },
        "description": {
            "de": "NGOs, Verbände, Vereine und andere zivilgesellschaftliche Organisationen",
            "en": "NGOs, associations, clubs and other civil society organizations"
        },
        "status": "active",
        "created_at": datetime.now(),
        "updated_at": datetime.now()
    }
]

# Test-Session-Daten (simuliert)
TEST_SESSIONS = [
    {
        "session_id": "session1",
        "title": "Kreislaufwirtschaft in der Praxis",
        "event": "forum-2023",
        "content": {
            "de": "In dieser Session wurde über praktische Ansätze zur Kreislaufwirtschaft diskutiert. Die Teilnehmer stellten verschiedene Modelle vor, wie Unternehmen Ressourcen schonen und Abfall reduzieren können.",
            "en": "This session discussed practical approaches to circular economy. Participants presented various models of how companies can conserve resources and reduce waste."
        },
        "metadata": {
            "topics": ["nachhaltigkeit-2023"],
            "relevance": {
                "politik": 0.8,
                "wirtschaft": 0.9,
                "zivilgesellschaft": 0.7
            }
        }
    },
    {
        "session_id": "session2",
        "title": "KI für Energieeffizienz",
        "event": "forum-2023",
        "content": {
            "de": "Diese Session befasste sich mit dem Einsatz von künstlicher Intelligenz zur Optimierung der Energieeffizienz in Gebäuden und industriellen Prozessen.",
            "en": "This session focused on the use of artificial intelligence to optimize energy efficiency in buildings and industrial processes."
        },
        "metadata": {
            "topics": ["energie-2023", "digitalisierung-2023"],
            "relevance": {
                "politik": 0.6,
                "wirtschaft": 0.9,
                "zivilgesellschaft": 0.5
            }
        }
    },
    {
        "session_id": "session3",
        "title": "Nachhaltige Stadtentwicklung im digitalen Zeitalter",
        "event": "forum-2023",
        "content": {
            "de": "In dieser Session wurde diskutiert, wie digitale Technologien für eine nachhaltigere Stadtentwicklung eingesetzt werden können, von intelligenten Verkehrssystemen bis hin zu energieeffizienten Gebäuden.",
            "en": "This session discussed how digital technologies can be used for more sustainable urban development, from intelligent transport systems to energy-efficient buildings."
        },
        "metadata": {
            "topics": ["nachhaltigkeit-2023", "digitalisierung-2023"],
            "relevance": {
                "politik": 0.9,
                "wirtschaft": 0.7,
                "zivilgesellschaft": 0.8
            }
        }
    }
]

def create_test_data():
    """Erstellt Test-Daten für die Story-Funktionalität in der MongoDB."""
    print("Erstelle Test-Daten für die Story-Funktionalität...")
    
    try:
        # MongoDB-URI aus Umgebungsvariable oder Standardwert
        mongo_uri = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.environ.get("MONGODB_DB", "event_processor")
        
        print(f"Verbinde mit MongoDB: {mongo_uri}, Datenbank: {db_name}")
        
        # MongoDB-Client und Datenbank initialisieren
        client: MongoClient[Dict[str, Any]] = MongoClient(mongo_uri)
        db: Database[Dict[str, Any]] = client[db_name]
        
        # StoryRepository initialisieren
        repository = StoryRepository(client, db)
        
        # Prüfen, ob Topics bereits existieren
        for topic in TEST_TOPICS:
            existing_topic = repository.get_topic_by_id(topic["topic_id"])
            if existing_topic:
                print(f"Topic {topic['topic_id']} existiert bereits, wird aktualisiert...")
                repository.update_topic(topic["topic_id"], topic)
            else:
                print(f"Erstelle neues Topic: {topic['topic_id']}...")
                repository.create_topic(topic)
        
        # Prüfen, ob Zielgruppen bereits existieren
        for target_group in TEST_TARGET_GROUPS:
            existing_target = repository.get_target_group_by_id(target_group["target_id"])
            if existing_target:
                print(f"Zielgruppe {target_group['target_id']} existiert bereits, wird aktualisiert...")
                repository.update_target_group(target_group["target_id"], target_group)
            else:
                print(f"Erstelle neue Zielgruppe: {target_group['target_id']}...")
                repository.create_target_group(target_group)
        
        # Sessions im Cache speichern
        session_cache = db.session_cache
        for session in TEST_SESSIONS:
            # Prüfen, ob Session bereits existiert
            existing_session = session_cache.find_one({"session_id": session["session_id"]})
            if existing_session:
                print(f"Session {session['session_id']} existiert bereits, wird aktualisiert...")
                session_cache.update_one({"session_id": session["session_id"]}, {"$set": session})
            else:
                print(f"Erstelle neue Session: {session['session_id']}...")
                session_cache.insert_one(session)
        
        print("Test-Daten erfolgreich erstellt!")
        
    except Exception as e:
        print(f"Fehler beim Erstellen der Test-Daten: {str(e)}")
        raise

if __name__ == "__main__":
    create_test_data() 