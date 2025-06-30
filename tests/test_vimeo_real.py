"""
Test für echte Vimeo-URL-Verarbeitung.
"""

import asyncio
import sys
from pathlib import Path

# Füge src zum Python-Pfad hinzu
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.processors.video_processor import VideoProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.video import VideoSource


async def test_vimeo_url():
    """Testet die Verarbeitung einer echten Vimeo-URL."""
    
    # Resource Calculator erstellen
    resource_calculator = ResourceCalculator()
    
    # VideoProcessor erstellen
    processor = VideoProcessor(resource_calculator, process_id="test-vimeo")
    
    # Test-URL (Player-URL)
    test_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
    
    print(f"Teste Vimeo-URL: {test_url}")
    
    # URL normalisieren
    normalized_url = processor._normalize_vimeo_url(test_url)
    print(f"Normalisierte URL: {normalized_url}")
    
    # VideoSource erstellen
    video_source = VideoSource(url=test_url)
    
    try:
        # Video-Informationen extrahieren (ohne Download)
        print("Extrahiere Video-Informationen...")
        title, duration, video_id = processor._extract_video_info(test_url)
        
        print(f"Titel: {title}")
        print(f"Dauer: {duration} Sekunden ({processor._format_duration(duration)})")
        print(f"Video-ID: {video_id}")
        
        print("\n✅ Vimeo-URL-Verarbeitung erfolgreich!")
        
    except Exception as e:
        print(f"❌ Fehler bei der Vimeo-Verarbeitung: {e}")
        print(f"Fehlertyp: {type(e).__name__}")
        
        # Detaillierte Fehlerinformationen
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_vimeo_url()) 