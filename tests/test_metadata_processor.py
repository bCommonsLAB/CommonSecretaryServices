import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import json
import os
from datetime import datetime
from src.processors.metadata_processor import MetadataProcessor
from src.utils.types import TechnicalMetadata, ContentMetadata, CompleteMetadata
from src.core.exceptions import ProcessingError, UnsupportedMimeTypeError
from src.core.resource_tracking import ResourceCalculator
import io
from src.utils.types import TransformerResponse, LLMRequest, ErrorInfo
import tempfile

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
    return Mock(spec=ResourceCalculator)

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
        file_path=pdf_path
    )
    
    # Speichere Ergebnis
    save_metadata_to_json(
        technical_metadata.model_dump(),  # Verwende model_dump statt dict
        "technical_metadata_pdf"
    )
    
    # Überprüfung
    assert technical_metadata.file_name == "sample.pdf"
    assert technical_metadata.file_mime == "application/pdf"
    assert technical_metadata.file_size > 0
    assert technical_metadata.doc_pages is not None  # PDF-spezifisch
    assert technical_metadata.doc_pages > 0  # PDF-spezifisch

@pytest.mark.asyncio
async def test_extract_technical_metadata_from_audio(metadata_processor):
    """Test der technischen Metadaten-Extraktion aus einer Audio-Datei."""
    # Setup
    audio_path = Path("tests/sample.mp3")
    
    # Ausführung
    technical_metadata = await metadata_processor.extract_technical_metadata(
        file_path=audio_path
    )
    
    # Speichere Ergebnis
    save_metadata_to_json(
        technical_metadata.model_dump(),  # Verwende model_dump statt dict
        "technical_metadata_audio"
    )
    
    # Überprüfung
    assert technical_metadata.file_name == "sample.mp3"
    assert technical_metadata.file_mime == "audio/mpeg"
    assert technical_metadata.file_size > 0
    assert technical_metadata.media_duration is not None  # Audio-spezifisch
    assert technical_metadata.media_duration > 0  # Audio-spezifisch
    assert technical_metadata.media_bitrate is not None
    assert technical_metadata.media_channels is not None
    assert technical_metadata.media_sample_rate is not None
    assert technical_metadata.media_codec == "mpeg"
    assert technical_metadata.media_channels == 2
    assert technical_metadata.media_sample_rate == 44100

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
        transformed_text = "Transformierter Text"
        template_result = TransformerResponse(
            status="success",
            request={
                "processor": "transformer",
                "timestamp": "2025-01-23T12:00:00",
                "parameters": {}
            },
            process={
                "id": "test-id",
                "main_processor": "transformer",
                "sub_processors": ["openai"],
                "started": "2025-01-23T12:00:00",
                "completed": "2025-01-23T12:00:00",
                "duration": 1000,
                "llm_info": {
                    "requests_count": 1,
                    "total_tokens": 100,
                    "total_duration": 500,
                    "requests": [
                        {
                            "model": "gpt-4",
                            "duration": 500,
                            "tokens": 100,
                            "timestamp": "2025-01-23T12:00:00"
                        }
                    ]
                }
            },
            data={
                "input": {"text": content, "language": "de"},
                "output": {"text": transformed_text, "language": "en"}
            }
        )
        content_metadata = ContentMetadata(
            type="text",
            created="2025-01-23T12:00:00",
            modified="2025-01-23T12:00:00",
            title="Test Dokument",
            authors="Test Autor",
            language="de"
        )
        return transformed_text, template_result, content_metadata
    
    # Mock setzen
    metadata_processor.transcriber.transform_by_template = mock_transform
    metadata_processor.get_last_operation_time = lambda: 0.1  # Mock für operation time
    
    # Ausführung
    llm_info, content_metadata = await metadata_processor.extract_content_metadata(
        content=content,
        context=context
    )
    
    # Speichere Ergebnis
    if content_metadata:
        save_metadata_to_json(
            content_metadata.model_dump(),
            "content_metadata"
        )
    
    # Überprüfung
    assert isinstance(content_metadata, ContentMetadata)
    assert content_metadata.type == "text"
    assert content_metadata.language == "de"
    assert content_metadata.created is not None
    
    # LLM Info prüfen
    assert llm_info is not None
    assert isinstance(llm_info, list)
    if llm_info:
        assert isinstance(llm_info[0], dict)
        assert llm_info[0]["model"] == "gpt-4"
        assert llm_info[0]["duration"] == 500
        assert llm_info[0]["tokens"] == 100

