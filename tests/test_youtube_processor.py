import pytest
from unittest.mock import patch, MagicMock
from processors.youtube_processor import YoutubeProcessor
from core.exceptions import ProcessingError
from utils.logger import ProcessingLogger
from core.config import Config

@pytest.fixture
def mock_calculator():
    """Erstellt einen Mock für den ResourceCalculator.
    
    Dieser Mock simuliert die Berechnung von Ressourcen mit festen Rückgabewerten:
    - compute_units: 1.0
    - storage_units: 1.0
    - total_units: 2.0
    
    Returns:
        MagicMock: Ein vorkonfigurierter Mock des ResourceCalculators
    """
    calculator = MagicMock()
    calculator.calculate_compute_units.return_value = 1.0
    calculator.calculate_storage_units.return_value = 1.0
    calculator.calculate_total_units.return_value = 2.0
    return calculator

@pytest.fixture
def mock_config():
    """Erstellt einen Mock für die Config-Klasse.
    
    Dieser Mock simuliert die Konfiguration mit Test-Werten:
    - max_file_size: 1000000 (Bytes)
    - max_duration: 3600 (Sekunden)
    
    Returns:
        MagicMock: Ein vorkonfigurierter Mock der Config-Klasse
    """
    with patch('src.core.config.Config', autospec=True) as mock_config:
        mock_instance = MagicMock()
        mock_instance.get.return_value = {
            'max_file_size': 1000000,
            'max_duration': 3600,
            'temp_dir': "temp-processing/video",
            'audio_cache_dir': "temp-processing/youtube-audio",
            'ydl_opts': {}
        }
        mock_config.return_value = mock_instance
        yield mock_config

@pytest.fixture
def mock_yt_dlp():
    """Erstellt einen Mock für die Youtube-DL Bibliothek.
    
    Dieser Mock simuliert:
    1. Das Kontextmanager-Verhalten von YoutubeDL
    2. Die extract_info Methode mit einem Test-Video von 4000 Sekunden Länge
    
    Die simulierten Video-Informationen sind:
    - title: 'Test Video'
    - duration: 4000 (Sekunden)
    - filesize: 1000000 (Bytes)
    
    Returns:
        MagicMock: Ein vorkonfigurierter Mock der YoutubeDL-Klasse
    """
    with patch('yt_dlp.YoutubeDL', autospec=True) as mock_ydl_constructor:
        # Erstelle eine MagicMock-Instanz
        mock_instance = MagicMock()
        
        # Rückgabedaten für extract_info
        mock_info = {
            'title': 'Test Video',
            'duration': 4000,  # Überschreitet bewusst max_duration für den Test
            'filesize': 1000000
        }
        mock_instance.extract_info.return_value = mock_info

        # Kontextmanager-Verhalten simulieren
        mock_ydl_constructor.return_value.__enter__.return_value = mock_instance
        mock_ydl_constructor.return_value.__exit__.return_value = None

        yield mock_ydl_constructor

class TestYoutubeProcessor:
    """Testsuite für den YoutubeProcessor.
    
    Diese Testsuite überprüft die Funktionalität des YoutubeProcessors,
    insbesondere die Verarbeitung von Videos und die Fehlerbehandlung.
    """
    
    @pytest.mark.asyncio
    async def test_process_video_too_long(self, mock_calculator, mock_yt_dlp, mock_config):
        """Testet die Fehlerbehandlung bei zu langen Videos.
        
        Dieser Test überprüft, ob der YoutubeProcessor korrekt reagiert,
        wenn ein Video die maximale Länge überschreitet.
        
        Testschritte:
        1. Erstellen eines YoutubeProcessors mit gemockter Konfiguration
        2. Simulieren eines 4000 Sekunden langen Videos (via mock_yt_dlp)
        3. Überprüfen, ob eine ProcessingError Exception mit korrekter
           Fehlermeldung ausgelöst wird
        
        Args:
            mock_calculator: Mock des ResourceCalculators
            mock_yt_dlp: Mock der Youtube-DL Bibliothek
            mock_config: Mock der Config-Klasse
        
        Assertions:
            - Prüft, ob ProcessingError mit "Video zu lang" ausgelöst wird
        """
        processor = YoutubeProcessor(resource_calculator=mock_calculator)

        with pytest.raises(ProcessingError) as exc_info:
            await processor.process("https://youtube.com/test")

        assert "Video zu lang" in str(exc_info.value)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_video_processing(self, mock_calculator):
        """Integrationstest: Verarbeitet ein echtes Youtube-Video."""
        processor = YoutubeProcessor(resource_calculator=mock_calculator)

        # "Me at the zoo" - erstes Youtube Video (21 Sekunden)
        #url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"

        # How to Build a WhatsApp AI Chatbot in Minutes Using Flowise - 19:45 Minuten
        url = "https://www.youtube.com/watch?v=91aW9YGr6lo&t=840s"
        try:
            result = await processor.process(url)
            print("result", result)
            # Log success
            logger.info("Test-Video erfolgreich verarbeitet",
                       title=result['title'],
                       duration=result['duration'],
                       audio_size=result['file_size'])
            
            # Grundlegende Überprüfungen
            assert "title" in result
            assert "duration" in result
            assert "text" in result
            assert len(result["text"]) > 0
            
            print("\nIntegrationstest Ergebnisse:")
            print(f"Titel: {result['title']}")
            print(f"Länge: {result['duration']} Sekunden")
            print(f"Audio-Größe: {result['file_size']} Bytes")
            
        except Exception as e:
            logger.error("Test-Video-Verarbeitung fehlgeschlagen",
                        error=e,
                        url=url)
            raise 