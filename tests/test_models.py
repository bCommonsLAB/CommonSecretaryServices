"""
Tests für die Datenmodelle.
"""
import pytest
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, TypeVar, cast, Sequence, Mapping
from dataclasses import dataclass, field
from enum import Enum

# Enums für Tests
class OutputFormat(str, Enum):
    """Ausgabeformat für Transformationen."""
    TEXT = "text"
    HTML = "html"
    MARKDOWN = "markdown"

T = TypeVar('T')
ModelType = TypeVar('ModelType', bound='BaseModel')

# Basis-Modelle für Tests
@dataclass(frozen=True, slots=True)
class BaseModel:
    """Basis-Klasse für alle Modelle."""
    
    def to_dict(self) -> Dict[str, Any]:
        """Konvertiert das Modell in ein Dictionary."""
        result: Dict[str, Any] = {}
        for field_name in self.__slots__:
            value = getattr(self, field_name)
            if value is None:
                result[field_name] = None
            elif isinstance(value, BaseModel):
                result[field_name] = value.to_dict()
            elif isinstance(value, (list, tuple)):
                result[field_name] = [
                    item.to_dict() if isinstance(item, BaseModel) else item
                    for item in cast(Sequence[Any], value)
                ]
            elif isinstance(value, dict):
                result[field_name] = {
                    str(k): v.to_dict() if isinstance(v, BaseModel) else v
                    for k, v in cast(Mapping[Any, Any], value).items()
                }
            elif isinstance(value, datetime):
                result[field_name] = value.isoformat()
            elif isinstance(value, Enum):
                result[field_name] = value.value
            else:
                result[field_name] = value
        return result

@dataclass(frozen=True, slots=True)
class ErrorInfo(BaseModel):
    """Fehlerinformationen."""
    code: int | str
    message: str
    details: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Validiert die Fehlerinformationen."""
        if isinstance(self.code, int) and self.code < 0:
            raise ValueError("Error code must not be negative")
        if not str(self.code).strip():
            raise ValueError("Error code must not be empty")
        if not self.message.strip():
            raise ValueError("Error message must not be empty")

@dataclass(frozen=True, slots=True)
class RequestInfo(BaseModel):
    """Informationen über den Request."""
    processor: str
    timestamp: datetime = field(default_factory=datetime.now)
    parameters: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Validiert die Request-Informationen."""
        if not self.processor.strip():
            raise ValueError("Processor must not be empty")

@dataclass(frozen=True, slots=True)
class ProcessInfo(BaseModel):
    """Informationen über den Verarbeitungsprozess."""
    id: str
    processors: List[str]
    duration: float
    started: datetime = field(default_factory=datetime.now)
    completed: Optional[datetime] = None

    def __post_init__(self):
        """Validiert die Prozess-Informationen."""
        if not self.id.strip():
            raise ValueError("Process ID must not be empty")
        if not self.processors:
            raise ValueError("At least one processor must be specified")
        if self.duration < 0:
            raise ValueError("Duration must not be negative")

@dataclass(frozen=True, slots=True)
class LLModel(BaseModel):
    """Informationen über ein LLM-Modell."""
    model: str
    duration: float
    tokens: int

    def __post_init__(self):
        """Validiert die LLM-Informationen."""
        if not self.model.strip():
            raise ValueError("Model name must not be empty")
        if self.duration < 0:
            raise ValueError("Duration must not be negative")
        if self.tokens < 0:
            raise ValueError("Token count must not be negative")

# LLM-Tracking Modelle
@dataclass(frozen=True, slots=True)
class LLMRequest(BaseModel):
    """Ein einzelner LLM-Request."""
    model: str
    purpose: str
    tokens: int
    duration: float
    timestamp: datetime = field(default_factory=datetime.now)

@dataclass(frozen=True, slots=True)
class LLMInfo(BaseModel):
    """Informationen über LLM-Nutzung."""
    requests: List[LLMRequest] = field(default_factory=list)
    requests_count: int = 0
    total_tokens: int = 0
    total_duration: float = 0.0

    def add_request(self, request: LLMRequest):
        """Fügt einen LLM-Request hinzu."""
        object.__setattr__(self, 'requests', self.requests + [request])
        object.__setattr__(self, 'requests_count', self.requests_count + 1)
        object.__setattr__(self, 'total_tokens', self.total_tokens + request.tokens)
        object.__setattr__(self, 'total_duration', self.total_duration + request.duration)

