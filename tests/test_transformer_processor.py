"""Tests für den TransformerProcessor."""
import pytest
from datetime import datetime
from typing import Dict, Any
from unittest.mock import Mock, patch
from src.processors.transformer_processor import TransformerProcessor
from src.core.models.transformer import TransformerResponse, TransformerInput, TransformerOutput, TransformerData
from src.core.models.base import RequestInfo, ProcessInfo
from src.core.models.enums import ProcessorType, OutputFormat, ProcessingStatus
from src.core.resource_tracking import ResourceCalculator
from src.core.models.llm import LLMInfo, LLMRequest

@pytest.fixture
def resource_calculator() -> ResourceCalculator:
    """Mock für den ResourceCalculator."""
    return Mock(spec=ResourceCalculator)

@pytest.fixture
def transformer_processor(resource_calculator: ResourceCalculator, parent_process_info: ProcessInfo) -> TransformerProcessor:
    """Fixture für den TransformerProcessor."""
    processor = TransformerProcessor(
        resource_calculator=resource_calculator, 
        process_id="test_transformer_processor"
    )
    return processor

def test_transform_basic(transformer_processor: TransformerProcessor) -> None:
    """Test der grundlegenden Transformation ohne Template."""
    # Arrange
    source_text = "Hello World"
    source_language = "en"
    target_language = "de"
    
    # Act
    result = transformer_processor.transform(
        source_text=source_text,
        source_language=source_language,
        target_language=target_language
    )
    
    # Assert
    assert isinstance(result, TransformerResponse)
    assert result.status == ProcessingStatus.SUCCESS
    assert result.error is None
    assert isinstance(result.data, TransformerData)
    assert result.data.input.text == source_text
    assert result.data.input.language == source_language
    assert result.data.output.language == target_language
    assert result.process.llm_info is not None
    assert len(result.process.llm_info.requests) > 0

def test_transform_with_template(transformer_processor: TransformerProcessor) -> None:
    """Test der Template-basierten Transformation mit dem Gedanken.md Template."""
    # Arrange
    source_text = """
    Heute habe ich mit Peter und Maria über KI gesprochen.
    Das Gespräch fand am 2024-02-17 in Berlin statt.
    Wir diskutierten über maschinelles Lernen und neuronale Netze.
    """
    template = "Gedanken"  # Verwendet das Gedanken.md Template
    
    # Act
    result = transformer_processor.transformByTemplate(
        source_text=source_text,
        source_language="de",
        target_language="de",
        template=template
    )
    
    # Assert
    assert isinstance(result, TransformerResponse)
    assert result.status == ProcessingStatus.SUCCESS
    assert result.error is None
    assert isinstance(result.data, TransformerData)
    assert result.data.output.structured_data is not None
    
    # Prüfe die erwarteten Template-Felder
    structured_data = result.data.output.structured_data
    assert "tags" in structured_data
    assert "personen" in structured_data
    assert "upload_date" in structured_data
    assert "ort" in structured_data
    assert "title" in structured_data
    assert "summary" in structured_data
    assert "messages" in structured_data
    
    # Prüfe spezifische Werte
    assert "Peter" in structured_data["personen"]
    assert "Maria" in structured_data["personen"]
    assert structured_data["upload_date"] == "2024-02-17"
    assert structured_data["ort"] == "Berlin"
    assert "KI" in structured_data["tags"].lower()
    
    assert result.process.llm_info is not None
    assert len(result.process.llm_info.requests) > 0

def test_transform_error_handling(transformer_processor: TransformerProcessor) -> None:
    """Test der Fehlerbehandlung."""
    # Arrange
    invalid_text = ""
    
    # Act
    result = transformer_processor.transform(
        source_text=invalid_text,
        source_language="en",
        target_language="de"
    )
    
    # Assert
    assert isinstance(result, TransformerResponse)
    assert result.status == ProcessingStatus.ERROR
    assert result.error is not None
    assert result.error.code == "ValueError"

