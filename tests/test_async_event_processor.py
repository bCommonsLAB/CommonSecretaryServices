"""
Test für die asynchrone Event-Verarbeitung mit Webhook-Callbacks.
"""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List

from src.processors.event_processor import EventProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.event import WebhookConfig, AsyncEventInput, AsyncBatchEventInput

@pytest.fixture
def event_processor():
    """Erstellt eine Instanz des EventProcessors für Tests."""
    resource_calculator = ResourceCalculator()
    return EventProcessor(resource_calculator=resource_calculator)

@pytest.fixture
def webhook_config():
    """Erstellt eine Test-Webhook-Konfiguration."""
    return WebhookConfig(
        url="https://example.com/webhook",
        headers={"Authorization": "Bearer test-token"},
        include_markdown=True,
        include_metadata=True,
        event_id="test-event-123"
    )

@pytest.fixture
def async_event_input(webhook_config):
    """Erstellt Test-Eingabedaten für die asynchrone Event-Verarbeitung."""
    return AsyncEventInput(
        event="Test Event",
        session="Test Session",
        url="https://example.com/event",
        filename="test-event.md",
        track="Test Track",
        day="2025-01-01",
        starttime="10:00",
        endtime="11:00",
        speakers=["Test Speaker"],
        video_url="https://example.com/video.mp4",
        attachments_url="https://example.com/attachments.pdf",
        source_language="en",
        target_language="de",
        webhook=webhook_config
    )

@pytest.fixture
def async_batch_input(webhook_config):
    """Erstellt Test-Eingabedaten für die asynchrone Batch-Verarbeitung."""
    return AsyncBatchEventInput(
        events=[
            {
                "event": "Test Event 1",
                "session": "Test Session 1",
                "url": "https://example.com/event1",
                "filename": "test-event-1.md",
                "track": "Test Track",
                "day": "2025-01-01",
                "starttime": "10:00",
                "endtime": "11:00",
                "speakers": ["Test Speaker 1"],
                "video_url": "https://example.com/video1.mp4",
                "attachments_url": "https://example.com/attachments1.pdf",
                "source_language": "en",
                "target_language": "de"
            },
            {
                "event": "Test Event 2",
                "session": "Test Session 2",
                "url": "https://example.com/event2",
                "filename": "test-event-2.md",
                "track": "Test Track",
                "day": "2025-01-01",
                "starttime": "11:00",
                "endtime": "12:00",
                "speakers": ["Test Speaker 2"],
                "video_url": "https://example.com/video2.mp4",
                "attachments_url": "https://example.com/attachments2.pdf",
                "source_language": "en",
                "target_language": "de"
            }
        ],
        webhook=webhook_config
    )

@patch('requests.post')
@patch('src.processors.event_processor.EventProcessor.process_event')
async def test_process_event_async(mock_process_event, mock_post, event_processor, async_event_input):
    """Testet die asynchrone Verarbeitung eines einzelnen Events."""
    # Mock für die Event-Verarbeitung einrichten
    mock_response = MagicMock()
    mock_response.status = "success"
    mock_response.data.output.markdown_file = "/path/to/test-event.md"
    mock_response.data.output.markdown_content = "# Test Event\n\nTest content"
    mock_response.data.output.metadata = {"test": "metadata"}
    mock_process_event.return_value = mock_response
    
    # Mock für den Webhook-Request einrichten
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post.return_value = mock_post_response
    
    # Asynchrone Event-Verarbeitung starten
    result = await event_processor.process_event_async(
        event=async_event_input.event,
        session=async_event_input.session,
        url=async_event_input.url,
        filename=async_event_input.filename,
        track=async_event_input.track,
        webhook_url=async_event_input.webhook.url,
        day=async_event_input.day,
        starttime=async_event_input.starttime,
        endtime=async_event_input.endtime,
        speakers=async_event_input.speakers,
        video_url=async_event_input.video_url,
        attachments_url=async_event_input.attachments_url,
        source_language=async_event_input.source_language,
        target_language=async_event_input.target_language,
        webhook_headers=async_event_input.webhook.headers,
        include_markdown=async_event_input.webhook.include_markdown,
        include_metadata=async_event_input.webhook.include_metadata,
        event_id=async_event_input.webhook.event_id
    )
    
    # Prüfen, ob die Antwort korrekt ist
    assert result.status == "success"
    assert result.request.event == async_event_input.event
    assert result.request.session == async_event_input.session
    assert result.request.async_processing is True
    
    # Warten, bis die asynchrone Verarbeitung abgeschlossen ist
    await asyncio.sleep(0.1)
    
    # Prüfen, ob process_event aufgerufen wurde
    mock_process_event.assert_called_once_with(
        event=async_event_input.event,
        session=async_event_input.session,
        url=async_event_input.url,
        filename=async_event_input.filename,
        track=async_event_input.track,
        day=async_event_input.day,
        starttime=async_event_input.starttime,
        endtime=async_event_input.endtime,
        speakers=async_event_input.speakers,
        video_url=async_event_input.video_url,
        attachments_url=async_event_input.attachments_url,
        source_language=async_event_input.source_language,
        target_language=async_event_input.target_language
    )

