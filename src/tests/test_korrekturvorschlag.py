"""Tests fuer den Korrekturvorschlag (Transkript plus Begleittexte).

Geprueft werden der Prompt (Schema steht im Text, Transkript nummeriert, Begleittexte
drin), die Pruefung beider Vorschlagslisten (alt genau einmal, Namen nur aus den
Begleittexten, beleg aus der festen Menge, zeile aus dem Transkript berechnet) und der
Dienst mit einem aufgezeichneten Chat-Modell.
"""

import json
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List

from src.api.routes.transcript_routes import parse_begleittexte
from src.core.exceptions import ProcessingError
from src.core.transcript.korrekturvorschlag import (
    ANTWORTSCHEMA,
    Begleittext,
    build_messages,
    extract_json,
    parse_vorschlaege,
)
from src.core.transcript.korrekturvorschlag_service import KorrekturvorschlagService

TRANSKRIPT = (
    "**Sprecher A:** Guten Morgen, ich bin Frau Mahler vom Dachverband.\n"
    "**Sprecher B:** Die Zahl war 2023 bei vierzig Prozent.\n"
    "**Sprecher A:** Danke, das stimmt so.\n"
    "**Stück 2 Sprecher A:** Frage aus dem Saal zur Finanzierung."
)
BEGLEITTEXTE = [
    Begleittext("Einladung", "Journalistenschulung. Referentinnen: Dr. Anna Mahlknecht (Dachverband), Lea Berger (Verein)."),
    Begleittext("Folien Vortrag 1", "Folie 1: Titel\nFolie 3: Anteil 2023: 14 Prozent"),
]


