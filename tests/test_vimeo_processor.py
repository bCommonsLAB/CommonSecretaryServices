"""
Test für Vimeo-Video-Verarbeitung.
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from src.processors.video_processor import VideoProcessor
from src.core.resource_tracking import ResourceCalculator


class TestVimeoProcessor:
    """Test-Klasse für Vimeo-Video-Verarbeitung."""
    
    @pytest.fixture
    def video_processor(self):
        """Erstellt einen VideoProcessor für Tests."""
        resource_calculator = Mock(spec=ResourceCalculator)
        return VideoProcessor(resource_calculator, process_id="test-process")
    
    def test_normalize_vimeo_player_url(self, video_processor):
        """Testet die Normalisierung von Vimeo-Player-URLs."""
        # Player-URL
        player_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
        normalized = video_processor._normalize_vimeo_url(player_url)
        assert normalized == "https://vimeo.com/1029641432"
        
        # Direkte Vimeo-URL sollte unverändert bleiben
        direct_url = "https://vimeo.com/1029641432"
        normalized = video_processor._normalize_vimeo_url(direct_url)
        assert normalized == direct_url
        
        # Andere URLs sollten unverändert bleiben
        other_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        normalized = video_processor._normalize_vimeo_url(other_url)
        assert normalized == other_url
    
    @patch('yt_dlp.YoutubeDL')
    def test_extract_vimeo_info(self, mock_ydl, video_processor):
        """Testet die Extraktion von Vimeo-Video-Informationen."""
        # Mock für yt-dlp
        mock_instance = Mock()
        mock_instance.extract_info.return_value = {
            'id': '1029641432',
            'title': 'Test Vimeo Video',
            'duration': 120
        }
        mock_ydl.return_value.__enter__.return_value = mock_instance
        
        # Test mit Player-URL
        player_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
        title, duration, video_id = video_processor._extract_video_info(player_url)
        
        assert title == "Test Vimeo Video"
        assert duration == 120
        assert video_id == "1029641432"
        
        # Prüfe, dass die normalisierte URL verwendet wurde
        mock_instance.extract_info.assert_called_with("https://vimeo.com/1029641432", download=False)
    
    @patch('yt_dlp.YoutubeDL')
    def test_vimeo_download_with_normalized_url(self, mock_ydl, video_processor):
        """Testet den Download mit normalisierter Vimeo-URL."""
        # Mock für Info-Extraktion
        mock_info_instance = Mock()
        mock_info_instance.extract_info.return_value = {
            'id': '1029641432',
            'title': 'Test Vimeo Video',
            'duration': 120
        }
        
        # Mock für Download
        mock_download_instance = Mock()
        
        def mock_enter():
            return mock_download_instance
        
        mock_ydl.return_value.__enter__.side_effect = [mock_info_instance, mock_download_instance]
        
        # Test mit Player-URL
        player_url = "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1"
        
        # Simuliere VideoSource
        from src.core.models.video import VideoSource
        video_source = VideoSource(url=player_url)
        
        # Teste die _extract_video_info Methode
        title, duration, video_id = video_processor._extract_video_info(player_url)
        
        assert title == "Test Vimeo Video"
        assert duration == 120
        assert video_id == "1029641432"
        
        # Prüfe, dass die normalisierte URL verwendet wurde
        mock_info_instance.extract_info.assert_called_with("https://vimeo.com/1029641432", download=False)


if __name__ == "__main__":
    pytest.main([__file__]) 