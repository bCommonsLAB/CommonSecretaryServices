"""
Temporäre MongoDB-Initialisierungsdatei für Tests.
Vermeidet zirkuläre Importe.
"""

from src.core.mongodb.repository import EventJobRepository
from src.core.mongodb.connection import get_mongodb_client, get_mongodb_database, close_mongodb_connection

# Singleton-Instanz des Repositories
_job_repository = None

def get_job_repository() -> EventJobRepository:
    """
    Gibt eine Singleton-Instanz des EventJobRepository zurück.
    
    Returns:
        EventJobRepository: Repository-Instanz
    """
    global _job_repository
    
    if _job_repository is None:
        _job_repository = EventJobRepository()
    
    return _job_repository

# Singleton-Instanz des Worker-Managers
# Wird hier nicht implementiert, da wir es für den Test nicht brauchen

__all__ = [
    'EventJobRepository',
    'get_job_repository',
    'get_mongodb_client',
    'get_mongodb_database',
    'close_mongodb_connection'
] 