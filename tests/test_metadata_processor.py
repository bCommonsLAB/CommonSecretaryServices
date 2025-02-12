import pytest
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import json
from datetime import datetime
from src.processors.metadata_processor import MetadataProcessor
from src.core.models.metadata import (
    TechnicalMetadata, 
    ContentMetadata,
    MetadataResponse,
    MetadataData
)
from src.core.models.transformer import TransformerResponse, TransformerData
from src.core.models.base import (
    RequestInfo,
    ProcessInfo,
    BaseResponse,
    ErrorInfo
)
from src.core.models.llm import LLMInfo
from src.core.models.enums import ProcessingStatus
from src.core.exceptions import ProcessingError, UnsupportedMimeTypeError
from src.core.resource_tracking import ResourceCalculator
import io
from typing import Dict, Any, Generator, cast, TypeVar, Optional
from dataclasses import asdict, dataclass
from src.core.resource_tracking import ResourceCalculator

T = TypeVar('T')

@dataclass(frozen=True, slots=True, init=False)
class CompleteMetadata(BaseResponse):
    """Vollständige Metadaten-Response."""
    data: Dict[str, Any]
    llm_info: Optional[LLMInfo] = None

    def __init__(
        self,
        request: RequestInfo,
        process: ProcessInfo,
        data: Dict[str, Any],
        llm_info: Optional[LLMInfo] = None,
        status: ProcessingStatus = ProcessingStatus.PENDING,
        error: Optional[ErrorInfo] = None
    ) -> None:
        """Initialisiert die CompleteMetadata."""
        super().__init__(request=request, process=process, status=status, error=error)
        object.__setattr__(self, 'data', data)
        object.__setattr__(self, 'llm_info', llm_info)

    @classmethod
    def create(
        cls,
        request: RequestInfo,
        process: ProcessInfo,
        data: Dict[str, Any],
        llm_info: Optional[LLMInfo] = None
    ) -> 'CompleteMetadata':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            request=request,
            process=process,
            data=data,
            llm_info=llm_info,
            status=ProcessingStatus.SUCCESS
        )

    @classmethod
    def create_error(
        cls,
        request: RequestInfo,
        process: ProcessInfo,
        error: ErrorInfo
    ) -> 'CompleteMetadata':
        """Erstellt eine Error-Response."""
        return cls(
            request=request,
            process=process,
            data={},
            status=ProcessingStatus.ERROR,
            error=error
        )

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
def resource_calculator():
    """Mock für den ResourceCalculator."""
    calculator = Mock(spec=ResourceCalculator)
    calculator.calculate_cost = Mock(return_value=0.1)
    calculator.track_usage = Mock()
    return calculator

@pytest.fixture
def test_file(tmp_path):
    """Erstellt eine Test-Datei."""
    file_path = tmp_path / "test.txt"
    file_path.write_text("Test content")
    return file_path

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
async def test_extract_technical_metadata_from_audio(metadata_processor: MetadataProcessor, sample_audio_file: Path) -> None:
    """Test der technischen Metadaten-Extraktion aus einer Audio-Datei."""
    # Ausführung
    technical_metadata = await metadata_processor.extract_technical_metadata(sample_audio_file)

    # Überprüfung
    assert isinstance(technical_metadata, TechnicalMetadata)
    assert technical_metadata.file_name == "sample.mp3"
    assert technical_metadata.file_mime == "audio/mpeg"
    assert technical_metadata.file_size > 0

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
    assert isinstance(complete_metadata, MetadataResponse)
    assert complete_metadata.data is not None
    assert complete_metadata.data.technical is not None
    assert complete_metadata.data.technical.file_mime == "application/pdf"
    assert complete_metadata.data.technical.doc_pages is not None

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(complete_metadata),
        "complete_metadata"
    )

