"""
Test für den optimierten Event-Processor.
Verarbeitet ein FOSDEM-Event und misst die Performance.
"""

import asyncio
import json
from typing import Dict, Any, List
from src.processors.event_processor import EventProcessor
from src.core.resource_tracking import ResourceCalculator

async def test_event_processor():
    """Testet den Event-Processor mit einem FOSDEM-Event."""
    
    # Test-Event-Daten
    event_data: Dict[str, Any] = {
        "event": str("FOSDEM 2025"),
        "session": str("Welcome to FOSDEM 2025"),
        "url": str("https://fosdem.org/2025/schedule/event/fosdem-2025-6712-welcome-to-fosdem-2025/"),
        "filename": str("Welcome-to-FOSDEM-2025.md"),
        "track": str("Keynotes-13"),
        "day": str("2025-02-01"),
        "starttime": str("09:30"),
        "endtime": str("09:50"),
        "speakers": ["FOSDEM Staff", "Richard \"RichiH\" Hartmann"],
        "video_url": str("https://video.fosdem.org/2025/janson/fosdem-2025-6712-welcome-to-fosdem-2025.av1.webm"),
        "attachments_url": str("https://fosdem.org/2025/events/attachments/fosdem-2025-6712-welcome-to-fosdem-2025/slides/236658/2025-02-0_6CcRbRi.pdf"),
        "source_language": str("en"),
        "target_language": str("de")
    }

    # Event-Processor initialisieren
    resource_calculator = ResourceCalculator()
    processor = EventProcessor(resource_calculator=resource_calculator)

    try:
        # Event verarbeiten
        result = await processor.process_event(**event_data)

        # Performance-Metriken ausgeben
        print("\n=== Performance-Metriken ===")
        if hasattr(result, 'data') and hasattr(result.data, 'output'):
            print(f"Gesamtverarbeitungszeit: {result.data.output.metadata['total_processing_time']:.2f} Sekunden")
            print(f"Markdown-Länge: {result.data.output.metadata['markdown_length']} Zeichen")
        
        # LLM-Nutzung ausgeben
        if hasattr(result, 'process') and hasattr(result.process, 'llm_info'):
            print("\n=== LLM-Nutzung ===")
            for req in result.process.llm_info.requests:
                print(f"Modell: {req.model}")
                print(f"Zweck: {req.purpose}")
                if hasattr(req, 'token_count'):
                    print(f"Token-Anzahl: {req.token_count}")
                print("---")

        # Erfolg/Fehler Status
        print("\n=== Status ===")
        print(f"Status: {'Erfolg' if not result.error else 'Fehler'}")
        if result.error:
            print(f"Fehler: {result.error.message}")

        # Generierte Markdown-Datei anzeigen
        if hasattr(result, 'data') and hasattr(result.data, 'output'):
            print("\n=== Generierte Markdown-Datei ===")
            print(f"Pfad: {result.data.output.markdown_file}")
            print("\nInhalt:")
            print(result.data.output.markdown_content[:500] + "..." if len(result.data.output.markdown_content) > 500 else result.data.output.markdown_content)

    except Exception as e:
        print(f"Fehler beim Test: {str(e)}")

if __name__ == "__main__":
    asyncio.run(test_event_processor()) 