@pytest.mark.asyncio
async def test_extract_complete_metadata(metadata_processor):
    """Test der vollständigen Metadaten-Extraktion."""
    # Setup
    pdf_path = Path("tests/sample.pdf")
    context = {"type": "document"}

    # Mock für transform_by_template
    def mock_transform(*args, **kwargs):
        transformed_text = "Transformierter Text"
        template_result = TransformerResponse(
            llms=[
                LLMRequest(
                    model="gpt-4",
                    duration=0.5,
                    tokens=100,
                    timestamp="2025-01-23T12:00:00"
                )
            ]
        )
        content_metadata = ContentMetadata(
            type="text",
            created="2025-01-23T12:00:00",
            modified="2025-01-23T12:00:00",
            title="Test PDF",
            authors="Test Autor",
            language="de"
        )
        return transformed_text, template_result, content_metadata

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
    assert complete_metadata.data["technical"] is not None
    assert complete_metadata.status == "success"
    assert complete_metadata.request.processor == "metadata"
    assert complete_metadata.request.timestamp is not None
    assert complete_metadata.request.parameters == {
        "has_content": False,
        "context_keys": ["type"]
    }
    assert complete_metadata.process.id is not None
    assert complete_metadata.process.main_processor == "metadata"
    assert complete_metadata.process.started is not None
    assert complete_metadata.process.completed is not None
    assert complete_metadata.process.llm_info is not None

@pytest.mark.asyncio
async def test_unsupported_mime_type(metadata_processor):
    """Test für nicht unterstützte MIME-Types."""
    # Setup - Erstelle temporäre Datei
    test_content = b"Test content"
    temp_file = Path("tests/temp_test.xyz")
    temp_file.write_bytes(test_content)
    
    try:
        # Ausführung und Überprüfung
        with pytest.raises(UnsupportedMimeTypeError):
            await metadata_processor.extract_technical_metadata(
                file_path=temp_file
            )
    finally:
        # Aufräumen
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
            file_path=nonexistent_path
        ) 

@pytest.fixture
def metadata_processor():
    return MetadataProcessor(ResourceCalculator())

@pytest.fixture
def sample_audio_file():
    """Erstellt eine temporäre Audio-Datei für Tests."""
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as temp_file:
        temp_file.write(b'Dummy MP3 content')
        return Path(temp_file.name)

async def test_metadata_extraction_structure(metadata_processor, sample_audio_file):
    """Testet die Struktur der Metadaten-Response."""
    
    # Test-Content und Kontext
    content = "Dies ist ein Test-Content für die Metadaten-Extraktion"
    context = {"key": "value"}
    
    # Metadaten extrahieren
    result = await metadata_processor.extract_metadata(
        binary_data=sample_audio_file,
        content=content,
        context=context
    )
    
    # Basis-Struktur prüfen
    assert isinstance(result, CompleteMetadata)
    assert result.status in ["success", "error", "processing"]
    
    # Request-Informationen prüfen
    assert result.request.processor == "metadata"
    assert isinstance(result.request.timestamp, str)
    assert "has_content" in result.request.parameters
    assert "context_keys" in result.request.parameters
    
    # Process-Informationen prüfen
    assert result.process.id is not None
    assert result.process.main_processor == "metadata"
    assert isinstance(result.process.sub_processors, list)
    assert isinstance(result.process.started, str)
    if result.status != "processing":
        assert isinstance(result.process.completed, str)
        assert isinstance(result.process.duration, float)
    
    # LLM-Informationen prüfen
    assert result.process.llm_info is not None
    assert isinstance(result.process.llm_info.requests_count, int)
    assert isinstance(result.process.llm_info.total_tokens, int)
    assert isinstance(result.process.llm_info.total_duration, float)
    assert isinstance(result.process.llm_info.requests, list)
    
    # Daten-Struktur prüfen
    assert "metadata_type" in result.data
    assert result.data["metadata_type"] == "complete"
    
    if "technical" in result.data:
        assert result.data["technical_available"] is True
        technical = result.data["technical"]
        assert "file_name" in technical
        assert "file_mime" in technical
        assert "file_size" in technical
    
    if "content" in result.data:
        assert result.data["content_available"] is True
        content_data = result.data["content"]
        # Optionale Felder prüfen
        assert isinstance(content_data.get("type", ""), str)
        assert isinstance(content_data.get("title", ""), str)
    
    # Bei Erfolg
    if result.status == "success":
        assert result.error is None
        assert result.process.completed is not None
        assert result.process.duration is not None
    
    # Bei Fehler
    if result.status == "error":
        assert result.error is not None
        assert result.error.code is not None
        assert result.error.message is not None
        assert isinstance(result.error.details, dict)

