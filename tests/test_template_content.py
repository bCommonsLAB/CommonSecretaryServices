"""
Test für die neue template_content Funktionalität.
Testet sowohl Datei-basierte als auch inline Template-Transformationen.
"""
import pytest
import json
from typing import Dict, Any

from src.processors.transformer_processor import TransformerProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.transformer import TransformerResponse, TransformerData
from src.core.models.enums import ProcessingStatus


class TestTemplateContent:
    """Test-Klasse für template_content Funktionalität."""
    
    @pytest.fixture
    def transformer_processor(self) -> TransformerProcessor:
        """Erstellt einen TransformerProcessor für Tests."""
        resource_calculator = ResourceCalculator()
        return TransformerProcessor(resource_calculator, process_id="test-template-content")
    
    def test_transform_with_template_content(self, transformer_processor: TransformerProcessor) -> None:
        """Test der Transformation mit direktem Template-Inhalt."""
        # Arrange
        test_text = "Max Mustermann ist 30 Jahre alt und wohnt in Berlin."
        template_content = """
---
title: {{title|Titel der Person}}
age: {{age|Alter der Person}}
city: {{city|Wohnort der Person}}
---

# {{title}}

**Alter:** {{age}}
**Wohnort:** {{city}}

## Zusammenfassung
{{summary|Kurze Zusammenfassung der Person}}
"""
        
        # Act
        result = transformer_processor.transformByTemplate(
            text=test_text,
            source_language="de",
            target_language="de",
            template_content=template_content
        )
        
        # Assert
        assert isinstance(result, TransformerResponse)
        assert result.status == ProcessingStatus.SUCCESS
        assert result.error is None
        assert isinstance(result.data, TransformerData)
        assert result.data.output.structured_data is not None
        
        # Prüfe die erwarteten Template-Felder
        structured_data = result.data.output.structured_data
        assert "title" in structured_data
        assert "age" in structured_data
        assert "city" in structured_data
        assert "summary" in structured_data
        
        # Prüfe, dass der transformierte Text vorhanden ist
        assert result.data.output.text is not None
        assert len(result.data.output.text) > 0
        
        # Prüfe, dass der Titel im Text ersetzt wurde
        assert "Max Mustermann" in result.data.output.text or "30" in result.data.output.text
        
        # Prüfe LLM-Tracking
        assert result.process.llm_info is not None
        assert len(result.process.llm_info.requests) > 0
    
    def test_transform_with_template_file(self, transformer_processor: TransformerProcessor) -> None:
        """Test der Transformation mit Template-Datei (bestehende Funktionalität)."""
        # Arrange
        test_text = "Max Mustermann ist 30 Jahre alt und wohnt in Berlin."
        template = "Gedanken"  # Verwendet das bestehende Gedanken.md Template
        
        # Act
        result = transformer_processor.transformByTemplate(
            text=test_text,
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
        
        # Prüfe die erwarteten Template-Felder (Gedanken Template)
        structured_data = result.data.output.structured_data
        assert "title" in structured_data
        assert "summary" in structured_data
        assert "tags" in structured_data
        assert "personen" in structured_data
    
    def test_error_both_template_and_content(self, transformer_processor: TransformerProcessor) -> None:
        """Test, dass ein Fehler auftritt, wenn beide Parameter angegeben werden."""
        # Arrange
        test_text = "Test Text"
        template = "Gedanken"
        template_content = "{{title|Titel}}"
        
        # Act
        result = transformer_processor.transformByTemplate(
            text=test_text,
            source_language="de",
            target_language="de",
            template=template,
            template_content=template_content
        )
        
        # Assert
        assert isinstance(result, TransformerResponse)
        assert result.status == ProcessingStatus.ERROR
        assert result.error is not None
        assert "Nur entweder template oder template_content" in result.error.message
    
    def test_error_no_template_or_content(self, transformer_processor: TransformerProcessor) -> None:
        """Test, dass ein Fehler auftritt, wenn kein Template angegeben wird."""
        # Arrange
        test_text = "Test Text"
        
        # Act
        result = transformer_processor.transformByTemplate(
            text=test_text,
            source_language="de",
            target_language="de"
        )
        
        # Assert
        assert isinstance(result, TransformerResponse)
        assert result.status == ProcessingStatus.ERROR
        assert result.error is not None
        assert "Entweder template oder template_content" in result.error.message
    
    def test_url_transform_with_template_content(self, transformer_processor: TransformerProcessor) -> None:
        """Test der URL-Transformation mit direktem Template-Inhalt."""
        # Arrange
        test_url = "https://httpbin.org/html"  # Einfache Test-URL
        template_content = """
---
title: {{title|Titel der Webseite}}
content: {{content|Inhalt der Webseite}}
---

# {{title}}

{{content}}
"""
        
        # Act
        result = transformer_processor.transformByUrl(
            url=test_url,
            source_language="de",
            target_language="de",
            template_content=template_content
        )
        
        # Assert
        assert isinstance(result, TransformerResponse)
        assert result.status == ProcessingStatus.SUCCESS
        assert result.error is None
        assert isinstance(result.data, TransformerData)
        assert result.data.output.structured_data is not None
        
        # Prüfe die erwarteten Template-Felder
        structured_data = result.data.output.structured_data
        assert "title" in structured_data
        assert "content" in structured_data
        
        # Prüfe, dass der transformierte Text vorhanden ist
        assert result.data.output.text is not None
        assert len(result.data.output.text) > 0


if __name__ == "__main__":
    # Einfacher Test für die Kommandozeile
    resource_calculator = ResourceCalculator()
    processor = TransformerProcessor(resource_calculator, process_id="cli-test")
    
    test_text = "Max Mustermann ist 30 Jahre alt und wohnt in Berlin."
    template_content = """
---
title: {{title|Titel der Person}}
age: {{age|Alter der Person}}
city: {{city|Wohnort der Person}}
---

# {{title}}

**Alter:** {{age}}
**Wohnort:** {{city}}

## Zusammenfassung
{{summary|Kurze Zusammenfassung der Person}}
"""
    
    print("Teste Template-Transformation mit direktem Template-Inhalt...")
    result = processor.transformByTemplate(
        text=test_text,
        source_language="de",
        target_language="de",
        template_content=template_content
    )
    
    if result.status == ProcessingStatus.SUCCESS:
        print("✅ Test erfolgreich!")
        print(f"Strukturierte Daten: {json.dumps(result.data.output.structured_data, indent=2, ensure_ascii=False)}")
        print(f"Transformierter Text: {result.data.output.text[:200]}...")
    else:
        print(f"❌ Test fehlgeschlagen: {result.error.message}") 