"""Tests fuer die Vorbelegung der LLM-Konfigurationsmaske.

Die Maske erzeugt ihre Zeilen dynamisch aus dem ``UseCase``-Enum, Beschriftung und
Vorbelegung stehen aber in zwei Tabellen. Fehlt dort ein Eintrag, zeigt die Zeile den
ersten Provider der Liste und eine leere Modellliste — das sieht nach einem Fehler
aus, ist aber nur "noch nichts zugeordnet". Genau so ist ``live_transcription`` nach
seiner Einfuehrung durchgerutscht.
"""

import unittest

from src.core.llm.use_cases import UseCase
from src.dashboard.routes.llm_config_routes import USE_CASE_DEFAULTS, USE_CASE_LABELS


class TestVollstaendigkeit(unittest.TestCase):
    """Jeder Use-Case aus dem Enum braucht Beschriftung und Vorbelegung."""

    def test_every_use_case_has_a_label(self) -> None:
        fehlend = [uc.value for uc in UseCase if uc.value not in USE_CASE_LABELS]

        self.assertEqual(fehlend, [], f"Ohne Beschriftung in der Maske: {fehlend}")

    def test_every_use_case_has_a_default(self) -> None:
        fehlend = [uc.value for uc in UseCase if uc.value not in USE_CASE_DEFAULTS]

        self.assertEqual(fehlend, [], f"Ohne Vorbelegung in der Maske: {fehlend}")

    def test_defaults_name_provider_and_model(self) -> None:
        for use_case, default in USE_CASE_DEFAULTS.items():
            with self.subTest(use_case=use_case):
                self.assertTrue(default.get("provider"))
                self.assertTrue(default.get("model"))


class TestLiveTranscription(unittest.TestCase):
    """Live-Transkription bietet nur OpenAI an — die Vorbelegung muss das treffen."""

    def test_default_provider_is_openai(self) -> None:
        self.assertEqual(USE_CASE_DEFAULTS["live_transcription"]["provider"], "openai")

    def test_default_model_is_realtime_capable(self) -> None:
        from src.core.llm.realtime_transcription import MODELS_WITHOUT_TURN_DETECTION

        modell = USE_CASE_DEFAULTS["live_transcription"]["model"]
        # Ein Modell, das der Dienst kennt — sonst waere die Vorbelegung ein 502 in Wartestellung.
        self.assertIn(modell, MODELS_WITHOUT_TURN_DETECTION | {"gpt-4o-transcribe", "gpt-4o-mini-transcribe"})


if __name__ == "__main__":
    unittest.main()
