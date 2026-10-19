"""
Tests: Das Dashboard legt Modelle ohne doppeltes Provider-Präfix an und erkennt Dubletten.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from flask import Flask

from src.dashboard.routes import llm_config_routes as routes


class _Repo:
    def __init__(self, existing: Optional[List[str]] = None) -> None:
        self.ids: List[str] = list(existing or [])
        self.created: List[Any] = []

    def get_model(self, model_id: str) -> Any:
        return object() if model_id in self.ids else None

    def create_model(self, model: Any) -> str:
        self.ids.append(model.model_id)
        self.created.append(model)
        return str(model.model_id)


def _post(monkeypatch: pytest.MonkeyPatch, repo: _Repo, body: Dict[str, Any]) -> Any:
    monkeypatch.setattr(routes, "LLMModelRepository", lambda: repo)
    app = Flask(__name__)
    with app.test_request_context("/llm-config/api/models", method="POST", json=body):
        return routes.create_model_api()


def _status(result: Any) -> int:
    return result[1] if isinstance(result, tuple) else result.status_code


@pytest.mark.parametrize("name", ["mistral-ocr-latest", "mistral/mistral-ocr-latest", "mistralai/mistral-ocr-latest"])
def test_create_model_strips_provider_prefix(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    repo = _Repo()
    result = _post(monkeypatch, repo, {"provider": "mistral", "model_name": name, "use_cases": ["ocr_pdf"]})
    assert _status(result) in (200, 201)
    assert repo.ids == ["mistral/mistral-ocr-latest"]
    assert repo.created[0].model_name == "mistral-ocr-latest"


def test_create_model_rejects_prefixed_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _Repo(existing=["mistral/mistral-ocr-2512"])
    result = _post(monkeypatch, repo, {"provider": "mistral", "model_name": "mistralai/mistral-ocr-2512"})
    assert _status(result) == 409
    assert repo.created == []


def test_create_model_keeps_openrouter_vendor_slug(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _Repo()
    _post(monkeypatch, repo, {"provider": "openrouter", "model_name": "mistralai/mistral-small-3.2-24b-instruct"})
    assert repo.ids == ["openrouter/mistralai/mistral-small-3.2-24b-instruct"]


def test_mistral_ocr_defaults_are_ocr_models() -> None:
    import yaml
    from pathlib import Path

    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "config.yaml").read_text(encoding="utf-8"))
    ocr_models = cfg["llm_providers"]["mistral"]["available_models"]["ocr_pdf"]
    assert ocr_models and all(m.startswith("mistral-ocr") for m in ocr_models)
    assert routes.USE_CASE_DEFAULTS["ocr_pdf"] == {"provider": "mistral", "model": "mistral-ocr-latest"}