async def test_llm_info_structure(metadata_processor, sample_audio_file):
    """Testet die Struktur der LLM-Informationen."""
    
    content = "Test-Content für LLM-Verarbeitung"
    
    result = await metadata_processor.extract_metadata(
        binary_data=sample_audio_file,
        content=content
    )
    
    # LLM-Request prüfen
    if result.process.llm_info.requests:
        request = result.process.llm_info.requests[0]
        assert isinstance(request.model, str)
        assert isinstance(request.duration, float)
        assert isinstance(request.tokens, int)
        assert isinstance(request.timestamp, str)
        
        # Gesamtwerte prüfen
        assert result.process.llm_info.requests_count == len(result.process.llm_info.requests)
        assert result.process.llm_info.total_tokens == sum(r.tokens for r in result.process.llm_info.requests)
        assert result.process.llm_info.total_duration == sum(r.duration for r in result.process.llm_info.requests)

async def test_error_handling(metadata_processor):
    """Testet die Fehlerbehandlung."""
    
    # Nicht existierende Datei
    with pytest.raises(Exception):
        result = await metadata_processor.extract_metadata(
            binary_data=Path("nicht_existierende_datei.mp3")
        )
        
        assert result.status == "error"
        assert result.error is not None
        assert result.error.code == "FileNotFoundError"
        assert "nicht_existierende_datei.mp3" in result.error.message
        assert result.process.completed is not None

@pytest.mark.asyncio
async def test_metadata_response_structure(metadata_processor):
    """Test der neuen Response-Struktur des MetadataProcessors."""
    # Test-Datei erstellen
    test_content = "Dies ist ein Test-Inhalt für die Metadaten-Extraktion."
    test_file = io.BytesIO(test_content.encode('utf-8'))
    test_file.name = "test.txt"  # Name für MIME-Type Erkennung

    # Unterstützte MIME-Types erweitern
    metadata_processor.supported_mime_types.append('text/*')

    # Mock für transform_by_template
    def mock_transform(*args, **kwargs):
        transformed_text = "Transformierter Text"
        template_result = TransformerResponse(
            llms=[
                LLMRequest(
                    model="gpt-4",
                    duration=0.5,
                    tokens=100,
                    timestamp="2025-01-23T12:00:00"
                )
            ]
        )
        content_metadata = ContentMetadata(
            type="text",
            created="2025-01-23T12:00:00",
            modified="2025-01-23T12:00:00",
            title="Test Dokument",
            authors="Test Autor",
            language="de"
        )
        return transformed_text, template_result, content_metadata

    # Mock setzen
    metadata_processor.transcriber.transform_by_template = mock_transform

    # Metadaten extrahieren
    result = await metadata_processor.extract_metadata(
        binary_data=test_file,
        content=test_content,
        context={'test': True}
    )

    # Struktur validieren
    assert result.status == "success"
    assert result.request.processor == "metadata"
    assert result.request.timestamp is not None
    assert result.request.parameters == {
        "has_content": True,
        "context_keys": ["test"]
    }
    assert result.process.id is not None
    assert result.process.main_processor == "metadata"
    assert result.process.started is not None
    assert result.process.completed is not None
    assert result.data is not None

@pytest.mark.asyncio
async def test_metadata_error_response(metadata_processor):
    """Überprüft die Fehlerbehandlung bei ungültigem MIME-Type."""
    # Ausführung
    with tempfile.NamedTemporaryFile(suffix=".xyz") as temp_file:
        temp_file.write(b"Test content")
        temp_file.seek(0)
        result = await metadata_processor.extract_metadata(temp_file)

    # Überprüfung
    assert result.status == "error"
    assert result.error.code == "UnsupportedMimeTypeError"
    assert "MIME-Type nicht unterstützt" in result.error.message
    assert isinstance(result.error.details, dict)
    assert "error_type" in result.error.details
    assert "traceback" in result.error.details

