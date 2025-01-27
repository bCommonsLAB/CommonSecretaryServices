import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import json
from datetime import datetime
from src.processors.metadata_processor import MetadataProcessor
from src.core.models.metadata import (
    TechnicalMetadata, 
    ContentMetadata
)
from src.core.models.transformer import TransformerResponse, TransformerData
from src.core.models.base import (
    RequestInfo,
    ProcessInfo,
    BaseResponse
)
from src.core.models.llm import LLMRequest, LLMInfo
from src.core.models.enums import ProcessingStatus
from src.core.exceptions import ProcessingError, UnsupportedMimeTypeError
from src.core.resource_tracking import ResourceCalculator
import io
import tempfile
from typing import Dict, Any, Generator, cast, TypeVar, Type
from dataclasses import asdict, dataclass

T = TypeVar('T')

@dataclass(frozen=True)
class CompleteMetadata(BaseResponse):
    """Vollständige Metadaten-Response."""
    data: Dict[str, Any]

def save_metadata_to_json(metadata: Dict[str, Any], test_name: str) -> Path:
    """Speichert Metadaten als JSON für Testvergleiche."""
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
def resource_calculator() -> ResourceCalculator:
    """Mock für den ResourceCalculator."""
    return Mock(spec=ResourceCalculator)

@pytest.fixture
def metadata_processor(resource_calculator: ResourceCalculator) -> MetadataProcessor:
    """Fixture für den MetadataProcessor."""
    return MetadataProcessor(resource_calculator=resource_calculator)

@pytest.mark.asyncio
async def test_extract_technical_metadata(metadata_processor: MetadataProcessor) -> None:
    """Test der technischen Metadaten-Extraktion."""
    # Setup
    pdf_path = Path("tests/sample.pdf")

    # Ausführung
    technical_metadata = await metadata_processor.extract_technical_metadata(pdf_path)

    # Überprüfung
    assert isinstance(technical_metadata, TechnicalMetadata)
    assert technical_metadata.file_name == "sample.pdf"
    assert technical_metadata.file_mime == "application/pdf"
    assert technical_metadata.file_size > 0
    if technical_metadata.doc_pages is not None:
        assert technical_metadata.doc_pages > 0

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(technical_metadata),
        "technical_metadata"
    )

@pytest.mark.asyncio
async def test_extract_technical_metadata_from_audio(metadata_processor: MetadataProcessor) -> None:
    """Test der technischen Metadaten-Extraktion aus einer Audio-Datei."""
    # Setup
    audio_path = Path("tests/sample.mp3")

    # Ausführung
    technical_metadata = await metadata_processor.extract_technical_metadata(audio_path)

    # Überprüfung
    assert isinstance(technical_metadata, TechnicalMetadata)
    assert technical_metadata.file_name == "sample.mp3"
    assert technical_metadata.file_mime == "audio/mpeg"
    assert technical_metadata.file_size > 0
    assert technical_metadata.media_duration is not None
    assert technical_metadata.media_duration > 0
    assert technical_metadata.media_bitrate is not None
    assert technical_metadata.media_bitrate > 0
    assert technical_metadata.media_channels is not None
    assert technical_metadata.media_channels > 0

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(technical_metadata),
        "technical_metadata_audio"
    )

@pytest.mark.asyncio
async def test_extract_content_metadata(metadata_processor: MetadataProcessor) -> None:
    """Test der inhaltlichen Metadaten-Extraktion."""
    # Setup
    content = "Dies ist ein Test-Inhalt für die Metadaten-Extraktion."
    context = {"type": "document"}

    # Ausführung
    llm_info, content_metadata = await metadata_processor.extract_content_metadata(
        content=content,
        context=context
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

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(content_metadata),
        "content_metadata"
    )

