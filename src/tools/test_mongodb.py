#!/usr/bin/env python3
"""
Test-Skript zur Überprüfung der MongoDB-Integration.
"""

import sys
import os
import logging
from pathlib import Path

# Logging konfigurieren
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Stelle sicher, dass das Hauptverzeichnis im Pythonpfad ist
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from src.core.mongodb import get_job_repository, close_mongodb_connection
    logger.info("MongoDB-Module erfolgreich importiert")
except ImportError as e:
    logger.error(f"Fehler beim Import der MongoDB-Module: {str(e)}")
    sys.exit(1)

def test_mongodb_connection():
    """
    Testet die MongoDB-Verbindung und das Repository.
    """
    try:
        # Repository holen
        repo = get_job_repository()
        logger.info("Repository erfolgreich geholt")
        
        # Test-Job erstellen
        job_data = {
            "parameters": {
                "event": "Test Event",
                "session": "Test Session",
                "url": "https://example.com/test",
                "filename": "test.md",
                "track": "Test Track"
            }
        }
        
        job_id = repo.create_job(job_data, user_id="test-user")
        logger.info(f"Job erstellt: {job_id}")
        
        # Job abrufen
        job = repo.get_job(job_id)
        logger.info(f"Job abgerufen: {job['job_id']}")
        
        # Job-Status aktualisieren
        success = repo.update_job_status(
            job_id=job_id,
            status="processing",
            progress={
                "step": "testing",
                "percent": 50,
                "message": "Test läuft"
            }
        )
        logger.info(f"Job-Status aktualisiert: {success}")
        
        # Log-Eintrag hinzufügen
        success = repo.add_log_entry(
            job_id=job_id,
            level="info",
            message="Test-Log-Eintrag"
        )
        logger.info(f"Log-Eintrag hinzugefügt: {success}")
        
        # Job erneut abrufen
        job = repo.get_job(job_id)
        logger.info(f"Job-Status: {job['status']}")
        logger.info(f"Job-Fortschritt: {job['progress']}")
        logger.info(f"Job-Logs: {job['logs']}")
        
        # Batch erstellen
        batch_data = {
            "job_ids": [job_id],
            "total_jobs": 1
        }
        
        batch_id = repo.create_batch(batch_data, user_id="test-user")
        logger.info(f"Batch erstellt: {batch_id}")
        
        # Job abschließen
        success = repo.update_job_status(
            job_id=job_id,
            status="completed",
            results={
                "markdown_file": "/events/test/test.md",
                "markdown_url": "/api/events/files/test/test.md",
                "assets": []
            }
        )
        logger.info(f"Job abgeschlossen: {success}")
        
        # Batch-Fortschritt aktualisieren
        success = repo.update_batch_progress(batch_id)
        logger.info(f"Batch-Fortschritt aktualisiert: {success}")
        
        logger.info("MongoDB-Test erfolgreich abgeschlossen!")
        
    except Exception as e:
        logger.error(f"Fehler beim MongoDB-Test: {str(e)}", exc_info=True)
        raise
    finally:
        # MongoDB-Verbindung schließen
        close_mongodb_connection()
        logger.info("MongoDB-Verbindung geschlossen")

if __name__ == "__main__":
    logger.info("Starte MongoDB-Test")
    test_mongodb_connection() 