@pytest.mark.asyncio
async def test_extract_metadata():
    """Test der Metadaten-Extraktion aus einer Markdown-Datei mit zusätzlichem Content."""
    # Mock-Daten
    file_content = """# Mein Weg zu einem gemeinsamen Leben
Dies ist ein Beispieltext für den Test."""
    
    file_obj = io.BytesIO(file_content.encode('utf-8'))
    file_obj.name = "Mein Weg zu einem gemeinsamen Leben.md"
    
    additional_content = "Das ist ein Text aus dem jahr 2024 in Brixen"

    expected_output = {
        "status": "success",
        "request": {
            "processor": "metadata",
            "timestamp": "2025-01-26T01:47:04.514215",
            "parameters": {
                "has_content": True,
                "context_keys": []
            }
        },
        "process": {
            "id": "f1627315-553b-437a-ac85-fa794e0a6f96",
            "main_processor": "metadata",
            "sub_processors": ["transformer"],
            "started": "2025-01-26T01:47:04.514215",
            "completed": "2025-01-26T01:47:06.903670",
            "duration": 2389.455,
            "llm_info": {
                "requests_count": 1,
                "total_tokens": 3158,
                "total_duration": 2236,
                "requests": [
                    {
                        "model": "gpt-4o-mini",
                        "duration": 2236,
                        "tokens": 3158,
                        "timestamp": "2025-01-26T01:47:06.903670"
                    }
                ]
            }
        },
        "data": {
            "technical": {
                "file_name": "tmp3k33_ae0.md",
                "file_mime": "text/markdown",
                "file_size": 1268,
                "created": "2025-01-26T01:47:04.587826",
                "modified": "2025-01-26T01:47:04.587826"
            },
            "content": {
                "created": "2024-01-01T00:00:00Z",
                "temporal_start": "2024-01-01T00:00:00Z",
                "temporal_end": "2024-12-31T23:59:59Z",
                "spatial_location": "Brixen"
            },
            "metadata_type": "complete",
            "content_available": True,
            "technical_available": True
        }
    }

    # Test-Ausführung
    with patch('src.processors.metadata_processor.MetadataProcessor.extract_metadata') as mock_extract:
        mock_extract.return_value = CompleteMetadata(**expected_output)

        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        result = await processor.extract_metadata(
            binary_data=file_obj,
            content=additional_content
        )

        # Überprüfungen
        assert result.status == "success"
        assert result.request.processor == "metadata"
        assert result.process.main_processor == "metadata"
        assert result.process.sub_processors == ["transformer"]
        assert result.process.llm_info.requests_count == 1
        assert result.process.llm_info.total_tokens == 3158
        assert result.data["technical"]["file_mime"] == "text/markdown"
        assert result.data["content"]["spatial_location"] == "Brixen"
        assert result.data["content"]["created"].startswith("2024")
        assert result.data["metadata_type"] == "complete"
        assert result.data["content_available"] is True
        assert result.data["technical_available"] is True

@pytest.mark.asyncio
async def test_extract_metadata_without_content():
    """Test der Metadaten-Extraktion ohne zusätzlichen Content."""
    # Mock-Daten
    file_content = """# Mein Weg zu einem gemeinsamen Leben
Dies ist ein Beispieltext für den Test."""
    
    file_obj = io.BytesIO(file_content.encode('utf-8'))
    file_obj.name = "Mein Weg zu einem gemeinsamen Leben.md"

    expected_output = {
        "status": "success",
        "request": {
            "processor": "metadata",
            "timestamp": "2025-01-26T01:47:04.514215",
            "parameters": {
                "has_content": False,
                "context_keys": []
            }
        },
        "process": {
            "id": "f1627315-553b-437a-ac85-fa794e0a6f96",
            "main_processor": "metadata",
            "sub_processors": [],
            "started": "2025-01-26T01:47:04.514215",
            "completed": "2025-01-26T01:47:06.903670",
            "duration": 2389.455,
            "llm_info": {
                "requests_count": 0,
                "total_tokens": 0,
                "total_duration": 0,
                "requests": []
            }
        },
        "data": {
            "technical": {
                "file_name": "tmp3k33_ae0.md",
                "file_mime": "text/markdown",
                "file_size": 1268,
                "created": "2025-01-26T01:47:04.587826",
                "modified": "2025-01-26T01:47:04.587826"
            },
            "metadata_type": "complete",
            "technical_available": True
        }
    }

    # Test-Ausführung
    with patch('src.processors.metadata_processor.MetadataProcessor.extract_metadata') as mock_extract:
        mock_extract.return_value = CompleteMetadata(**expected_output)

        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        result = await processor.extract_metadata(
            binary_data=file_obj,
            content=None
        )

        # Überprüfungen
        assert result.status == "success"
        assert result.request.processor == "metadata"
        assert result.process.main_processor == "metadata"
        assert result.process.sub_processors == []
        assert result.process.llm_info.requests_count == 0
        assert result.data["technical"]["file_mime"] == "text/markdown"
        assert "content" not in result.data
        assert result.data["metadata_type"] == "complete"
        assert result.data["technical_available"] is True
        assert "content_available" not in result.data

@pytest.mark.asyncio
async def test_extract_metadata_error_handling():
    """Test der Fehlerbehandlung bei der Metadaten-Extraktion."""
    # Test: Ungültige Datei
    with pytest.raises(ProcessingError) as exc_info:
        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        await processor.extract_metadata(
            binary_data=None,
            content=None
        )
    assert "Fehler bei der technischen Metadaten-Extraktion" in str(exc_info.value)

    # Test: Zu große Datei
    large_content = "x" * (100 * 1024 * 1024)  # 100MB
    large_file = io.BytesIO(large_content.encode('utf-8'))
    large_file.name = "large_file.txt"
    
    with pytest.raises(ProcessingError) as exc_info:
        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        await processor.extract_metadata(
            binary_data=large_file,
            content=None
        )
    assert "Datei ist zu groß" in str(exc_info.value) 