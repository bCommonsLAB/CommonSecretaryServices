#!/usr/bin/env python
"""
Überprüft die Ergebnisse der verarbeiteten Jobs.
"""

import argparse
import logging
import sys
import os
from typing import Optional, List
from tabulate import tabulate

from test_repository import TestEventJobRepository
from src.core.models.job_models import JobStatus

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def check_file_exists(file_path: str) -> bool:
    """
    Überprüft, ob eine Datei existiert.
    
    Args:
        file_path: Dateipfad
        
    Returns:
        bool: True, wenn die Datei existiert, sonst False
    """
    return os.path.isfile(file_path)

def check_job_results(batch_id: Optional[str] = None) -> None:
    """
    Überprüft die Ergebnisse der verarbeiteten Jobs.
    
    Args:
        batch_id: Optional, Batch-ID für die Filterung
    """
    # Repository initialisieren
    repository = TestEventJobRepository()
    
    # Abgeschlossene Jobs abrufen
    completed_jobs = repository.get_jobs_by_status(JobStatus.COMPLETED, batch_id=batch_id)
    
    if not completed_jobs:
        logger.warning(f"Keine abgeschlossenen Jobs gefunden" + 
                      (f" für Batch {batch_id}" if batch_id else ""))
        return
    
    logger.info(f"{len(completed_jobs)} abgeschlossene Jobs gefunden" + 
               (f" für Batch {batch_id}" if batch_id else ""))
    
    # Ergebnisse überprüfen
    results_data: List[List[str]] = []
    
    for job in completed_jobs:
        job_dict = job.to_dict()
        results = job_dict.get("results", {})
        
        markdown_file = results.get("markdown_file")
        markdown_url = results.get("markdown_url")
        assets = results.get("assets", [])
        
        # Überprüfe, ob die Markdown-Datei existiert
        markdown_exists = check_file_exists(markdown_file) if markdown_file else False
        
        # Überprüfe, ob die Assets existieren
        asset_exists = [check_file_exists(asset) for asset in assets]
        asset_status = f"{sum(asset_exists)}/{len(asset_exists)}" if asset_exists else "0/0"
        
        # Füge die Ergebnisse zur Tabelle hinzu
        results_data.append([
            job.job_id,
            markdown_file or "N/A",
            "Ja" if markdown_exists else "Nein",
            markdown_url or "N/A",
            ", ".join(assets) if assets else "N/A",
            asset_status
        ])
    
    # Tabelle ausgeben
    headers = ["Job-ID", "Markdown-Datei", "Existiert", "Markdown-URL", "Assets", "Assets existieren"]
    print(tabulate(results_data, headers=headers, tablefmt="grid"))

def main() -> None:
    """
    Hauptfunktion zum Überprüfen der Ergebnisse.
    """
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description="Überprüft die Ergebnisse der verarbeiteten Jobs.")
    parser.add_argument("--batchId", type=str, help="Batch-ID für die Filterung")
    args = parser.parse_args()
    
    try:
        # Ergebnisse überprüfen
        check_job_results(args.batchId)
    
    except Exception as e:
        logger.error(f"Fehler beim Überprüfen der Ergebnisse: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 