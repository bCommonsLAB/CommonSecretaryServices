"""
MongoDB-Modul.
Stellt Funktionen und Klassen für die Interaktion mit MongoDB bereit.
"""

from .connection import get_mongodb_client, get_mongodb_database, close_mongodb_connection
from .repository import EventJobRepository

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

# Importiere worker_manager erst nach der Definition von get_job_repository
from .worker_manager import EventWorkerManager, get_worker_manager

__all__ = [
    'EventJobRepository',
    'EventWorkerManager',
    'get_job_repository',
    'get_worker_manager',
    'get_mongodb_client',
    'get_mongodb_database',
    'close_mongodb_connection'
] 