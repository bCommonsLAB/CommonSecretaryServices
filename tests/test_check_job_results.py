#!/usr/bin/env python
"""
Test-Skript zum Überprüfen der Job-Ergebnisse.

Dieses Skript überprüft, ob die erfolgreichen Jobs Markdown-Dateien und Bilder haben
und ob diese über einen Endpunkt abrufbar sind.

Voraussetzungen:
- MongoDB muss installiert und erreichbar sein
- Die Jobs müssen bereits erstellt und verarbeitet worden sein

Verwendung:
python test_check_job_results.py --batchId=<batch_id>
"""

import argparse
import logging
import sys
import os
import requests
from typing import Dict, Any, List, Optional, Tuple, cast
from urllib.parse import urlparse
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
    from src.core.models.job_models import Job, JobStatus, JobResults
    
    # Importiere die Test-Repository-Klasse
    from test_repository import TestEventJobRepository
except ImportError as e:
    logger.error(f"Fehler beim Importieren der Module: {str(e)}")
    sys.exit(1)

def check_url_accessibility(url: str, timeout: int = 5) -> Tuple[bool, Optional[str]]:
    """
    Überprüft, ob eine URL zugänglich ist.
    
    Args:
        url: Die zu überprüfende URL
        timeout: Timeout in Sekunden
        
    Returns:
        Tuple mit (Erfolg, Fehlermeldung)
    """
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        if response.status_code == 200:
            return True, None
        else:
            return False, f"HTTP-Status: {response.status_code}"
    except requests.RequestException as e:
        return False, str(e)

def check_job_results(job: Job) -> Dict[str, Any]:
    """
    Überprüft die Ergebnisse eines Jobs.
    
    Args:
        job: Job-Objekt
        
    Returns:
        Dictionary mit Prüfergebnissen
    """
    # Initialisiere das Ergebnis-Dictionary mit Standardwerten
    result_dict: Dict[str, Any] = {
        "job_id": job.job_id,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "has_results": False,
        "markdown_file": None,
        "markdown_url": None,
        "markdown_accessible": False,
        "image_files": [],
        "image_urls": [],
        "images_accessible": [],
        "errors": []
    }
    
    # Prüfe, ob der Job Ergebnisse hat
    if not hasattr(job, "results") or job.results is None:
        result_dict["errors"].append("Job hat keine Ergebnisse")
        return result_dict
    
    result_dict["has_results"] = True
    job_results = job.results
    
    # Prüfe Markdown-Datei
    if hasattr(job_results, "markdown_file") and job_results.markdown_file:
        result_dict["markdown_file"] = job_results.markdown_file
    else:
        result_dict["errors"].append("Keine Markdown-Datei in den Ergebnissen")
    
    # Prüfe Markdown-URL
    if hasattr(job_results, "markdown_url") and job_results.markdown_url:
        result_dict["markdown_url"] = job_results.markdown_url
        
        # Prüfe, ob die Markdown-URL zugänglich ist
        accessible, error = check_url_accessibility(job_results.markdown_url)
        result_dict["markdown_accessible"] = accessible
        if not accessible:
            result_dict["errors"].append(f"Markdown-URL nicht zugänglich: {error}")
    else:
        result_dict["errors"].append("Keine Markdown-URL in den Ergebnissen")
    
    # Prüfe Bild-Dateien und URLs
    if hasattr(job_results, "image_files") and job_results.image_files:
        result_dict["image_files"] = job_results.image_files
    else:
        result_dict["errors"].append("Keine Bild-Dateien in den Ergebnissen")
    
    if hasattr(job_results, "image_urls") and job_results.image_urls:
        result_dict["image_urls"] = job_results.image_urls
        
        # Prüfe, ob die Bild-URLs zugänglich sind
        for url in job_results.image_urls:
            accessible, error = check_url_accessibility(url)
            result_dict["images_accessible"].append(accessible)
            if not accessible:
                result_dict["errors"].append(f"Bild-URL nicht zugänglich: {url} - {error}")
    else:
        result_dict["errors"].append("Keine Bild-URLs in den Ergebnissen")
    
    return result_dict

