#!/usr/bin/env python
"""
Startet den Worker Manager für die Verarbeitung von Event-Jobs.
"""

import argparse
import logging
import signal
import sys
import time
from typing import Optional, Any, NoReturn, cast

# Importiere die Worker-Manager-Klasse
# Hinweis: Der Import kann fehlschlagen, wenn die Datei nicht im Pythonpfad ist
try:
    from test_worker_manager import TestEventWorkerManager
    from test_repository import TestEventJobRepository
except ImportError:
    # Füge das aktuelle Verzeichnis zum Pythonpfad hinzu
    import os
    sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
    from test_worker_manager import TestEventWorkerManager
    from test_repository import TestEventJobRepository

# Logger konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('worker_manager.log')
    ]
)

logger = logging.getLogger(__name__)

# Globale Variable für den Worker Manager
worker_manager: Optional[TestEventWorkerManager] = None

def signal_handler(sig: int, frame: Any) -> NoReturn:
    """
    Behandelt Signale zum Beenden des Programms.
    
    Args:
        sig: Signal-Nummer
        frame: Frame-Objekt
    """
    logger.info("Beende Worker Manager...")
    if worker_manager:
        worker_manager.stop()
    sys.exit(0)

def main() -> None:
    """
    Hauptfunktion zum Starten des Worker Managers.
    """
    global worker_manager
    
    # Kommandozeilenargumente parsen
    parser = argparse.ArgumentParser(description="Startet den Worker Manager für die Verarbeitung von Event-Jobs.")
    parser.add_argument("--maxWorkers", type=int, default=5, help="Maximale Anzahl gleichzeitiger Worker")
    parser.add_argument("--pollInterval", type=int, default=5, help="Intervall in Sekunden, in dem nach neuen Jobs gesucht wird")
    parser.add_argument("--runTime", type=int, default=0, help="Laufzeit in Sekunden (0 = unbegrenzt)")
    parser.add_argument("--batchId", type=str, help="Batch-ID für die Verarbeitung (optional)")
    args = parser.parse_args()
    
    # Signal-Handler registrieren
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Repository initialisieren
        repository = TestEventJobRepository()
        
        # Worker Manager initialisieren
        worker_manager = TestEventWorkerManager(
            max_workers=args.maxWorkers,
            poll_interval=args.pollInterval,
            repository=repository
        )
        
        # Worker Manager starten
        worker_manager.start()
        
        # Batch-ID ausgeben, falls vorhanden
        if args.batchId:
            batch = repository.get_batch(args.batchId)
            if batch:
                logger.info(f"Verarbeite Batch {args.batchId} mit {len(batch.job_ids)} Jobs")
            else:
                logger.warning(f"Batch {args.batchId} nicht gefunden")
        
        # Laufzeit begrenzen, falls angegeben
        if args.runTime > 0:
            logger.info(f"Worker Manager läuft für {args.runTime} Sekunden")
            time.sleep(args.runTime)
            worker_manager.stop()
            logger.info("Worker Manager beendet")
        else:
            logger.info("Worker Manager läuft unbegrenzt (STRG+C zum Beenden)")
            # Warte auf Signal zum Beenden
            signal.pause()
    
    except Exception as e:
        logger.error(f"Fehler beim Starten des Worker Managers: {str(e)}")
        if worker_manager:
            worker_manager.stop()
        sys.exit(1)

if __name__ == "__main__":
    main() 