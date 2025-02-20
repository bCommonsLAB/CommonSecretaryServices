"""Tests für die Metadata API."""
import pytest
from io import BytesIO
from pathlib import Path
import json
from src.api.routes import blueprint as api_blueprint
from flask import Flask
from flask.testing import FlaskClient
from typing import Any, Dict

@pytest.fixture
def app() -> Flask:
    """Erstellt eine Flask Test-App."""
    app = Flask(__name__)
    app.register_blueprint(api_blueprint)
    return app

@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Erstellt einen Test-Client."""
    return app.test_client()

def test_extract_metadata_success(client: FlaskClient) -> None:
    """Test für erfolgreiche Metadaten-Extraktion."""
    # Test-Datei erstellen (minimales PDF)
    test_content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"
    test_file = BytesIO(test_content)
    test_file.name = "test.pdf"
    
    # Zusätzliche Parameter
    content = "Zusätzlicher Inhalt für die Analyse"
    context: Dict[str, Any] = {"key": "value"}
    
    # Multipart-Request senden
    response = client.post(
        "/extract-metadata",
        data={
            "file": (test_file, "test.pdf"),
            "content": content,
            "context": json.dumps(context)
        },
        content_type="multipart/form-data"
    )
    
    # Response überprüfen
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))
    
    # Struktur überprüfen
    assert "status" in data
    assert "request" in data
    assert "process" in data
    assert "data" in data
    
    # Status überprüfen
    assert data["status"] == "success"
    
    # Request-Informationen überprüfen
    assert data["request"]["processor"] == "metadata"
    assert data["request"]["parameters"]["has_content"] is True
    assert "context_keys" in data["request"]["parameters"]
    
    # Process-Informationen überprüfen
    assert "id" in data["process"]
    assert data["process"]["main_processor"] == "metadata"
    assert "started" in data["process"]
    assert "completed" in data["process"]
    
    # Daten überprüfen
    assert "technical" in data["data"]
    assert data["data"]["technical"]["file_mime"] == "application/pdf"

def test_extract_metadata_error(client: FlaskClient) -> None:
    """Test für Fehlerfall bei der Metadaten-Extraktion."""
    # Ungültige Datei (leeres BytesIO)
    test_file = BytesIO()
    test_file.name = "invalid.xyz"
    
    # Request senden
    response = client.post(
        "/extract-metadata",
        data={
            "file": (test_file, "invalid.xyz")
        },
        content_type="multipart/form-data"
    )
    
    # Response überprüfen
    assert response.status_code == 400
    data = json.loads(response.get_data(as_text=True))
    
    # Struktur überprüfen
    assert "status" in data
    assert "request" in data
    assert "process" in data
    assert "error" in data
    
    # Status und Error überprüfen
    assert data["status"] == "error"
    assert data["error"]["code"] == "UnsupportedMimeTypeError"
    assert "MIME-Type nicht unterstützt" in data["error"]["message"]

def test_extract_metadata_with_pdf(client: FlaskClient, tmp_path: Path) -> None:
    """Test für Metadaten-Extraktion aus einer PDF-Datei."""
    # PDF-Testdatei laden
    pdf_path = Path("tests/sample.pdf")
    if not pdf_path.exists():
        pytest.skip("PDF-Testdatei nicht gefunden")
    
    with open(pdf_path, "rb") as f:
        # Request senden
        response = client.post(
            "/extract-metadata",
            data={
                "file": (f, "sample.pdf")
            },
            content_type="multipart/form-data"
        )
    
    # Response überprüfen
    assert response.status_code == 200
    data = json.loads(response.get_data(as_text=True))
    
    # Struktur überprüfen
    assert data["status"] == "success"
    assert "technical" in data["data"]
    assert data["data"]["technical"]["file_mime"] == "application/pdf"
    assert "doc_pages" in data["data"]["technical"] 