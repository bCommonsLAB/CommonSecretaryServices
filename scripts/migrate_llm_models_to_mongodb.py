"""
Migrations-Script: Migriert LLM-Modell-Konfiguration von config.yaml nach MongoDB.

Dieses Script liest die Modell-Konfiguration aus config.yaml und migriert sie
nach MongoDB. Die Migration ist idempotent - mehrfaches Ausführen ist sicher.

Verwendung:
    python scripts/migrate_llm_models_to_mongodb.py
"""

import sys
from pathlib import Path

# Füge src zum Python-Pfad hinzu
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.config import Config
from src.core.models.llm_models import LLMModel, LLMUseCaseConfig
from src.core.mongodb.llm_model_repository import (
    LLMModelRepository,
    LLMUseCaseConfigRepository
)
from src.core.mongodb.connection import get_mongodb_database
import logging
from datetime import datetime, UTC

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_model_id(provider: str, model_name: str) -> str:
    """
    Erstellt eine Modell-ID im Format "{provider}/{model_name}".
    
    Args:
        provider: Provider-Name
        model_name: Modell-Name
        
    Returns:
        str: Modell-ID
    """
    return f"{provider}/{model_name}"


def migrate_models_from_config() -> int:
    """
    Migriert alle Modelle aus config.yaml nach MongoDB.
    
    Returns:
        int: Anzahl der migrierten Modelle
    """
    config = Config()
    config_data = config.get_all()
    
    llm_providers_config = config_data.get('llm_providers', {})
    
    model_repo = LLMModelRepository()
    migrated_count = 0
    
    # Durchlaufe alle Provider
    for provider_name, provider_data in llm_providers_config.items():
        if not isinstance(provider_data, dict):
            continue
        
        # Prüfe ob Provider aktiviert ist
        if not provider_data.get('enabled', True):
            logger.info(f"Provider {provider_name} ist deaktiviert, überspringe")
            continue
        
        # Lade verfügbare Modelle
        available_models = provider_data.get('available_models', {})
        
        # Durchlaufe alle Use-Cases für diesen Provider
        for use_case, models_list in available_models.items():
            if not isinstance(models_list, list):
                continue
            
            # Erstelle Modell für jeden Eintrag in der Liste
            for model_name in models_list:
                if not isinstance(model_name, str) or not model_name.strip():
                    continue
                
                model_id = create_model_id(provider_name, model_name)
                
                # Prüfe ob Modell bereits existiert
                existing_model = model_repo.get_model(model_id)
                
                if existing_model:
                    # Aktualisiere Use-Cases falls nötig
                    if use_case not in existing_model.use_cases:
                        updated_use_cases = list(existing_model.use_cases) + [use_case]
                        model_repo.update_model(model_id, {"use_cases": updated_use_cases})
                        logger.info(f"Modell {model_id} aktualisiert: Use-Case {use_case} hinzugefügt")
                    else:
                        logger.debug(f"Modell {model_id} existiert bereits mit Use-Case {use_case}")
                else:
                    # Erstelle neues Modell
                    try:
                        model = LLMModel(
                            model_id=model_id,
                            provider=provider_name,
                            model_name=model_name,
                            use_cases=[use_case],
                            enabled=True
                        )
                        model_repo.create_model(model)
                        migrated_count += 1
                        logger.info(f"Modell {model_id} migriert (Use-Case: {use_case})")
                    except ValueError as e:
                        logger.warning(f"Fehler beim Erstellen des Modells {model_id}: {str(e)}")
    
    return migrated_count


def migrate_use_case_configs_from_config() -> int:
    """
    Migriert Use-Case-Konfigurationen aus config.yaml nach MongoDB.
    
    Returns:
        int: Anzahl der migrierten Konfigurationen
    """
    config = Config()
    config_data = config.get_all()
    
    llm_config_data = config_data.get('llm_config', {})
    use_cases_config = llm_config_data.get('use_cases', {})
    
    config_repo = LLMUseCaseConfigRepository()
    migrated_count = 0
    
    # Durchlaufe alle Use-Cases
    for use_case_name, use_case_data in use_cases_config.items():
        if not isinstance(use_case_data, dict):
            continue
        
        provider = use_case_data.get('provider')
        model = use_case_data.get('model')
        
        if not provider or not model:
            logger.warning(f"Use-Case {use_case_name} hat keinen Provider oder Modell, überspringe")
            continue
        
        # Erstelle Modell-ID
        model_id = create_model_id(provider, model)
        
        # Prüfe ob Modell existiert
        model_repo = LLMModelRepository()
        existing_model = model_repo.get_model(model_id)
        
        if not existing_model:
            logger.warning(
                f"Modell {model_id} für Use-Case {use_case_name} existiert nicht in MongoDB. "
                f"Bitte migrieren Sie zuerst die Modelle."
            )
            continue
        
        # Setze aktuelles Modell
        if config_repo.set_current_model(use_case_name, model_id):
            migrated_count += 1
            logger.info(f"Use-Case {use_case_name} konfiguriert: {model_id}")
        else:
            logger.warning(f"Fehler beim Setzen des Modells für Use-Case {use_case_name}")
    
    return migrated_count


def main() -> None:
    """Hauptfunktion für die Migration."""
    logger.info("Starte Migration von config.yaml nach MongoDB...")
    
    try:
        # Prüfe MongoDB-Verbindung
        db = get_mongodb_database()
        db.admin.command('ping')
        logger.info("MongoDB-Verbindung erfolgreich")
    except Exception as e:
        logger.error(f"Fehler bei der MongoDB-Verbindung: {str(e)}")
        logger.error("Bitte stellen Sie sicher, dass MongoDB läuft und MONGODB_URI korrekt gesetzt ist.")
        sys.exit(1)
    
    # Migriere Modelle
    logger.info("Migriere Modelle...")
    models_count = migrate_models_from_config()
    logger.info(f"{models_count} Modelle migriert")
    
    # Migriere Use-Case-Konfigurationen
    logger.info("Migriere Use-Case-Konfigurationen...")
    configs_count = migrate_use_case_configs_from_config()
    logger.info(f"{configs_count} Use-Case-Konfigurationen migriert")
    
    logger.info("Migration abgeschlossen!")
    logger.info(f"Zusammenfassung:")
    logger.info(f"  - {models_count} Modelle migriert")
    logger.info(f"  - {configs_count} Use-Case-Konfigurationen migriert")


if __name__ == "__main__":
    main()