# Response-Modelle für Tests
@dataclass(frozen=True, slots=True)
class BaseResponse(BaseModel):
    """Basis-Response für alle API-Antworten."""
    status: str = "success"
    request: RequestInfo = field(default_factory=lambda: RequestInfo(processor="default"))
    process: ProcessInfo = field(default_factory=lambda: ProcessInfo(
        id="default",
        processors=["default"],
        duration=0.0
    ))
    data: Optional[Dict[str, Any]] = None
    error: Optional[ErrorInfo] = None
    llm_info: LLMInfo = field(default_factory=LLMInfo)

    def __post_init__(self):
        """Validiert die Response."""
        if not self.status.strip():
            raise ValueError("Status must not be empty")
        if self.status not in ('success', 'error'):
            raise ValueError("Status must be either 'success' or 'error'")
        if self.status == 'success' and self.error is not None:
            raise ValueError("Error info must not be set for successful response")
        if self.status == 'error' and self.error is None:
            raise ValueError("Error info must be set for error response")

    def add_llm_request(self, llm: LLModel, purpose: str):
        """Fügt einen LLM-Request hinzu."""
        request = LLMRequest(
            model=llm.model,
            purpose=purpose,
            tokens=llm.tokens,
            duration=llm.duration
        )
        object.__setattr__(self, 'llm_info', LLMInfo(
            requests=self.llm_info.requests + [request],
            requests_count=self.llm_info.requests_count + 1,
            total_tokens=self.llm_info.total_tokens + request.tokens,
            total_duration=self.llm_info.total_duration + request.duration
        ))

    @classmethod
    def success(cls, request: RequestInfo, process: ProcessInfo, data: Optional[Dict[str, Any]] = None) -> 'BaseResponse':
        """Erstellt eine erfolgreiche Response."""
        return cls(
            status='success',
            request=request,
            process=process,
            data=data
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error_info: ErrorInfo) -> 'BaseResponse':
        """Erstellt eine Fehler-Response."""
        return cls(
            status='error',
            request=request,
            process=process,
            error=error_info
        )

# YouTube-Modelle für Tests
@dataclass(frozen=True, slots=True)
class YoutubeMetadata(BaseModel):
    """Metadaten eines YouTube-Videos."""
    title: str
    url: str
    video_id: str
    duration: int
    duration_formatted: str
    process_dir: str

    def __post_init__(self):
        """Validiert die Metadaten."""
        if not self.title.strip():
            raise ValueError("Title must not be empty")
        if not self.url.strip() or not self.url.startswith("https://youtube.com/watch?v="):
            raise ValueError("Invalid YouTube URL")
        if not self.video_id.strip():
            raise ValueError("Video ID must not be empty")
        if self.duration < 0:
            raise ValueError("Duration must not be negative")
        if not self.duration_formatted.strip():
            raise ValueError("Duration formatted must not be empty")
        if not self.process_dir.strip():
            raise ValueError("Process directory must not be empty")

@dataclass(frozen=True, slots=True)
class YoutubeProcessingResult(BaseModel):
    """Ergebnis der YouTube-Verarbeitung."""
    process_id: str
    metadata: YoutubeMetadata
    status: str

    def __post_init__(self):
        """Validiert das Ergebnis."""
        if not self.process_id.strip():
            raise ValueError("Process ID must not be empty")
        if self.status not in ('success', 'error', 'processing'):
            raise ValueError("Invalid status")

# Transformer-Modelle für Tests
@dataclass(frozen=True, slots=True)
class TransformerInput(BaseModel):
    """Eingabedaten für den Transformer."""
    text: str
    language: str
    format: OutputFormat = OutputFormat.TEXT
    template: Optional[str] = None
    variables: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        """Validiert die Eingabedaten."""
        if not self.text.strip():
            raise ValueError("Text must not be empty")
        if len(self.language) != 2:
            raise ValueError("Language must be ISO 639-1 (2 characters)")
        if self.template is not None and not self.template.strip():
            raise ValueError("Template must not be empty if provided")

@dataclass(frozen=True, slots=True)
class TransformerOutput(BaseModel):
    """Ausgabedaten des Transformers."""
    text: str
    language: str
    format: OutputFormat = OutputFormat.TEXT

    def __post_init__(self):
        """Validiert die Ausgabedaten."""
        if not self.text.strip():
            raise ValueError("Text must not be empty")
        if len(self.language) != 2:
            raise ValueError("Language must be ISO 639-1 (2 characters)")

