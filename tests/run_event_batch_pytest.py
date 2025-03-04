#!/usr/bin/env python
"""
Ausführungsskript für den Event-Processor Batch-Test mit pytest.
"""

import os
import sys
import pytest

# Füge das Hauptverzeichnis zum Pfad hinzu, damit die Imports funktionieren
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

if __name__ == "__main__":
    print("Starte Event-Processor Batch-Test mit pytest...")
    
    # Führe den Test mit pytest aus
    pytest.main(["-xvs", "tests/test_event_processor_batch.py"])
    
    print("\nTest abgeschlossen.") 