"""
Test für Vimeo-API-Funktionalität.
"""

import asyncio
import sys
import json
from pathlib import Path

# Füge src zum Python-Pfad hinzu
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.processors.video_processor import VideoProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.video import VideoSource


async def test_vimeo_api():
    """Testet die Vimeo-Verarbeitung über den VideoProcessor."""
    
    # Resource Calculator erstellen
    resource_calculator = ResourceCalculator()
    
    # VideoProcessor erstellen
    processor = VideoProcessor(resource_calculator, process_id="test-vimeo-api")
    
    # Test-URL (Player-URL)
    test_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
    
    print(f"Teste Vimeo-API mit URL: {test_url}")
    
    # VideoSource erstellen
    video_source = VideoSource(url=test_url)
    
    try:
        # Video verarbeiten (nur Metadaten, kein Download)
        print("Verarbeite Video...")
        response = await processor.process(
            source=video_source,
            target_language="de",
            template="youtube",
            use_cache=False  # Cache deaktivieren für Test
        )
        
        print(f"✅ Verarbeitung erfolgreich!")
        print(f"Status: {response.status}")
        print(f"Titel: {response.data.metadata.title if response.data and response.data.metadata else 'N/A'}")
        print(f"Dauer: {response.data.metadata.duration_formatted if response.data and response.data.metadata else 'N/A'}")
        
        # Response-Details ausgeben
        print("\nResponse-Details:")
        print(json.dumps(response.to_dict(), indent=2, ensure_ascii=False))
        
    except Exception as e:
        print(f"❌ Fehler bei der API-Verarbeitung: {e}")
        print(f"Fehlertyp: {type(e).__name__}")
        
        # Detaillierte Fehlerinformationen
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_vimeo_api()) 