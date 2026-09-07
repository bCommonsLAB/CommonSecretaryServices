"""
Unit-Tests für OpenRouter-Usage-Extraktion (ohne Netz).

Ausführen:
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_usage_cost.py -q
"""

from types import SimpleNamespace

from src.core.llm.usage_cost import extract_usage_cost, extract_usage_tokens


def test_extract_cost_from_object() -> None:
    usage = SimpleNamespace(cost=0.0123, total_tokens=10)
    assert extract_usage_cost(usage) == 0.0123
    assert extract_usage_tokens(usage) == 10


def test_extract_cost_from_dict() -> None:
    usage = {"cost": 0.004, "total_tokens": 42}
    assert extract_usage_cost(usage) == 0.004
    assert extract_usage_tokens(usage) == 42


def test_extract_cost_from_model_extra() -> None:
    usage = SimpleNamespace(total_tokens=5, model_extra={"cost": 0.99})
    assert extract_usage_cost(usage) == 0.99


def test_extract_cost_missing_is_zero() -> None:
    assert extract_usage_cost(None) == 0.0
    assert extract_usage_cost({}) == 0.0
    assert extract_usage_cost(SimpleNamespace(total_tokens=3)) == 0.0
    assert extract_usage_tokens(None) == 0


def test_extract_cost_rejects_negative() -> None:
    assert extract_usage_cost(SimpleNamespace(cost=-1.0)) == 0.0
