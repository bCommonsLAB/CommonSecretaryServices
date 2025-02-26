#!/usr/bin/env python
"""
Ausführungsskript für den Event-Processor Batch-Test.
"""

import asyncio
import sys
import os

# Füge das Hauptverzeichnis zum Pfad hinzu, damit die Imports funktionieren
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tests.test_event_processor_batch import test_process_many_events

if __name__ == "__main__":
    print("Starte Event-Processor Batch-Test...")
    asyncio.run(test_process_many_events())
    print("\nTest abgeschlossen.") 