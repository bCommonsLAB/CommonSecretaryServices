"""
Event-Prozessor-Skript für isolierte Verarbeitung.

Dieses Skript wird als separater Prozess gestartet, um ein einzelnes Event
in einem völlig isolierten Kontext zu verarbeiten.
"""
import sys
import json
import os
# from pathlib import Path  # Wird aktuell nicht verwendet

# Stelle sicher, dass das Hauptverzeichnis im Pythonpfad ist
sys.path.append(os.getcwd())

from src.processors.event_processor import EventProcessor
from src.core.resource_tracking import ResourceCalculator
import asyncio

async def process_event(input_file_path: str, output_file_path: str):
    """Verarbeitet ein Event basierend auf den Daten in der Input-Datei."""
    
    print(f"Starte Verarbeitung von Event aus {input_file_path}")
    
    try:
        # Lese die Input-Daten
        with open(input_file_path, 'r', encoding='utf-8') as f:
            input_data = json.load(f)
        
        # Erstelle einen neuen EventProcessor
        process_id = input_data.get('process_id', 'isolated_event_processor')
        processor = EventProcessor(
            resource_calculator=ResourceCalculator(),
            process_id=process_id
        )
        
        # Verarbeite das Event
        result = await processor.create_event_summary(
            event_name=input_data.get('event', ''),
            template=input_data.get('template', 'event-eco-social-summary'),
            target_language=input_data.get('target_language', 'de'),
            use_cache=input_data.get('use_cache', True)
        )
        
        # Speichere das Ergebnis
        output_data = {
            "success": True,
            "error": None,
            "data": {
                "summary": result.data.output.summary if result.data and result.data.output else "",
                "metadata": result.data.output.metadata if result.data and result.data.output else {},
                "track_count": result.data.track_count if result.data else 0
            }
        }
        
        print(f"Verarbeitung erfolgreich, speichere Ergebnis in {output_file_path}")
        
    except Exception as e:
        import traceback
        error_msg = f"Fehler bei der Verarbeitung: {str(e)}"
        traceback_str = traceback.format_exc()
        print(f"FEHLER: {error_msg}")
        print(traceback_str)
        
        # Speichere den Fehler
        output_data = {
            "success": False,
            "error": {
                "message": str(e),
                "traceback": traceback_str
            },
            "data": None
        }
    
    # Schreibe das Ergebnis in die Output-Datei
    try:
        with open(output_file_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, indent=2)
        print(f"Ergebnis gespeichert in {output_file_path}")
    except Exception as e:
        print(f"Fehler beim Speichern des Ergebnisses: {str(e)}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Verwendung: python process_single_event.py <input_file_path> <output_file_path>")
        sys.exit(1)
    
    input_file_path = sys.argv[1]
    output_file_path = sys.argv[2]
    
    # Führe die Verarbeitung asynchron aus
    asyncio.run(process_event(input_file_path, output_file_path)) 