@pytest.mark.asyncio
async def test_unsupported_mime_type(metadata_processor: MetadataProcessor, tmp_path: Path) -> None:
    """Test der Fehlerbehandlung bei nicht unterstütztem MIME-Type."""
    # Setup
    unsupported_file = tmp_path / "sample.xyz"
    unsupported_file.write_text("Test content")

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
async def test_invalid_file(metadata_processor: MetadataProcessor, tmp_path: Path) -> None:
    """Test der Fehlerbehandlung bei ungültiger Datei."""
    # Setup
    invalid_file = tmp_path / "invalid.pdf"
    invalid_file.write_text("Invalid PDF content")

    # Ausführung und Überprüfung
    with pytest.raises(ProcessingError):
        await metadata_processor.extract_technical_metadata(invalid_file)

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
    result = await metadata_processor.extract_metadata(
        binary_data=sample_audio_file,
        context=context
    )

    # Überprüfung der Basisstruktur
    assert isinstance(result, MetadataResponse)
    assert result.data is not None
    assert result.data.technical is not None
    assert result.data.content is not None

    # Überprüfung der technischen Metadaten
    technical = result.data.technical
    assert technical.file_name == "sample.mp3"
    assert technical.file_mime == "audio/mpeg"
    assert technical.file_size > 0
    assert technical.media_duration is not None and technical.media_duration > 0
    assert technical.media_bitrate is not None and technical.media_bitrate > 0
    assert technical.media_channels is not None and technical.media_channels > 0

    # Überprüfung der Prozessinformationen
    assert result.process.id is not None
    assert result.process.main_processor == "metadata"
    assert result.process.started is not None
    assert result.process.completed is not None

    # Speichere Ergebnis
    save_metadata_to_json(
        asdict(result),
        "metadata_extraction_structure"
    )

@pytest.mark.asyncio
async def test_metadata_response_structure(metadata_processor: MetadataProcessor) -> None:
    """Test der Response-Struktur des MetadataProcessors."""
    # Test-Datei erstellen
    test_content = "Dies ist ein Test-Inhalt für die Metadaten-Extraktion."
    test_file = io.BytesIO(test_content.encode('utf-8'))
    test_file.name = "test.txt"

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
    result = await metadata_processor.extract_metadata(
        binary_data=test_file,
        content=test_content,
        context={'test': True}
    )

    # Struktur validieren
    assert result.status == ProcessingStatus.SUCCESS
    assert result.request.processor == "metadata"
    assert result.request.timestamp is not None
    assert result.request.parameters == {
        "has_content": True,
        "has_context": True,
        "context_keys": ["test"]
    }
    assert result.process.id is not None
    assert result.process.main_processor == "metadata"
    assert result.process.started is not None
    assert result.process.completed is not None
    assert result.data is not None

@pytest.mark.asyncio
async def test_extract_metadata() -> None:
    """Test der vollständigen Metadaten-Extraktion."""
    # Mock-Daten
    file_content = """# Mein Weg nach Brixen
    
    Dies ist ein Beispieltext für den Test.
    Er wurde am 15. Januar 2024 in Brixen verfasst."""
    
    additional_content = """Zusätzliche Informationen:
    - Autor: Max Mustermann
    - Datum: 15.01.2024
    - Ort: Brixen, Südtirol"""
    
    file_obj = io.BytesIO(file_content.encode('utf-8'))
    file_obj.name = "Mein Weg nach Brixen.md"

    # Test-Ausführung
    processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
    result = await processor.extract_metadata(
        binary_data=file_obj,
        content=additional_content
    )

    # Überprüfungen
    assert result.status == ProcessingStatus.SUCCESS
    assert result.request.processor == "metadata"
    assert result.process.main_processor == "metadata"
    assert result.process.sub_processors == ["transformer"]
    assert result.data.technical is not None
    assert result.data.technical.file_mime == "text/markdown"
    assert result.data.content is not None
    assert result.data.content.title == "Mein Weg nach Brixen"
    assert result.data.content.authors == "Max Mustermann"
    assert result.data.content.spatial_location == "Brixen"

