"""
Unit-Tests für Mistral-OCR-Seitenkosten (ohne Netz).

Ausführen:
    venv\\Scripts\\activate; $env:PYTHONPATH = "."; python -m pytest .tests/test_ocr_cost.py -q
"""

from src.core.llm.ocr_cost import (
    estimate_mistral_ocr_cost,
    extract_mistral_ocr_pages,
)


def test_cost_one_dollar_per_thousand_pages() -> None:
    assert estimate_mistral_ocr_cost(1000) == 1.0
    assert estimate_mistral_ocr_cost(6) == 0.006
    assert estimate_mistral_ocr_cost(1) == 0.001


def test_cost_zero_pages_is_zero() -> None:
    assert estimate_mistral_ocr_cost(0) == 0.0
    assert estimate_mistral_ocr_cost(-3) == 0.0


def test_pages_from_usage_info() -> None:
    ocr_json = {
        "pages": [{}, {}],
        "usage_info": {"pages_processed": 6},
    }
    assert extract_mistral_ocr_pages(ocr_json) == 6


def test_pages_fallback_to_pages_list() -> None:
    ocr_json = {"pages": [{}, {}, {}]}
    assert extract_mistral_ocr_pages(ocr_json) == 3


def test_pages_missing_is_zero() -> None:
    assert extract_mistral_ocr_pages(None) == 0
    assert extract_mistral_ocr_pages({}) == 0
    assert extract_mistral_ocr_pages({"usage_info": {"pages_processed": "x"}}) == 0
