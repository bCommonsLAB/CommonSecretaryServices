"""
Tests für die Utility-Module.
"""

import pytest
from pathlib import Path
from typing import Dict, Any

from src.utils.audio_utils import AudioProcessor
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.transformer import TransformerResponse

@pytest.fixture
def sample_audio_data() -> bytes:
    test_file = Path(__file__).parent / "test_data" / "test_audio.mp3"
    if not test_file.exists():
        pytest.skip("Test-Audio-Datei nicht gefunden")
    return test_file.read_bytes()

@pytest.fixture
def whisper_config() -> Dict[str, Any]:
    return {
        "model": "whisper-1",
        "debug_dir": "tests/test_data/debug",
        "language": "de"
    }

class TestAudioProcessor:
    def test_split_audio(self, sample_audio_data: bytes) -> None:
        """Test der Audio-Splitting-Funktionalität."""
        segments = AudioProcessor.split_audio(sample_audio_data, segment_length_minutes=1)
        
        assert isinstance(segments, list)
        assert len(segments) > 0
        assert all(isinstance(segment, bytes) for segment in segments)

class TestWhisperTranscriber:
    @pytest.mark.integration
    def test_transform_text(self, whisper_config: Dict[str, Any]) -> None:
        """Test der Whisper-Transformation."""
        transcriber = WhisperTranscriber(whisper_config)
        
        result = transcriber.transform_by_template(
            text="Test text",
            template="Zusammenfassung: {{text}}",
            target_language="de",
            context={"language": "de"}
        )
        
        assert isinstance(result, TransformerResponse)
        assert result.data is not None
        assert isinstance(result.data.output.text, str)
        assert len(result.data.output.text) > 0 