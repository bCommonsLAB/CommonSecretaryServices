"""
Tests: LLM-JSON robust parsen (Befund 05.11.–08.11.2026, Vorlage chatverlauf-de).

Gemini lieferte bei langen ``*_md``-Feldern in etwa der Hälfte der Fälle ungültiges
JSON (unmaskierte gerade Anführungszeichen, rohe Zeilenumbrüche, ungültige Escapes).
Der Secretary schrieb die Fehlermeldung als Feldwert in ``structured_data`` und
antwortete mit HTTP 200. Geprüft wird jetzt:

- jede Fixture in ``.tests/fixtures/llm_json`` als eigener Fall: reparierbar mit
  ``repaired=True`` und richtiger Stufe, oder ein Fehler mit Zeile/Spalte
- abgeschnittene Antworten und reine Prosa bleiben Fehler (kein stilles Teilobjekt)
- ``LLM_JSON_DEBUG_DIR`` legt die vollständige Rohantwort ab, der Pfad steht im Fehler
- JSON-Antwortmodus je Modell/Provider/Umgebung
- ``transform_by_template``: response_format geht an den Provider, Reparatur steht in
  der Antwort, ein Parse-Fehler wird ein Fehlerstatus (HTTP 400, status=error) statt
  Feldwerten in ``structured_data``
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from src.core.llm.json_mode import (
    JSON_RESPONSE_MODE_ENV,
    json_response_mode_enabled,
    looks_like_response_format_rejection,
    response_format_kwargs,
)
from src.core.models.enums import OutputFormat
from src.core.models.llm import LLMRequest
from src.core.models.transformer import TransformationResult, TransformerData
from src.utils.json_validation import (
    LLM_JSON_DEBUG_DIR_ENV,
    JSONParseError,
    JSONParseOutcome,
    extract_and_parse_json,
    parse_llm_json,
)

FIXTURES = Path(__file__).parent / "fixtures" / "llm_json"

MD_FELDER = ("entscheidungen_md", "getan_md", "befunde_md", "verweise_md")


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --- Fixtures: reparierbar -------------------------------------------------------


def test_gemini_quotes_newlines_escape_is_repaired_to_20_fields() -> None:
    outcome = parse_llm_json(_fixture("gemini_quotes_newlines_escape.txt"), label="chatverlauf-de")

    assert outcome.repaired is True
    assert outcome.stage == "escaped_quotes"
    assert len(outcome.data) == 20
    assert sorted(outcome.data) == sorted(
        ["titel", "datum", "umgebung", "hauptvorhaben", "nebenvorhaben", "beteiligte", "dauer_min",
         "zuege", "status", "zusammenfassung", "stimmung", "offene_punkte", "naechster_schritt",
         "tags", "sprache", "quelle", *MD_FELDER]
    ), "keine Phantomfelder aus Zitaten wie \"Fehler: …\""
    assert '"Fehler: LLM-JSON (2×)"' in outcome.data["getan_md"]
    assert "\\d+" in outcome.data["entscheidungen_md"]
    for feld in MD_FELDER:
        assert isinstance(outcome.data[feld], str) and outcome.data[feld]
    # Die geraden Anführungszeichen stehen im Wert, die Zeilenumbrüche sind erhalten.
    assert '"chatverlauf-de"' in outcome.data["entscheidungen_md"]
    assert '`git commit -m "fix: parser"`' in outcome.data["getan_md"]
    assert "\n" in outcome.data["getan_md"]
    assert outcome.data["verweise_md"].startswith("[[Organisation/Arbeitsliste")
    assert outcome.data["dauer_min"] == 240
    assert outcome.repair_log, "Reparaturhinweise müssen mitkommen"
    assert outcome.repair_info()["stage"] == "escaped_quotes"


def test_json_repair_library_catches_what_the_quote_stage_cannot() -> None:
    # Einfache Anführungszeichen und fehlende Klammer: kein Maskierungsproblem.
    outcome = parse_llm_json("{'titel': 'T', 'tags': ['a', 'b'}")
    assert outcome.repaired is True
    assert outcome.stage == "json_repair"
    assert outcome.data == {"titel": "T", "tags": ["a", "b"]}


@pytest.mark.parametrize("raw, expected", [
    # Zitat mit Doppelpunkt im Wert bleibt Text, kein neuer Schlüssel
    ('{"a": "x "Fehler: y" z", "b": 1}', {"a": 'x "Fehler: y" z', "b": 1}),
    # Zitat direkt vor dem Komma, danach der nächste Schlüssel
    ('{"a": "er sagte "ja"", "b": "nein"}', {"a": 'er sagte "ja"', "b": "nein"}),
    # Zitat am Ende des letzten Werts
    ('{"a": "Vermerk "LLM-JSON""}', {"a": 'Vermerk "LLM-JSON"'}),
    # Array von Strings mit Zitaten
    ('{"tags": ["eins", "sagt "zwei"", "drei"]}', {"tags": ["eins", 'sagt "zwei"', "drei"]}),
    # rohe Steuerzeichen und ungültige Escapes
    ('{"a": "Zeile 1\nZeile\t2 \\d+ C:\\Users"}', {"a": "Zeile 1\nZeile\t2 \\d+ C:\\Users"}),
    # fehlendes Komma vor dem nächsten Schlüssel
    ('{"titel": "T"\n"status": "ok"}', {"titel": "T", "status": "ok"}),
    # Echter Fall 08.11.2026 (Beleg A2, Gemini im JSON-Modus, "Expecting ',' delimiter: line 39
    # column 665"): Code-Span mit Schlüssel-Wert-Paar in geraden Anführungszeichen im Wert
    ('{"befunde_md": "- Der Pfad (`content: "PDF"`) läuft über den Mask-Mechanismus.", "offen_md": "x"}',
     {"befunde_md": '- Der Pfad (`content: "PDF"`) läuft über den Mask-Mechanismus.', "offen_md": "x"}),
])
def test_escape_stage_cases(raw: str, expected: Dict[str, Any]) -> None:
    outcome = parse_llm_json(raw)
    assert outcome.data == expected
    assert outcome.repaired is True
    assert outcome.stage == "escaped_quotes"


def test_escape_stage_leaves_valid_json_untouched() -> None:
    from src.utils.json_validation import escape_unescaped_in_strings

    valid = '{"a": "\\"ok\\" \\u00e4 \\\\ \\n", "b": [1, "x: y", {"c": "d"}], "e": null}'
    assert escape_unescaped_in_strings(valid) == valid
    assert parse_llm_json(valid).repaired is False


def test_invalid_escape_fixture_is_repaired() -> None:
    outcome = parse_llm_json(_fixture("invalid_escape.txt"))

    assert outcome.repaired is True
    assert outcome.data["titel"] == "Pfade"
    assert outcome.data["pfad"].startswith("C:")
    assert "Users" in outcome.data["pfad"] and "projekte" in outcome.data["pfad"]


def test_trailing_comma_fixture_uses_sanitize_stage() -> None:
    outcome = parse_llm_json(_fixture("trailing_comma.txt"))

    assert outcome.repaired is True
    assert outcome.stage == "sanitized"
    assert outcome.data == {"titel": "T", "tags": ["a", "b"]}


def test_prose_around_object_is_extracted() -> None:
    outcome = parse_llm_json(_fixture("prose_around_object.txt"))

    assert outcome.repaired is True
    assert outcome.data == {"titel": "T", "status": "ok"}


def test_valid_direct_fixture_is_not_marked_repaired() -> None:
    outcome = parse_llm_json(_fixture("valid_direct.txt"))

    assert outcome.repaired is False
    assert outcome.stage == "direct"
    assert outcome.data["getan_md"] == 'Alles "gut" — mit \n Zeilenumbruch'


# --- Fixtures: bleiben Fehler ---------------------------------------------------


def test_prose_only_fixture_raises_with_line_and_column() -> None:
    with pytest.raises(JSONParseError) as info:
        parse_llm_json(_fixture("prose_only.txt"))

    assert info.value.line == 1
    assert info.value.column == 1
    assert "Zeile 1, Spalte 1" in str(info.value)
    assert "Antwortlänge" in str(info.value)


def test_truncated_fixture_is_an_error_not_a_partial_object() -> None:
    with pytest.raises(JSONParseError) as info:
        parse_llm_json(_fixture("truncated.txt"))

    assert "abgeschnitten" in str(info.value)
    assert info.value.line is not None and info.value.column is not None


def test_array_is_not_an_object() -> None:
    with pytest.raises(JSONParseError) as info:
        parse_llm_json('[{"a": 1}]')
    assert "kein Objekt" in str(info.value)


def test_empty_content_is_an_error() -> None:
    with pytest.raises(JSONParseError):
        parse_llm_json("   ")


def test_outcome_rejects_inconsistent_state() -> None:
    with pytest.raises(ValueError):
        JSONParseOutcome(data={"a": 1}, repaired=True, stage="direct")
    with pytest.raises(ValueError):
        JSONParseOutcome(data={"a": 1}, stage="magic")


def test_extract_and_parse_json_stays_compatible() -> None:
    assert extract_and_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_and_parse_json(_fixture("gemini_quotes_newlines_escape.txt"))["datum"] == "2026-11-05"


# --- Debug-Ablage der Rohantwort ------------------------------------------------


def test_debug_dir_receives_full_raw_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LLM_JSON_DEBUG_DIR_ENV, str(tmp_path / "llm-json"))
    raw = _fixture("prose_only.txt") + ("x" * 2000)

    with pytest.raises(JSONParseError) as info:
        parse_llm_json(raw, label="chatverlauf-de", model="google/gemini-2.5-flash")

    assert info.value.dump_path is not None
    dump = Path(info.value.dump_path)
    assert dump.exists()
    assert dump.name.endswith(".failed.txt") and "chatverlauf-de" in dump.name
    assert dump.read_text(encoding="utf-8") == raw, "vollständig, nicht nur 500 Zeichen"
    assert str(dump) in str(info.value)
    assert "Content-Snippet" not in str(info.value)

    meta = json.loads(dump.with_suffix("").with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["model"] == "google/gemini-2.5-flash"
    assert meta["outcome"] == "failed"
    assert meta["line"] == 1 and meta["column"] == 1
    assert meta["content_chars"] == len(raw)


def test_debug_dir_also_keeps_repaired_responses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reparierte Antworten sind Fixture-Material und landen ebenfalls im Debug-Ordner."""
    debug_dir = tmp_path / "llm-json"
    monkeypatch.setenv(LLM_JSON_DEBUG_DIR_ENV, str(debug_dir))
    raw = _fixture("gemini_quotes_newlines_escape.txt")

    outcome = parse_llm_json(raw, label="chatverlauf-de", model="google/gemini-2.5-flash")

    assert outcome.repaired is True
    dumps = sorted(debug_dir.glob("*.repaired.txt"))
    assert len(dumps) == 1
    assert dumps[0].read_text(encoding="utf-8") == raw
    meta = json.loads(dumps[0].with_suffix("").with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["outcome"] == "repaired" and meta["stage"] == "escaped_quotes"
    assert meta["line"] is not None, "Ort des ersten Parse-Fehlers bleibt erhalten"

    # Direkt parsebare Antworten erzeugen keine Datei.
    parse_llm_json(_fixture("valid_direct.txt"))
    assert len(list(debug_dir.iterdir())) == 2


def test_debug_dir_off_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LLM_JSON_DEBUG_DIR_ENV, raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(JSONParseError) as info:
        parse_llm_json(_fixture("prose_only.txt"))

    assert info.value.dump_path is None
    assert "Content-Snippet" in str(info.value)
    assert list(tmp_path.iterdir()) == []


# --- JSON-Antwortmodus ----------------------------------------------------------


def test_json_mode_default_on_for_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    assert json_response_mode_enabled("google/gemini-2.5-flash", "openrouter", config_section={}) is True
    assert json_response_mode_enabled("gpt-4o", "openai", config_section={}) is True


def test_json_mode_off_for_providers_without_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    assert json_response_mode_enabled("mistral-large-latest", "mistral", config_section={}) is False
    assert json_response_mode_enabled("x", None, config_section={}) is False


def test_json_mode_per_model_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    section = {"enabled": True, "models": {"google/gemini-2.5-flash": False, "openai/gpt-4o": "off"}}
    assert json_response_mode_enabled("google/gemini-2.5-flash", "openrouter", section) is False
    # Use-Case-Konfiguration nennt das Modell mit Provider-Präfix
    assert json_response_mode_enabled("openrouter/google/gemini-2.5-flash", "openrouter", section) is False
    assert json_response_mode_enabled("openai/gpt-4o", "openrouter", section) is False
    assert json_response_mode_enabled("anthropic/claude-sonnet-4.5", "openrouter", section) is True
    # enabled: false, einzelnes Modell wieder an
    section_off = {"enabled": False, "models": {"google/gemini-2.5-flash": True}}
    assert json_response_mode_enabled("anthropic/claude-sonnet-4.5", "openrouter", section_off) is False
    assert json_response_mode_enabled("google/gemini-2.5-flash", "openrouter", section_off) is True


def test_json_mode_env_switches_everything_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JSON_RESPONSE_MODE_ENV, "off")
    assert json_response_mode_enabled("google/gemini-2.5-flash", "openrouter", {"enabled": True}) is False