def test_llm_tracking(transformer_processor: TransformerProcessor) -> None:
    """Test des LLM-Trackings."""
    # Arrange
    source_text = "Hello World"
    
    # Act
    result = transformer_processor.transform(
        source_text=source_text,
        source_language="en",
        target_language="de"
    )
    
    # Assert
    assert result.process.llm_info is not None
    assert isinstance(result.process.llm_info, LLMInfo)
    assert result.process.llm_info.model == transformer_processor.model
    assert result.process.llm_info.requests_count > 0
    assert result.process.llm_info.total_tokens > 0
    assert result.process.llm_info.total_duration > 0
    
    # Prüfe Request-Details
    first_request = result.process.llm_info.requests[0]
    assert isinstance(first_request, LLMRequest)
    assert first_request.model == transformer_processor.model
    assert first_request.purpose == "translation"
    assert first_request.tokens > 0
    assert first_request.duration > 0

def test_transform_basic_functionality(transformer_processor: TransformerProcessor):
    """Test der grundlegenden Transformationsfunktionalität."""
    input_text = "Das ist ein Testtext."
    
    # Mock für WhisperTranscriber.translate_text
    with patch('src.utils.transcription_utils.WhisperTranscriber.translate_text') as mock_translate:
        # Mock-Ergebnis erstellen
        now = datetime.now()
        response = TransformerResponse.create(
            request=RequestInfo(
                processor=ProcessorType.TRANSFORMER.value,
                timestamp=now.isoformat()
            ),
            process=ProcessInfo(
                id="transform_" + now.strftime("%Y%m%d_%H%M%S"),
                main_processor=ProcessorType.TRANSFORMER.value,
                started=now.isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text=input_text,
                    language="de",
                    format=OutputFormat.MARKDOWN
                ),
                output=TransformerOutput(
                    text="This is a test text.",
                    language="en",
                    format=OutputFormat.MARKDOWN
                )
            )
        )
        mock_translate.return_value = response
        
        result = transformer_processor.transform(
            source_text=input_text,
            source_language="de",
            target_language="en"
        )
        
        # Überprüfungen
        assert result.data.output.text == "This is a test text."
        assert result.data.output.language == "en"
        assert result.data.input.language == "de"
        
        # Überprüfe, dass translate_text aufgerufen wurde
        mock_translate.assert_called_once()

def test_transform_specific_error_handling(transformer_processor: TransformerProcessor):
    """Test der transformer-spezifischen Fehlerbehandlung."""
    # Test: Fehler bei der Übersetzung
    with patch('src.utils.transcription_utils.WhisperTranscriber.translate_text', 
              side_effect=Exception("Übersetzungsfehler")):
        result = transformer_processor.transform(
            source_text="Test",
            source_language="de",
            target_language="en"
        )
        assert result.error is not None
        assert "Übersetzungsfehler" in result.error.message
        
    # Test: Fehler bei der Template-Transformation
    with patch('src.utils.transcription_utils.WhisperTranscriber.translate_text') as mock_translate, \
         patch('src.utils.transcription_utils.WhisperTranscriber.transform_by_template',
               side_effect=Exception("Template nicht gefunden")):
        
        # Mock für erfolgreiche Übersetzung
        now = datetime.now()
        response = TransformerResponse.create(
            request=RequestInfo(
                processor=ProcessorType.TRANSFORMER.value,
                timestamp=now.isoformat()
            ),
            process=ProcessInfo(
                id="transform_" + now.strftime("%Y%m%d_%H%M%S"),
                main_processor=ProcessorType.TRANSFORMER.value,
                started=now.isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text="Test",
                    language="de",
                    format=OutputFormat.MARKDOWN
                ),
                output=TransformerOutput(
                    text="Test",
                    language="en",
                    format=OutputFormat.MARKDOWN
                )
            )
        )
        mock_translate.return_value = response
        
        result = transformer_processor.transformByTemplate(
            source_text="Test",
            source_language="de",
            target_language="en",
            template="nicht_existierendes_template"
        )
        assert result.error is not None
        assert "Template nicht gefunden" in result.error.message 