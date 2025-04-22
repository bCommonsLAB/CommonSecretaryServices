#!/usr/bin/env python
"""
Test-Skript zum Testen der Batch-Event-Verarbeitung mit MongoDB.

Voraussetzungen:
- MongoDB muss installiert und erreichbar sein
- Die Datei fosdem-events.json muss im Verzeichnis tests/samples liegen

Verwendung:
python test_batch_events_async.py --startEvent=0 --countEvents=10
"""

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime
from typing import Dict, Any, List
import os

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Konstanten
EVENT_FILE = os.path.join("tests", "samples", "fosdem-events.json")

try:
    # Importiere die benötigten Klassen direkt
    from src.core.models.job_models import Job, Batch, JobStatus, JobParameters
    
    # Importiere die Test-Repository-Klasse
    from test_repository import TestEventJobRepository
except ImportError as e:
    logger.error(f"Fehler beim Importieren der Module: {str(e)}")
    sys.exit(1)

def load_events(start_index: int, count: int) -> List[Dict[str, Any]]:
    """
    Lädt Events aus der JSON-Datei.
    
    Args:
        start_index: Startindex der Events
        count: Anzahl der zu ladenden Events
        
    Returns:
        Liste von Event-Daten
    """
    try:
        with open(EVENT_FILE, 'r', encoding='utf-8') as f:
            all_events = json.load(f)
        
        # Extrahiere die gewünschten Events
        selected_events = all_events[start_index:start_index + count]
        logger.info(f"{len(selected_events)} Events geladen (von {len(all_events)} verfügbar)")
        
        return selected_events
    except Exception as e:
        logger.error(f"Fehler beim Laden der Events: {str(e)}")
        logger.error(f"Aktuelles Verzeichnis: {os.getcwd()}")
        logger.error(f"Gesuchte Datei: {os.path.abspath(EVENT_FILE)}")
        sys.exit(1)

def create_batch_and_jobs(events: List[Dict[str, Any]]) -> None:
    """
    Erstellt einen Batch und Jobs in MongoDB.
    
    Args:
        events: Liste von Event-Daten
    """
    # Repository-Instanz erstellen
    job_repo = TestEventJobRepository()
    
    # Batch erstellen
    batch_id = str(uuid.uuid4())
    batch = Batch(
        batch_id=batch_id,
        created_at=datetime.now(),
        total_jobs=len(events),
        completed_jobs=0,
        failed_jobs=0,
        status=JobStatus.PENDING,
        job_ids=[]
    )
    
    # Batch in MongoDB speichern
    job_repo.create_batch(batch)
    logger.info(f"Batch {batch_id} erstellt mit {len(events)} Jobs")
    
    # Jobs erstellen
    job_ids: List[str] = []
    for event in events:
        job_id = str(uuid.uuid4())
        
        # Parameter erstellen
        parameters = JobParameters(
            event=event.get("event"),
            session=event.get("session"),
            url=event.get("url"),
            filename=event.get("filename"),
            track=event.get("track")
        )
        
        # Job erstellen
        job = Job(
            job_id=job_id,
            batch_id=batch_id,
            created_at=datetime.now(),
            status=JobStatus.PENDING,
            parameters=parameters
        )
        
        # Job in MongoDB speichern
        job_repo.create_job(job)
        job_ids.append(job_id)
        logger.info(f"Job {job_id} erstellt für Event: {event.get('session', 'Unbekannt')}")
    
    # Job-IDs zum Batch hinzufügen
    job_repo.update_batch_job_ids(batch_id, job_ids)
    
    logger.info(f"Alle Jobs wurden erstellt. Batch-ID: {batch_id}")
    logger.info("Die Jobs werden nun vom Worker-Manager verarbeitet.")

def main():
    """
    Hauptfunktion des Skripts.
    """
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description='Test der Batch-Event-Verarbeitung')
    parser.add_argument('--startEvent', type=int, default=0, help='Startindex der Events')
    parser.add_argument('--countEvents', type=int, default=10, help='Anzahl der zu verarbeitenden Events')
    args = parser.parse_args()
    
    # Events laden
    events = load_events(args.startEvent, args.countEvents)
    
    # Batch und Jobs erstellen
    create_batch_and_jobs(events)

if __name__ == "__main__":
    main() 