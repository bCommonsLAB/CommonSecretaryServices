"""Tests für den BaseProcessor."""
import pytest
from src.processors.base_processor import BaseProcessor, BaseProcessorResponse
from src.core.exceptions import ValidationError
from src.core.resource_tracking import ResourceCalculator
from src.core.models.base import ErrorInfo
from typing import Any, Dict, Optional

@pytest.fixture
def mock_resource_calculator() -> ResourceCalculator:
    """Fixture für einen ResourceCalculator Mock."""
    calculator = ResourceCalculator()
    calculator.calculate = lambda: {"cpu": 0.0, "memory": 0.0}  # type: ignore
    return calculator

class TestBaseProcessor:
    """Testklasse für den BaseProcessor."""
    
    @pytest.fixture
    def processor(self, mock_resource_calculator: ResourceCalculator) -> BaseProcessor:
        """Fixture für einen BaseProcessor."""
        proc = BaseProcessor(mock_resource_calculator)
        proc.init_logger("test")  # Logger initialisieren
        return proc
        
    @pytest.fixture
    def response(self) -> BaseProcessorResponse:
        """Fixture für eine BaseProcessorResponse."""
        return BaseProcessorResponse("test")

    def test_init(self, processor: BaseProcessor) -> None:
        """Test der Initialisierung."""
        assert processor.process_id is not None
        assert processor.resource_calculator is not None
        assert processor.logger is not None
        assert processor.temp_dir is None  # Temp-Dir wird erst durch init_temp_dir gesetzt

    def test_validate_text(self, processor: BaseProcessor) -> None:
        """Test der Text-Validierung."""
        # Valide Fälle
        assert processor.validate_text("Test") == "Test"
        assert processor.validate_text("  Test  ") == "Test"
        
        # Invalide Fälle
        with pytest.raises(ValidationError) as exc:
            processor.validate_text(None)
        assert "darf nicht leer sein" in str(exc.value)
        
        with pytest.raises(ValidationError) as exc:
            processor.validate_text("")
        assert "darf nicht leer sein" in str(exc.value)
        
        with pytest.raises(ValidationError) as exc:
            processor.validate_text("   ")
        assert "darf nicht nur aus Whitespace bestehen" in str(exc.value)

    def test_validate_language_code(self, processor: BaseProcessor) -> None:
        """Test der Sprach-Code-Validierung."""
        # Valide Fälle
        assert processor.validate_language_code("de") == "de"
        assert processor.validate_language_code("EN") == "en"
        
        # Invalide Fälle
        with pytest.raises(ValidationError) as exc:
            processor.validate_language_code(None)
        assert "muss angegeben werden" in str(exc.value)
        
        with pytest.raises(ValidationError) as exc:
            processor.validate_language_code("xyz")
        assert "Nicht unterstützter language" in str(exc.value)

    def test_validate_format(self, processor: BaseProcessor) -> None:
        """Test der Format-Validierung."""
        # Valide Fälle
        assert processor.validate_format("text") == "text"
        assert processor.validate_format("html") == "html"
        assert processor.validate_format("markdown") == "markdown"
        assert processor.validate_format(None) == "text"  # Default
        
        # Invalide Fälle werden auf Default gesetzt
        assert processor.validate_format("invalid") == "text"
        assert processor.validate_format("") == "text"

    def test_validate_context(self, processor: BaseProcessor) -> None:
        """Test der Context-Validierung."""
        # Valide Fälle
        valid_context: Dict[str, Any] = {"key": "value"}
        assert processor.validate_context(valid_context) == valid_context
        assert processor.validate_context(None) is None
        
        # Invalide Fälle
        invalid_str_context: Optional[Dict[str, Any]] = None
        invalid_int_context: Optional[Dict[str, Any]] = None
        assert processor.validate_context(invalid_str_context) is None
        assert processor.validate_context(invalid_int_context) is None

    def test_init_temp_dir(self, processor: BaseProcessor, tmp_path: Any) -> None:
        """Test der Temp-Dir-Initialisierung (veraltet)."""
        # Hinweis: Diese Methode ist veraltet, wird aber für Rückwärtskompatibilität getestet
        
        # Test mit Standard-Pfad
        temp_dir = processor.init_temp_dir("test")
        assert temp_dir.exists()
        assert "temp" in str(temp_dir)  # Es sollte jetzt ein Unterverzeichnis 'temp' sein
        
        # Test mit Config-Pfad
        config = {"cache_dir": str(tmp_path / "custom")}
        temp_dir = processor.init_temp_dir("test", config)
        assert temp_dir.exists()
        assert "custom" in str(temp_dir)
        assert "temp" in str(temp_dir)  # Auch hier sollte ein Unterverzeichnis 'temp' sein

    def test_get_cache_dir(self, processor: BaseProcessor, tmp_path: Any) -> None:
        """Test der Cache-Dir-Funktionalität."""
        # Test ohne Unterverzeichnis
        cache_dir = processor.get_cache_dir("test")
        assert cache_dir.exists()
        assert "test" in str(cache_dir)
        
        # Test mit Unterverzeichnis
        cache_dir = processor.get_cache_dir("test", subdirectory="processed")
        assert cache_dir.exists()
        assert "test" in str(cache_dir)
        assert "processed" in str(cache_dir)
        
        # Test mit eigener Konfiguration
        config = {"cache_dir": str(tmp_path / "custom_cache")}
        cache_dir = processor.get_cache_dir("test", config)
        assert cache_dir.exists()
        assert "custom_cache" in str(cache_dir)
        
        # Test mit Konfiguration und Unterverzeichnis
        cache_dir = processor.get_cache_dir("test", config, subdirectory="data")
        assert cache_dir.exists()
        assert "custom_cache" in str(cache_dir)
        assert "data" in str(cache_dir)

    def test_processor_response(self, response: BaseProcessorResponse) -> None:
        """Test der BaseProcessorResponse."""
        # Test der Initialisierung
        assert response.request.processor == "test"
        assert response.process.main_processor == "test"
        assert not response.process.sub_processors
        assert response.error is None
        
        # Test Parameter hinzufügen
        response.add_parameter("test_param", "value")
        assert response.request.parameters["test_param"] == "value"
        
        # Test Sub-Processor hinzufügen
        response.add_sub_processor("sub_test")
        assert "sub_test" in response.process.sub_processors
        
        # Test LLM-Info hinzufügen
        response.add_llm_info("gpt-4", "test", 100, 1.5)
        
        # Test Error setzen
        error = ErrorInfo(code="test", message="error")
        response.set_error(error)
        assert response.error == error
        
        # Test Completed setzen
        response.set_completed()
        assert response.process.completed is not None 