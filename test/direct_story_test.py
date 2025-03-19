"""
Direkter Test der Story-Generierungsfunktionalität ohne API.
"""
import asyncio
import sys
import os
import json

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.models.story import StoryProcessorInput
from core.resource_tracking import ResourceCalculator
from processors.story_processor import StoryProcessor

async def test_story_generation_directly():
    """Testet die Story-Generierung direkt mit dem StoryProcessor."""
    print("Teste direkte Story-Generierung...")
    
    # Story-Processor-Input erstellen
    input_data = StoryProcessorInput(
        topic_id="nachhaltigkeit-2023",
        event="forum-2023",
        target_group="politik",
        languages=["de", "en"],
        detail_level=3
    )
    
    # Story-Processor initialisieren und Story generieren
    resource_calculator = ResourceCalculator()
    processor = StoryProcessor(resource_calculator=resource_calculator)
    
    try:
        response = await processor.process_story(input_data)
        
        # Konvertiere die Antwort in ein Dictionary für die Ausgabe
        response_dict = response.to_dict()
        
        # Ausgabe der Antwort
        print("\nErfolgreiche Verarbeitung:")
        print(json.dumps(response_dict, indent=2, ensure_ascii=False))
        
        # Prüfen, ob Markdown-Dateien erstellt wurden
        if "data" in response_dict and "output" in response_dict["data"]:
            output = response_dict["data"]["output"]
            if "markdown_files" in output:
                print("\nGenerierte Markdown-Dateien:")
                for language, file_path in output["markdown_files"].items():
                    print(f"- {language}: {file_path}")
                    # Inhalt der Datei anzeigen
                    if os.path.exists(file_path):
                        print(f"\nInhalt der {language} Markdown-Datei:")
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            # Zeige nur die ersten 300 Zeichen an
                            print(content[:300] + "..." if len(content) > 300 else content)
                    else:
                        print(f"Warnung: Datei {file_path} existiert nicht")
        
        return response
    
    except Exception as e:
        print(f"Fehler bei der Story-Generierung: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(test_story_generation_directly()) 