"""
MongoDB-Repository für Übersetzungen.
Verwaltet die Speicherung und Abfrage von Übersetzungen in der MongoDB.
"""

from pymongo import ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from typing import Any, Optional, Callable
import logging
import datetime

from src.core.models.translation import Translation
from .connection import get_mongodb_database

# Logger initialisieren
logger = logging.getLogger(__name__)

class TranslationRepository:
    """
    Repository für die Verwaltung von Übersetzungen in MongoDB.
    Verwendet typisierte Dataclasses für die Datenmodellierung.
    """
    
    def __init__(self, db_name: Optional[str] = None):
        """
        Initialisiert das Repository.
        
        Args:
            db_name: Optional, Name der Datenbank. Wenn nicht angegeben, wird der Name aus der Konfiguration verwendet.
        """
        self.db: Database[Any] = get_mongodb_database(db_name)
        self.translations: Collection[Any] = self.db.translations
        
        # Indizes erstellen
        self._create_indexes()
        
        logger.debug("TranslationRepository initialisiert")
    
    def _create_indexes(self) -> None:
        """
        Erstellt die notwendigen Indizes für die Translations-Collection.
        """
        # Kombinierter Index für eindeutige Entity-Identifikation
        self.translations.create_index([
            ("entity_type", ASCENDING),
            ("entity_id", ASCENDING),
            ("original_language", ASCENDING)
        ], unique=True)
        
        # Index für schnelle Suche nach Entitytyp
        self.translations.create_index([("entity_type", ASCENDING)])
        
        # Index für Originaltext-Suche
        self.translations.create_index([("original_text", ASCENDING)])
        
        logger.debug("MongoDB-Indizes für Translations erstellt")
    
    def get_translation(
        self,
        entity_type: str,
        entity_id: str,
        target_language: str,
        original_language: str = "en"
    ) -> Optional[str]:
        """
        Holt eine Übersetzung für eine Entity.
        
        Args:
            entity_type: Typ der Entity ("track", "session", etc.)
            entity_id: ID oder Name der Entity
            target_language: Zielsprache (z.B. "de")
            original_language: Originalsprache (Standard: "en")
            
        Returns:
            str oder None: Die Übersetzung oder None wenn keine existiert
        """
        # Suche nach der Entity in der Datenbank
        result = self.translations.find_one({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "original_language": original_language
        })
        
        if result and target_language in result.get("translations", {}):
            return result["translations"][target_language]
        
        return None
    
    def save_translation(
        self,
        entity_type: str,
        entity_id: str,
        original_text: str,
        target_language: str,
        translated_text: str,
        original_language: str = "en"
    ) -> bool:
        """
        Speichert eine Übersetzung in der Datenbank.
        
        Args:
            entity_type: Typ der Entity ("track", "session", etc.)
            entity_id: ID oder Name der Entity
            original_text: Originaltext
            target_language: Zielsprache (z.B. "de")
            translated_text: Übersetzter Text
            original_language: Originalsprache (Standard: "en")
            
        Returns:
            bool: True bei Erfolg, False bei Fehler
        """
        now = datetime.datetime.now(datetime.UTC)
        
        # Prüfen, ob die Entity bereits existiert
        existing = self.translations.find_one({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "original_language": original_language
        })
        
        if existing:
            # Update der bestehenden Übersetzung
            result = self.translations.update_one(
                {
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "original_language": original_language
                },
                {
                    "$set": {
                        f"translations.{target_language}": translated_text,
                        "updated_at": now
                    }
                }
            )
            return result.modified_count > 0
        else:
            # Neue Übersetzung erstellen
            translation = Translation(
                entity_type=entity_type,
                entity_id=entity_id,
                original_text=original_text,
                original_language=original_language,
                translations={target_language: translated_text},
                created_at=now,
                updated_at=now
            )
            
            try:
                self.translations.insert_one(translation.to_dict())
                return True
            except Exception as e:
                logger.error(f"Fehler beim Speichern der Übersetzung: {str(e)}")
                return False
    
    def get_or_create_translation(
        self,
        entity_type: str,
        entity_id: str,
        original_text: str,
        target_language: str,
        translator_func: Callable[[str, str], str],  # Eine Funktion, die einen Text übersetzt
        original_language: str = "en"
    ) -> str:
        """
        Holt eine Übersetzung aus der Datenbank oder erstellt sie, wenn sie nicht existiert.
        
        Args:
            entity_type: Typ der Entity ("track", "session", etc.)
            entity_id: ID oder Name der Entity
            original_text: Originaltext
            target_language: Zielsprache (z.B. "de")
            translator_func: Eine Funktion, die einen Text übersetzt (original_text, target_language) -> str
            original_language: Originalsprache (Standard: "en")
            
        Returns:
            str: Die Übersetzung
        """
        # Wenn Zielsprache gleich Originalsprache, Original zurückgeben
        if target_language == original_language:
            return original_text
            
        # Nach existierender Übersetzung suchen
        existing_translation = self.get_translation(
            entity_type=entity_type,
            entity_id=entity_id,
            target_language=target_language,
            original_language=original_language
        )
        
        if existing_translation:
            return existing_translation
        
        # Neue Übersetzung erstellen
        try:
            translated_text: str = translator_func(original_text, target_language)
            
            # Übersetzung speichern
            self.save_translation(
                entity_type=entity_type,
                entity_id=entity_id,
                original_text=original_text,
                target_language=target_language,
                translated_text=translated_text,
                original_language=original_language
            )
            
            return translated_text
        except Exception as e:
            logger.error(f"Fehler bei der Übersetzung: {str(e)}")
            # Im Fehlerfall Originaltext zurückgeben
            return original_text
    
    def delete_translation(
        self,
        entity_type: str,
        entity_id: str,
        original_language: str = "en"
    ) -> bool:
        """
        Löscht eine Übersetzungs-Entity.
        
        Args:
            entity_type: Typ der Entity ("track", "session", etc.)
            entity_id: ID oder Name der Entity
            original_language: Originalsprache (Standard: "en")
            
        Returns:
            bool: True bei Erfolg, False wenn nicht gefunden
        """
        result = self.translations.delete_one({
            "entity_type": entity_type,
            "entity_id": entity_id,
            "original_language": original_language
        })
        
        return result.deleted_count > 0 