@pytest.mark.asyncio
async def test_extract_metadata_error_handling() -> None:
    """Test der Fehlerbehandlung bei der Metadaten-Extraktion."""
    # Test: Ungültige Datei
    with pytest.raises(ProcessingError) as exc_info:
        processor = MetadataProcessor(resource_calculator=Mock(spec=ResourceCalculator))
        await processor.extract_metadata(
            binary_data=None,
            content="Test content"  # Content hinzugefügt
        )
    assert "Fehler bei der technischen Metadaten-Extraktion" in str(exc_info.value)

    # Test: Zu große Datei
    large_content = "x" * (100 * 1024 * 1024)  # 100MB
    large_file = io.BytesIO(large_content.encode('utf-8'))
    large_file.name = "large_file.txt"
    
    with pytest.raises(ProcessingError) as exc_info:
        await processor.extract_metadata(
            binary_data=large_file,
            content=None
        )
    assert "Datei zu groß" in str(exc_info.value)

@pytest.mark.asyncio
async def test_metadata_processor_basic(resource_calculator: ResourceCalculator, test_file: Path) -> None:
    """Testet die grundlegende Funktionalität des MetadataProcessors."""
    processor = MetadataProcessor(resource_calculator, "test-process")
    
    response = await processor.process(
        binary_data=test_file,
        content="Test content",
        context={"test": True}
    )
    
    assert response is not None
    assert response.status == ProcessingStatus.SUCCESS
    assert response.data is not None
    assert response.data.technical is not None
    assert response.data.technical.file_name == "test.txt"
    assert response.data.technical.file_mime == "text/plain"
    assert response.data.steps is not None
    assert len(response.data.steps) > 0

@pytest.mark.asyncio
async def test_metadata_processor_technical_only(resource_calculator: ResourceCalculator, test_file: Path) -> None:
    """Testet die Extraktion von technischen Metadaten."""
    processor = MetadataProcessor(resource_calculator, "test-process")
    
    response = await processor.process(
        binary_data=test_file
    )
    
    assert response.status == ProcessingStatus.SUCCESS
    assert response.data.technical is not None
    assert response.data.content is None
    assert len(response.data.steps) == 1
    assert response.data.steps[0].name == "technical_metadata"
    assert response.data.steps[0].status == ProcessingStatus.SUCCESS

@pytest.mark.asyncio
async def test_metadata_processor_content_only(resource_calculator: ResourceCalculator) -> None:
    """Testet die Extraktion von inhaltlichen Metadaten."""
    processor = MetadataProcessor(resource_calculator, "test-process")
    
    response = await processor.process(
        binary_data=None,  # Kein binary_data für Content-Only
        content="Test content for analysis"
    )
    
    assert response.status == ProcessingStatus.SUCCESS
    assert response.data.content is not None
    assert response.data.content.title is not None
    assert response.data.content.type == "text"
    assert len(response.data.steps) > 0
    content_step = next(s for s in response.data.steps if s.name == "content_metadata")
    assert content_step.status == ProcessingStatus.SUCCESS

@pytest.mark.asyncio
async def test_metadata_processor_error_handling(resource_calculator: ResourceCalculator):
    """Testet die Fehlerbehandlung."""
    processor = MetadataProcessor(resource_calculator, "test-process")
    
    with pytest.raises(Exception):
        await processor.process(
            binary_data="nonexistent_file.txt"
        )

@pytest.fixture
def sample_pdf_file(tmp_path: Path) -> Path:
    """Erstellt eine minimale PDF-Datei für Tests."""
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%EOF")
    return pdf_path

@pytest.fixture
def sample_audio_file(tmp_path: Path) -> Path:
    """Erstellt eine minimale MP3-Datei für Tests."""
    audio_path = tmp_path / "sample.mp3"
    # Minimale MP3-Header-Bytes
    audio_path.write_bytes(b"ID3\x03\x00\x00\x00\x00\x00\x00")
    return audio_path

@pytest.fixture
def sample_text_file(tmp_path: Path) -> Path:
    """Erstellt eine Text-Datei für Tests."""
    text_path = tmp_path / "sample.txt"
    text_path.write_text("Dies ist ein Testtext.")
    return text_path 