def _antwort(**overrides: Any) -> str:
    data: Dict[str, Any] = {
        "ersetzungen": [
            {"alt": "Frau Mahler", "neu": "Frau Mahlknecht", "zeile": 99, "kontext": "", "begruendung": "Name laut Einladung", "beleg": "einladung"},
            {"alt": "vierzig Prozent", "neu": "vierzehn Prozent", "zeile": 2, "kontext": "Die Zahl war 2023 bei vierzig Prozent.", "begruendung": "Folie nennt 14 Prozent", "beleg": "Folie 3"},
        ],
        "sprecher": [
            {"label": "Sprecher A", "name": "Dr. Anna Mahlknecht", "begruendung": "stellt sich vor", "beleg": "selbstvorstellung"},
            {"label": "Sprecher B", "name": "Lea Berger", "begruendung": "Thema passt", "beleg": "unsicher"},
        ],
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


class TestPrompt(unittest.TestCase):
    def test_schema_is_spelled_out_in_the_prompt(self) -> None:
        messages = build_messages(TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(messages[0]["role"], "system")
        self.assertIn(ANTWORTSCHEMA, messages[0]["content"])
        for feld in ("alt", "neu", "zeile", "kontext", "begruendung", "beleg", "label", "name"):
            self.assertIn(f'"{feld}"', messages[0]["content"])
        self.assertIn("einladung | folie <N> | selbstvorstellung | unsicher", messages[0]["content"])

    def test_user_message_numbers_lines_and_lists_begleittexte(self) -> None:
        user = build_messages(TRANSKRIPT, BEGLEITTEXTE, zielsprache="de")[1]["content"]

        self.assertIn("=== Begleittext 1: Einladung ===", user)
        self.assertIn("=== Begleittext 2: Folien Vortrag 1 ===", user)
        self.assertIn("2: **Sprecher B:** Die Zahl war 2023 bei vierzig Prozent.", user)

    def test_without_begleittexte_the_prompt_says_so(self) -> None:
        user = build_messages(TRANSKRIPT, [])[1]["content"]

        self.assertIn("Keine Begleittexte", user)


class TestErsetzungen(unittest.TestCase):
    def test_valid_replacements_are_kept_with_recomputed_line(self) -> None:
        vorschlag = parse_vorschlaege(_antwort(), TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(len(vorschlag.ersetzungen), 2)
        erste = vorschlag.ersetzungen[0]
        self.assertEqual((erste.alt, erste.neu), ("Frau Mahler", "Frau Mahlknecht"))
        self.assertEqual(erste.zeile, 1)  # nicht die 99 aus der Antwort
        self.assertEqual(erste.beleg, "einladung")
        self.assertIn("Frau Mahler", erste.kontext)  # Kontext aus der Zeile ergaenzt
        self.assertEqual(vorschlag.ersetzungen[1].beleg, "folie 3")  # normalisiert

    def test_alt_must_occur_exactly_once(self) -> None:
        antwort = _antwort(ersetzungen=[
            {"alt": "Sprecher A", "neu": "Mahlknecht", "beleg": "einladung"},   # 3x im Transkript
            {"alt": "Gibt es nicht", "neu": "x", "beleg": "einladung"},         # 0x
        ])

        vorschlag = parse_vorschlaege(antwort, TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(vorschlag.ersetzungen, [])
        self.assertEqual(len(vorschlag.verworfen), 2)
        self.assertTrue(any("3x" in v for v in vorschlag.verworfen))
        self.assertTrue(any("0x" in v for v in vorschlag.verworfen))

    def test_invalid_beleg_is_rejected_not_defaulted(self) -> None:
        antwort = _antwort(ersetzungen=[{"alt": "Frau Mahler", "neu": "Frau Mahlknecht", "beleg": "vermutung"}])

        vorschlag = parse_vorschlaege(antwort, TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(vorschlag.ersetzungen, [])
        self.assertIn("beleg 'vermutung' nicht erlaubt", vorschlag.verworfen[0])

    def test_duplicate_alt_and_identical_replacement_are_rejected(self) -> None:
        antwort = _antwort(ersetzungen=[
            {"alt": "Frau Mahler", "neu": "Frau Mahlknecht", "beleg": "einladung"},
            {"alt": "Frau Mahler", "neu": "Frau Mahlknechtt", "beleg": "einladung"},
            {"alt": "Danke", "neu": "Danke", "beleg": "unsicher"},
        ])

        vorschlag = parse_vorschlaege(antwort, TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(len(vorschlag.ersetzungen), 1)
        self.assertEqual(len(vorschlag.verworfen), 2)


class TestSprecher(unittest.TestCase):
    def test_valid_assignments_are_kept(self) -> None:
        vorschlag = parse_vorschlaege(_antwort(), TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual([s.label for s in vorschlag.sprecher], ["Sprecher A", "Sprecher B"])
        self.assertEqual(vorschlag.sprecher[0].name, "Dr. Anna Mahlknecht")
        self.assertEqual(vorschlag.sprecher[1].beleg, "unsicher")

    def test_names_must_come_from_begleittexte(self) -> None:
        antwort = _antwort(sprecher=[{"label": "Sprecher A", "name": "Peter Beispiel", "beleg": "einladung"}])

        vorschlag = parse_vorschlaege(antwort, TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(vorschlag.sprecher, [])
        self.assertIn("steht in keinem Begleittext", vorschlag.verworfen[0])

    def test_label_must_exist_in_transcript(self) -> None:
        antwort = _antwort(sprecher=[{"label": "Sprecher Z", "name": "Lea Berger", "beleg": "einladung"}])

        vorschlag = parse_vorschlaege(antwort, TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(vorschlag.sprecher, [])
        self.assertIn("Label kommt im Transkript nicht vor", vorschlag.verworfen[0])

    def test_chunk_labels_are_accepted(self) -> None:
        antwort = _antwort(sprecher=[{"label": "Stück 2 Sprecher A", "name": "Lea Berger", "beleg": "unsicher"}])

        vorschlag = parse_vorschlaege(antwort, TRANSKRIPT, BEGLEITTEXTE)

        self.assertEqual(vorschlag.sprecher[0].label, "Stück 2 Sprecher A")

    def test_without_begleittexte_no_names_pass(self) -> None:
        vorschlag = parse_vorschlaege(_antwort(), TRANSKRIPT, [])

        self.assertEqual(vorschlag.sprecher, [])


class TestJsonLesen(unittest.TestCase):
    def test_code_fences_and_surrounding_text_are_tolerated(self) -> None:
        self.assertEqual(extract_json('```json\n{"a": 1}\n```')["a"], 1)
        self.assertEqual(extract_json('Hier die Antwort: {"a": 2} Ende.')["a"], 2)

    def test_non_json_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            extract_json("keine Antwort")


class _FakeProvider:
    def __init__(self, raw: str) -> None:
        self.raw = raw
        self.calls: List[Dict[str, Any]] = []

    def chat_completion(self, messages: List[Dict[str, str]], model: str, temperature: float, **kwargs: Any) -> Any:
        self.calls.append({"messages": messages, "model": model, "temperature": temperature})
        return self.raw, SimpleNamespace(tokens=321, duration=12.5, model=model)


class _FakeConfig:
    def __init__(self, provider: Any, model: str = "gpt-test") -> None:
        self._provider, self._model = provider, model

    def reload_config(self) -> None: ...
    def get_provider_for_use_case(self, _use_case: Any) -> Any: return self._provider
    def get_model_for_use_case(self, _use_case: Any) -> str: return self._model


class TestDienst(unittest.TestCase):
    def test_service_returns_both_lists_and_meta(self) -> None:
        provider = _FakeProvider(_antwort())
        service = KorrekturvorschlagService(config_manager=_FakeConfig(provider))  # type: ignore[arg-type]

        vorschlag, meta = service.vorschlagen(TRANSKRIPT, BEGLEITTEXTE, "de")

        self.assertEqual(len(vorschlag.ersetzungen), 2)
        self.assertEqual(len(vorschlag.sprecher), 2)
        self.assertEqual(meta, {"modell": "gpt-test", "tokens": 321, "dauer_ms": 12.5})
        self.assertEqual(provider.calls[0]["temperature"], 0.0)

    def test_unreadable_answer_is_a_processing_error(self) -> None:
        service = KorrekturvorschlagService(config_manager=_FakeConfig(_FakeProvider("Ich weiss es nicht.")))  # type: ignore[arg-type]

        with self.assertRaises(ProcessingError) as ctx:
            service.vorschlagen(TRANSKRIPT, BEGLEITTEXTE)
        self.assertEqual(ctx.exception.details["error_code"], "INVALID_LLM_RESPONSE")

    def test_missing_model_is_reported(self) -> None:
        service = KorrekturvorschlagService(config_manager=_FakeConfig(None, model=""))  # type: ignore[arg-type]

        with self.assertRaises(ProcessingError) as ctx:
            service.vorschlagen(TRANSKRIPT, BEGLEITTEXTE)
        self.assertEqual(ctx.exception.details["error_code"], "NO_MODEL_CONFIGURED")


class TestRouteEingabe(unittest.TestCase):
    def test_begleittexte_are_parsed(self) -> None:
        result = parse_begleittexte([{"name": "Einladung", "text": "Hallo"}])

        self.assertEqual(result, [Begleittext("Einladung", "Hallo")])

    def test_incomplete_entries_are_errors(self) -> None:
        with self.assertRaises(ValueError):
            parse_begleittexte([{"name": "", "text": "x"}])
        with self.assertRaises(ValueError):
            parse_begleittexte("kein array")

    def test_none_means_no_begleittexte(self) -> None:
        self.assertEqual(parse_begleittexte(None), [])


if __name__ == "__main__":
    unittest.main()
