"""Tests fuer den Transkriptions-Kontext.

Geprueft wird, dass jedes Modell genau die Kontextfelder bekommt, die es annimmt,
und dass verworfene Felder gemeldet statt stillschweigend geschluckt werden.
"""

import unittest

from src.api.routes.audio_routes import parse_list_field
from src.core.llm.transcription_context import (
    TranscriptionContext,
    build_context_params,
)


class TestKeywords(unittest.TestCase):
    """Begriffslisten kennen nur die neuen Modelle."""

    def test_keywords_reach_supporting_model(self) -> None:
        applied = build_context_params(
            "gpt-transcribe", TranscriptionContext(keywords=["Vinschgau", "Permakultur"])
        )

        self.assertEqual(applied.params["keywords"], ["Vinschgau", "Permakultur"])
        self.assertEqual(applied.dropped, [])

    def test_keywords_are_reported_when_model_cannot_use_them(self) -> None:
        applied = build_context_params("whisper-1", TranscriptionContext(keywords=["Vinschgau"]))

        self.assertNotIn("keywords", applied.params)
        self.assertEqual(len(applied.dropped), 1)
        self.assertIn("keywords", applied.dropped[0])

    def test_duplicates_and_blanks_are_removed(self) -> None:
        applied = build_context_params(
            "gpt-transcribe", TranscriptionContext(keywords=["Hof", " Hof ", "", "Alm"])
        )

        self.assertEqual(applied.params["keywords"], ["Hof", "Alm"])


class TestPrompt(unittest.TestCase):
    """Freitext-Kontext und Sprecher-Erkennung schliessen sich aus."""

    def test_prompt_reaches_ordinary_models(self) -> None:
        applied = build_context_params("gpt-transcribe", TranscriptionContext(prompt="Hofinterview"))

        self.assertEqual(applied.params["prompt"], "Hofinterview")

    def test_prompt_is_reported_for_diarize_model(self) -> None:
        applied = build_context_params(
            "gpt-4o-transcribe-diarize", TranscriptionContext(prompt="Hofinterview")
        )

        self.assertNotIn("prompt", applied.params)
        self.assertEqual(len(applied.dropped), 1)
        self.assertIn("prompt", applied.dropped[0])

    def test_blank_prompt_is_no_drop(self) -> None:
        applied = build_context_params(
            "gpt-4o-transcribe-diarize", TranscriptionContext(prompt="   ")
        )

        self.assertEqual(applied.dropped, [])


class TestLanguages(unittest.TestCase):
    """Die neuen Modelle nehmen eine Liste, die uebrigen eine einzelne Sprache."""

    def test_single_language_for_classic_models(self) -> None:
        applied = build_context_params("whisper-1", TranscriptionContext(language="de"))

        self.assertEqual(applied.params["language"], "de")
        self.assertNotIn("languages", applied.params)

    def test_list_for_new_models(self) -> None:
        applied = build_context_params(
            "gpt-transcribe", TranscriptionContext(languages=["de", "it"])
        )

        self.assertEqual(applied.params["languages"], ["de", "it"])
        self.assertNotIn("language", applied.params)

    def test_single_language_becomes_list_for_new_models(self) -> None:
        # Der Hinweis darf nicht verloren gehen, nur weil das Feld anders heisst.
        applied = build_context_params("gpt-transcribe", TranscriptionContext(language="de"))

        self.assertEqual(applied.params["languages"], ["de"])

    def test_auto_is_not_a_language_code(self) -> None:
        applied = build_context_params("whisper-1", TranscriptionContext(language="auto"))

        self.assertNotIn("language", applied.params)

    def test_language_list_is_reported_for_classic_models(self) -> None:
        applied = build_context_params(
            "whisper-1", TranscriptionContext(language="de", languages=["de", "it"])
        )

        self.assertEqual(applied.params["language"], "de")
        self.assertEqual(len(applied.dropped), 1)
        self.assertIn("languages", applied.dropped[0])


class TestContextObject(unittest.TestCase):
    """Der Kontext selbst."""

    def test_empty_context_is_recognised(self) -> None:
        self.assertTrue(TranscriptionContext().is_empty)
        self.assertFalse(TranscriptionContext(prompt="x").is_empty)

    def test_to_dict_is_stable_for_cache_keys(self) -> None:
        context = TranscriptionContext(language="de", prompt="Hof", keywords=["Alm"])

        self.assertEqual(
            context.to_dict(),
            {"language": "de", "languages": [], "prompt": "Hof", "keywords": ["Alm"]},
        )


class TestListFieldParsing(unittest.TestCase):
    """Formularfelder kommen als JSON-Liste oder kommagetrennt."""

    def test_comma_separated(self) -> None:
        self.assertEqual(parse_list_field("Vinschgau, Permakultur"), ["Vinschgau", "Permakultur"])

    def test_json_list(self) -> None:
        self.assertEqual(parse_list_field('["Vinschgau", "Alm"]'), ["Vinschgau", "Alm"])

    def test_empty_input(self) -> None:
        self.assertEqual(parse_list_field(""), [])
        self.assertEqual(parse_list_field(None), [])

    def test_broken_json_falls_back_to_comma_reading(self) -> None:
        # Unlesbares JSON wird nicht zu einem einzigen sinnlosen Begriff.
        self.assertEqual(parse_list_field('["Alm", '), ['["Alm"'])


if __name__ == "__main__":
    unittest.main()
