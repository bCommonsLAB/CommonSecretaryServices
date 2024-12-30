import pytest
from src.utils.audio_utils import AudioProcessor
from src.utils.transcription_utils import WhisperTranscriber
from pathlib import Path

@pytest.fixture
def sample_audio_data():
    test_file = Path(__file__).parent / "test_data" / "test_audio.mp3"
    if not test_file.exists():
        pytest.skip("Test-Audio-Datei nicht gefunden")
    return test_file.read_bytes()

class TestAudioProcessor:
    def test_split_audio(self, sample_audio_data):
        """Test der Audio-Splitting-Funktionalität."""
        segments = AudioProcessor.split_audio(sample_audio_data, segment_length_minutes=1)
        
        assert isinstance(segments, list)
        assert len(segments) > 0
        assert all(isinstance(segment, bytes) for segment in segments)

class TestWhisperTranscriber:
    @pytest.mark.integration  # Markiere als Integrationstest, da API-Zugriff erforderlich
    def test_transcribe_segment(self, sample_audio_data):
        """Test der Whisper-Transkription."""
        transcriber = WhisperTranscriber()
        
        result = transcriber.transcribe_segment(sample_audio_data)
        
        assert isinstance(result, str)
        assert len(result) > 0 