@pytest.mark.asyncio
async def test_extract_complete_metadata(metadata_processor: MetadataProcessor) -> None:
    """Test der vollständigen Metadaten-Extraktion."""
    # Setup
    pdf_path = Path("tests/sample.pdf")
    context = {"type": "document"}

    # Ausführung
    complete_metadata = await metadata_processor.extract_metadata(
        binary_data=pdf_path,
        context=context
    )

    # Überprüfung
    assert isinstance(complete_metadata, CompleteMetadata)
    assert complete_metadata.data is not None
    assert "technical" in complete_metadata.data
    assert "content" in complete_metadata.data
    assert complete_metadata.data["technical"]["file_name"] == "sample.pdf"
    assert complete_metadata.data["technical"]["file_mime"] == "application/pdf"
    assert complete_metadata.data["technical"]["file_size"] > 0

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(complete_metadata),
        "complete_metadata"
    )

@pytest.mark.asyncio
async def test_unsupported_mime_type(metadata_processor: MetadataProcessor) -> None:
    """Test der Fehlerbehandlung bei nicht unterstütztem MIME-Type."""
    # Setup
    unsupported_file = Path("tests/sample.xyz")

    # Ausführung und Überprüfung
    with pytest.raises(UnsupportedMimeTypeError):
        await metadata_processor.extract_technical_metadata(unsupported_file)

@pytest.mark.asyncio
async def test_file_not_found(metadata_processor: MetadataProcessor) -> None:
    """Test der Fehlerbehandlung bei nicht existierender Datei."""
    # Setup
    non_existent_file = Path("tests/non_existent.pdf")

    # Ausführung und Überprüfung
    with pytest.raises(ProcessingError):
        await metadata_processor.extract_technical_metadata(non_existent_file)

@pytest.mark.asyncio
async def test_invalid_file(metadata_processor: MetadataProcessor) -> None:
    """Test der Fehlerbehandlung bei ungültiger Datei."""
    # Setup
    invalid_file = Path("tests/invalid.pdf")
    with open(invalid_file, "w") as f:
        f.write("Invalid PDF content")

    try:
        # Ausführung und Überprüfung
        with pytest.raises(ProcessingError):
            await metadata_processor.extract_technical_metadata(invalid_file)
    finally:
        # Aufräumen
        invalid_file.unlink()

@pytest.fixture
def sample_audio_file() -> Generator[Path, None, None]:
    """Fixture für eine Test-Audio-Datei."""
    # Setup
    audio_path = Path("tests/sample.mp3")
    if not audio_path.exists():
        # Erstelle eine Test-Audio-Datei
        audio_data = b"Test audio content"
        audio_path.write_bytes(audio_data)
    
    yield audio_path
    
    # Cleanup
    if audio_path.exists():
        audio_path.unlink()

@pytest.mark.asyncio
async def test_metadata_extraction_structure(metadata_processor: MetadataProcessor, sample_audio_file: Path) -> None:
    """Test der Struktur der Metadaten-Extraktion."""
    # Setup
    context = {"type": "audio"}

    # Ausführung
    result = cast(CompleteMetadata, await metadata_processor.extract_metadata(
        binary_data=sample_audio_file,
        context=context
    ))

    # Überprüfung der Basisstruktur
    assert isinstance(result, CompleteMetadata)
    assert result.data is not None
    assert "technical" in result.data
    assert "content" in result.data

    # Überprüfung der technischen Metadaten
    technical = result.data["technical"]
    assert technical["file_name"] == "sample.mp3"
    assert technical["file_mime"] == "audio/mpeg"
    assert technical["file_size"] > 0
    assert technical["media_duration"] > 0
    assert technical["media_bitrate"] > 0
    assert technical["media_channels"] > 0

    # Überprüfung der Prozessinformationen
    assert result.process.id is not None
    assert result.process.main_processor == "metadata"
    assert result.process.started is not None
    assert result.process.completed is not None

    # Überprüfung der LLM-Informationen
    process_info = cast(ProcessInfo, result.process)
    if hasattr(process_info, 'llm_info') and process_info.llm_info:
        llm_info = cast(LLMInfo, process_info.llm_info)
        if hasattr(llm_info, 'requests_count'):
            assert llm_info.requests_count >= 0
        if hasattr(llm_info, 'total_tokens'):
            assert llm_info.total_tokens >= 0
        if hasattr(llm_info, 'total_duration'):
            assert llm_info.total_duration >= 0

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(result),
        "metadata_extraction_structure"
    )

