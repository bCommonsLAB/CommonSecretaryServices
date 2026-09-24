"""Tests: echte Operationsfehler (z. B. Mistral-OCR 429 mit Limit 0) verschlechtern den Health-Status."""

from typing import Any, Dict

import pytest

from src.core.llm import health
from src.core.llm.health import (
    LLMHealthService,
    classify_operation_error,
    record_operation_result,
)
from src.core.llm.use_cases import UseCase


@pytest.fixture(autouse=True)
def _clear_errors() -> Any:
    health._operation_errors.clear()
    yield
    health._operation_errors.clear()


def _service_with_healthy_probe() -> LLMHealthService:
    svc = LLMHealthService()

    def fake_uncached(uc: UseCase) -> Dict[str, Any]:
        return {
            "use_case": uc.value,
            "status": "healthy",
            "detail": "Verfügbar.",
            "checks": {"connectivity": {"reachable": True, "detail": "models.list ok"}},
        }

    svc._check_use_case_uncached = fake_uncached  # type: ignore[method-assign]
    return svc


def test_classify_zero_quota_429_is_unavailable() -> None:
    assert classify_operation_error(429, {"X-RateLimit-Limit-Req-Minute": "0"}) == "unavailable"
    assert classify_operation_error(429, {"x-ratelimit-limit-req-minute": "60"}) == "degraded"
    assert classify_operation_error(401) == "unavailable"
    assert classify_operation_error(503) == "degraded"


def test_recent_error_overrides_green_probe_and_cache() -> None:
    svc = _service_with_healthy_probe()
    assert svc.check_use_case(UseCase.OCR_PDF)["status"] == "healthy"  # füllt Cache

    record_operation_result(
        UseCase.OCR_PDF, ok=False, http_status=429,
        detail="Rate limit exceeded", headers={"x-ratelimit-limit-req-minute": "0"},
    )
    res = svc.check_use_case(UseCase.OCR_PDF)
    assert res["status"] == "unavailable"
    assert res["checks"]["recent_errors"]["http_status"] == 429
    assert svc.check_endpoint("pdf")["status"] == "unavailable"

    record_operation_result(UseCase.OCR_PDF, ok=True)
    assert svc.check_use_case(UseCase.OCR_PDF)["status"] == "healthy"


def test_error_expires_after_window(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = _service_with_healthy_probe()
    record_operation_result(UseCase.OCR_PDF, ok=False, http_status=503)
    assert svc.check_use_case(UseCase.OCR_PDF)["status"] == "degraded"

    real_time = health.time.time
    monkeypatch.setattr(
        health.time, "time", lambda: real_time() + health.OPERATION_ERROR_WINDOW_S + 1
    )
    assert svc.check_use_case(UseCase.OCR_PDF, use_cache=False)["status"] == "healthy"
