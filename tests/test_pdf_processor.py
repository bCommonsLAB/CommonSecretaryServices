import pytest
pytestmark = pytest.mark.asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock
from processors.pdf_processor import PDFProcessor
from core.exceptions import FileSizeLimitExceeded, ProcessingError
from core.config import Config

@pytest.fixture
def mock_calculator():
    """Erstellt einen Mock für den ResourceCalculator.
    
    Dieser Mock simuliert die Berechnung von Ressourcen mit festen Rückgabewerten:
    - compute_units: 1.0
    - storage_units: 1.0
    - total_units: 2.0
    
    Returns:
        MagicMock: Ein vorkonfigurierter Mock des ResourceCalculators
    """
    calculator = MagicMock()
    calculator.calculate_compute_units.return_value = 1.0
    calculator.calculate_storage_units.return_value = 1.0
    calculator.calculate_total_units.return_value = 2.0
    return calculator

@pytest.fixture
def mock_config():
    """Erstellt einen Mock für die Config-Klasse.
    
    Dieser Mock simuliert die Konfiguration mit Test-Werten:
    - max_file_size: 10MB
    - max_pages: 15
    
    Returns:
        MagicMock: Ein vorkonfigurierter Mock der Config-Klasse
    """
    with patch('src.core.config.Config', autospec=True) as mock_config:
        mock_instance = MagicMock()
        mock_instance.get.return_value = {
            'max_file_size': 10 * 1024 * 1024,  # 10MB
            'max_pages': 15,
            'temp_dir': "temp-processing/pdf"
        }
        mock_config.return_value = mock_instance
        yield mock_config

@pytest.fixture
def pdf_processor(mock_calculator, mock_config):
    """Fixture für den PDF-Prozessor mit gemockter Konfiguration"""
    return PDFProcessor(resource_calculator=mock_calculator)

@pytest.mark.asyncio
async def test_pdf_processing(pdf_processor):
    """Test der PDF-Verarbeitung mit einer Beispiel-PDF.
    
    Dieser Test überprüft die grundlegende Funktionalität des PDFProcessors
    mit einer Beispiel-PDF-Datei.
    
    Args:
        pdf_processor: Fixture des PDFProcessors mit gemockter Konfiguration
        
    Assertions:
        - Prüft ob alle erwarteten Felder im Ergebnis vorhanden sind
        - Prüft ob die Seitenzahl korrekt erkannt wird
    """
    # Verwende die existierende sample.pdf aus dem tests Verzeichnis
    sample_pdf = Path(__file__).parent / "sample.pdf"
    
    result = await pdf_processor.process(str(sample_pdf))
    
    assert "text" in result
    assert "page_count" in result
    assert "resources_used" in result
    assert "total_units" in result
    assert result["page_count"] == 12

@pytest.mark.asyncio
async def test_pdf_too_large(pdf_processor):
    """Test der Größenbeschränkung.
    
    Dieser Test überprüft, ob der PDFProcessor korrekt reagiert,
    wenn eine PDF-Datei die maximale Größe überschreitet.
    
    Args:
        pdf_processor: Fixture des PDFProcessors mit gemockter Konfiguration
        
    Assertions:
        - Prüft ob FileSizeLimitExceeded ausgelöst wird
    """
    with pytest.raises(FileSizeLimitExceeded):
        await pdf_processor.process("tests/CommonsFreiFairLebendig.pdf")

@pytest.mark.asyncio
async def test_pdf_too_many_pages(pdf_processor):
    """Test der Seitenzahlbeschränkung.
    
    Dieser Test überprüft, ob der PDFProcessor korrekt reagiert,
    wenn eine PDF-Datei zu viele Seiten hat.
    
    Args:
        pdf_processor: Fixture des PDFProcessors mit gemockter Konfiguration
        
    Assertions:
        - Prüft ob ProcessingError mit "zu viele Seiten" ausgelöst wird
    """
    with pytest.raises(ProcessingError) as exc_info:
        await pdf_processor.process("tests/CommonsFreiFairLebendig.pdf")
    assert "zu viele Seiten" in str(exc_info.value).lower() 