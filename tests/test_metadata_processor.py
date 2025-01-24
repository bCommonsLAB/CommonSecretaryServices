import pytest
from pathlib import Path
from unittest.mock import Mock
import json
import os
from datetime import datetime
from src.processors.metadata_processor import MetadataProcessor
from src.utils.types import TechnicalMetadata, ContentMetadata, CompleteMetadata
from src.core.exceptions import ProcessingError, UnsupportedMimeTypeError

def save_metadata_to_json(metadata: dict, test_name: str):
    """Speichert Metadaten als JSON für spätere Analyse."""
    # Erstelle Verzeichnis falls nicht vorhanden
    output_dir = Path("temp-processing/tests/metadata")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Erstelle Dateinamen mit Timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{test_name}_{timestamp}.json"
    output_path = output_dir / filename
    
    # Speichere als JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    return output_path

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
        binary_data=pdf_path
    )
    
    # Speichere Ergebnis
    save_metadata_to_json(
        technical_metadata.model_dump(),  # Verwende model_dump statt dict
        "technical_metadata_pdf"
    )
    
    # Überprüfung
    assert isinstance(technical_metadata, TechnicalMetadata)
    assert technical_metadata.file_mime == "application/pdf"
    assert technical_metadata.file_size > 0
    assert technical_metadata.doc_pages > 0  # PDF-spezifisch

@pytest.mark.asyncio
async def test_extract_technical_metadata_from_audio(metadata_processor):
    """Test der technischen Metadaten-Extraktion aus einer Audio-Datei."""
    # Setup
    audio_path = Path("tests/sample.mp3")
    
    # Ausführung
    technical_metadata = await metadata_processor.extract_technical_metadata(
        binary_data=audio_path
    )
    
    # Speichere Ergebnis
    save_metadata_to_json(
        technical_metadata.model_dump(),  # Verwende model_dump statt dict
        "technical_metadata_audio"
    )
    
    # Überprüfung
    assert isinstance(technical_metadata, TechnicalMetadata)
    assert technical_metadata.file_mime.startswith("audio/")  # Flexibler Test für Audio MIME-Types
    assert technical_metadata.file_size > 0
    assert technical_metadata.media_duration > 0  # Audio-spezifisch
    assert technical_metadata.media_channels is not None  # Audio-spezifisch

@pytest.mark.asyncio
async def test_extract_content_metadata(metadata_processor):
    """Test der inhaltlichen Metadaten-Extraktion."""
    # Setup
    content = "Dies ist ein Testtext für die Metadaten-Extraktion."
    context = {
        "type": "text",
        "language": "de",
        "created": "2025-01-23T12:00:00",
        "Hobby": "Programmieren"
    }
    
    # Mock für transform_by_template
    async def mock_transform(*args, **kwargs):
        return json.dumps({  # JSON-String zurückgeben
            "type": "text",
            "created": "2025-01-23T12:00:00",
            "modified": "2025-01-23T12:00:00",
            "title": "Test Dokument",
            "authors": ["Test Autor"],
            "language": "de"
        }), None
    
    # Mock setzen
    metadata_processor.transcriber.transform_by_template = mock_transform
    metadata_processor.get_last_operation_time = lambda: 0.1  # Mock für operation time
    
    # Ausführung
    content_metadata = await metadata_processor.extract_content_metadata(
        content=content,
        context=context
    )
    
    # Speichere Ergebnis
    save_metadata_to_json(
        content_metadata.model_dump(),  # Verwende model_dump statt dict
        "content_metadata"
    )
    
    # Überprüfung
    assert isinstance(content_metadata, ContentMetadata)
    assert content_metadata.type == "text"
    assert content_metadata.language == "de"
    assert content_metadata.created is not None

@pytest.mark.asyncio
async def test_extract_complete_metadata(metadata_processor):
    """Test der vollständigen Metadaten-Extraktion."""
    # Setup
    pdf_path = Path("tests/sample.pdf")
    context = {"type": "document"}
    
    # Mock für transform_by_template
    async def mock_transform(*args, **kwargs):
        return json.dumps({  # JSON-String zurückgeben
            "type": "document",
            "created": "2025-01-23T12:00:00",
            "modified": "2025-01-23T12:00:00",
            "title": "Test PDF",
            "authors": ["Test Autor"],
            "language": "de"
        }), None
    
    # Mock setzen
    metadata_processor.transcriber.transform_by_template = mock_transform
    # Mock für get_last_operation_time
    metadata_processor.get_last_operation_time = lambda: 0.1
    
    # Ausführung
    complete_metadata = await metadata_processor.extract_metadata(
        binary_data=pdf_path,
        context=context
    )
    
    # Speichere Ergebnis
    save_metadata_to_json(
        complete_metadata.model_dump(),  # Verwende model_dump statt dict
        "complete_metadata"
    )
    
    # Überprüfung
    assert isinstance(complete_metadata, CompleteMetadata)
    assert complete_metadata.technical is not None
    assert complete_metadata.content is not None
    assert complete_metadata.technical.file_mime == "application/pdf"

@pytest.mark.asyncio
async def test_unsupported_mime_type(metadata_processor):
    """Test für nicht unterstützte MIME-Types."""
    # Setup - Erstelle temporäre Datei
    test_content = b"Test content"
    temp_file = Path("tests/temp_test.xyz")
    temp_file.write_bytes(test_content)
    
    try:
        # Überprüfung
        with pytest.raises(UnsupportedMimeTypeError):
            await metadata_processor.extract_technical_metadata(
                binary_data=temp_file  # MIME-Type wird automatisch erkannt
            )
    finally:
        # Cleanup
        if temp_file.exists():
            temp_file.unlink()

@pytest.mark.asyncio
async def test_file_not_found(metadata_processor):
    """Test für nicht existierende Dateien."""
    # Setup
    nonexistent_path = Path("tests/nonexistent.pdf")
    
    # Überprüfung
    with pytest.raises(ProcessingError):
        await metadata_processor.extract_technical_metadata(
            binary_data=nonexistent_path
        ) 