def test_response_format_kwargs_and_rejection_detection() -> None:
    assert response_format_kwargs() == {"response_format": {"type": "json_object"}}
    assert looks_like_response_format_rejection(RuntimeError("response_format is not supported for this model"))
    assert not looks_like_response_format_rejection(RuntimeError("rate limit exceeded"))


# --- Modelle: repaired in der Antwort -------------------------------------------


def test_transformer_data_to_dict_carries_repaired() -> None:
    plain = TransformerData(text="t", language="de", format=OutputFormat.TEXT, structured_data={"a": 1})
    assert plain.to_dict()["repaired"] is False
    assert "repair_info" not in plain.to_dict()

    fixed = TransformerData(
        text="t", language="de", format=OutputFormat.TEXT, structured_data={"a": 1},
        repaired=True, repair_info={"stage": "json_repair", "hints": ["x"]},
    )
    assert fixed.to_dict()["repaired"] is True
    assert fixed.to_dict()["repair_info"]["stage"] == "json_repair"


def test_transformation_result_roundtrip_keeps_repaired() -> None:
    result = TransformationResult(
        text="t", target_language="de", structured_data={"a": 1},
        repaired=True, repair_info={"stage": "sanitized", "hints": []},
    )
    again = TransformationResult.from_dict(result.to_dict())
    assert again.repaired is True and again.repair_info == {"stage": "sanitized", "hints": []}
    with pytest.raises(ValueError):
        TransformationResult(text="t", target_language="de", repair_info={"stage": "x"})


