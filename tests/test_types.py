import pytest
from datetime import datetime
from src.utils.types import BaseResponse, TransformerResponse, LLModel

def test_base_response_success():
    """Test für erfolgreiche Response"""
    response = BaseResponse(
        status="success",
        request={
            "processor": "test",
            "timestamp": datetime.now().isoformat(),
            "parameters": {"param1": "value1"}
        },
        process={
            "id": "123",
            "main_processor": "test",
            "sub_processors": [],
            "duration": 1.0,
            "started": datetime.now().isoformat(),
            "completed": datetime.now().isoformat()
        },
        data={"test": "data"}
    )
    assert response.status == "success"
    assert response.request["processor"] == "test"
    assert response.process["id"] == "123"
    assert response.data["test"] == "data"
    assert response.error is None
    assert "llm_info" in response.process
    assert response.process["llm_info"]["requests_count"] == 0

def test_base_response_error():
    """Test für Fehler-Response"""
    response = BaseResponse(
        status="error",
        request={
            "processor": "test",
            "timestamp": datetime.now().isoformat()
        },
        process={
            "id": "123",
            "main_processor": "test"
        },
        error={
            "code": "TEST_ERROR",
            "message": "Test Fehlermeldung"
        }
    )
    assert response.status == "error"
    assert response.error["code"] == "TEST_ERROR"
    assert response.data is None

def test_base_response_validation():
    """Test für Validierungsregeln"""
    # Error ohne error-Info sollte fehlschlagen
    with pytest.raises(ValueError):
        BaseResponse(status="error")
    
    # Success mit error-Info sollte fehlschlagen
    with pytest.raises(ValueError):
        BaseResponse(
            status="success",
            error={"code": "TEST_ERROR"}
        )

def test_base_response_defaults():
    """Test für Default-Werte"""
    response = BaseResponse()
    assert response.status == "success"
    assert isinstance(response.request, dict)
    assert isinstance(response.process, dict)
    assert response.data is None
    assert response.error is None

def test_base_response_llm():
    """Test für LLM-Request Tracking"""
    response = BaseResponse()
    
    # Füge einen LLM-Request hinzu
    response.add_llm_request(
        model="gpt-4",
        purpose="translation",
        tokens=100,
        duration=1.5
    )
    
    assert response.process["llm_info"]["requests_count"] == 1
    assert response.process["llm_info"]["total_tokens"] == 100
    assert response.process["llm_info"]["total_duration"] == 1.5
    assert len(response.process["llm_info"]["requests"]) == 1
    
    # Prüfe Request-Details
    request = response.process["llm_info"]["requests"][0]
    assert request["model"] == "gpt-4"
    assert request["purpose"] == "translation"
    assert request["tokens"] == 100
    assert request["duration"] == 1.5
    assert "timestamp" in request

def test_transformer_response_success():
    """Test für erfolgreiche TransformerResponse"""
    response = TransformerResponse(
        input_text="Hello",
        input_language="en",
        output_text="Hallo",
        output_language="de",
        model="gpt-4",
        task="translation",
        duration=1.5,
        token_count=10,
        request={
            "processor": "transformer",
            "timestamp": datetime.now().isoformat()
        },
        process={
            "id": "123",
            "main_processor": "transformer"
        }
    )
    assert response.status == "success"
    # Prüfe Input-Struktur
    assert response.data["input"]["text"] == "Hello"
    assert response.data["input"]["language"] == "en"
    # Prüfe Output-Struktur
    assert response.data["output"]["text"] == "Hallo"
    assert response.data["output"]["language"] == "de"
    # Prüfe Transform-Struktur
    assert response.data["transform"]["model"] == "gpt-4"
    assert response.data["transform"]["task"] == "translation"
    assert response.data["transform"]["duration"] == 1.5
    assert response.data["transform"]["token_count"] == 10
    # Prüfe LLM-Tracking
    assert "llm_info" in response.process
    assert response.process["llm_info"]["requests_count"] == 1
    assert len(response.process["llm_info"]["requests"]) == 1
    assert response.process["llm_info"]["requests"][0]["model"] == "gpt-4"

def test_transformer_response_template():
    """Test für TransformerResponse mit Template"""
    response = TransformerResponse(
        input_text="Meeting Notizen",
        template_name="meeting",
        template_variables={
            "title": "Team Meeting",
            "date": "2024-03-20"
        },
        output_text="# Team Meeting\n\nDatum: 2024-03-20\n\nNotizen:\nMeeting Notizen",
        output_format="markdown",
        model="gpt-4",
        task="template_transform",
        duration=1.2,
        token_count=15
    )
    assert response.status == "success"
    # Prüfe Template-Informationen
    assert response.data["input"]["template"] == "meeting"
    assert response.data["input"]["variables"]["title"] == "Team Meeting"
    assert response.data["input"]["variables"]["date"] == "2024-03-20"
    # Prüfe Output-Format
    assert response.data["output"]["format"] == "markdown"
    # Prüfe Transform-Informationen
    assert response.data["transform"]["task"] == "template_transform"
    # Prüfe LLM-Tracking
    assert response.process["llm_info"]["requests_count"] == 1

def test_transformer_response_error():
    """Test für Fehler-TransformerResponse"""
    response = TransformerResponse(
        status="error",
        request={
            "processor": "transformer",
            "timestamp": datetime.now().isoformat()
        },
        process={
            "id": "123",
            "main_processor": "transformer"
        },
        error={
            "code": "TRANSFORM_ERROR",
            "message": "Transformation fehlgeschlagen"
        }
    )
    assert response.status == "error"
    assert response.error["code"] == "TRANSFORM_ERROR"
    assert response.data == {}

def test_transformer_response_partial():
    """Test für TransformerResponse mit teilweisen Daten"""
    response = TransformerResponse(
        input_text="Hello",
        model="gpt-4"
    )
    assert response.status == "success"
    assert response.data["input"]["text"] == "Hello"
    assert response.data["transform"]["model"] == "gpt-4"
    assert response.data["output"]["text"] is None
    assert response.data["transform"]["task"] is None
    assert response.error is None

    llm_usage = LLModel(
        model="gpt-4",
        duration=0.5,
        tokens=15
    ) 