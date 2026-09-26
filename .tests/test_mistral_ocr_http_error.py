"""Tests: Mistral-OCR-Fehlerantworten werden zu verständlichen ProcessingErrors."""

from typing import Any, Dict

from src.core.exceptions import ProcessingError
from src.processors.pdf_processor import PDFProcessor


class _Resp:
    def __init__(self, status: int, body: Dict[str, Any], headers: Dict[str, str]) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers
        self.text = str(body)

    def json(self) -> Dict[str, Any]:
        return self._body


def test_429_with_zero_limit_names_account_quota() -> None:
    resp = _Resp(
        429,
        {"message": "Rate limit exceeded", "type": "rate_limited"},
        {"x-ratelimit-limit-req-minute": "0", "mistral-correlation-id": "abc"},
    )
    err = PDFProcessor._mistral_ocr_http_error(resp, "mistral-ocr-latest")
    assert isinstance(err, ProcessingError)
    assert "HTTP 429" in str(err) and "Rate limit exceeded" in str(err)
    assert "Kontingent" in str(err)
    assert err.details["http_status"] == 429
    assert err.details["ratelimit_limit_req_minute"] == "0"
    assert err.details["correlation_id"] == "abc"


def test_400_invalid_model() -> None:
    resp = _Resp(400, {"message": "Invalid model: foo", "type": "invalid_model"}, {})
    err = PDFProcessor._mistral_ocr_http_error(resp, "foo")
    assert "Invalid model: foo" in str(err)
    assert "Modell 'foo'" in str(err)
