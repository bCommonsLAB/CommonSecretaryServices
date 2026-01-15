from typing import Any, Dict, cast

import pytest


def _voyageai_available() -> bool:
    """
    Diese Tests erfordern (aktuell) das optionale Paket `voyageai`.
    In Entwicklungsumgebungen ist es nicht immer installiert, daher skippen wir
    die Tests sauber, statt hard-fail.
    """
    try:
        import voyageai  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False

from flask import Flask

from src.api import create_app


def _get_test_client() -> Any:
    """Hilfsfunktion, um einen Flask-Test-Client für die API zu erstellen."""
    app: Flask = create_app()
    app.testing = True
    return app.test_client()


def test_embed_text_uses_default_embedding_model_when_not_specified() -> None:
    """Ohne embedding_model-Parameter wird das Defaultmodell verwendet und in der Response zurückgegeben."""
    if not _voyageai_available():
        pytest.skip("voyageai ist nicht installiert")
    client = _get_test_client()

    payload: Dict[str, Any] = {
        "markdown": "# Überschrift\n\nDies ist ein Testdokument."
    }

    response = client.post("/api/rag/embed-text", json=payload)
    assert response.status_code == 200

    data_any = response.get_json()
    assert isinstance(data_any, dict)
    data = cast(Dict[str, Any], data_any)
    assert data.get("status") == "success"

    # Embedding-Ergebnis prüfen
    # `get_json()` liefert dynamisches JSON -> explizit casten für Type-Checker
    result_data = cast(Dict[str, Any], data.get("data") or {})
    embedding_model_any = result_data.get("embedding_model")
    embedding_model = str(embedding_model_any) if embedding_model_any is not None else ""
    # Das Modell muss gesetzt sein, auch wenn der Client keines übergeben hat
    assert isinstance(embedding_model, str)
    assert embedding_model


def test_embed_text_accepts_explicit_embedding_model() -> None:
    """Mit explizitem embedding_model wird dieses Modell in der Response gespiegelt."""
    if not _voyageai_available():
        pytest.skip("voyageai ist nicht installiert")
    client = _get_test_client()

    requested_model = "voyage-2"
    payload: Dict[str, Any] = {
        "markdown": "# Überschrift\n\nDies ist ein Testdokument.",
        "embedding_model": requested_model,
    }

    response = client.post("/api/rag/embed-text", json=payload)
    assert response.status_code == 200

    data_any = response.get_json()
    assert isinstance(data_any, dict)
    data = cast(Dict[str, Any], data_any)
    assert data.get("status") == "success"

    result_data = cast(Dict[str, Any], data.get("data") or {})
    embedding_model = result_data.get("embedding_model")
    assert embedding_model == requested_model




