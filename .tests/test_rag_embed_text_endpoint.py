from typing import Any, Dict

from flask import Flask

from src.api import create_app


def _get_test_client() -> Any:
    """Hilfsfunktion, um einen Flask-Test-Client für die API zu erstellen."""
    app: Flask = create_app()
    app.testing = True
    return app.test_client()


def test_embed_text_uses_default_embedding_model_when_not_specified() -> None:
    """Ohne embedding_model-Parameter wird das Defaultmodell verwendet und in der Response zurückgegeben."""
    client = _get_test_client()

    payload: Dict[str, Any] = {
        "markdown": "# Überschrift\n\nDies ist ein Testdokument."
    }

    response = client.post("/api/rag/embed-text", json=payload)
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data.get("status") == "success"

    # Embedding-Ergebnis prüfen
    result_data = data.get("data") or {}
    embedding_model = result_data.get("embedding_model")
    # Das Modell muss gesetzt sein, auch wenn der Client keines übergeben hat
    assert isinstance(embedding_model, str)
    assert embedding_model


def test_embed_text_accepts_explicit_embedding_model() -> None:
    """Mit explizitem embedding_model wird dieses Modell in der Response gespiegelt."""
    client = _get_test_client()

    requested_model = "voyage-context-3"
    payload: Dict[str, Any] = {
        "markdown": "# Überschrift\n\nDies ist ein Testdokument.",
        "embedding_model": requested_model,
    }

    response = client.post("/api/rag/embed-text", json=payload)
    assert response.status_code == 200

    data = response.get_json()
    assert data is not None
    assert data.get("status") == "success"

    result_data = data.get("data") or {}
    embedding_model = result_data.get("embedding_model")
    assert embedding_model == requested_model