# --- transform_by_template mit Fake-Provider ------------------------------------


TEMPLATE = (
    "---\n"
    "titel: {{titel|Titel der Sitzung}}\n"
    "datum: {{datum|Datum}}\n"
    "---\n"
    "## Entscheidungen\n{{entscheidungen_md|Entscheidungen als Markdown}}\n\n"
    "## Getan\n{{getan_md|Getan als Markdown}}\n\n"
    "## Befunde\n{{befunde_md|Befunde als Markdown}}\n\n"
    "## Verweise\n{{verweise_md|Verweise als Markdown}}\n"
)


class _FakeProvider:
    """Chat-Provider, der feste Antworten liefert und seine Aufrufe aufzeichnet."""

    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.calls: List[Dict[str, Any]] = []

    def get_provider_name(self) -> str:
        return "openrouter"

    def chat_completion(self, messages: List[Dict[str, str]], model: str, **kwargs: Any) -> Tuple[str, LLMRequest]:
        self.calls.append({"model": model, **kwargs})
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return str(answer), LLMRequest(model=model, purpose="chat_completion", tokens=1234, duration=10.0, processor="fake", cost=0.01)


class _FakeConfigManager:
    def __init__(self, provider: _FakeProvider) -> None:
        self._provider = provider

    def get_provider_for_use_case(self, _use_case: Any) -> _FakeProvider:
        return self._provider

    def get_model_for_use_case(self, _use_case: Any) -> str:
        return "google/gemini-2.5-flash"

    def get_provider_config(self, _name: str) -> None:
        return None


