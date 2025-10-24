#!/usr/bin/env python3
"""
Test-Skript für die Dataclasses der Job- und Batch-Modelle.
"""

import sys
import os
import logging
from datetime import datetime, UTC

# Logging konfigurieren
logging.basicConfig(level=logging.INFO,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Stelle sicher, dass das Hauptverzeichnis im Pythonpfad ist
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

try:
    from src.core.models import (
        JobStatus, 
        AccessVisibility, 
        AccessControl, 
        LogEntry, 
        JobProgress, 
        JobParameters, 
        JobResults, 
        JobError, 
        Job, 
        Batch
    )
    from src.core.mongodb import get_job_repository, close_mongodb_connection
    logger.info("Module erfolgreich importiert")
except ImportError as e:
    logger.error(f"Fehler beim Import der Module: {str(e)}")
    sys.exit(1)

def test_job_model():
    """
    Testet die Job-Dataclass durch Erstellung und Konvertierung.
    """
    logger.info("Teste Job-Modell...")
    
    # Erstellung von Job-Komponenten
    params = JobParameters(
        event="Test-Event",
        session="Test-Session",
        url="https://example.com",
        filename="test.md"
    )
    
    progress = JobProgress(
        step="Verarbeitung",
        percent=50,
        message="Die Hälfte ist geschafft"
    )
    
    log_entry = LogEntry(
        timestamp=datetime.now(UTC),
        level="info",
        message="Test-Log-Eintrag"
    )
    
    # Job erstellen
    job = Job(
        parameters=params,
        user_id="test-user",
        progress=progress,
        logs=[log_entry]
    )
    
    # In Dict umwandeln
    job_dict = job.to_dict()
    
    # Wieder zurück in Job-Objekt
    job_reconverted = Job.from_dict(job_dict)
    
    # Ausgabe
    logger.info(f"Job-ID: {job.job_id}")
    logger.info(f"Job-Status: {job.status}")
    logger.info(f"Job-Parameter: {job.parameters}")
    logger.info(f"Job-Fortschritt: {job.progress.step} - {job.progress.percent}%")
    
    # Prüfen, ob die Konvertierung funktioniert hat
    assert job.job_id == job_reconverted.job_id, "Job-ID stimmt nicht überein"
    assert job.status == job_reconverted.status, "Status stimmt nicht überein"
    assert job.user_id == job_reconverted.user_id, "User-ID stimmt nicht überein"
    assert job.parameters.event == job_reconverted.parameters.event, "Event stimmt nicht überein"
    
    logger.info("Job-Modell-Test erfolgreich")
    return job

def test_batch_model():
    """
    Testet die Batch-Dataclass durch Erstellung und Konvertierung.
    """
    logger.info("Teste Batch-Modell...")
    
    # Batch erstellen
    batch = Batch(
        total_jobs=3,
        job_ids=["job-1", "job-2", "job-3"],
        user_id="test-user",
        completed_jobs=1,
        failed_jobs=0
    )
    
    # In Dict umwandeln
    batch_dict = batch.to_dict()
    
    # Wieder zurück in Batch-Objekt
    batch_reconverted = Batch.from_dict(batch_dict)
    
    # Ausgabe
    logger.info(f"Batch-ID: {batch.batch_id}")
    logger.info(f"Batch-Status: {batch.status}")
    logger.info(f"Batch-Jobs: {batch.job_ids}")
    logger.info(f"Batch-Fortschritt: {batch.completed_jobs}/{batch.total_jobs}")
    
    # Prüfen, ob die Konvertierung funktioniert hat
    assert batch.batch_id == batch_reconverted.batch_id, "Batch-ID stimmt nicht überein"
    assert batch.status == batch_reconverted.status, "Status stimmt nicht überein"
    assert batch.user_id == batch_reconverted.user_id, "User-ID stimmt nicht überein"
    assert batch.total_jobs == batch_reconverted.total_jobs, "Anzahl der Jobs stimmt nicht überein"
    
    logger.info("Batch-Modell-Test erfolgreich")
    return batch

def test_mongodb_integration():
    """
    Testet die Interaktion zwischen den Dataclasses und MongoDB.
    """
    logger.info("Teste MongoDB-Integration...")
    
    try:
        # Repository holen
        repo = get_job_repository()
        logger.info("Repository erfolgreich geholt")
        
        # Job erstellen
        job = test_job_model()
        
        # Job speichern
        job_id = repo.create_job(job)
        logger.info(f"Job in MongoDB gespeichert: {job_id}")
        
        # Job laden
        loaded_job = repo.get_job(job_id)
        logger.info(f"Job aus MongoDB geladen: {loaded_job.job_id}")
        
        # Job aktualisieren
        update_success = repo.update_job_status(
            job_id=job_id,
            status=JobStatus.PROCESSING,
            progress=JobProgress(
                step="Dateiverarbeitung",
                percent=75,
                message="Fast fertig"
            )
        )
        logger.info(f"Job aktualisiert: {update_success}")
        
        # Log hinzufügen
        log_success = repo.add_log_entry(
            job_id=job_id,
            level="info",
            message="Test der Log-Funktion"
        )
        logger.info(f"Log hinzugefügt: {log_success}")
        
        # Batch erstellen
        batch = test_batch_model()
        batch.job_ids = [job_id]
        
        # Batch speichern
        batch_id = repo.create_batch(batch)
        logger.info(f"Batch in MongoDB gespeichert: {batch_id}")
        
        # Batch laden
        loaded_batch = repo.get_batch(batch_id)
        logger.info(f"Batch aus MongoDB geladen: {loaded_batch.batch_id}")
        
        # Job abschließen
        complete_success = repo.update_job_status(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            results=JobResults(
                markdown_file="/events/test/event.md",
                markdown_url="/api/events/files/test/event.md",
                assets=["/assets/image1.png"]
            )
        )
        logger.info(f"Job abgeschlossen: {complete_success}")
        
        # Batch aktualisieren
        batch_success = repo.update_batch_progress(batch_id)
        logger.info(f"Batch aktualisiert: {batch_success}")
        
        # Fertig
        logger.info("MongoDB-Integration erfolgreich getestet")
        
    except Exception as e:
        logger.error(f"Fehler beim MongoDB-Test: {str(e)}", exc_info=True)
        raise
    finally:
        # MongoDB-Verbindung schließen
        close_mongodb_connection()
        logger.info("MongoDB-Verbindung geschlossen")

if __name__ == "__main__":
    logger.info("Starte Tests...")
    test_mongodb_integration()
    logger.info("Tests abgeschlossen") 