def check_batch_results(batch_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Überprüft die Ergebnisse aller erfolgreichen Jobs eines Batches.
    
    Args:
        batch_id: Optional, Batch-ID für die Filterung
        
    Returns:
        Liste mit Prüfergebnissen für jeden Job
    """
    # Repository-Instanz erstellen
    job_repo = TestEventJobRepository()
    
    # Erfolgreiche Jobs abrufen
    completed_jobs = job_repo.get_jobs_by_status(JobStatus.COMPLETED, batch_id)
    
    if not completed_jobs:
        logger.warning(f"Keine erfolgreichen Jobs gefunden" + 
                      (f" für Batch {batch_id}" if batch_id else ""))
        return []
    
    # Ergebnisse für jeden Job überprüfen
    results = []
    for job in completed_jobs:
        job_results = check_job_results(job)
        results.append(job_results)
        
        # Log-Ausgabe
        if job_results["errors"]:
            logger.warning(f"Job {job.job_id}: {len(job_results['errors'])} Fehler gefunden")
            for error in job_results["errors"]:
                logger.warning(f"  - {error}")
        else:
            logger.info(f"Job {job.job_id}: Alle Ergebnisse sind verfügbar und zugänglich")
    
    # Zusammenfassung
    total_jobs = len(results)
    jobs_with_errors = sum(1 for r in results if r["errors"])
    
    logger.info(f"Zusammenfassung: {total_jobs} Jobs überprüft, {jobs_with_errors} mit Fehlern")
    
    return results

def print_results_table(results: List[Dict[str, Any]]) -> None:
    """
    Gibt die Ergebnisse als Tabelle aus.
    
    Args:
        results: Liste mit Prüfergebnissen
    """
    if not results:
        print("Keine Ergebnisse zum Anzeigen.")
        return
    
    # Tabellendaten vorbereiten
    table_data = []
    for result in results:
        job_id = result["job_id"]
        status = result["status"]
        has_results = "Ja" if result["has_results"] else "Nein"
        markdown_file = result["markdown_file"] or "-"
        markdown_url = result["markdown_url"] or "-"
        markdown_accessible = "Ja" if result["markdown_accessible"] else "Nein"
        image_count = len(result["image_files"]) if result["image_files"] else 0
        images_accessible = "Ja" if all(result["images_accessible"]) else "Nein" if result["images_accessible"] else "-"
        error_count = len(result["errors"])
        
        table_data.append([
            job_id,
            status,
            has_results,
            markdown_file,
            markdown_url,
            markdown_accessible,
            image_count,
            images_accessible,
            error_count
        ])
    
    # Tabelle ausgeben
    headers = [
        "Job-ID",
        "Status",
        "Hat Ergebnisse",
        "Markdown-Datei",
        "Markdown-URL",
        "MD zugänglich",
        "Bilder",
        "Bilder zugänglich",
        "Fehler"
    ]
    
    print("\nErgebnisse der Job-Überprüfung:")
    print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    # Fehlerdetails ausgeben
    print("\nFehlerdetails:")
    for result in results:
        if result["errors"]:
            print(f"\nJob {result['job_id']}:")
            for i, error in enumerate(result["errors"], 1):
                print(f"  {i}. {error}")

def main():
    """
    Hauptfunktion des Skripts.
    """
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description='Überprüfung der Job-Ergebnisse')
    parser.add_argument('--batchId', type=str, help='Batch-ID für die Filterung')
    args = parser.parse_args()
    
    # Ergebnisse überprüfen
    results = check_batch_results(args.batchId)
    
    # Ausgabe der Ergebnisse
    if not results:
        logger.info("Keine Ergebnisse zum Überprüfen gefunden.")
    else:
        logger.info(f"{len(results)} Jobs überprüft.")
        print_results_table(results)

if __name__ == "__main__":
    main() 