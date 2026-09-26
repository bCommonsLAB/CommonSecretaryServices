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