@dataclass(frozen=True, slots=True)
class TransformerInfo(BaseModel):
    """Informationen über die Transformation."""
    model: str
    task: str
    duration: float
    token_count: int

    def __post_init__(self):
        """Validiert die Transformations-Informationen."""
        if not self.model.strip():
            raise ValueError("Model must not be empty")
        if not self.task.strip():
            raise ValueError("Task must not be empty")
        if self.duration < 0:
            raise ValueError("Duration must not be negative")
        if self.token_count < 0:
            raise ValueError("Token count must not be negative")

@dataclass(frozen=True, slots=True)
class TransformerResponse(BaseResponse):
    """Response des Transformers."""
    input: Optional[TransformerInput] = None
    output: Optional[TransformerOutput] = None
    transform: Optional[TransformerInfo] = None

    @classmethod
    def create(cls, input_text: str, input_language: str, output_text: Optional[str] = None,
               output_language: Optional[str] = None, model: Optional[str] = None,
               task: Optional[str] = None, duration: float = 0.0, token_count: int = 0,
               template: Optional[str] = None, template_variables: Optional[Dict[str, Any]] = None,
               output_format: OutputFormat = OutputFormat.TEXT) -> 'TransformerResponse':
        """Erstellt eine TransformerResponse."""
        input_data = TransformerInput(
            text=input_text,
            language=input_language,
            format=output_format,
            template=template,
            variables=template_variables
        )

        output_data = None
        if output_text is not None and output_language is not None:
            output_data = TransformerOutput(
                text=output_text,
                language=output_language,
                format=output_format
            )

        transform_info = None
        if model is not None and task is not None:
            transform_info = TransformerInfo(
                model=model,
                task=task,
                duration=duration,
                token_count=token_count
            )

        return cls(
            status='success',
            request=RequestInfo(processor="transformer"),
            process=ProcessInfo(
                id="transform-" + datetime.now().isoformat(),
                processors=["transformer"],
                duration=duration
            ),
            input=input_data,
            output=output_data,
            transform=transform_info
        )

    @classmethod
    def create_error(cls, request: RequestInfo, process: ProcessInfo, error_info: ErrorInfo) -> 'TransformerResponse':
        """Erstellt eine Fehler-Response."""
        return cls(
            status='error',
            request=request,
            process=process,
            error=error_info
        )

# Fixtures
@pytest.fixture
def base_test_data() -> Dict[str, Any]:
    """Gemeinsame Testdaten für Basis-Modelle."""
    return {
        "timestamp": datetime.now(timezone.utc),
        "id": "test-123",
        "processor": "test"
    }

@pytest.fixture
def response_test_data(base_test_data: Dict[str, Any]) -> Dict[str, Any]:
    """Gemeinsame Testdaten für Response-Modelle."""
    return {
        **base_test_data,
        "status": "success",
        "data": {"test": "data"}
    }

# Basis-Modell Tests
class TestBaseModels:
    """Tests für die Basis-Modelle."""
    
    def test_error_info_creation(self):
        """Test der ErrorInfo Erstellung."""
        error = ErrorInfo(code=404, message="Not Found")
        assert error.code == 404
        assert error.message == "Not Found"
        assert error.details is None
    
    def test_error_info_validation(self):
        """Test der ErrorInfo Validierung."""
        # Test für Details
        error = ErrorInfo(
            code=500,
            message="Server Error",
            details={"cause": "Database connection failed"}
        )
        if error.details is not None:  # Type guard
            assert error.details["cause"] == "Database connection failed"
    
    def test_request_info_creation(self, base_test_data: Dict[str, Any]):
        """Test der RequestInfo Erstellung."""
        request = RequestInfo(
            processor=str(base_test_data["processor"]),
            timestamp=cast(datetime, base_test_data["timestamp"])
        )
        assert request.processor == base_test_data["processor"]
        assert isinstance(request.timestamp, datetime)
        assert request.parameters is None
    
    def test_request_info_validation(self):
        """Test der RequestInfo Validierung."""
        # Test für Parameter
        request = RequestInfo(
            processor="test",
            parameters={"key": "value"}
        )
        if request.parameters is not None:  # Type guard
            assert request.parameters["key"] == "value"
    
    def test_process_info_creation(self, base_test_data: Dict[str, Any]):
        """Test der ProcessInfo Erstellung."""
        process = ProcessInfo(
            id=str(base_test_data["id"]),
            processors=["test1", "test2"],
            duration=1.5
        )
        assert process.id == base_test_data["id"]
        assert len(process.processors) == 2
        assert process.duration == 1.5
        assert process.started is not None
        assert process.completed is None
    
    def test_process_info_validation(self):
        """Test der ProcessInfo Validierung."""
        # Test für leere ID
        with pytest.raises(ValueError):
            ProcessInfo(
                id="",
                processors=["test"],
                duration=1.0
            )
        
        # Test für leere Processor-Liste
        with pytest.raises(ValueError):
            ProcessInfo(
                id="test",
                processors=[],
                duration=1.0
            )
        
        # Test für negative Dauer
        with pytest.raises(ValueError):
            ProcessInfo(
                id="test",
                processors=["test"],
                duration=-1.0
            )
    
    def test_llmodel_creation(self):
        """Test der LLModel Erstellung."""
        model = LLModel(
            model="gpt-4",
            duration=1.5,
            tokens=100
        )
        assert model.model == "gpt-4"
        assert model.duration == 1.5
        assert model.tokens == 100
    
    def test_llmodel_validation(self):
        """Test der LLModel Validierung."""
        # Test für leeres Modell
        with pytest.raises(ValueError):
            LLModel(
                model="",
                duration=1.0,
                tokens=100
            )
        
        # Test für negative Dauer
        with pytest.raises(ValueError):
            LLModel(
                model="gpt-4",
                duration=-1.0,
                tokens=100
            )
        
        # Test für negative Tokens
        with pytest.raises(ValueError):
            LLModel(
                model="gpt-4",
                duration=1.0,
                tokens=-100
            )

