# type: ignore
from typing import Dict, List, Optional, Any, cast
from pymongo import ASCENDING, IndexModel
from pymongo.collection import Collection
from src.core.mongodb.connection import get_mongodb_database  # type: ignore

# Typdefinitionen für bessere Typunterstützung
TopicDict = Dict[str, Any]
TargetGroupDict = Dict[str, Any]
SessionDict = Dict[str, Any]

class StoryRepository:
    """Repository für die Verwaltung von Story-bezogenen Daten in MongoDB."""
    
    def __init__(self, connection: Any):
        """
        Initialisiert das StoryRepository.
        
        Args:
            connection: Die MongoDB-Verbindung
        """
        self.connection = connection
        self.db = get_mongodb_database()
        
        # Collections definieren
        self.topics_collection: Collection[Dict[str, Any]] = self.db.topics
        self.target_groups_collection: Collection[Dict[str, Any]] = self.db.target_groups
        self.session_cache: Collection[Dict[str, Any]] = self.db.session_cache
        
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
    def get_topics(self, filter_query: Optional[Dict[str, Any]] = None, status: str = "active") -> List[TopicDict]:
        """
        Ruft Themen basierend auf Filterkriterien ab.
        
        Args:
            filter_query: Optionale Filterkriterien
            status: Status der abzurufenden Themen (active/inactive)
            
        Returns:
            Liste mit Themen-Dokumenten
        """
        query: Dict[str, Any] = filter_query or {}
        query["status"] = status
        
        cursor = self.topics_collection.find(query)
        result = list(cursor)  # Direkter Zugriff statt await
        return cast(List[TopicDict], result)
    
    def get_all_topics(self) -> List[TopicDict]:
        """
        Ruft alle Themen aus der Datenbank ab.
        
        Returns:
            Liste mit allen Themen-Dokumenten
        """
        return self.get_topics(filter_query=None)
    
    def get_topic_by_id(self, topic_id: str) -> Optional[TopicDict]:
        """
        Ruft ein Thema anhand seiner ID ab.
        
        Args:
            topic_id: Die ID des Themas
            
        Returns:
            Das Thema-Dokument oder None, wenn nicht gefunden
        """
        result = self.topics_collection.find_one({"topic_id": topic_id})
        return cast(Optional[TopicDict], result)
    
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
    def get_target_groups(self, filter_query: Optional[Dict[str, Any]] = None, status: str = "active") -> List[TargetGroupDict]:
        """
        Ruft Zielgruppen basierend auf Filterkriterien ab.
        
        Args:
            filter_query: Optionale Filterkriterien
            status: Status der abzurufenden Zielgruppen (active/inactive)
            
        Returns:
            Liste mit Zielgruppen-Dokumenten
        """
        query: Dict[str, Any] = filter_query or {}
        query["status"] = status
        
        cursor = self.target_groups_collection.find(query)
        result = list(cursor)  # Direkter Zugriff statt await
        return cast(List[TargetGroupDict], result)
    
    def get_all_target_groups(self) -> List[TargetGroupDict]:
        """
        Ruft alle Zielgruppen aus der Datenbank ab.
        
        Returns:
            Liste mit allen Zielgruppen-Dokumenten
        """
        return self.get_target_groups(filter_query=None)
    
    def get_target_group_by_id(self, target_id: str) -> Optional[TargetGroupDict]:
        """
        Ruft eine Zielgruppe anhand ihrer ID ab.
        
        Args:
            target_id: Die ID der Zielgruppe
            
        Returns:
            Das Zielgruppen-Dokument oder None, wenn nicht gefunden
        """
        result = self.target_groups_collection.find_one({"target_id": target_id})
        return cast(Optional[TargetGroupDict], result)
    
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
    
    # Hilfsmethoden für den StoryProcessor
    def get_sessions_by_topic(self, topic_id: str, event: str, target_group: str) -> List[SessionDict]:
        """
        Ruft alle Sessions ab, die für ein bestimmtes Thema, Event und Zielgruppe relevant sind.
        
        Args:
            topic_id: Die ID des Themas
            event: Die ID des Events
            target_group: Die ID der Zielgruppe
            
        Returns:
            Liste mit relevanten Session-Dokumenten
        """
        # Thema abrufen, um den Relevanz-Schwellenwert zu erhalten
        topic = self.get_topic_by_id(topic_id)
        if not topic:
            return []
        
        threshold: float = topic.get("relevance_threshold", 7)
        
        # Sessions abfragen
        # Annahme: Sessions haben ein Metadaten-Feld mit Themen und Relevanzwerten
        query: Dict[str, Any] = {
            "data.event": event,
            "data.topic": topic_id,
            #f"data.relevance": {"$gte": threshold}
        }
        
        # Cache-Collection für Sessions verwenden
        cursor = self.session_cache.find(query).sort(
            [(f"data.relevance", -1)]  # Nach Relevanz absteigend sortieren
        )
        result = list(cursor)  # Direkter Zugriff statt await
        return cast(List[SessionDict], result)

    def get_sessions_by_data_topic(self, topic_text: str, limit: int = 50) -> List[SessionDict]:
        """
        Ruft Sessions ab, die einen bestimmten Thementext im data.topic-Feld haben.
        Dies ist eine alternative Methode zum Abrufen von Sessions, die direkter filtert.
        
        Args:
            topic_text: Der gesuchte Text im data.topic-Feld
            limit: Maximale Anzahl von zurückgegebenen Sessions
            
        Returns:
            Liste mit relevanten Session-Dokumenten
        """
        # Sessions basierend auf dem data.topic-Feld abfragen
        query: Dict[str, Any] = {
            "data.topic": topic_text
        }
        
        # Cache-Collection für Sessions verwenden
        cursor = self.session_cache.find(query).limit(limit)
        raw_sessions = list(cursor)  # Direkter Zugriff statt await
        
        # Anzahl der gefundenen Sessions ausgeben
        print(f"Gefunden: {len(raw_sessions)} Sessions mit data.topic='{topic_text}'")
        
        # Hier können wir direkt die Session-IDs zurückgeben, 
        # die dann an _load_sessions übergeben werden können
        session_ids = [str(session.get("_id")) for session in raw_sessions if session.get("_id")]
        
        # Für Debugging-Zwecke: Zeige die ersten 5 Session-IDs
        if session_ids:
            id_sample = session_ids[:min(5, len(session_ids))]
            print(f"Beispiel-Session-IDs: {id_sample}")
        
        # Sessions in das erwartete Format umwandeln
        formatted_sessions: List[SessionDict] = []
        for i, raw_session in enumerate(raw_sessions):
            # Grundlegende Daten extrahieren
            session_id = str(raw_session.get('_id', f'generated_id_{i}'))
            title = raw_session.get('data', {}).get('session', f'Session {i+1}')
            content = raw_session.get('data', {}).get('result', {}).get('markdown_content', 'Keine Inhalte verfügbar')
            topic = raw_session.get('data', {}).get('topic', topic_text)
            
            # Formatierte Session erstellen, die mit _load_sessions kompatibel ist
            formatted_session: SessionDict = {
                "session_id": session_id,
                "title": title,
                "markdown_content": content,
                "target_language": "de",
                "topic": [topic],
                "relevance": 7,  # Standard-Relevanz für allgemeine Zielgruppe
            }
            formatted_sessions.append(formatted_session)
        
        return formatted_sessions

    def get_sessions_by_session_ids(self, session_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Ruft Sessions anhand ihrer IDs ab.
        
        Args:
            session_ids: Liste von Session-IDs
            
        Returns:
            Liste von Session-Daten
        """
        return list(self.session_cache.find({"_id": {"$in": session_ids}})) 