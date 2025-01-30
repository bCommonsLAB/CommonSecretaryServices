"""
Pytest-Konfiguration für alle Tests.
"""

import sys
from pathlib import Path
import pytest

# Füge src-Verzeichnis zum Python-Path hinzu
src_path = str(Path(__file__).parent.parent / "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

@pytest.fixture
def sample_pdf_file(tmp_path: Path) -> Path:
    """Erstellt eine minimale PDF-Datei für Tests."""
    pdf_path = tmp_path / "sample.pdf"
    with open(pdf_path, "wb") as f:
        # Minimale PDF-Struktur
        f.write(b"%PDF-1.4\n")
        f.write(b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n")
        f.write(b"2 0 obj\n<</Type/Pages/Count 1/Kids[3 0 R]>>\nendobj\n")
        f.write(b"3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>\nendobj\n")
        f.write(b"%%EOF\n")
    return pdf_path

@pytest.fixture
def sample_audio_file(tmp_path: Path) -> Path:
    """Erstellt eine minimale MP3-Datei für Tests."""
    mp3_path = tmp_path / "sample.mp3"
    with open(mp3_path, "wb") as f:
        # Minimaler MP3-Header
        f.write(b"ID3\x03\x00\x00\x00\x00\x00\x00")
        f.write(b"\xFF\xFB\x90\x64") # MPEG-1 Layer 3 Header
    return mp3_path

@pytest.fixture
def sample_text_file(tmp_path: Path) -> Path:
    """Erstellt eine Text-Datei für Tests."""
    text_path = tmp_path / "sample.txt"
    with open(text_path, "w", encoding="utf-8") as f:
        f.write("Dies ist ein Test-Text.\n")
        f.write("Er enthält mehrere Zeilen.\n")
        f.write("Autor: Max Mustermann\n")
        f.write("Ort: Brixen")
    return text_path 