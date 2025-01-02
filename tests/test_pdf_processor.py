import pytest
pytestmark = pytest.mark.asyncio
from pathlib import Path
from processors.pdf_processor import PDFProcessor
from core.exceptions import FileSizeLimitExceeded, ProcessingError

@pytest.fixture
def pdf_processor(resource_calculator):
    """Fixture für den PDF-Prozessor"""
    return PDFProcessor(
        resource_calculator=resource_calculator,
        max_file_size=10 * 1024 * 1024,  # 10MB
        max_pages=15
    )

@pytest.mark.skip(reason="Temporarily disabled while refactoring")
@pytest.mark.asyncio
async def test_pdf_processing(pdf_processor):
    """Test der PDF-Verarbeitung mit einer Beispiel-PDF"""
    # Verwende die existierende sample.pdf aus dem tests Verzeichnis
    sample_pdf = Path(__file__).parent / "sample.pdf"
    
    result = await pdf_processor.process(str(sample_pdf))
    
    assert "text" in result
    assert "page_count" in result
    assert "resources_used" in result
    assert "total_units" in result
    assert result["page_count"] == 12

@pytest.mark.skip(reason="Temporarily disabled while refactoring")
@pytest.mark.asyncio
async def test_pdf_too_large(pdf_processor):
    """Test der Größenbeschränkung"""
    with pytest.raises(FileSizeLimitExceeded):
        await pdf_processor.process("tests/CommonsFreiFairLebendig.pdf")


@pytest.mark.skip(reason="Temporarily disabled while refactoring")
@pytest.mark.asyncio
async def test_pdf_too_many_pages(pdf_processor):
    """Test der Seitenzahlbeschränkung"""
    with pytest.raises(ProcessingError) as exc_info:
        await pdf_processor.process("tests/CommonsFreiFairLebendig.pdf")
    assert "Zu viele Seiten" in str(exc_info.value) 