def _transcriber(provider: _FakeProvider) -> Any:
    """WhisperTranscriber ohne OpenAI-Client, MongoDB und Dateisystem."""
    from src.utils.transcription_utils import WhisperTranscriber

    transcriber: Any = object.__new__(WhisperTranscriber)
    transcriber.config = {}
    transcriber.processor = None
    transcriber._logger = None
    transcriber.llm_config_manager = _FakeConfigManager(provider)
    transcriber.model = "whisper-1"
    transcriber.temperature = 0.1
    transcriber.tracked: List[Dict[str, Any]] = []

    def create_llm_request(**kwargs: Any) -> None:
        transcriber.tracked.append(kwargs)

    transcriber.create_llm_request = create_llm_request
    return transcriber


def _run(provider: _FakeProvider, monkeypatch: pytest.MonkeyPatch, json_mode_env: Optional[str] = None) -> TransformationResult:
    if json_mode_env is None:
        monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(JSON_RESPONSE_MODE_ENV, json_mode_env)
    monkeypatch.delenv(LLM_JSON_DEBUG_DIR_ENV, raising=False)
    monkeypatch.setattr("src.core.llm.json_mode._load_section", lambda: {"enabled": True})
    return _transcriber(provider).transform_by_template(
        text="Ein langer Chatverlauf.",
        target_language="de",
        template_content=TEMPLATE,
        context={"quelle": "Beleg A2"},
        use_cache=False,
    )


