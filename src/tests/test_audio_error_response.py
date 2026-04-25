"""Tests fuer aussagekraeftige Audio-Fehlerantworten."""

import unittest

from src.processors.audio_processor import AudioProcessor


class TestAudioErrorResponse(unittest.TestCase):
    """Prueft den Fehlertext, der nach fehlgeschlagener Transkription persistiert wird."""

    def test_failure_transcription_keeps_original_error_message(self) -> None:
        error = RuntimeError("Fehler bei der OpenAI-Transkription: invalid_api_key")

        transcription = AudioProcessor.create_failure_transcription(error, "de")

        self.assertIn("Transkription fehlgeschlagen", transcription.text)
        self.assertIn("invalid_api_key", transcription.text)
        self.assertEqual(transcription.source_language, "de")

    def test_failure_transcription_masks_api_keys(self) -> None:
        error = RuntimeError("Incorrect API key provided: sk-secretValue123456")

        transcription = AudioProcessor.create_failure_transcription(error, "de")

        self.assertIn("sk-***", transcription.text)
        self.assertNotIn("sk-secretValue123456", transcription.text)


if __name__ == "__main__":
    unittest.main()
