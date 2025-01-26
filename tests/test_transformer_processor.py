"""Tests für den TransformerProcessor."""
import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from src.processors.transformer_processor import TransformerProcessor
from src.utils.types import TransformerResponse, RequestInfo, ProcessInfo, LLModel, TranslationResult
from src.core.resource_tracking import ResourceCalculator

@pytest.fixture
def resource_calculator():
    """Mock für den ResourceCalculator."""
    return Mock(spec=ResourceCalculator)

@pytest.fixture
def transformer_processor(resource_calculator):
    """Fixture für den TransformerProcessor."""
    processor = TransformerProcessor(resource_calculator=resource_calculator)
    return processor

def test_transform_basic_functionality(transformer_processor):
    """Test der grundlegenden Transformationsfunktionalität."""
    input_text = "Das ist ein Testtext."
    
    # Mock für WhisperTranscriber.translate_text
    with patch('src.utils.transcription_utils.WhisperTranscriber.translate_text') as mock_translate:
        # Mock-Ergebnis erstellen
        translation_result = TranslationResult(
            text="This is a test text.",
            source_language="de",
            target_language="en",
            llms=[LLModel(
                model="gpt-4",
                duration=1.5,
                tokens=10,
                timestamp=datetime.now().isoformat()
            )]
        )
        mock_translate.return_value = translation_result
        
        result = transformer_processor.transform(
            source_text=input_text,
            source_language="de",
            target_language="en"
        )
        
        # Überprüfungen
        assert result.data["output"]["text"] == "This is a test text."
        assert result.data["output"]["language"] == "en"
        assert result.data["input"]["language"] == "de"
        
        # Überprüfe, dass translate_text aufgerufen wurde
        mock_translate.assert_called_once()

def test_transform_with_template(transformer_processor):
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
        translation_result = TranslationResult(
            text="Meeting with Peter on March 12, 2024",
            source_language="de",
            target_language="en",
            llms=[LLModel(
                model="gpt-4",
                duration=1.0,
                tokens=15,
                timestamp=datetime.now().isoformat()
            )]
        )
        
        template_text = "Meeting Summary:\nDate: March 12, 2024\nType: Customer Meeting\nLocation: Online"
        
        mock_translate.return_value = translation_result
        mock_template.return_value = template_text
        
        result = transformer_processor.transformByTemplate(
            source_text=input_text,
            source_language="de",
            target_language="en",
            template="meeting",
            context=context
        )
        
        # Überprüfungen
        assert result.data["output"]["text"] == template_text
        assert result.data["input"]["template"] == "meeting"
        assert result.data["input"]["context"] == context
        
        # Überprüfe Methodenaufrufe
        mock_translate.assert_called_once()
        mock_template.assert_called_once()

def test_transform_specific_error_handling(transformer_processor):
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
        translation_result = TranslationResult(
            text="Test",
            source_language="de",
            target_language="en",
            llms=[LLModel(
                model="gpt-4",
                duration=0.5,
                tokens=5,
                timestamp=datetime.now().isoformat()
            )]
        )
        mock_translate.return_value = translation_result
        
        result = transformer_processor.transformByTemplate(
            source_text="Test",
            source_language="de",
            target_language="en",
            template="nicht_existierendes_template"
        )
        assert result.error is not None
        assert "Template nicht gefunden" in result.error.message 