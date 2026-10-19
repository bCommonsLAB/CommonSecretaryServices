"""Tests: Mistral-OCR-Modell-ID wird ohne Provider-Präfix an die API geschickt."""

from types import SimpleNamespace
from typing import Any

import pytest

from src.processors import pdf_processor
from src.processors.pdf_processor import PDFProcessor


class _Mgr:
    def __init__(self, model: str) -> None:
        self._model = model

    def get_use_case_config(self, _uc: Any) -> Any:
        return SimpleNamespace(provider="mistral", model=self._model)


@pytest.mark.parametrize(
    "configured, expected",
    [
        ("mistral-ocr-latest", "mistral-ocr-latest"),
        ("mistral/mistral-ocr-latest", "mistral-ocr-latest"),
        ("mistral/mistral/mistral-ocr-4-0", "mistral-ocr-4-0"),
    ],
)
def test_resolve_strips_provider_prefix(
    monkeypatch: pytest.MonkeyPatch, configured: str, expected: str
) -> None:
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    monkeypatch.setattr(pdf_processor, "LLMConfigManager", lambda: _Mgr(configured))
    proc = PDFProcessor.__new__(PDFProcessor)
    assert proc._resolve_mistral_ocr_api_model() == expected


def test_resolve_env_override_strips_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MISTRAL_MODEL", "mistral/mistral-ocr-latest")
    proc = PDFProcessor.__new__(PDFProcessor)
    assert proc._resolve_mistral_ocr_api_model() == "mistral-ocr-latest"


@pytest.mark.parametrize(
    "provider, name, expected",
    [
        ("mistral", "mistral-ocr-latest", "mistral-ocr-latest"),
        ("mistral", "mistral/mistral-ocr-latest", "mistral-ocr-latest"),
        ("mistral", "mistralai/mistral-ocr-2512", "mistral-ocr-2512"),
        ("mistral", "mistral/mistralai/mistral-ocr-2512", "mistral-ocr-2512"),
        ("Mistral", " Mistral/pixtral-large-latest ", "pixtral-large-latest"),
        ("openai", "openai/gpt-4o", "gpt-4o"),
        # OpenRouter: "anbieter/modell" ist der echte Name und bleibt
        ("openrouter", "mistralai/mistral-small-3.2-24b-instruct", "mistralai/mistral-small-3.2-24b-instruct"),
        ("openrouter", "openrouter/auto", "openrouter/auto"),
        ("ollama", "llava", "llava"),
        (None, "mistral/x", "mistral/x"),
        ("mistral", None, ""),
    ],
)
def test_normalize_model_name(provider: Any, name: Any, expected: str) -> None:
    from src.core.llm.model_names import normalize_model_name

    assert normalize_model_name(provider, name) == expected


def test_resolve_strips_openrouter_vendor_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISTRAL_MODEL", raising=False)
    monkeypatch.setattr(pdf_processor, "LLMConfigManager", lambda: _Mgr("mistralai/mistral-ocr-2512"))
    proc = PDFProcessor.__new__(PDFProcessor)
    assert proc._resolve_mistral_ocr_api_model() == "mistral-ocr-2512"


class _Resp:
    def __init__(self, status: int, body: Any) -> None:
        import json as _json

        self.status_code = status
        self._body = body
        self.text = _json.dumps(body)
        self.content = self.text.encode()
        self.headers = {"content-type": "application/json"}

    def json(self) -> Any:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code} Client Error")


def _run_ocr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, ocr_responses: list, env_model: str = "mistral-ocr-4-0"
) -> list:
    from pathlib import Path
    from unittest.mock import MagicMock

    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("MISTRAL_MODEL", env_model)
    monkeypatch.setattr(pdf_processor, "record_operation_result", lambda *a, **k: None)
    sent_models: list = []

    def fake_post(url: str, **kwargs: Any) -> _Resp:
        if url.endswith("/v1/files"):
            return _Resp(200, {"id": "file-1"})
        sent_models.append(kwargs["json"]["model"])
        return ocr_responses.pop(0)

    monkeypatch.setattr(pdf_processor.requests, "post", fake_post)
    pdf = Path(tmp_path) / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    proc = PDFProcessor.__new__(PDFProcessor)
    proc.logger = MagicMock()
    import asyncio

    try:
        asyncio.run(proc._process_mistral_ocr(pdf))
    except Exception:
        # Nach dem OCR-Aufruf folgende Verarbeitung ist hier nicht Gegenstand des Tests
        pass
    return sent_models


def test_ocr_retries_once_with_fallback_on_invalid_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    invalid = _Resp(400, {"object": "error", "message": "Invalid model: mistral-ocr-4-0", "type": "invalid_model"})
    ok = _Resp(200, {"pages": [{"index": 0, "markdown": "Hallo", "images": []}], "usage_info": {"pages_processed": 1}})
    assert _run_ocr(monkeypatch, tmp_path, [invalid, ok]) == ["mistral-ocr-4-0", "mistral-ocr-latest"]


def test_ocr_does_not_retry_other_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    other = _Resp(400, {"object": "error", "message": "Document too large", "type": "invalid_request"})
    assert _run_ocr(monkeypatch, tmp_path, [other]) == ["mistral-ocr-4-0"]


def test_ocr_does_not_retry_when_fallback_already_used(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    invalid = _Resp(400, {"object": "error", "message": "Invalid model", "type": "invalid_model"})
    assert _run_ocr(monkeypatch, tmp_path, [invalid], env_model="mistral-ocr-latest") == ["mistral-ocr-latest"]
