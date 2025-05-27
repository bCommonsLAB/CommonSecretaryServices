"""
Test für die Batch-Verarbeitung des Event-Processors.
Verarbeitet mehrere FOSDEM-Events und misst die Performance.
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, List
from src.core.models.event import BatchEventResponse
from src.processors.event_processor import EventProcessor
from src.core.resource_tracking import ResourceCalculator

async def test_process_many_events(max_events: int = 3, verbose: bool = True):
    """
    Testet die Batch-Verarbeitung des Event-Processors mit FOSDEM-Events.
    
    Args:
        max_events: Maximale Anzahl der zu verarbeitenden Events
        verbose: Ob detaillierte Ausgaben angezeigt werden sollen
    """
    start_time = time.time()
    
    # Lade Test-Event-Daten aus der JSON-Datei
    sample_path = Path("tests/samples/fosdem-events.json")
    
    if not sample_path.exists():
        print(f"Fehler: Testdatei {sample_path} nicht gefunden!")
        return
    
    with open(sample_path, "r", encoding="utf-8") as f:
        events_data: List[Dict[str, Any]] = json.load(f)
    
    # Begrenze die Anzahl der Events für den Test
    test_events = events_data[:max_events]
    
    print(f"\n=== Starte Batch-Verarbeitung von {len(test_events)} Events ===")
    print(f"Zeitstempel: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Event-Processor initialisieren
    resource_calculator = ResourceCalculator()
    processor = EventProcessor(resource_calculator=resource_calculator)

    try:
        # Zeige Informationen zu den Events an
        if verbose:
            print("\nZu verarbeitende Events:")
            for i, event in enumerate(test_events):
                print(f"{i+1}. {event.get('session', 'Unbekannt')} ({event.get('track', 'Unbekannt')})")
        
        print(f"\nStarte Verarbeitung um {time.strftime('%H:%M:%S')}...")
        
        # Events verarbeiten
        result: BatchEventResponse = await processor.process_many_events(test_events)
        
        processing_time = time.time() - start_time
        print(f"\nVerarbeitung abgeschlossen nach {processing_time:.2f} Sekunden")

        # Performance-Metriken ausgeben
        print("\n=== Performance-Metriken ===")
        if result.data and result.data.output:
            summary = result.data.output.summary
            print(f"Gesamtverarbeitungszeit: {summary['processing_time']:.2f} Sekunden")
            print(f"Verarbeitete Events: {summary['total_events']}")
            print(f"Erfolgreiche Events: {summary['successful']}")
            print(f"Fehlgeschlagene Events: {summary['failed']}")
            
            # Zeige Fehler an, falls vorhanden
            if summary['failed'] > 0 and 'errors' in summary:
                print("\nAufgetretene Fehler:")
                for error in summary['errors']:
                    print(f"  - Event {error.get('index', '?')}: {error.get('error', 'Unbekannter Fehler')}")
        
        # LLM-Nutzung ausgeben
        if result.process and result.process.llm_info:
            print("\n=== LLM-Nutzung ===")
            total_tokens = 0
            for req in result.process.llm_info.requests:
                print(f"Modell: {req.model}")
                print(f"Zweck: {req.purpose}")
                if hasattr(req, 'tokens'):
                    print(f"Token-Anzahl: {req.tokens}")
                    total_tokens += req.tokens
                print("---")
            print(f"Gesamtzahl Token: {total_tokens}")

        # Erfolg/Fehler Status
        print("\n=== Status ===")
        print(f"Status: {'Erfolg' if not result.error else 'Fehler'}")
        if result.error:
            print(f"Fehler: {result.error.message}")

        # Generierte Markdown-Dateien anzeigen
        if result.data and result.data.output:
            print("\n=== Generierte Markdown-Dateien ===")
            for i, output in enumerate(result.data.output.results):
                print(f"\nDatei {i+1}: {output.markdown_file}")
                print(f"Länge: {output.metadata.get('markdown_length', 'unbekannt')} Zeichen")
                
                # Zeige einen Ausschnitt des Inhalts, wenn verbose aktiviert ist
                if verbose:
                    content = output.markdown_content
                    preview = content[:300] + "..." if len(content) > 300 else content
                    print(f"Vorschau:\n{preview}")

        return result

    except Exception as e:
        print(f"Fehler beim Test: {str(e)}")
        raise

if __name__ == "__main__":
    # Prüfe, ob Kommandozeilenargumente übergeben wurden
    max_events = 3  # Standard: 3 Events
    verbose = True  # Standard: Ausführliche Ausgabe
    
    # Verarbeite Kommandozeilenargumente
    if len(sys.argv) > 1:
        try:
            max_events = int(sys.argv[1])
        except ValueError:
            print(f"Ungültiges Argument: {sys.argv[1]}. Verwende Standardwert: 3 Events")
    
    if len(sys.argv) > 2 and sys.argv[2].lower() in ['false', '0', 'no', 'n']:
        verbose = False
    
    print(f"Verarbeite {max_events} Events mit {'ausführlicher' if verbose else 'minimaler'} Ausgabe")
    asyncio.run(test_process_many_events(max_events=max_events, verbose=verbose)) 