"""
Pytest-Konfiguration für alle Tests.
"""

import sys
from pathlib import Path

# Füge src-Verzeichnis zum Python-Path hinzu
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path) 