"""Tests: Chat-Aufrufe und Embeddings stehen mit Modell, Tokens und Kosten in der Metrik.

Prod 10.11.2026: Alle Eintraege von /api/transformer/chat in request_metrics hatten
total_tokens 0, models_used [] und weder priced noch unpriced. Ursache: die Route
setzte process.llm_info direkt, am Metrik-Tracker vorbei. Geprueft wird:

- der Chat-Aufruf landet ueber add_llm_requests im Tracker (Modell, Tokens, Kosten)
- ohne Betrag vom Provider zaehlt er als unpriced, nicht als 0
- die Antwort traegt additiv ``usage`` (Eingabe-/Ausgabe-/Gesamt-Tokens, Modell, Kosten)
- Korrelations-Header werden als Kennungen am Metrik-Eintrag gespeichert, Freitext nicht
- voyage-3-large hat einen Listenpreis, ein unbekanntes Embedding-Modell keinen
- weder Metrik noch usage enthalten Nachrichteninhalt
"""

import json
import unittest
from datetime import datetime
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from flask import Flask

from src.api.routes import transformer_routes
from src.api.routes.transformer_routes import ChatEndpoint
from src.core.llm.embedding_cost import estimate_embedding_cost, has_embedding_price
from src.core.models.base import ProcessInfo
from src.core.models.llm import LLMRequest
from src.processors.transformer_processor import TransformerProcessor
from src.utils import performance_tracker as tracker_module
from src.utils.correlation import correlation_from_headers, rejected_correlation_headers
from src.utils.performance_tracker import (
    PerformanceTracker,
    clear_performance_tracker,
    get_performance_tracker,
)

GEHEIMER_PROMPT = "GEHEIM-Inhalt-der-Frage-4711"
MODELL = "google/gemini-2.5-flash"


class _FakeProvider:
    """Provider-Ersatz: liefert ein LLMRequest wie der OpenRouter-Provider."""

    def __init__(self, cost: float, with_split: bool = True) -> None:
        self.cost = cost
        self.with_split = with_split
        self.calls: List[str] = []

    def chat_completion(self, messages: List[Dict[str, str]], model: str, **_kwargs: Any) -> tuple[str, LLMRequest]:
        self.calls.append(model)
        return "Antwort.", LLMRequest(
            model=model,
            purpose="chat_completion",
            tokens=84170,
            duration=11788.0,
            processor="OpenRouterProvider",
            cost=self.cost,
            prompt_tokens=80449 if self.with_split else None,
            completion_tokens=3721 if self.with_split else None,
        )


class _FakeConfigManager:
    provider: Optional[_FakeProvider] = None

    def get_model_for_use_case(self, _use_case: Any) -> str:
        return "deepseek/deepseek-v4.1-flash"

    def get_use_case_config(self, _use_case: Any) -> None:
        return None

    def get_provider_for_use_case(self, _use_case: Any) -> Optional[_FakeProvider]:
        return _FakeConfigManager.provider


def _processor() -> TransformerProcessor:
    """Processor ohne LLM- und Datenbank-Anbindung; add_llm_requests/create_response sind echt."""
    processor = object.__new__(TransformerProcessor)
    processor.process_info = ProcessInfo(
        id="p-test", main_processor="TransformerProcessor", started=datetime.now().isoformat()
    )
    return processor


def _post_chat(provider: _FakeProvider, model: Optional[str] = MODELL) -> tuple[Dict[str, Any], int, PerformanceTracker]:
    """Ruft die Chat-Route mit einem frischen Thread-Tracker auf."""
    clear_performance_tracker()
    tracker = get_performance_tracker("t-chat")
    assert tracker is not None
    _FakeConfigManager.provider = provider
    body: Dict[str, Any] = {"messages": [{"role": "user", "content": GEHEIMER_PROMPT}]}
    if model:
        body["model"] = model
    app = Flask(__name__)
    try:
        with patch.object(transformer_routes, "get_transformer_processor", return_value=_processor()), \
                patch.object(transformer_routes, "LLMConfigManager", _FakeConfigManager):
            with app.test_request_context("/api/transformer/chat", method="POST", json=body):
                result: Any = ChatEndpoint().post()
    finally:
        clear_performance_tracker()
    if isinstance(result, tuple):
        return result[0], result[1], tracker
    return result, 200, tracker


