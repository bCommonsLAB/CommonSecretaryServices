"""Tests für den TransformerProcessor."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from src.processors.transformer_processor import TransformerProcessor
from src.core.models.transformer import TransformerResponse, TransformerInput, TransformerOutput, TransformerData
from src.core.models.base import RequestInfo, ProcessInfo
from src.core.models.enums import ProcessorType, OutputFormat
from src.core.resource_tracking import ResourceCalculator

@pytest.fixture
def resource_calculator() -> ResourceCalculator:
    """Mock für den ResourceCalculator."""
    return Mock(spec=ResourceCalculator)

@pytest.fixture
def transformer_processor(resource_calculator: ResourceCalculator) -> TransformerProcessor:
    """Fixture für den TransformerProcessor."""
    processor = TransformerProcessor(resource_calculator=resource_calculator)
    return processor

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

def test_transform_with_template(transformer_processor: TransformerProcessor):
    """Test der Template-basierten Transformation."""
    input_text = "Meeting mit Peter am 12.03.2024"
    context = {
        "meeting_type": "Kundentermin",
        "location": "online"
    }
    
    # Mock für translate_text und transform_by_template
    with patch('src.utils.transcription_utils.WhisperTranscriber.translate_text') as mock_translate, \
         patch('src.utils.transcription_utils.WhisperTranscriber.transform_by_template') as mock_template:
        
        # Mock-Ergebnisse erstellen
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
                    text="Meeting Summary:\nDate: March 12, 2024\nType: Customer Meeting\nLocation: Online",
                    language="en",
                    format=OutputFormat.MARKDOWN
                )
            )
        )
        
        mock_translate.return_value = response
        mock_template.return_value = response
        
        result = transformer_processor.transformByTemplate(
            source_text=input_text,
            source_language="de",
            target_language="en",
            template="meeting",
            context=context
        )
        
        # Überprüfungen
        assert result.data.output.text == "Meeting Summary:\nDate: March 12, 2024\nType: Customer Meeting\nLocation: Online"
        assert result.data.input.text == input_text
        assert result.data.input.language == "de"
        
        # Überprüfe Methodenaufrufe
        mock_translate.assert_called_once()
        mock_template.assert_called_once()

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