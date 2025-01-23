import pytest
from pathlib import Path
from unittest.mock import Mock
from src.processors.metadata_processor import MetadataProcessor
from src.utils.types import TechnicalMetadata

@pytest.fixture
def resource_calculator():
    """Mock für den ResourceCalculator."""
    return Mock()

@pytest.fixture
def metadata_processor(resource_calculator):
    """Fixture für einen MetadataProcessor."""
    return MetadataProcessor(resource_calculator=resource_calculator)

@pytest.mark.asyncio
async def test_extract_technical_metadata_from_pdf(metadata_processor):
    """Test der technischen Metadaten-Extraktion aus einer PDF-Datei."""
    # Setup
    pdf_path = Path("tests/sample.pdf")
    
    # Ausführung
    technical_metadata = await metadata_processor.extract_technical_metadata(
        binary_data=pdf_path,
        mime_type="application/pdf"
    )
    
    # Überprüfung
    assert isinstance(technical_metadata, TechnicalMetadata)
    assert technical_metadata.file_mime == "application/pdf"
    assert technical_metadata.file_size > 0
    assert technical_metadata.doc_pages > 0  # PDF-spezifisch 