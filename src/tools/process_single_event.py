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
        result = await processor.process_event(
            event=input_data.get('event', ''),
            session=input_data.get('session', ''),
            url=input_data.get('url', ''),
            filename=input_data.get('filename', ''),
            track=input_data.get('track', ''),
            day=input_data.get('day'),
            starttime=input_data.get('starttime'),
            endtime=input_data.get('endtime'),
            speakers=input_data.get('speakers'),
            video_url=input_data.get('video_url'),
            attachments_url=input_data.get('attachments_url'),
            source_language=input_data.get('source_language', 'en'),
            target_language=input_data.get('target_language', 'de')
        )
        
        # Speichere das Ergebnis
        output_data = {
            "success": True,
            "error": None,
            "data": {
                "markdown": result.data.markdown if hasattr(result.data, 'markdown') else "",
                "file_path": result.data.file_path if hasattr(result.data, 'file_path') else "",
                "metadata": result.data.metadata if hasattr(result.data, 'metadata') else {}
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