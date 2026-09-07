"""
Unit-Tests für LLMRequest.cost und LLMInfo.total_cost.

Ausführen:
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_llm_request_cost.py -q
"""

import pytest

from src.core.models.llm import LLMInfo, LLMRequest


def _req(tokens: int = 10, cost: float = 0.0) -> LLMRequest:
    return LLMRequest(
        model="openai/gpt-4o-mini",
        purpose="chat_completion",
        tokens=tokens,
        duration=100.0,
        processor="OpenRouterProvider",
        cost=cost,
        timestamp="2026-08-21T12:00:00",
    )


def test_cost_default_is_zero() -> None:
    req = LLMRequest(
        model="x",
        purpose="y",
        tokens=1,
        duration=0.0,
        processor="p",
        timestamp="2026-08-21T12:00:00",
    )
    assert req.cost == 0.0


def test_to_dict_and_from_dict_roundtrip() -> None:
    req = _req(tokens=20, cost=0.015)
    restored = LLMRequest.from_dict(req.to_dict())
    assert restored.cost == 0.015
    assert restored.tokens == 20


def test_from_dict_without_cost_is_zero() -> None:
    data = _req().to_dict()
    del data["cost"]
    restored = LLMRequest.from_dict(data)
    assert restored.cost == 0.0


def test_negative_cost_is_rejected() -> None:
    with pytest.raises(ValueError):
        _req(cost=-0.01)


def test_llm_info_total_cost() -> None:
    info = LLMInfo(requests=[_req(cost=0.01), _req(cost=0.02)])
    assert info.total_cost == pytest.approx(0.03)
    assert info.to_dict()["total_cost"] == pytest.approx(0.03)
