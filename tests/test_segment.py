import asyncio
from src.processors.audio_processor import AudioProcessor
from pathlib import Path
import sys
import logging

# Konfiguriere Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('test_segment.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

async def main():
    logger.info("Starte Test-Verarbeitung")
    processor = AudioProcessor(None)
    segment_path = Path("temp-processing/audio/575b4aff6041be6f3e9506bc51e956b5/segment_21.mp3")
    
    if not segment_path.exists():
        logger.error(f"Segment-Datei nicht gefunden: {segment_path}")
        return
        
    logger.info(f"Verarbeite Segment: {segment_path}")
    logger.info(f"Dateigröße: {segment_path.stat().st_size / (1024*1024):.2f} MB")
    
    try:
        result = await processor.process(
            segment_path,
            skip_segments=list(range(0, 20))
        )
        logger.info("Verarbeitung erfolgreich")
        
    except Exception as e:
        logger.error(f"Fehler bei der Verarbeitung: {str(e)}", exc_info=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Verarbeitung durch Benutzer abgebrochen")
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}", exc_info=True) 