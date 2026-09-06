"""Tests fuer die Uebergabe der Kontextfelder an den OpenAI-SDK.

Der SDK kennt in ``transcriptions.create()`` nur einen festen Parametersatz.
``languages`` und ``keywords`` gehoeren nicht dazu und wuerden als
"unexpected keyword argument" schon lokal scheitern — der Request ginge nie raus.
Geprueft wird deshalb, dass genau diese Felder ueber ``extra_body`` gehen und die
uebrigen weiterhin als benannte Parameter.
"""

import time
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

from src.core.llm.providers.openai_provider import OpenAIProvider
from src.core.llm.transcription_context import TranscriptionContext


class _AufgezeichneterClient:
    """Merkt sich die Aufrufe statt sie an OpenAI zu schicken."""

    def __init__(self, fehler: Exception | None = None) -> None:
        self.aufrufe: List[Dict[str, Any]] = []
        self._fehler = fehler
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, **params: Any) -> Any:
        self.aufrufe.append(params)
        # Ein Segment braucht eine Dauer groesser null; ohne diese Pause waere der
        # Aufruf in null Millisekunden fertig und das Ergebnis nicht konstruierbar.
        time.sleep(0.002)
        if self._fehler is not None and len(self.aufrufe) == 1:
            raise self._fehler
        return SimpleNamespace(text="Guten Tag.", language="german", usage=None)


def _provider(client: _AufgezeichneterClient) -> OpenAIProvider:
    with patch("src.core.llm.providers.openai_provider.OpenAI", return_value=client):
        return OpenAIProvider(api_key="test-key")


class TestExtraBody(unittest.TestCase):
    """Felder, die der SDK nicht kennt, muessen durchgereicht werden."""

    def test_languages_and_keywords_go_through_extra_body(self) -> None:
        client = _AufgezeichneterClient()
        provider = _provider(client)

        provider.transcribe(
            b"audio",
            model="gpt-transcribe",
            context=TranscriptionContext(languages=["de", "it"], keywords=["Brixen"]),
        )

        params = client.aufrufe[0]
        self.assertNotIn("languages", params)
        self.assertNotIn("keywords", params)
        self.assertEqual(params["extra_body"], {"languages": ["de", "it"], "keywords": ["Brixen"]})

    def test_prompt_stays_a_named_parameter(self) -> None:
        client = _AufgezeichneterClient()
        provider = _provider(client)

        provider.transcribe(
            b"audio",
            model="gpt-transcribe",
            context=TranscriptionContext(prompt="Sitzung einer Genossenschaft"),
        )

        params = client.aufrufe[0]
        self.assertEqual(params["prompt"], "Sitzung einer Genossenschaft")
        self.assertNotIn("extra_body", params)

    def test_classic_model_keeps_single_language(self) -> None:
        client = _AufgezeichneterClient()
        provider = _provider(client)

        provider.transcribe(b"audio", model="whisper-1", language="de")

        params = client.aufrufe[0]
        self.assertEqual(params["language"], "de")
        self.assertNotIn("extra_body", params)

    def test_no_extra_body_without_context(self) -> None:
        client = _AufgezeichneterClient()
        provider = _provider(client)

        provider.transcribe(b"audio", model="gpt-transcribe")

        self.assertNotIn("extra_body", client.aufrufe[0])


class TestRetryOhneSprache(unittest.TestCase):
    """Der Retry muss die Sprache auch im extra_body loswerden."""

    def test_unsupported_language_drops_languages_from_extra_body(self) -> None:
        client = _AufgezeichneterClient(fehler=Exception("unsupported_language"))
        provider = _provider(client)

        provider.transcribe(
            b"audio",
            model="gpt-transcribe",
            context=TranscriptionContext(languages=["xx"], keywords=["Brixen"]),
        )

        self.assertEqual(len(client.aufrufe), 2)
        zweiter = client.aufrufe[1]
        # Die Sprache ist weg, die Begriffe bleiben — sie waren nicht das Problem.
        self.assertEqual(zweiter["extra_body"], {"keywords": ["Brixen"]})

    def test_extra_body_disappears_when_only_languages_were_in_it(self) -> None:
        client = _AufgezeichneterClient(fehler=Exception("unsupported_language"))
        provider = _provider(client)

        provider.transcribe(
            b"audio", model="gpt-transcribe", context=TranscriptionContext(languages=["xx"])
        )

        self.assertEqual(len(client.aufrufe), 2)
        self.assertNotIn("extra_body", client.aufrufe[1])


if __name__ == "__main__":
    unittest.main()