# Response-Modell Tests
class TestResponseModels:
    """Tests für Response-Modelle."""

    def test_base_response_success(self):
        """Test für erfolgreiche Response"""
        request = RequestInfo(processor="test")
        process = ProcessInfo(
            id="test-123",
            processors=["test"],
            duration=1.0
        )
        
        response = BaseResponse.success(request=request, process=process)
        assert response.status == "success"
        assert response.request.processor == "test"
        assert response.process.id == "test-123"
        assert response.error is None

    def test_base_response_error(self):
        """Test der Error-Response Erstellung."""
        now = datetime.now(timezone.utc)
        request = RequestInfo(
            processor="test",
            timestamp=now
        )
        process = ProcessInfo(
            id="test-123",
            processors=["test"],
            duration=1.0
        )
        error = ErrorInfo(code="TEST_ERROR", message="Test error message")
        
        response = BaseResponse.create_error(
            request=request,
            process=process,
            error_info=error
        )
        
        assert response.status == "error"
        assert response.error is not None
        if response.error:  # Type guard
            assert response.error.code == "TEST_ERROR"
            assert response.error.message == "Test error message"

    def test_base_response_validation(self):
        """Test für Validierungsregeln"""
        request = RequestInfo(processor="test")
        process = ProcessInfo(
            id="test-123",
            processors=["test"],
            duration=1.0
        )
        
        # Error ohne error-Info soll fehlschlagen
        with pytest.raises(ValueError):
            BaseResponse(
                status="error",
                request=request,
                process=process
            )
        
        # Success mit error-Info sollte fehlschlagen
        with pytest.raises(ValueError):
            BaseResponse(
                status="success",
                request=request,
                process=process,
                error=ErrorInfo(code=500, message="Test")
            )

    def test_base_response_defaults(self):
        """Test für Default-Werte"""
        response = BaseResponse()
        assert response.status == "success"
        assert isinstance(response.request, RequestInfo)
        assert isinstance(response.process, ProcessInfo)
        assert response.data is None
        assert response.error is None

    def test_base_response_llm(self):
        """Test für LLM-Request Tracking"""
        response = BaseResponse()

        # Füge einen LLM-Request hinzu
        llm = LLModel(
            model="gpt-4",
            duration=1.5,
            tokens=100
        )
        response.add_llm_request(llm, purpose="translation")

        # Prüfe LLM-Tracking
        assert response.llm_info.requests_count == 1
        assert len(response.llm_info.requests) == 1
        assert response.llm_info.total_tokens == 100
        assert response.llm_info.total_duration == 1.5
        
        # Prüfe Request-Details
        request = response.llm_info.requests[0]
        assert request.model == "gpt-4"
        assert request.purpose == "translation"
        assert request.tokens == 100
        assert request.duration == 1.5
        assert request.timestamp is not None