class TestChatMetrik(unittest.TestCase):
    def test_chat_call_reaches_the_metric_tracker(self) -> None:
        body, status, tracker = _post_chat(_FakeProvider(cost=0.0123))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        res = tracker.measurements["resources"]
        self.assertEqual(res["models_used"], [MODELL])
        self.assertEqual(res["total_tokens"], 84170)
        self.assertAlmostEqual(res["total_cost"], 0.0123)
        self.assertEqual(res["priced_requests"], 1)
        self.assertEqual(res["unpriced_requests"], 0)

    def test_call_without_price_counts_as_unpriced(self) -> None:
        body, _status, tracker = _post_chat(_FakeProvider(cost=0.0))
        res = tracker.measurements["resources"]
        self.assertEqual(res["priced_requests"], 0)
        self.assertEqual(res["unpriced_requests"], 1)
        self.assertEqual(res["total_tokens"], 84170)
        self.assertIsNone(body["usage"]["cost"])

    def test_response_carries_usage(self) -> None:
        body, _status, _tracker = _post_chat(_FakeProvider(cost=0.0123))
        self.assertEqual(body["usage"], {
            "model": MODELL,
            "prompt_tokens": 80449,
            "completion_tokens": 3721,
            "total_tokens": 84170,
            "cost": 0.0123,
            "cost_currency": "USD",
        })
        # Bestehendes Format bleibt: Antworttext und llm_info wie zuvor.
        self.assertEqual(body["data"]["text"], "Antwort.")
        requests = body["process"]["llm_info"]["requests"]
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["model"], MODELL)

    def test_missing_token_split_is_null_not_zero(self) -> None:
        body, _status, _tracker = _post_chat(_FakeProvider(cost=0.01, with_split=False))
        self.assertIsNone(body["usage"]["prompt_tokens"])
        self.assertIsNone(body["usage"]["completion_tokens"])
        self.assertEqual(body["usage"]["total_tokens"], 84170)

    def test_request_model_wins_over_default(self) -> None:
        provider = _FakeProvider(cost=0.01)
        _post_chat(provider, model=MODELL)
        self.assertEqual(provider.calls, [MODELL])
        default_provider = _FakeProvider(cost=0.01)
        _body, _status, tracker = _post_chat(default_provider, model=None)
        self.assertEqual(default_provider.calls, ["deepseek/deepseek-v4.1-flash"])
        self.assertEqual(tracker.measurements["resources"]["models_used"], ["deepseek/deepseek-v4.1-flash"])

    def test_exactly_one_model_call_per_request(self) -> None:
        provider = _FakeProvider(cost=0.01)
        _post_chat(provider)
        self.assertEqual(len(provider.calls), 1)

    def test_no_prompt_content_in_metric_or_usage(self) -> None:
        body, _status, tracker = _post_chat(_FakeProvider(cost=0.01))
        self.assertNotIn(GEHEIMER_PROMPT, json.dumps(tracker.measurements, default=str))
        self.assertNotIn(GEHEIMER_PROMPT, json.dumps(body["usage"]))
        self.assertNotIn(GEHEIMER_PROMPT, json.dumps(body["request"], default=str))


