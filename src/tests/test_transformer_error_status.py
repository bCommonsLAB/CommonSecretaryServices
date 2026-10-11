"""Tests: gescheiterte Transformationen kommen als Fehler beim Client an.

Prod 10.10.2026: OpenRouter wies eine ungueltige Modellkennung ab. Der Processor
lieferte eine Antwort mit ``error``; die Route verpackte sie ein zweites Mal und
schickte aussen ``status: "success"`` mit HTTP 200, die Fehlerantwort steckte in
``data``. Geprueft wird jetzt fuer /template (Text und Vorlage) und den Helfer, den
auch /text und /text/file nutzen:

- aussen ``status: "error"``, HTTP 400, ``error.code`` und ``error.message`` des Processors
- kein Traceback in der Antwort an den Client
- ein erfolgreiches Ergebnis bleibt unveraendert (HTTP 200, ``status: "success"``)
"""

import unittest
from datetime import datetime
from typing import Any, Dict, Optional
from unittest.mock import patch

from flask import Flask

from src.api.routes import transformer_routes
from src.api.routes.transformer_routes import (
    FAILED_TRANSFORMATION_STATUS,
    TemplateTransformEndpoint,
    _failed_result_response,
)
from src.core.models.base import ErrorInfo, ProcessInfo
from src.core.models.transformer import TransformerResponse
from src.processors.transformer_processor import TransformerProcessor

OPENROUTER_FEHLER = (
    "Fehler bei der Template-Transformation: LLM-Anfrage fehlgeschlagen. Modell: "
    "deepseek/deepseek-v4-flash-latest. Fehler: 'deepseek/deepseek-v4-flash-latest is not a valid model ID'"
)


def _processor(fail: bool) -> TransformerProcessor:
    """Processor ohne LLM- und Datenbank-Anbindung; create_response ist der echte."""
    processor = object.__new__(TransformerProcessor)
    processor.process_info = ProcessInfo(
        id="p-test", main_processor="TransformerProcessor", started=datetime.now().isoformat()
    )

    def transform_by_template(**_kwargs: Any) -> TransformerResponse:
        if fail:
            return processor.create_response(
                processor_name="transformer",
                result=None,
                request_info={"template": ""},
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=ErrorInfo(
                    code="TEMPLATE_TRANSFORMATION_ERROR",
                    message=OPENROUTER_FEHLER,
                    details={"error_type": "ProcessingError", "traceback": "Traceback (most recent call last): ..."},
                ),
            )
        from src.core.models.enums import OutputFormat
        from src.core.models.transformer import TransformerData

        return processor.create_response(
            processor_name="transformer",
            result=TransformerData(text="Fertig.", language="de", format=OutputFormat.TEXT, structured_data={"title": "T"}),
            request_info={"template": ""},
            response_class=TransformerResponse,
            from_cache=False,
            cache_key="",
        )

    setattr(processor, "transformByTemplate", transform_by_template)
    return processor


def _post_template(processor: TransformerProcessor) -> tuple[Dict[str, Any], int]:
    app = Flask(__name__)
    form = {"text": "Ein kurzer Text.", "template_content": "---\ntitle: {{title}}\n---\n{{text}}", "useCache": "false"}
    with patch.object(transformer_routes, "get_transformer_processor", return_value=processor):
        with app.test_request_context("/api/transformer/template", method="POST", data=form):
            result: Any = TemplateTransformEndpoint().post()
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, 200


class TestTemplateRoute(unittest.TestCase):
    def test_failed_transformation_is_an_error_on_the_outside(self) -> None:
        body, status = _post_template(_processor(fail=True))

        self.assertEqual(status, FAILED_TRANSFORMATION_STATUS)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error"]["code"], "TEMPLATE_TRANSFORMATION_ERROR")
        self.assertIn("not a valid model ID", body["error"]["message"])
        # Keine verschachtelte Fehlerantwort mehr in data.
        self.assertFalse(isinstance(body.get("data"), dict) and body["data"].get("status") == "error")

    def test_traceback_does_not_reach_the_client(self) -> None:
        body, _status = _post_template(_processor(fail=True))
        self.assertNotIn("traceback", body["error"].get("details", {}))
        self.assertEqual(body["error"]["details"].get("error_type"), "ProcessingError")

    def test_successful_transformation_is_unchanged(self) -> None:
        body, status = _post_template(_processor(fail=False))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["data"]["structured_data"], {"title": "T"})


class TestHelfer(unittest.TestCase):
    def test_no_error_means_no_error_response(self) -> None:
        processor = _processor(fail=False)
        ok = getattr(processor, "transformByTemplate")()
        self.assertIsNone(_failed_result_response(processor, ok, {}))

    def test_error_status_without_error_object_gets_a_generic_error(self) -> None:
        processor = _processor(fail=False)

        class _Kaputt:
            error: Optional[ErrorInfo] = None
            status = transformer_routes.ProcessingStatus.ERROR

        failed = _failed_result_response(processor, _Kaputt(), {"text": "x"})
        assert failed is not None
        body, status = failed
        self.assertEqual(status, FAILED_TRANSFORMATION_STATUS)
        self.assertEqual(body["error"]["code"], "TRANSFORMATION_ERROR")


if __name__ == "__main__":
    unittest.main()
