"""
Test für verzögertes Importieren in CacheableProcessor.
Prüft, ob der zirkuläre Import durch die verzögerte Importierung behoben wurde.
"""

import sys
import os
import logging

# Logger einrichten
logger = logging.getLogger(__name__)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def test_processor_imports():
    """Testet die Import-Struktur der Prozessoren."""
    logger.info("Teste Import-Struktur der Prozessoren...")
    
    try:
        # Importiere CacheableProcessor
        logger.info("Importiere CacheableProcessor...")
        from src.processors.cacheable_processor import CacheableProcessor
        logger.info("CacheableProcessor erfolgreich importiert")
        
        # Importiere AudioProcessor
        logger.info("Importiere AudioProcessor...")
        from src.processors.audio_processor import AudioProcessor
        logger.info("AudioProcessor erfolgreich importiert")
        
        # Importiere VideoProcessor
        logger.info("Importiere VideoProcessor...")
        from src.processors.video_processor import VideoProcessor
        logger.info("VideoProcessor erfolgreich importiert")
        
        # Importiere EventProcessor
        logger.info("Importiere EventProcessor...")
        from src.processors.event_processor import EventProcessor
        logger.info("EventProcessor erfolgreich importiert")
        
        # Importiere mongodb.connection
        logger.info("Importiere MongoDB-Connection...")
        from src.core.mongodb.connection import get_mongodb_database
        logger.info("MongoDB-Connection erfolgreich importiert")
        
        # Importiere worker_manager
        logger.info("Importiere WorkerManager...")
        from src.core.mongodb.worker_manager import EventWorkerManager
        logger.info("WorkerManager erfolgreich importiert")
        
        logger.info("Alle Importe erfolgreich")
        return True
    except ImportError as e:
        logger.error(f"Import-Fehler: {str(e)}")
        return False

if __name__ == "__main__":
    logger.info("Starte Import-Test...")
    result = test_processor_imports()
    if result:
        logger.info("Test erfolgreich: Zirkuläre Importe behoben!")
        sys.exit(0)
    else:
        logger.error("Test fehlgeschlagen: Zirkuläre Importe noch vorhanden")
        sys.exit(1) 