@pytest.mark.asyncio
async def test_llm_info_structure(metadata_processor: MetadataProcessor, sample_audio_file: Path) -> None:
    """Testet die Struktur der LLM-Informationen."""
    content = "Test-Content für LLM-Verarbeitung"
    
    result = cast(CompleteMetadata, await metadata_processor.extract_metadata(
        binary_data=sample_audio_file,
        content=content
    ))
    
    # LLM-Request prüfen
    process_info = result.process
    if hasattr(process_info, 'llm_info') and process_info.llm_info:
        llm_info = process_info.llm_info
        if hasattr(llm_info, 'requests') and llm_info.requests:
            request = llm_info.requests[0]
            assert isinstance(request.model, str)
            assert isinstance(request.duration, float)
            assert isinstance(request.tokens, int)
            assert isinstance(request.timestamp, str)
            
            # Gesamtwerte prüfen
            if hasattr(llm_info, 'requests_count'):
                assert llm_info.requests_count == len(llm_info.requests)
            if hasattr(llm_info, 'total_tokens'):
                assert llm_info.total_tokens == sum(r.tokens for r in llm_info.requests)
            if hasattr(llm_info, 'total_duration'):
                assert llm_info.total_duration == sum(r.duration for r in llm_info.requests)

@pytest.mark.asyncio
async def test_error_handling(metadata_processor: MetadataProcessor) -> None:
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
async def test_metadata_error_response(metadata_processor: MetadataProcessor) -> None:
    """Überprüft die Fehlerbehandlung bei ungültigem MIME-Type."""
    # Ausführung
    with tempfile.NamedTemporaryFile(suffix=".xyz") as temp_file:
        temp_file.write(b"Test content")
        temp_file.seek(0)
        result = await metadata_processor.extract_metadata(temp_file)

    # Überprüfung
    assert result.status == "error"
    assert result.error is not None
    assert result.error.code == "UnsupportedMimeTypeError"
    assert "MIME-Type nicht unterstützt" in result.error.message
    assert isinstance(result.error.details, dict)
    assert "error_type" in result.error.details
    assert "traceback" in result.error.details

