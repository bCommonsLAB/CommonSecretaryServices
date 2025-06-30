"""
Integration-Test für Video-Platzhalter-Ersetzung in Session-Templates.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from src.processors.session_processor import SessionProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.session import SessionInput


class TestSessionVideoIntegration:
    """Integration-Test für Video-Platzhalter in Session-Templates."""
    
    @pytest.fixture
    def session_processor(self):
        """Erstellt einen SessionProcessor für Tests."""
        resource_calculator = Mock(spec=ResourceCalculator)
        return SessionProcessor(resource_calculator, process_id="test-integration")
    
    def test_video_placeholder_in_session_template(self, session_processor):
        """Testet die Video-Platzhalter-Ersetzung in einem echten Session-Template."""
        
        # Simuliere Session-Template-Inhalt
        template_content = """---
tags: {{tags|Was sind die max. 10 wichtigsten Schlüsselwörter aus dem Text?}}
title: {{title|einen treffenden Titel der Session}}
---
# {{title|einen treffenden Titel der Session}}

> [! hinweis]-
> Der Inhalt dieser Seite ist durch Audio/Video-Transkribtion generiert.

Quelle: [{{url}}]({{url}})

{videoplayer}

## Zusammenfassung & Highlights:

{{summary|Bitte die Texte sinnvoll auswerten.}}

{slides}
"""
        
        # Test mit normaler Video-URL
        video_url = "https://example.com/session_video.mp4"
        result = session_processor._replace_video_placeholder(template_content, video_url)
        
        # Prüfe, dass das HTML5 video Element eingefügt wurde
        expected_video_tag = '<video src="https://example.com/session_video.mp4" controls></video>'
        assert expected_video_tag in result
        assert "{videoplayer}" not in result
        
        # Prüfe, dass andere Platzhalter unverändert bleiben
        assert "{{title|" in result
        assert "{{summary|" in result
        assert "{slides}" in result
    
    def test_vimeo_placeholder_in_session_template(self, session_processor):
        """Testet die Vimeo-Platzhalter-Ersetzung in einem Session-Template."""
        
        # Simuliere Session-Template-Inhalt
        template_content = """---
title: {{title|einen treffenden Titel der Session}}
---
# {{title|einen treffenden Titel der Session}}

{videoplayer}

## Zusammenfassung & Highlights:

{{summary|Bitte die Texte sinnvoll auswerten.}}
"""
        
        # Test mit Vimeo-URL
        video_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
        result = session_processor._replace_video_placeholder(template_content, video_url)
        
        # Prüfe, dass das iframe Element eingefügt wurde
        expected_iframe_tag = '<iframe src="https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
        assert expected_iframe_tag in result
        assert "{videoplayer}" not in result
    
    def test_video_url_placeholder_in_template(self, session_processor):
        """Testet die {{video_url}} Platzhalter-Ersetzung."""
        
        # Simuliere Template mit {{video_url}} Platzhalter
        template_content = """---
title: {{title}}
---
# {{title}}

{{video_url}}

## Zusammenfassung:

{{summary}}
"""
        
        # Test mit normaler Video-URL
        video_url = "https://video.fosdem.org/2025/session.mp4"
        result = session_processor._replace_video_placeholder(template_content, video_url)
        
        # Prüfe, dass das HTML5 video Element eingefügt wurde
        expected_video_tag = '<video src="https://video.fosdem.org/2025/session.mp4" controls></video>'
        assert expected_video_tag in result
        assert "{{video_url}}" not in result
    
    def test_no_video_in_template(self, session_processor):
        """Testet Template ohne Video-URL."""
        
        # Simuliere Template ohne Video
        template_content = """---
title: {{title}}
---
# {{title}}

{videoplayer}

## Zusammenfassung:

{{summary}}
"""
        
        # Test ohne Video-URL
        result = session_processor._replace_video_placeholder(template_content, None)
        
        # Prüfe, dass Platzhalter entfernt wurden
        assert "{videoplayer}" not in result
        assert "{{video_url}}" not in result
        
        # Prüfe, dass andere Platzhalter unverändert bleiben
        assert "{{title}}" in result
        assert "{{summary}}" in result
    
    def test_multiple_video_placeholders(self, session_processor):
        """Testet mehrere Video-Platzhalter im gleichen Template."""
        
        # Simuliere Template mit mehreren Video-Platzhaltern
        template_content = """---
title: {{title}}
---
# {{title}}

{videoplayer}

## Video Section
{{video_url}}

## Zusammenfassung:

{{summary}}
"""
        
        # Test mit Vimeo-URL
        video_url = "https://vimeo.com/1029641432"
        result = session_processor._replace_video_placeholder(template_content, video_url)
        
        # Prüfe, dass beide Platzhalter ersetzt wurden
        expected_iframe_tag = '<iframe src="https://vimeo.com/1029641432" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
        assert result.count(expected_iframe_tag) == 2
        assert "{videoplayer}" not in result
        assert "{{video_url}}" not in result
    
    def test_mixed_video_types(self, session_processor):
        """Testet verschiedene Video-Typen in verschiedenen Templates."""
        
        # Test-Cases mit verschiedenen Video-URLs
        test_cases = [
            {
                "url": "https://example.com/video.mp4",
                "expected_tag": '<video src="https://example.com/video.mp4" controls></video>',
                "description": "normales Video"
            },
            {
                "url": "https://player.vimeo.com/video/1029641432",
                "expected_tag": '<iframe src="https://player.vimeo.com/video/1029641432" width="640" height="360" frameborder="0" allowfullscreen></iframe>',
                "description": "Vimeo Player-URL"
            },
            {
                "url": "https://vimeo.com/1029641432",
                "expected_tag": '<iframe src="https://vimeo.com/1029641432" width="640" height="360" frameborder="0" allowfullscreen></iframe>',
                "description": "direkte Vimeo-URL"
            },
            {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "expected_tag": '<video src="https://www.youtube.com/watch?v=dQw4w9WgXcQ" controls></video>',
                "description": "YouTube-URL"
            }
        ]
        
        template_content = "# Test Session\n\n{videoplayer}\n\n## Summary\n\n{{summary}}"
        
        for test_case in test_cases:
            result = session_processor._replace_video_placeholder(template_content, test_case["url"])
            
            assert test_case["expected_tag"] in result, f"Fehler bei {test_case['description']}"
            assert "{videoplayer}" not in result, f"Platzhalter nicht ersetzt bei {test_case['description']}"


if __name__ == "__main__":
    pytest.main([__file__]) 