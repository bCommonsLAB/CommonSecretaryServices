"""
MongoDB-Modul.
Stellt Funktionen und Klassen für die Interaktion mit MongoDB bereit.
"""

from .connection import get_mongodb_client, get_mongodb_database, close_mongodb_connection
from .repository import SessionJobRepository
from .secretary_repository import SecretaryJobRepository
from .metrics_repository import RequestMetricsRepository

# Singleton-Instanz des Repositories
_job_repository = None
# Singleton-Instanz des Metrik-Repositories
_metrics_repository: "RequestMetricsRepository | None" = None

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

def get_metrics_repository() -> RequestMetricsRepository:
    """
    Gibt eine Singleton-Instanz des RequestMetricsRepository zurück.

    Returns:
        RequestMetricsRepository: Repository-Instanz für Request-Metriken
    """
    global _metrics_repository

    if _metrics_repository is None:
        _metrics_repository = RequestMetricsRepository()

    return _metrics_repository

# Importiere worker_manager erst nach der Definition von get_job_repository
from .worker_manager import SessionWorkerManager, get_worker_manager
from .secretary_worker_manager import SecretaryWorkerManager, get_secretary_worker_manager

__all__ = [
    'SessionJobRepository',
    'SecretaryJobRepository',
    'RequestMetricsRepository',
    'SessionWorkerManager',
    'SecretaryWorkerManager',
    'get_job_repository',
    'get_metrics_repository',
    'get_worker_manager',
    'get_secretary_worker_manager',
    'get_mongodb_client',
    'get_mongodb_database',
    'close_mongodb_connection'
] 