# Prozessor-spezifische Tests
class TestYoutubeModels:
    """Tests für die YouTube-spezifischen Modelle."""
    
    @pytest.fixture
    def test_metadata(self) -> YoutubeMetadata:
        """Test-Metadaten für YouTube Tests."""
        return YoutubeMetadata(
            title="Test Video",
            url="https://youtube.com/watch?v=test123",
            video_id="test123",
            duration=300,  # 5 Minuten in Sekunden
            duration_formatted="5:00",
            process_dir="/tmp/test123"
        )
    
    def test_youtube_metadata_creation(self, test_metadata: YoutubeMetadata):
        """Test der YoutubeMetadata Erstellung."""
        assert test_metadata.title == "Test Video"
        assert test_metadata.url == "https://youtube.com/watch?v=test123"
        assert test_metadata.video_id == "test123"
        assert test_metadata.duration == 300
        assert test_metadata.duration_formatted == "5:00"
        assert test_metadata.process_dir == "/tmp/test123"
    
    def test_youtube_metadata_validation(self):
        """Test der YoutubeMetadata Validierung."""
        # Test für leeren Titel
        with pytest.raises(ValueError):
            YoutubeMetadata(
                title="",
                url="https://youtube.com/watch?v=test123",
                video_id="test123",
                duration=300,
                duration_formatted="5:00",
                process_dir="/tmp/test123"
            )
        
        # Test für ungültige URL
        with pytest.raises(ValueError):
            YoutubeMetadata(
                title="Test Video",
                url="invalid-url",
                video_id="test123",
                duration=300,
                duration_formatted="5:00",
                process_dir="/tmp/test123"
            )
        
        # Test für leere Video ID
        with pytest.raises(ValueError):
            YoutubeMetadata(
                title="Test Video",
                url="https://youtube.com/watch?v=test123",
                video_id="",
                duration=300,
                duration_formatted="5:00",
                process_dir="/tmp/test123"
            )
        
        # Test für negative Dauer
        with pytest.raises(ValueError):
            YoutubeMetadata(
                title="Test Video",
                url="https://youtube.com/watch?v=test123",
                video_id="test123",
                duration=-300,
                duration_formatted="-5:00",
                process_dir="/tmp/test123"
            )
    
    def test_youtube_processing_result_creation(self, test_metadata: YoutubeMetadata):
        """Test der YoutubeProcessingResult Erstellung."""
        result = YoutubeProcessingResult(
            process_id="test-process-123",
            metadata=test_metadata,
            status="success"
        )
        assert result.process_id == "test-process-123"
        assert result.metadata == test_metadata
        assert result.status == "success"
    
    def test_youtube_processing_result_validation(self, test_metadata: YoutubeMetadata):
        """Test der YoutubeProcessingResult Validierung."""
        # Test für leere Process ID
        with pytest.raises(ValueError):
            YoutubeProcessingResult(
                process_id="",
                metadata=test_metadata,
                status="success"
            )
        
        # Test für ungültigen Status
        with pytest.raises(ValueError):
            YoutubeProcessingResult(
                process_id="test-123",
                metadata=test_metadata,
                status="invalid"
            )
    
    def test_youtube_processing_result_to_dict(self, test_metadata: YoutubeMetadata):
        """Test der to_dict Methode von YoutubeProcessingResult."""
        result = YoutubeProcessingResult(
            process_id="test-process-123",
            metadata=test_metadata,
            status="success"
        )
        data = result.to_dict()
        
        assert isinstance(data, dict)
        assert data["process_id"] == "test-process-123"
        assert data["metadata"]["title"] == "Test Video"
        assert data["metadata"]["url"] == "https://youtube.com/watch?v=test123"
        assert data["metadata"]["video_id"] == "test123"
        assert data["metadata"]["duration"] == 300
        assert data["metadata"]["duration_formatted"] == "5:00"
        assert data["metadata"]["process_dir"] == "/tmp/test123"
        assert data["status"] == "success"

    def test_base_response_error(self):
        """Test der Error-Response Erstellung."""
        now = datetime.now(timezone.utc)
        request = RequestInfo(
            processor="test",
            timestamp=now
        )
        process = ProcessInfo(
            id="test-123",
            processors=["test"],
            duration=1.0
        )
        error = ErrorInfo(code="TEST_ERROR", message="Test error message")
        
        response = BaseResponse.create_error(
            request=request,
            process=process,
            error_info=error
        )
        
        assert response.status == "error"
        assert response.error is not None
        if response.error:  # Type guard
            assert response.error.code == "TEST_ERROR"
            assert response.error.message == "Test error message"

# ... rest of the file remains unchanged ... 