@patch('requests.post')
@patch('src.processors.event_processor.EventProcessor._process_event_async_task')
async def test_process_many_events_async(mock_process_task, mock_post, event_processor, async_batch_input):
    """Testet die asynchrone Verarbeitung mehrerer Events."""
    # Mock für die Event-Verarbeitung einrichten
    mock_process_task.return_value = None
    
    # Mock für den Webhook-Request einrichten
    mock_post_response = MagicMock()
    mock_post_response.status_code = 200
    mock_post.return_value = mock_post_response
    
    # Asynchrone Batch-Verarbeitung starten
    result = await event_processor.process_many_events_async(
        events=async_batch_input.events,
        webhook_url=async_batch_input.webhook.url,
        webhook_headers=async_batch_input.webhook.headers,
        include_markdown=async_batch_input.webhook.include_markdown,
        include_metadata=async_batch_input.webhook.include_metadata,
        batch_id=async_batch_input.webhook.event_id
    )
    
    # Prüfen, ob die Antwort korrekt ist
    assert result.status == "success"
    assert result.request.event_count == len(async_batch_input.events)
    assert result.request.webhook_url == async_batch_input.webhook.url
    assert result.request.batch_id == async_batch_input.webhook.event_id
    assert result.request.async_processing is True
    
    # Prüfen, ob die Ausgabedaten korrekt sind
    assert result.data.output.summary.total_events == len(async_batch_input.events)
    assert result.data.output.summary.status == "accepted"
    assert result.data.output.summary.batch_id == async_batch_input.webhook.event_id
    assert result.data.output.summary.webhook_url == async_batch_input.webhook.url
    assert result.data.output.summary.async_processing is True
    
    # Warten, bis die asynchrone Verarbeitung abgeschlossen ist
    await asyncio.sleep(0.1)

@patch('requests.post')
async def test_send_webhook_callback(mock_post, event_processor, webhook_config):
    """Testet das Senden eines Webhook-Callbacks."""
    # Mock für den Webhook-Request einrichten
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_post.return_value = mock_response
    
    # Event-Eingabe- und Ausgabedaten erstellen
    from src.core.models.event import EventInput, EventOutput
    event_input = EventInput(
        event="Test Event",
        session="Test Session",
        url="https://example.com/event",
        filename="test-event.md",
        track="Test Track"
    )
    event_output = EventOutput(
        markdown_file="/path/to/test-event.md",
        markdown_content="# Test Event\n\nTest content",
        metadata={"test": "metadata"}
    )
    
    # Webhook-Callback senden
    result = await event_processor._send_webhook_callback(
        webhook_config=webhook_config,
        event_output=event_output,
        event_input=event_input,
        success=True
    )
    
    # Prüfen, ob der Webhook-Request korrekt gesendet wurde
    assert result is True
    mock_post.assert_called_once()
    
    # Prüfen, ob die URL und Header korrekt sind
    args, kwargs = mock_post.call_args
    assert kwargs["url"] == webhook_config.url
    assert kwargs["headers"]["Authorization"] == webhook_config.headers["Authorization"]
    assert kwargs["headers"]["Content-Type"] == "application/json"
    
    # Prüfen, ob die Payload korrekt ist
    payload = kwargs["json"]
    assert payload["event_id"] == webhook_config.event_id
    assert payload["success"] is True
    assert payload["event"] == event_input.event
    assert payload["session"] == event_input.session
    assert payload["file_path"] == event_output.markdown_file
    assert payload["markdown_content"] == event_output.markdown_content
    assert payload["metadata"] == event_output.metadata

@patch('requests.post')
async def test_send_webhook_callback_error(mock_post, event_processor, webhook_config):
    """Testet das Senden eines Webhook-Callbacks bei einem Fehler."""
    # Mock für den Webhook-Request einrichten, der einen Fehler auslöst
    mock_post.side_effect = Exception("Connection error")
    
    # Event-Eingabe- und Ausgabedaten erstellen
    from src.core.models.event import EventInput, EventOutput
    event_input = EventInput(
        event="Test Event",
        session="Test Session",
        url="https://example.com/event",
        filename="test-event.md",
        track="Test Track"
    )
    event_output = EventOutput(
        markdown_file="/path/to/test-event.md",
        markdown_content="# Test Event\n\nTest content",
        metadata={"test": "metadata"}
    )
    
    # Webhook-Callback senden
    result = await event_processor._send_webhook_callback(
        webhook_config=webhook_config,
        event_output=event_output,
        event_input=event_input,
        success=False,
        error="Test error message"
    )
    
    # Prüfen, ob die Funktion False zurückgibt, wenn ein Fehler auftritt
    assert result is False
    mock_post.assert_called_once() 