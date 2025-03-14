"""
MongoDB-Modul.
Stellt Funktionen und Klassen für die Interaktion mit MongoDB bereit.
"""

from .connection import get_mongodb_client, get_mongodb_database, close_mongodb_connection
from .repository import SessionJobRepository

# Singleton-Instanz des Repositories
_job_repository = None

def get_job_repository() -> SessionJobRepository:
    """
    Gibt eine Singleton-Instanz des SessionJobRepository zurück.
    
    Returns:
        SessionJobRepository: Repository-Instanz
    """
    global _job_repository
    
    if _job_repository is None:
        _job_repository = SessionJobRepository()
    
    return _job_repository

# Importiere worker_manager erst nach der Definition von get_job_repository
from .worker_manager import SessionWorkerManager, get_worker_manager

__all__ = [
    'SessionJobRepository',
    'SessionWorkerManager',
    'get_job_repository',
    'get_worker_manager',
    'get_mongodb_client',
    'get_mongodb_database',
    'close_mongodb_connection'
] 