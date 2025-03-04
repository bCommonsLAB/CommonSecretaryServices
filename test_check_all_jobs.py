#!/usr/bin/env python
"""
Test-Skript zum Anzeigen aller Jobs eines Batches.

Dieses Skript zeigt alle Jobs eines Batches an, unabhängig vom Status.

Voraussetzungen:
- MongoDB muss installiert und erreichbar sein
- Die Jobs müssen bereits erstellt worden sein

Verwendung:
python test_check_all_jobs.py --batchId=<batch_id>
"""

import argparse
import logging
import sys
import os
from typing import Dict, Any, List, Optional
from tabulate import tabulate

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    # Importiere die benötigten Klassen direkt
    from src.core.models.job_models import Job, Batch, JobStatus
    
    # Importiere die Test-Repository-Klasse
    from test_repository import TestEventJobRepository
except ImportError as e:
    logger.error(f"Fehler beim Importieren der Module: {str(e)}")
    sys.exit(1)

def get_all_jobs(batch_id: str) -> List[Job]:
    """
    Gibt alle Jobs eines Batches zurück.
    
    Args:
        batch_id: Batch-ID
        
    Returns:
        Liste von Job-Objekten
    """
    # Repository-Instanz erstellen
    job_repo = TestEventJobRepository()
    
    # Batch abrufen
    batch = job_repo.get_batch(batch_id)
    if not batch:
        logger.error(f"Batch {batch_id} nicht gefunden")
        return []
    
    # Jobs abrufen
    jobs = []
    for job_id in batch.job_ids:
        job = job_repo.get_job(job_id)
        if job:
            jobs.append(job)
    
    logger.info(f"{len(jobs)} Jobs für Batch {batch_id} gefunden")
    
    return jobs

def print_jobs_table(jobs: List[Job]) -> None:
    """
    Gibt die Jobs als Tabelle aus.
    
    Args:
        jobs: Liste von Job-Objekten
    """
    if not jobs:
        print("Keine Jobs zum Anzeigen.")
        return
    
    # Tabellendaten vorbereiten
    table_data = []
    for job in jobs:
        job_id = job.job_id
        status = job.status.value if hasattr(job.status, "value") else str(job.status)
        created_at = job.created_at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(job.created_at, "strftime") else str(job.created_at)
        
        # Parameter extrahieren
        event = job.parameters.event if hasattr(job.parameters, "event") else "-"
        session = job.parameters.session if hasattr(job.parameters, "session") else "-"
        
        # Ergebnisse prüfen
        has_results = hasattr(job, "results") and job.results is not None
        
        table_data.append([
            job_id,
            status,
            created_at,
            event,
            session,
            "Ja" if has_results else "Nein"
        ])
    
    # Tabelle ausgeben
    headers = [
        "Job-ID",
        "Status",
        "Erstellt am",
        "Event",
        "Session",
        "Hat Ergebnisse"
    ]
    
    print("\nJobs im Batch:")
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    # Status-Zusammenfassung
    status_counts = {}
    for job in jobs:
        status = job.status.value if hasattr(job.status, "value") else str(job.status)
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print("\nStatus-Zusammenfassung:")
    for status, count in status_counts.items():
        print(f"  {status}: {count} Jobs")

def main():
    """
    Hauptfunktion des Skripts.
    """
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description='Anzeige aller Jobs eines Batches')
    parser.add_argument('--batchId', type=str, required=True, help='Batch-ID')
    args = parser.parse_args()
    
    # Jobs abrufen
    jobs = get_all_jobs(args.batchId)
    
    # Ausgabe der Jobs
    if not jobs:
        logger.info("Keine Jobs gefunden.")
    else:
        logger.info(f"{len(jobs)} Jobs gefunden.")
        print_jobs_table(jobs)

if __name__ == "__main__":
    main() 