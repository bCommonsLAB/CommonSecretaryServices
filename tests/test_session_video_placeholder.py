"""
Test für Video-Platzhalter-Ersetzung im SessionProcessor.
"""

import pytest
from unittest.mock import Mock

from src.processors.session_processor import SessionProcessor
from src.core.resource_tracking import ResourceCalculator


class TestSessionVideoPlaceholder:
    """Test-Klasse für Video-Platzhalter-Ersetzung."""
    
    @pytest.fixture
    def session_processor(self):
        """Erstellt einen SessionProcessor für Tests."""
        resource_calculator = Mock(spec=ResourceCalculator)
        return SessionProcessor(resource_calculator, process_id="test-process")
    
    def test_replace_normal_video_url(self, session_processor):
        """Testet die Ersetzung einer normalen Video-URL."""
        # Test-Markdown mit {videoplayer} Platzhalter
        markdown_content = """
# Test Session

{videoplayer}

## Zusammenfassung
Test content.
"""
        
        video_url = "https://example.com/video.mp4"
        
        # Platzhalter ersetzen
        result = session_processor._replace_video_placeholder(markdown_content, video_url)
        
        # Prüfe, dass das HTML5 video Element eingefügt wurde
        expected_video_tag = '<video src="https://example.com/video.mp4" controls></video>'
        assert expected_video_tag in result
        assert "{videoplayer}" not in result
    
    def test_replace_vimeo_video_url(self, session_processor):
        """Testet die Ersetzung einer Vimeo-Video-URL."""
        # Test-Markdown mit {videoplayer} Platzhalter
        markdown_content = """
# Test Session

{videoplayer}

## Zusammenfassung
Test content.
"""
        
        video_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
        
        # Platzhalter ersetzen
        result = session_processor._replace_video_placeholder(markdown_content, video_url)
        
        # Prüfe, dass das iframe Element eingefügt wurde
        expected_iframe_tag = '<iframe src="https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
        assert expected_iframe_tag in result
        assert "{videoplayer}" not in result
    
    def test_replace_vimeo_direct_url(self, session_processor):
        """Testet die Ersetzung einer direkten Vimeo-URL."""
        markdown_content = """
# Test Session

{videoplayer}

## Zusammenfassung
Test content.
"""
        
        video_url = "https://vimeo.com/1029641432"
        
        # Platzhalter ersetzen
        result = session_processor._replace_video_placeholder(markdown_content, video_url)
        
        # Prüfe, dass das iframe Element eingefügt wurde
        expected_iframe_tag = '<iframe src="https://vimeo.com/1029641432" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
        assert expected_iframe_tag in result
        assert "{videoplayer}" not in result
    
    def test_replace_video_url_placeholder(self, session_processor):
        """Testet die Ersetzung des {{video_url}} Platzhalters."""
        markdown_content = """
# Test Session

{{video_url}}

## Zusammenfassung
Test content.
"""
        
        video_url = "https://example.com/video.mp4"
        
        # Platzhalter ersetzen
        result = session_processor._replace_video_placeholder(markdown_content, video_url)
        
        # Prüfe, dass das HTML5 video Element eingefügt wurde
        expected_video_tag = '<video src="https://example.com/video.mp4" controls></video>'
        assert expected_video_tag in result
        assert "{{video_url}}" not in result
    
    def test_replace_no_video_url(self, session_processor):
        """Testet die Ersetzung ohne Video-URL."""
        markdown_content = """
# Test Session

{videoplayer}

## Zusammenfassung
Test content.
"""
        
        # Platzhalter ersetzen (keine Video-URL)
        result = session_processor._replace_video_placeholder(markdown_content, None)
        
        # Prüfe, dass die Platzhalter entfernt wurden
        assert "{videoplayer}" not in result
        assert "{{video_url}}" not in result
    
    def test_replace_multiple_placeholders(self, session_processor):
        """Testet die Ersetzung mehrerer Platzhalter."""
        markdown_content = """
# Test Session

{videoplayer}

## Video Section
{{video_url}}

## Zusammenfassung
Test content.
"""
        
        video_url = "https://player.vimeo.com/video/1029641432"
        
        # Platzhalter ersetzen
        result = session_processor._replace_video_placeholder(markdown_content, video_url)
        
        # Prüfe, dass beide Platzhalter ersetzt wurden
        expected_iframe_tag = '<iframe src="https://player.vimeo.com/video/1029641432" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
        assert result.count(expected_iframe_tag) == 2
        assert "{videoplayer}" not in result
        assert "{{video_url}}" not in result
    
    def test_replace_youtube_url(self, session_processor):
        """Testet die Ersetzung einer YouTube-URL (sollte als normales Video behandelt werden)."""
        markdown_content = """
# Test Session

{videoplayer}

## Zusammenfassung
Test content.
"""
        
        video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        
        # Platzhalter ersetzen
        result = session_processor._replace_video_placeholder(markdown_content, video_url)
        
        # Prüfe, dass das HTML5 video Element eingefügt wurde (nicht iframe)
        expected_video_tag = '<video src="https://www.youtube.com/watch?v=dQw4w9WgXcQ" controls></video>'
        assert expected_video_tag in result
        assert "iframe" not in result
        assert "{videoplayer}" not in result


if __name__ == "__main__":
    pytest.main([__file__]) 