def test_template_requests_json_mode_and_reports_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider([_fixture("gemini_quotes_newlines_escape.txt")])

    result = _run(provider, monkeypatch)

    assert provider.calls[0]["response_format"] == {"type": "json_object"}
    assert provider.calls[0]["model"] == "google/gemini-2.5-flash"
    assert result.repaired is True
    assert result.repair_info is not None
    assert result.repair_info["stage"] == "escaped_quotes"
    assert result.repair_info["json_mode"] is True
    assert result.structured_data is not None and len(result.structured_data) == 20
    assert "## Getan" in result.text and "fix: parser" in result.text
    assert "Fehler bei der Extraktion" not in result.text


def test_template_without_json_mode_when_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider([_fixture("valid_direct.txt")])

    result = _run(provider, monkeypatch, json_mode_env="off")

    assert "response_format" not in provider.calls[0]
    assert result.repaired is False and result.repair_info is None


def test_template_retries_once_without_json_mode_on_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider([
        RuntimeError("400: response_format is not supported by this model"),
        _fixture("valid_direct.txt"),
    ])

    result = _run(provider, monkeypatch)

    assert len(provider.calls) == 2
    assert provider.calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in provider.calls[1]
    assert result.structured_data == {"titel": "T", "getan_md": 'Alles "gut" — mit \n Zeilenumbruch'}


