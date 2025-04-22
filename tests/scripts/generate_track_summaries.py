#!/usr/bin/env python3
"""
Skript zum Generieren von Track-Zusammenfassungen für mehrere Tracks.
"""
import sys
import os
import asyncio
import json
from typing import List, Dict, Any
import time
from datetime import datetime

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# Jetzt können wir die Module importieren
from src.core.resource_tracking import ResourceCalculator
from src.processors.track_processor import TrackProcessor
from src.utils.logger import get_logger

# Logger initialisieren
logger = get_logger(processor_name="track_summary_generator", process_id="batch_process")

# Liste der Tracks, die verarbeitet werden sollen
TRACKS = [
    "Collaboration-and-Content-Management-19",
    "Government-Collaboration-11",
    "Open-Media-12",
    "Open-Research-22",
    "Main-Track-K-Building-18",
    "Open-Source-In-The-European-Legislative-Landscape-and-Beyond-34",
    "Community-17",
    "Social-Web-12",
    "Confidential-Computing-11",
    "Educational-14",
    "Embedded-Mobile-and-Automotive-19",
    "Energy-Accelerating-the-Transition-through-Open-Source-24",
    "FOSDEM-Junior-18",
    "FOSS-on-Mobile-Devices-11",
    "Funding-the-FOSS-Ecosystem-12",
    "Lightning-Talks-38",
    "LibreOffice-21",
    "Main-Track-Janson-7",
    "Keynotes-13",
    "Modern-Email-18",
    "Rust-12",
    "Tool-the-Docs-8",
    "APIs-GraphQL-OpenAPI-AsyncAPI-and-friends-7"
]

# Template für die Zusammenfassung
TEMPLATE = "track-eco-social-summary"

# Zielsprache
TARGET_LANGUAGE = "de"

# Ob der Cache verwendet werden soll
USE_CACHE = True

async def process_track(track_name: str) -> Dict[str, Any]:
    """
    Verarbeitet einen Track und erstellt eine Zusammenfassung.
    
    Args:
        track_name: Name des Tracks
        
    Returns:
        Dict[str, Any]: Die Zusammenfassung als Dictionary
    """
    start_time = time.time()
    logger.info(f"Starte Verarbeitung von Track: {track_name}")
    
    try:
        # Resource Calculator initialisieren
        resource_calculator = ResourceCalculator()
        
        # Track-Processor initialisieren
        processor = TrackProcessor(resource_calculator)
        
        # Track-Zusammenfassung erstellen
        response = await processor.create_track_summary(
            track_name=track_name,
            template=TEMPLATE,
            target_language=TARGET_LANGUAGE,
            use_cache=USE_CACHE
        )
        
        # Response in Dictionary umwandeln
        result = response.to_dict()
        
        # Verarbeitungszeit berechnen
        duration = time.time() - start_time
        logger.info(f"Track {track_name} erfolgreich verarbeitet in {duration:.2f} Sekunden")
        
        # Ergebnis zurückgeben
        return {
            "track_name": track_name,
            "status": "success",
            "duration": duration,
            "result": result
        }
        
    except Exception as e:
        # Fehler protokollieren
        duration = time.time() - start_time
        logger.error(f"Fehler bei der Verarbeitung von Track {track_name}: {str(e)}")
        
        # Fehlermeldung zurückgeben
        return {
            "track_name": track_name,
            "status": "error",
            "duration": duration,
            "error": str(e)
        }

async def process_all_tracks() -> List[Dict[str, Any]]:
    """
    Verarbeitet alle Tracks nacheinander.
    
    Returns:
        List[Dict[str, Any]]: Liste der Ergebnisse für jeden Track
    """
    results = []
    
    for track_name in TRACKS:
        result = await process_track(track_name)
        results.append(result)
        
        # Kurze Pause zwischen den Tracks
        await asyncio.sleep(1)
    
    return results

def save_results(results: List[Dict[str, Any]]) -> str:
    """
    Speichert die Ergebnisse in einer JSON-Datei.
    
    Args:
        results: Liste der Ergebnisse
        
    Returns:
        str: Pfad zur gespeicherten Datei
    """
    # Ergebnisverzeichnis erstellen
    results_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(results_dir, exist_ok=True)
    
    # Dateiname mit Zeitstempel
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"track_summaries_{timestamp}.json"
    file_path = os.path.join(results_dir, filename)
    
    # Ergebnisse speichern
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    logger.info(f"Ergebnisse gespeichert in: {file_path}")
    return file_path

def main() -> None:
    """
    Hauptfunktion zum Starten der Verarbeitung.
    """
    logger.info(f"Starte Verarbeitung von {len(TRACKS)} Tracks")
    
    # Alle Tracks verarbeiten
    results = asyncio.run(process_all_tracks())
    
    # Statistiken berechnen
    successful = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "error")
    total_duration = sum(r["duration"] for r in results)
    
    # Ergebnisse speichern
    file_path = save_results(results)
    
    # Zusammenfassung ausgeben
    logger.info(f"Verarbeitung abgeschlossen:")
    logger.info(f"- Erfolgreich: {successful}")
    logger.info(f"- Fehlgeschlagen: {failed}")
    logger.info(f"- Gesamtdauer: {total_duration:.2f} Sekunden")
    logger.info(f"- Ergebnisse gespeichert in: {file_path}")
    
    print(f"\nVerarbeitung abgeschlossen:")
    print(f"- Erfolgreich: {successful}")
    print(f"- Fehlgeschlagen: {failed}")
    print(f"- Gesamtdauer: {total_duration:.2f} Sekunden")
    print(f"- Ergebnisse gespeichert in: {file_path}")

if __name__ == "__main__":
    main() 