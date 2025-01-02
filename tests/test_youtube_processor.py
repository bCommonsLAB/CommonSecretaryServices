import pytest
from unittest.mock import patch, MagicMock
from processors.youtube_processor import YoutubeProcessor
from core.exceptions import ProcessingError
from utils.logger import ProcessingLogger

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
def mock_yt_dlp():
    """Erstellt einen Mock für die YouTube-DL Bibliothek.
    
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
    async def test_process_video_too_long(self, mock_calculator, mock_yt_dlp):
        """Testet die Fehlerbehandlung bei zu langen Videos.
        
        Dieser Test überprüft, ob der YoutubeProcessor korrekt reagiert,
        wenn ein Video die maximale Länge überschreitet.
        
        Testschritte:
        1. Erstellen eines YoutubeProcessors mit max_duration=3600 (1 Stunde)
        2. Simulieren eines 4000 Sekunden langen Videos (via mock_yt_dlp)
        3. Überprüfen, ob eine ProcessingError Exception mit korrekter
           Fehlermeldung ausgelöst wird
        
        Args:
            mock_calculator: Mock des ResourceCalculators
            mock_yt_dlp: Mock der YouTube-DL Bibliothek
        
        Assertions:
            - Prüft, ob ProcessingError mit "Video zu lang" ausgelöst wird
        """
        processor = YoutubeProcessor(
            resource_calculator=mock_calculator,
            max_file_size=1000000,
            max_duration=3600
        )

        with pytest.raises(ProcessingError) as exc_info:
            await processor.process("https://youtube.com/test")

        assert "Video zu lang" in str(exc_info.value) 

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_video_processing(self, mock_calculator):
        """Integrationstest: Verarbeitet ein echtes YouTube-Video."""
        logger = ProcessingLogger(process_id="test_real_video_processing")
        
        processor = YoutubeProcessor(
            resource_calculator=mock_calculator,
            max_file_size=10 * 1024 * 1024,  # 10MB
            max_duration=60 * 30  # 30 Minuten
        )

        # "Me at the zoo" - erstes YouTube Video (21 Sekunden)
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