def test_template_other_provider_errors_still_propagate(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider([RuntimeError("rate limit exceeded")])
    with pytest.raises(ValueError) as info:
        _run(provider, monkeypatch)
    assert "rate limit exceeded" in str(info.value)
    assert len(provider.calls) == 1


def test_template_parse_failure_is_an_error_result_not_field_values(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _FakeProvider([_fixture("prose_only.txt")])
    transcriber = _transcriber(provider)
    monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    monkeypatch.delenv(LLM_JSON_DEBUG_DIR_ENV, raising=False)
    monkeypatch.setattr("src.core.llm.json_mode._load_section", lambda: {})

    result = transcriber.transform_by_template(
        text="Text", target_language="de", template_content=TEMPLATE, use_cache=False
    )

    assert isinstance(result.structured_data, dict)
    assert result.structured_data["error_type"] == "LLMJSONParseError"
    assert result.structured_data["model"] == "google/gemini-2.5-flash"
    assert result.structured_data["json_mode"] is True
    assert result.structured_data["line"] == 1
    assert "Zeile 1, Spalte 1" in result.structured_data["error"]
    # Keine Fehlermeldung als Wert der Template-Felder
    for feld in ("titel", "datum") + MD_FELDER:
        assert feld not in result.structured_data
    # Der gescheiterte Aufruf wird trotzdem verbucht
    assert transcriber.tracked and transcriber.tracked[0]["tokens"] == 1234


def test_processor_and_route_turn_parse_failure_into_http_400(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ende-zu-Ende ohne LLM: transformByTemplate -> ErrorInfo -> _failed_result_response."""
    from src.api.routes.transformer_routes import FAILED_TRANSFORMATION_STATUS, _failed_result_response
    from src.core.models.base import ProcessInfo
    from src.processors.transformer_processor import TransformerProcessor

    provider = _FakeProvider([_fixture("prose_only.txt")])
    monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    monkeypatch.delenv(LLM_JSON_DEBUG_DIR_ENV, raising=False)
    monkeypatch.setattr("src.core.llm.json_mode._load_section", lambda: {})

    processor: Any = object.__new__(TransformerProcessor)
    processor.process_info = ProcessInfo(id="p-test", main_processor="TransformerProcessor", started=datetime.now().isoformat())
    processor.transcriber = _transcriber(provider)

    class _Logger:
        def error(self, *_a: Any, **_k: Any) -> None: ...
        def info(self, *_a: Any, **_k: Any) -> None: ...
        def warning(self, *_a: Any, **_k: Any) -> None: ...

    processor.logger = _Logger()

    response = processor.transformByTemplate(
        text="Text", source_language="de", target_language="de", template_content=TEMPLATE, use_cache=False
    )
    assert response.error is not None
    assert response.error.code == "TEMPLATE_ERROR"
    assert response.error.details["error_type"] == "LLMJSONParseError"
    assert "kein gültiges JSON" in response.error.message

    failed = _failed_result_response(processor, response, {"template": ""})
    assert failed is not None
    body, status = failed
    assert status == FAILED_TRANSFORMATION_STATUS
    assert body["status"] == "error"
    assert body["data"] is None
    assert body["error"]["details"]["error_type"] == "LLMJSONParseError"


def test_processor_passes_repaired_through_to_response(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.models.base import ProcessInfo
    from src.processors.transformer_processor import TransformerProcessor

    provider = _FakeProvider([_fixture("gemini_quotes_newlines_escape.txt")])
    monkeypatch.delenv(JSON_RESPONSE_MODE_ENV, raising=False)
    monkeypatch.delenv(LLM_JSON_DEBUG_DIR_ENV, raising=False)
    monkeypatch.setattr("src.core.llm.json_mode._load_section", lambda: {})

    processor: Any = object.__new__(TransformerProcessor)
    processor.process_info = ProcessInfo(id="p-test", main_processor="TransformerProcessor", started=datetime.now().isoformat())
    processor.transcriber = _transcriber(provider)
    processor.logger = None

    response = processor.transformByTemplate(
        text="Text", source_language="de", target_language="de", template_content=TEMPLATE, use_cache=False
    )
    assert response.error is None
    body = response.to_dict()
    assert body["status"] == "success"
    assert body["data"]["repaired"] is True
    assert body["data"]["repair_info"]["stage"] == "escaped_quotes"
    assert len(body["data"]["structured_data"]) == 20