class TestKorrelation(unittest.TestCase):
    def test_ids_are_read_from_headers(self) -> None:
        headers = {
            "X-Query-Id": "de0bd6c0-f409-4d95-9aeb-1c2c152fca6f",
            "X-Library-Id": "67774136-d829-412b-8c78-7d0f2d3f4bcd",
            "X-Chat-Id": "f44aed61-1fc1-4157-badd-8e11897c376d",
            "X-Job-Id": "job_1",
        }
        self.assertEqual(correlation_from_headers(headers), {
            "query_id": "de0bd6c0-f409-4d95-9aeb-1c2c152fca6f",
            "library_id": "67774136-d829-412b-8c78-7d0f2d3f4bcd",
            "chat_id": "f44aed61-1fc1-4157-badd-8e11897c376d",
            "job_id": "job_1",
        })
        self.assertEqual(rejected_correlation_headers(headers), [])

    def test_free_text_is_rejected(self) -> None:
        headers = {"X-Query-Id": "Wie wird Europa souveraen?", "X-Chat-Id": "x" * 129, "X-Library-Id": "lib-1"}
        self.assertEqual(correlation_from_headers(headers), {"library_id": "lib-1"})
        self.assertEqual(rejected_correlation_headers(headers), ["X-Query-Id", "X-Chat-Id"])

    def test_missing_headers_give_empty_result(self) -> None:
        self.assertEqual(correlation_from_headers({}), {})

    def test_correlation_is_stored_with_the_metric_entry(self) -> None:
        recorded: List[Dict[str, Any]] = []

        class _Repo:
            def record(self, doc: Dict[str, Any]) -> None:
                recorded.append(doc)

        tracker = PerformanceTracker("t-korr")
        tracker.set_correlation({"query_id": "q-1", "library_id": "l-1"})
        with patch("src.core.mongodb.get_metrics_repository", return_value=_Repo()):
            tracker.complete_tracking()
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["correlation"], {"query_id": "q-1", "library_id": "l-1"})

    def test_before_request_hook_applies_headers(self) -> None:
        from src.dashboard import app as dashboard_app

        clear_performance_tracker()
        try:
            with dashboard_app.app.test_request_context(
                "/api/rag/embed-text", method="POST", headers={"X-Query-Id": "q-42", "X-Chat-Id": "kein gueltiger wert"}
            ):
                dashboard_app._maybe_start_request_tracker()  # pyright: ignore[reportPrivateUsage]
                tracker = get_performance_tracker()
                assert tracker is not None
                self.assertEqual(tracker.measurements["correlation"], {"query_id": "q-42"})
                self.assertEqual(tracker.processor_name, "rag")
        finally:
            clear_performance_tracker()


class TestEmbeddingPreis(unittest.TestCase):
    def test_voyage_3_large_has_a_list_price(self) -> None:
        self.assertTrue(has_embedding_price("voyage-3-large"))
        self.assertAlmostEqual(estimate_embedding_cost("voyage-3-large", 1_000_000), 0.18)
        self.assertGreater(estimate_embedding_cost("voyage-3-large", 9), 0.0)

    def test_unknown_model_has_no_price(self) -> None:
        self.assertFalse(has_embedding_price("unbekanntes-modell"))
        self.assertEqual(estimate_embedding_cost("unbekanntes-modell", 1000), 0.0)

    def test_embedding_is_counted_as_priced(self) -> None:
        tracker = PerformanceTracker("t-embed")
        tracker.add_llm_request_list([LLMRequest(
            model="voyage-3-large", purpose="embedding", tokens=17, duration=0.0,
            processor="RAGProcessor", cost=estimate_embedding_cost("voyage-3-large", 17),
        )])
        res = tracker.measurements["resources"]
        self.assertEqual(res["priced_requests"], 1)
        self.assertEqual(res["unpriced_requests"], 0)


class TestLLMRequestAufteilung(unittest.TestCase):
    def test_split_is_only_serialized_when_reported(self) -> None:
        ohne = LLMRequest(model="m", purpose="p", tokens=5, duration=1.0, processor="x")
        self.assertNotIn("prompt_tokens", ohne.to_dict())
        mit = LLMRequest(model="m", purpose="p", tokens=5, duration=1.0, processor="x", prompt_tokens=3, completion_tokens=2)
        self.assertEqual(mit.to_dict()["prompt_tokens"], 3)
        self.assertEqual(LLMRequest.from_dict(mit.to_dict()).completion_tokens, 2)


if __name__ == "__main__":
    unittest.main()
