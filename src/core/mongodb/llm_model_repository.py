"""
@fileoverview LLM Model Repository - MongoDB repository for LLM model management

@description
MongoDB repository for LLM models, test results, and use case configurations.
Manages storage and querying of LLM models in MongoDB.

Main functionality:
- CRUD operations for LLM models
- Test result storage and retrieval
- Use case configuration management
- Best model selection based on test results

Features:
- Typed dataclass models for type safety
- Automatic index creation on initialization
- Compound unique indexes for test results
- Performance-optimized queries

@module core.mongodb.llm_model_repository

@exports
- LLMModelRepository: Class - Repository for LLM model management
- LLMTestResultRepository: Class - Repository for test result management
- LLMUseCaseConfigRepository: Class - Repository for use case configuration
"""

from pymongo import ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.results import UpdateResult, DeleteResult
from typing import Dict, Any, List, Optional
from datetime import datetime, UTC
import logging

from ..models.llm_models import LLMModel, LLMTestResult, LLMUseCaseConfig
from .connection import get_mongodb_database

logger = logging.getLogger(__name__)


class LLMModelRepository:
    """
    Repository für die Verwaltung von LLM-Modellen in MongoDB.
    """
    
    def __init__(self) -> None:
        """Initialisiert das Repository."""
        self.db: Database[Any] = get_mongodb_database()
        self.models: Collection[Any] = self.db.llm_models
        
        # Indizes erstellen
        self._create_indexes()
        
        logger.info("LLMModelRepository initialisiert")
    
    def _create_indexes(self) -> None:
        """Erstellt die notwendigen Indizes für die Collection."""
        try:
            # Unique Index auf model_id
            self.models.create_index([("model_id", ASCENDING)], unique=True)
            # Index auf provider für schnelle Filterung
            self.models.create_index([("provider", ASCENDING)])
            # Index auf use_cases für schnelle Suche
            self.models.create_index([("use_cases", ASCENDING)])
            # Index auf enabled für Filterung
            self.models.create_index([("enabled", ASCENDING)])
            
            logger.debug("MongoDB-Indizes für llm_models erstellt")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Indizes für llm_models: {str(e)}")
    
    def get_model(self, model_id: str) -> Optional[LLMModel]:
        """
        Gibt ein Modell anhand seiner ID zurück.
        
        Args:
            model_id: Die Modell-ID
            
        Returns:
            Optional[LLMModel]: Das Modell oder None wenn nicht gefunden
        """
        try:
            doc = self.models.find_one({"model_id": model_id})
            if doc:
                return LLMModel.from_dict(doc)
            return None
        except Exception as e:
            logger.error(f"Fehler beim Abrufen des Modells {model_id}: {str(e)}")
            return None
    
    def get_models_by_provider(self, provider: str) -> List[LLMModel]:
        """
        Gibt alle Modelle eines Providers zurück.
        
        Args:
            provider: Der Provider-Name
            
        Returns:
            List[LLMModel]: Liste der Modelle
        """
        try:
            cursor = self.models.find({"provider": provider})
            return [LLMModel.from_dict(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Modelle für Provider {provider}: {str(e)}")
            return []
    
    def get_models_by_use_case(self, use_case: str) -> List[LLMModel]:
        """
        Gibt alle Modelle zurück, die einen bestimmten Use-Case unterstützen.
        
        Args:
            use_case: Der Use-Case-Name
            
        Returns:
            List[LLMModel]: Liste der Modelle
        """
        try:
            cursor = self.models.find({
                "use_cases": use_case,
                "enabled": True
            })
            return [LLMModel.from_dict(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Modelle für Use-Case {use_case}: {str(e)}")
            return []
    
    def create_model(self, model: LLMModel) -> str:
        """
        Erstellt ein neues Modell.
        
        Args:
            model: Das zu erstellende Modell
            
        Returns:
            str: Die Modell-ID
            
        Raises:
            ValueError: Wenn das Modell bereits existiert
        """
        try:
            # Prüfe ob Modell bereits existiert
            existing = self.get_model(model.model_id)
            if existing:
                raise ValueError(f"Modell {model.model_id} existiert bereits")
            
            doc = model.to_dict()
            result = self.models.insert_one(doc)
            
            if result.inserted_id:
                logger.info(f"Modell {model.model_id} erstellt")
                return model.model_id
            else:
                raise ValueError("Fehler beim Erstellen des Modells")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen des Modells {model.model_id}: {str(e)}")
            raise
    
    def update_model(self, model_id: str, updates: Dict[str, Any]) -> bool:
        """
        Aktualisiert ein Modell.
        
        Args:
            model_id: Die Modell-ID
            updates: Dictionary mit zu aktualisierenden Feldern
            
        Returns:
            bool: True wenn erfolgreich, False sonst
        """
        try:
            # Füge updated_at hinzu
            updates["updated_at"] = datetime.now(UTC).isoformat()
            
            result: UpdateResult = self.models.update_one(
                {"model_id": model_id},
                {"$set": updates}
            )
            
            if result.modified_count > 0:
                logger.info(f"Modell {model_id} aktualisiert")
                return True
            return False
        except Exception as e:
            logger.error(f"Fehler beim Aktualisieren des Modells {model_id}: {str(e)}")
            return False
    
    def delete_model(self, model_id: str) -> bool:
        """
        Löscht ein Modell.
        
        Args:
            model_id: Die Modell-ID
            
        Returns:
            bool: True wenn erfolgreich, False sonst
        """
        try:
            result: DeleteResult = self.models.delete_one({"model_id": model_id})
            
            if result.deleted_count > 0:
                logger.info(f"Modell {model_id} gelöscht")
                return True
            return False
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Modells {model_id}: {str(e)}")
            return False
    
    def get_all_models(self, enabled_only: bool = False) -> List[LLMModel]:
        """
        Gibt alle Modelle zurück.
        
        Args:
            enabled_only: Wenn True, nur aktivierte Modelle
            
        Returns:
            List[LLMModel]: Liste aller Modelle
        """
        try:
            query = {}
            if enabled_only:
                query["enabled"] = True
            
            cursor = self.models.find(query)
            return [LLMModel.from_dict(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen aller Modelle: {str(e)}")
            return []


class LLMTestResultRepository:
    """
    Repository für die Verwaltung von LLM-Test-Ergebnissen in MongoDB.
    """
    
    def __init__(self) -> None:
        """Initialisiert das Repository."""
        self.db: Database[Any] = get_mongodb_database()
        self.test_results: Collection[Any] = self.db.llm_test_results
        
        # Indizes erstellen
        self._create_indexes()
        
        logger.info("LLMTestResultRepository initialisiert")
    
    def _create_indexes(self) -> None:
        """Erstellt die notwendigen Indizes für die Collection."""
        try:
            # Compound unique Index: (model_id, use_case, test_size)
            # Ermöglicht automatisches Überschreiben alter Ergebnisse
            self.test_results.create_index(
                [("model_id", ASCENDING), ("use_case", ASCENDING), ("test_size", ASCENDING)],
                unique=True
            )
            # Index auf use_case für schnelle Filterung
            self.test_results.create_index([("use_case", ASCENDING)])
            # Index auf test_size für Filterung
            self.test_results.create_index([("test_size", ASCENDING)])
            # Index auf status für Filterung
            self.test_results.create_index([("status", ASCENDING)])
            # Index auf tested_at für Sortierung
            self.test_results.create_index([("tested_at", DESCENDING)])
            # Index auf quality_score für Sortierung und Filterung
            self.test_results.create_index([("quality_score", DESCENDING)])
            
            logger.debug("MongoDB-Indizes für llm_test_results erstellt")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Indizes für llm_test_results: {str(e)}")
    
    def save_test_result(self, result: LLMTestResult) -> str:
        """
        Speichert ein Test-Ergebnis (überschreibt alte Ergebnisse).
        
        Args:
            result: Das Test-Ergebnis
            
        Returns:
            str: Die ID des gespeicherten Ergebnisses
        """
        try:
            doc = result.to_dict()
            
            # Verwende replace_one mit upsert=True für automatisches Überschreiben
            # Der unique compound Index sorgt dafür, dass alte Ergebnisse überschrieben werden
            update_result: UpdateResult = self.test_results.replace_one(
                {
                    "model_id": result.model_id,
                    "use_case": result.use_case,
                    "test_size": result.test_size
                },
                doc,
                upsert=True
            )
            
            if update_result.upserted_id:
                logger.info(
                    f"Test-Ergebnis für {result.model_id}/{result.use_case}/{result.test_size} gespeichert"
                )
                return str(update_result.upserted_id)
            elif update_result.modified_count > 0:
                logger.info(
                    f"Test-Ergebnis für {result.model_id}/{result.use_case}/{result.test_size} aktualisiert"
                )
                # Finde das aktualisierte Dokument
                updated_doc = self.test_results.find_one({
                    "model_id": result.model_id,
                    "use_case": result.use_case,
                    "test_size": result.test_size
                })
                if updated_doc:
                    return str(updated_doc["_id"])
            
            raise ValueError("Fehler beim Speichern des Test-Ergebnisses")
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Test-Ergebnisses: {str(e)}")
            raise
    
    def get_test_result(
        self,
        model_id: str,
        use_case: str,
        test_size: str
    ) -> Optional[LLMTestResult]:
        """
        Gibt ein Test-Ergebnis zurück.
        
        Args:
            model_id: Die Modell-ID
            use_case: Der Use-Case
            test_size: Die Test-Größe
            
        Returns:
            Optional[LLMTestResult]: Das Test-Ergebnis oder None
        """
        try:
            doc = self.test_results.find_one({
                "model_id": model_id,
                "use_case": use_case,
                "test_size": test_size
            })
            if doc:
                return LLMTestResult.from_dict(doc)
            return None
        except Exception as e:
            logger.error(
                f"Fehler beim Abrufen des Test-Ergebnisses für {model_id}/{use_case}/{test_size}: {str(e)}"
            )
            return None
    
    def get_test_results_by_model(self, model_id: str) -> List[LLMTestResult]:
        """
        Gibt alle Test-Ergebnisse für ein Modell zurück.
        
        Args:
            model_id: Die Modell-ID
            
        Returns:
            List[LLMTestResult]: Liste der Test-Ergebnisse
        """
        try:
            cursor = self.test_results.find({"model_id": model_id})
            return [LLMTestResult.from_dict(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Test-Ergebnisse für Modell {model_id}: {str(e)}")
            return []
    
    def get_test_results_by_use_case(self, use_case: str) -> List[LLMTestResult]:
        """
        Gibt alle Test-Ergebnisse für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case
            
        Returns:
            List[LLMTestResult]: Liste der Test-Ergebnisse
        """
        try:
            cursor = self.test_results.find({"use_case": use_case})
            return [LLMTestResult.from_dict(doc) for doc in cursor]
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Test-Ergebnisse für Use-Case {use_case}: {str(e)}")
            return []
    
    def get_best_model_for_use_case(
        self,
        use_case: str,
        test_size: str,
        criteria: str = "duration"
    ) -> Optional[str]:
        """
        Gibt das beste Modell für einen Use-Case basierend auf Test-Ergebnissen zurück.
        
        Args:
            use_case: Der Use-Case
            test_size: Die Test-Größe
            criteria: Kriterium für "beste" ("duration", "tokens", "reliability")
            
        Returns:
            Optional[str]: Die Modell-ID des besten Modells oder None
        """
        try:
            # Filtere nur erfolgreiche Tests
            query = {
                "use_case": use_case,
                "test_size": test_size,
                "status": "success"
            }
            
            if criteria == "duration":
                # Schnellste Dauer
                doc = self.test_results.find_one(
                    query,
                    sort=[("duration_ms", ASCENDING)]
                )
            elif criteria == "tokens":
                # Wenigste Tokens
                doc = self.test_results.find_one(
                    query,
                    sort=[("tokens", ASCENDING)]
                )
            elif criteria == "reliability":
                # Höchste Success-Rate (berechnet aus allen Tests)
                # Für jetzt: einfach nach Status sortieren (success zuerst)
                doc = self.test_results.find_one(
                    query,
                    sort=[("status", ASCENDING), ("duration_ms", ASCENDING)]
                )
            else:
                logger.warning(f"Unbekanntes Kriterium {criteria}, verwende 'duration'")
                doc = self.test_results.find_one(
                    query,
                    sort=[("duration_ms", ASCENDING)]
                )
            
            if doc:
                return doc.get("model_id")
            return None
        except Exception as e:
            logger.error(
                f"Fehler beim Finden des besten Modells für {use_case}/{test_size}: {str(e)}"
            )
            return None


class LLMUseCaseConfigRepository:
    """
    Repository für die Verwaltung von Use-Case-Konfigurationen in MongoDB.
    """
    
    def __init__(self) -> None:
        """Initialisiert das Repository."""
        self.db: Database[Any] = get_mongodb_database()
        self.use_case_configs: Collection[Any] = self.db.llm_use_case_config
        
        # Indizes erstellen
        self._create_indexes()
        
        logger.info("LLMUseCaseConfigRepository initialisiert")
    
    def _create_indexes(self) -> None:
        """Erstellt die notwendigen Indizes für die Collection."""
        try:
            # Unique Index auf use_case
            self.use_case_configs.create_index([("use_case", ASCENDING)], unique=True)
            
            logger.debug("MongoDB-Indizes für llm_use_case_config erstellt")
        except Exception as e:
            logger.error(f"Fehler beim Erstellen der Indizes für llm_use_case_config: {str(e)}")
    
    def get_current_model(self, use_case: str) -> Optional[str]:
        """
        Gibt das aktuell konfigurierte Modell für einen Use-Case zurück.
        
        Args:
            use_case: Der Use-Case
            
        Returns:
            Optional[str]: Die Modell-ID oder None wenn nicht konfiguriert
        """
        try:
            doc = self.use_case_configs.find_one({"use_case": use_case})
            if doc:
                return doc.get("current_model_id")
            return None
        except Exception as e:
            logger.error(f"Fehler beim Abrufen der Konfiguration für Use-Case {use_case}: {str(e)}")
            return None
    
    def set_current_model(self, use_case: str, model_id: str, updated_by: Optional[str] = None) -> bool:
        """
        Setzt das aktuelle Modell für einen Use-Case.
        
        Args:
            use_case: Der Use-Case
            model_id: Die Modell-ID
            updated_by: Optional, User-ID
            
        Returns:
            bool: True wenn erfolgreich, False sonst
        """
        try:
            config = LLMUseCaseConfig(
                use_case=use_case,
                current_model_id=model_id,
                updated_at=datetime.now(UTC),
                updated_by=updated_by
            )
            
            doc = config.to_dict()
            
            # Verwende replace_one mit upsert=True
            result: UpdateResult = self.use_case_configs.replace_one(
                {"use_case": use_case},
                doc,
                upsert=True
            )
            
            if result.upserted_id or result.modified_count > 0:
                logger.info(f"Aktuelles Modell für {use_case} auf {model_id} gesetzt")
                return True
            return False
        except Exception as e:
            logger.error(f"Fehler beim Setzen des aktuellen Modells für {use_case}: {str(e)}")
            return False
    
    def get_all_use_case_configs(self) -> Dict[str, str]:
        """
        Gibt alle Use-Case-Konfigurationen zurück.
        
        Returns:
            Dict[str, str]: Dictionary mit use_case -> model_id
        """
        try:
            cursor = self.use_case_configs.find({})
            return {
                doc["use_case"]: doc["current_model_id"]
                for doc in cursor
            }
        except Exception as e:
            logger.error(f"Fehler beim Abrufen aller Use-Case-Konfigurationen: {str(e)}")
            return {}