@pytest.mark.asyncio
async def test_metadata_response_structure(metadata_processor: MetadataProcessor) -> None:
    """Test der neuen Response-Struktur des MetadataProcessors."""
    # Test-Datei erstellen
    test_content = "Dies ist ein Test-Inhalt für die Metadaten-Extraktion."
    test_file = io.BytesIO(test_content.encode('utf-8'))
    test_file.name = "test.txt"  # Name für MIME-Type Erkennung

    # Unterstützte MIME-Types erweitern
    if not hasattr(metadata_processor, 'supported_mime_types'):
        metadata_processor.supported_mime_types = []
    metadata_processor.supported_mime_types.append('text/*')

    # Mock für transform_by_template
    def mock_transform(*args: Any, **kwargs: Any) -> tuple[str, TransformerResponse, ContentMetadata]:
        transformed_text = "Transformierter Text"
        template_result = TransformerResponse(
            request=RequestInfo(
                processor="transformer", 
                timestamp=datetime.now().isoformat(),
                parameters={}
            ),
            process=ProcessInfo(
                id="test", 
                main_processor="transformer",
                started=datetime.now().isoformat(),
                completed=datetime.now().isoformat()
            ),
            data=cast(TransformerData, {"text": transformed_text})
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
    if hasattr(metadata_processor, 'transcriber'):
        metadata_processor.transcriber.transform_by_template = mock_transform

    # Metadaten extrahieren
    result = cast(CompleteMetadata, await metadata_processor.extract_metadata(
        binary_data=test_file,
        content=test_content,
        context={'test': True}
    ))

    # Struktur validieren
    assert result.status == ProcessingStatus.SUCCESS
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
async def test_extract_metadata() -> None:
    """Test der Metadaten-Extraktion aus einer Markdown-Datei mit zusätzlichem Content."""
    # Mock-Daten
    file_content = """# Mein Weg zu einem gemeinsamen Leben
Dies ist ein Beispieltext für den Test."""
    
    file_obj = io.BytesIO(file_content.encode('utf-8'))
    file_obj.name = "Mein Weg zu einem gemeinsamen Leben.md"
    
    additional_content = "Das ist ein Text aus dem jahr 2024 in Brixen"

    # Test-Ausführung
    with patch('src.processors.metadata_processor.MetadataProcessor.extract_metadata') as mock_extract:
        mock_extract.return_value = CompleteMetadata(
            status=ProcessingStatus.SUCCESS,
            request=RequestInfo(
                processor="metadata",
                timestamp="2025-01-26T01:47:04.514215",
                parameters={
                    "has_content": True,
                    "context_keys": []
                }
            ),
            process=ProcessInfo(
                id="test",
                main_processor="metadata",
                sub_processors=["transformer"],
                started="2025-01-26T01:47:04.514215",
                completed="2025-01-26T01:47:06.903670"
            ),
            data={
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
        )

        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        result = cast(CompleteMetadata, await processor.extract_metadata(
            binary_data=file_obj,
            content=additional_content
        ))

        # Überprüfungen
        assert result.status == ProcessingStatus.SUCCESS
        assert result.request.processor == "metadata"
        assert result.process.main_processor == "metadata"
        assert result.process.sub_processors == ["transformer"]
        assert result.data["technical"]["file_mime"] == "text/markdown"
        assert result.data["content"]["spatial_location"] == "Brixen"
        assert result.data["content"]["created"].startswith("2024")
        assert result.data["metadata_type"] == "complete"
        assert result.data["content_available"] is True
        assert result.data["technical_available"] is True

@pytest.mark.asyncio
async def test_extract_metadata_without_content() -> None:
    """Test der Metadaten-Extraktion ohne zusätzlichen Content."""
    # Mock-Daten
    file_content = """# Mein Weg zu einem gemeinsamen Leben
Dies ist ein Beispieltext für den Test."""
    
    file_obj = io.BytesIO(file_content.encode('utf-8'))
    file_obj.name = "Mein Weg zu einem gemeinsamen Leben.md"

    # Test-Ausführung
    with patch('src.processors.metadata_processor.MetadataProcessor.extract_metadata') as mock_extract:
        mock_extract.return_value = CompleteMetadata(
            status=ProcessingStatus.SUCCESS,
            request=RequestInfo(
                processor="metadata",
                timestamp="2025-01-26T01:47:04.514215",
                parameters={
                    "has_content": False,
                    "context_keys": []
                }
            ),
            process=ProcessInfo(
                id="test",
                main_processor="metadata",
                sub_processors=[],
                started="2025-01-26T01:47:04.514215",
                completed="2025-01-26T01:47:06.903670"
            ),
            data={
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
        )

        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        result = cast(CompleteMetadata, await processor.extract_metadata(
            binary_data=file_obj,
            content=None
        ))

        # Überprüfungen
        assert result.status == ProcessingStatus.SUCCESS
        assert result.request.processor == "metadata"
        assert result.process.main_processor == "metadata"
        assert result.process.sub_processors == []
        assert result.data["technical"]["file_mime"] == "text/markdown"
        assert "content" not in result.data
        assert result.data["metadata_type"] == "complete"
        assert result.data["technical_available"] is True
        assert "content_available" not in result.data

@pytest.mark.asyncio
async def test_extract_metadata_error_handling() -> None:
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