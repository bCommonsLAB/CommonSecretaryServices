"""
Test für die ZIP-Archiv-Funktion im SessionProcessor.
Überprüft die Erstellung und Struktur der ZIP-Archive.
"""

import pytest
import base64
import zipfile
import io
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, Any, List

from src.processors.session_processor import SessionProcessor
from src.core.models.session import SessionInput, SessionResponse
from src.core.resource_tracking import ResourceCalculator


class TestSessionArchive:
    """Test der ZIP-Archiv-Funktionalität"""
    
    @pytest.fixture
    def session_processor(self) -> SessionProcessor:
        """Erstellt einen SessionProcessor für Tests"""
        resource_calculator = ResourceCalculator()
        return SessionProcessor(resource_calculator=resource_calculator)
    
    @pytest.fixture
    def sample_session_input(self) -> SessionInput:
        """Erstellt Beispiel-Session-Input-Daten"""
        return SessionInput(
            event="FOSDEM 2025",
            session="Welcome to FOSDEM",
            url="https://fosdem.org/2025/schedule/event/welcome/",
            filename="welcome_fosdem.md",
            track="Main Track",
            attachments_url="https://fosdem.org/2025/slides.pdf",
            source_language="en",
            target_language="de",
            template="Session"
        )
    
    def test_create_session_archive_basic(self, session_processor: SessionProcessor, sample_session_input: SessionInput):
        """Test der grundlegenden ZIP-Archiv-Erstellung"""
        
        # Teste Daten
        markdown_content = """# Welcome to FOSDEM
        
## Slides
![[FOSDEM_2025/assets/welcome_fosdem/slide_01.png|300]]
![[FOSDEM_2025/assets/welcome_fosdem/slide_02.png|300]]
"""
        markdown_filename = "welcome_fosdem.md"
        attachment_paths = [
            "FOSDEM_2025/assets/welcome_fosdem/slide_01.png",
            "FOSDEM_2025/assets/welcome_fosdem/slide_02.png"
        ]
        
        # Mock für Dateisystem - simuliere existierende Bilder
        with patch.object(Path, 'exists', return_value=True):
            with patch('zipfile.ZipFile.write') as mock_write:
                with patch('zipfile.ZipFile.writestr') as mock_writestr:
                    
                    # Führe die ZIP-Erstellung aus
                    base64_zip, zip_filename = session_processor._create_session_archive(
                        markdown_content=markdown_content,
                        markdown_filename=markdown_filename,
                        attachment_paths=attachment_paths,
                        session_data=sample_session_input
                    )
                    
                    # Überprüfe Ergebnisse
                    assert base64_zip is not None
                    assert len(base64_zip) > 0
                    assert zip_filename == "Welcome_to_FOSDEM.zip"
                    
                    # Überprüfe, dass Markdown mit angepassten Pfaden geschrieben wurde
                    markdown_calls = [call for call in mock_writestr.call_args_list if call[0][0].endswith('.md')]
                    assert len(markdown_calls) >= 1  # Mindestens Markdown-Datei
                    
                    # Überprüfe, dass Bilder hinzugefügt wurden
                    assert mock_write.call_count == len(attachment_paths)
    
    def test_adjust_markdown_paths_for_archive(self, session_processor: SessionProcessor):
        """Test der Markdown-Pfad-Anpassung für ZIP-Archive"""
        
        # Original Markdown mit verschiedenen Pfad-Formaten
        original_markdown = """# Test Session
        
## Slides
![[FOSDEM_2025/assets/session/slide_01.png|300]]
![Slide 2](FOSDEM_2025/assets/session/slide_02.png)
<img src="FOSDEM_2025/assets/session/slide_03.png" alt="Slide 3">
"""
        
        attachment_paths = [
            "FOSDEM_2025/assets/session/slide_01.png",
            "FOSDEM_2025/assets/session/slide_02.png",
            "FOSDEM_2025/assets/session/slide_03.png"
        ]
        
        # Führe Pfad-Anpassung aus
        adjusted_markdown = session_processor._adjust_markdown_paths_for_archive(
            markdown_content=original_markdown,
            attachment_paths=attachment_paths
        )
        
        # Überprüfe, dass Pfade korrekt angepasst wurden
        assert "images/slide_01.png" in adjusted_markdown
        assert "images/slide_02.png" in adjusted_markdown
        assert "images/slide_03.png" in adjusted_markdown
        
        # Überprüfe, dass originale Pfade ersetzt wurden
        assert "FOSDEM_2025/assets/session/" not in adjusted_markdown
    
    def test_create_archive_readme(self, session_processor: SessionProcessor, sample_session_input: SessionInput):
        """Test der README-Erstellung für ZIP-Archive"""
        
        image_count = 5
        readme_content = session_processor._create_archive_readme(
            session_data=sample_session_input,
            image_count=image_count
        )
        
        # Überprüfe README-Inhalt
        assert "# Welcome to FOSDEM" in readme_content
        assert "FOSDEM 2025" in readme_content
        assert "Main Track" in readme_content
        assert f"{image_count} Anhang-Bildern" in readme_content
        assert "welcome_fosdem.md" in readme_content
        assert sample_session_input.url in readme_content
    
    def test_archive_creation_disabled(self, session_processor: SessionProcessor):
        """Test dass ZIP-Erstellung korrekt deaktiviert werden kann"""
        
        # Mock für process_session mit create_archive=False
        with patch.object(session_processor, '_fetch_session_page', return_value="Mock web text"):
            with patch.object(session_processor, '_process_video', return_value="Mock transcript"):
                with patch.object(session_processor, '_process_attachments', return_value=(["image1.png"], ["page text"])):
                    with patch.object(session_processor, '_generate_markdown', return_value=(Path("test.md"), "# Test", {})):
                        with patch.object(session_processor, '_create_session_archive') as mock_create_archive:
                            
                            # Importiere asyncio für den Test
                            import asyncio
                            
                            # Führe Session-Verarbeitung mit deaktivierter ZIP-Erstellung aus
                            asyncio.run(session_processor.process_session(
                                event="Test Event",
                                session="Test Session",
                                url="http://test.com",
                                filename="test.md",
                                track="Test Track",
                                attachments_url="http://test.com/slides.pdf",
                                create_archive=False  # ZIP-Erstellung deaktiviert
                            ))
                            
                            # Überprüfe, dass ZIP-Erstellung nicht aufgerufen wurde
                            mock_create_archive.assert_not_called()
    
    def test_base64_encoding_decoding(self, session_processor: SessionProcessor, sample_session_input: SessionInput):
        """Test dass Base64-Kodierung/Dekodierung korrekt funktioniert"""
        
        # Teste Daten
        test_content = "Test ZIP content"
        markdown_filename = "test.md"
        
        # Mock für ZIP-Erstellung
        with patch('zipfile.ZipFile') as mock_zipfile:
            # Erstelle Mock ZIP
            mock_zip_buffer = io.BytesIO()
            mock_zip_buffer.write(test_content.encode('utf-8'))
            mock_zip_buffer.seek(0)
            
            with patch('io.BytesIO', return_value=mock_zip_buffer):
                base64_zip, zip_filename = session_processor._create_session_archive(
                    markdown_content="# Test",
                    markdown_filename=markdown_filename,
                    attachment_paths=[],
                    session_data=sample_session_input
                )
                
                # Überprüfe, dass Base64-String erstellt wurde
                assert base64_zip is not None
                assert len(base64_zip) > 0
                
                # Überprüfe, dass Base64-Dekodierung funktioniert
                decoded_data = base64.b64decode(base64_zip)
                assert isinstance(decoded_data, bytes)
    
    @pytest.mark.asyncio
    async def test_full_session_with_archive(self, session_processor: SessionProcessor):
        """Integrations-Test der kompletten Session-Verarbeitung mit ZIP-Archiv"""
        
        # Mock alle externen Abhängigkeiten
        with patch.object(session_processor, '_fetch_session_page', return_value="Mock web text"):
            with patch.object(session_processor, '_process_video', return_value="Mock transcript"):
                with patch.object(session_processor, '_process_attachments', return_value=(["test_image.png"], ["page text"])):
                    with patch.object(session_processor, '_generate_markdown', return_value=(Path("test.md"), "# Test Markdown", {})):
                        with patch.object(session_processor, '_create_session_archive', return_value=("dGVzdA==", "test.zip")):
                            
                            # Führe komplette Session-Verarbeitung aus
                            result = await session_processor.process_session(
                                event="Test Event",
                                session="Test Session",
                                url="http://test.com",
                                filename="test.md",
                                track="Test Track",
                                attachments_url="http://test.com/slides.pdf",
                                create_archive=True
                            )
                            
                            # Überprüfe Response-Struktur
                            assert isinstance(result, SessionResponse)
                            
                            if result.data and result.data.output:
                                # Überprüfe, dass ZIP-Daten vorhanden sind
                                assert result.data.output.archive_data == "dGVzdA=="
                                assert result.data.output.archive_filename == "test.zip"
                            else:
                                pytest.fail("Session Response enthält keine Output-Daten")
    
    def test_error_handling_in_archive_creation(self, session_processor: SessionProcessor, sample_session_input: SessionInput):
        """Test der Fehlerbehandlung bei ZIP-Archiv-Erstellung"""
        
        # Simuliere Fehler bei ZIP-Erstellung
        with patch('zipfile.ZipFile', side_effect=Exception("ZIP creation failed")):
            
            # Überprüfe, dass Exception korrekt behandelt wird
            with pytest.raises(Exception):  # ProcessingError erwartet
                session_processor._create_session_archive(
                    markdown_content="# Test",
                    markdown_filename="test.md",
                    attachment_paths=["test_image.png"],
                    session_data=sample_session_input
                )


if __name__ == "__main__":
    pytest.main([__file__]) 