"""
Testskript für die asynchrone Eventverarbeitung.

Dieses Skript testet die asynchrone Verarbeitung von Events
mit dem EventProcessor und prüft den Webhook-Callback.

Voraussetzungen:
---------------
1. Der API-Server muss laufen mit dem Webhook-Endpunkt '/api/test-webhook-callback'
2. Die Environment-Variablen müssen korrekt gesetzt sein
"""

import asyncio
import os
import sys
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List, TypedDict

# Füge das src-Verzeichnis zum Pythonpfad hinzu, falls notwendig
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Importiere den EventProcessor
from src.processors.event_processor import EventProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.event import EventResponse

# API-Basis-URL - anpassen, falls die API auf einem anderen Host/Port läuft
API_BASE_URL = "http://localhost:5001"
WEBHOOK_URL = f"{API_BASE_URL}/api/test-webhook-callback"

# Definition der Typen für Testdaten
class TestEventData(TypedDict):  # total=True ist standardmäßig aktiviert
    event: str
    session: str
    filename: str
    track: str
    video_url: str
    attachments_url: Optional[str]
    url: str
    day: str
    starttime: str
    endtime: str
    speakers: List[str]
    source_language: str
    target_language: str
    webhook_url: str
    webhook_headers: Dict[str, str]
    include_markdown: bool
    include_metadata: bool
    event_id: str

# Testdaten für den EventProcessor
TEST_EVENT_DATA: TestEventData = {
    "event": "FOSDEM 2025",
    "session": "Closing FOSDEM 2025",
    "filename": "Closing-FOSDEM-2025.md",
    "track": "Keynotes-13",
    "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6713-closing-fosdem-2025.av1.webm",
    "attachments_url": None,  # Entfernt für schnelleren Test
    "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6713-closing-fosdem-2025/",
    "day": "Sunday",
    "starttime": "17:50",
    "endtime": "18:15",
    "speakers": ["FOSDEM Staff"],
    "source_language": "en",
    "target_language": "en",
    "webhook_url": WEBHOOK_URL,
    "webhook_headers": {},
    "include_markdown": True,
    "include_metadata": True,
    "event_id": "test-event-001"
}

def clear_webhook_logs():
    """
    Löscht alle vorhandenen Webhook-Logs über den API-Endpunkt.
    """
    try:
        print(f"[{datetime.now().isoformat()}] Lösche vorhandene Webhook-Logs...")
        response = requests.post(f"{API_BASE_URL}/api/test-webhook-clear")
        
        if response.status_code == 200:
            data = response.json()
            print(f"Webhook-Logs gelöscht: {data.get('message')}")
        else:
            print(f"Fehler beim Löschen der Webhook-Logs: {response.status_code}")
    except Exception as e:
        print(f"Fehler beim Löschen der Webhook-Logs: {str(e)}")

def check_webhook_api_status():
    """
    Prüft, ob der Webhook-API-Endpunkt erreichbar ist.
    
    Returns:
        bool: True, wenn der Endpunkt erreichbar ist, sonst False
    """
    try:
        print(f"[{datetime.now().isoformat()}] Prüfe API-Status...")
        response = requests.get(f"{API_BASE_URL}/api")
        return response.status_code == 200
    except Exception as e:
        print(f"Fehler beim Prüfen des API-Status: {str(e)}")
        return False

async def test_event_processor_async():
    """
    Führt einen Test der asynchronen Eventverarbeitung durch.
    
    1. Initialisiert den EventProcessor
    2. Ruft process_event_async mit den Testdaten auf
    3. Wartet auf die asynchrone Verarbeitung und Webhook-Callbacks
    """
    print(f"[{datetime.now().isoformat()}] Starte Test der asynchronen Eventverarbeitung...")
    
    # Prüfe, ob die API erreichbar ist
    if not check_webhook_api_status():
        print(f"FEHLER: Die API ist nicht erreichbar unter {API_BASE_URL}")
        print("Bitte stelle sicher, dass der API-Server läuft.")
        return
        
    try:
        # Lösche vorhandene Webhook-Logs
        clear_webhook_logs()
        
        # Initialisiere ResourceCalculator und EventProcessor
        resource_calculator = ResourceCalculator()
        event_processor = EventProcessor(resource_calculator=resource_calculator)
        
        print(f"[{datetime.now().isoformat()}] EventProcessor initialisiert.")
        
        # Führe process_event_async aus
        print(f"[{datetime.now().isoformat()}] Rufe process_event_async mit Testdaten auf...")
        
        # Sichere Typen durch explizite Angabe
        event: str = TEST_EVENT_DATA["event"]
        session: str = TEST_EVENT_DATA["session"]
        url: str = TEST_EVENT_DATA["url"]
        filename: str = TEST_EVENT_DATA["filename"]
        track: str = TEST_EVENT_DATA["track"]
        webhook_url: str = TEST_EVENT_DATA["webhook_url"]
        day: str = TEST_EVENT_DATA["day"]
        starttime: str = TEST_EVENT_DATA["starttime"]
        endtime: str = TEST_EVENT_DATA["endtime"]
        speakers: List[str] = TEST_EVENT_DATA["speakers"]
        video_url: str = TEST_EVENT_DATA["video_url"]
        attachments_url: Optional[str] = TEST_EVENT_DATA["attachments_url"]
        source_language: str = TEST_EVENT_DATA["source_language"]
        target_language: str = TEST_EVENT_DATA["target_language"]
        webhook_headers: Dict[str, str] = TEST_EVENT_DATA["webhook_headers"]
        include_markdown: bool = TEST_EVENT_DATA["include_markdown"]
        include_metadata: bool = TEST_EVENT_DATA["include_metadata"]
        event_id: str = TEST_EVENT_DATA["event_id"]
        
        response: EventResponse = await event_processor.process_event_async(
            event=event,
            session=session,
            url=url,
            filename=filename,
            track=track,
            webhook_url=webhook_url,
            day=day,
            starttime=starttime,
            endtime=endtime,
            speakers=speakers,
            video_url=video_url,
            attachments_url=attachments_url,
            source_language=source_language,
            target_language=target_language,
            webhook_headers=webhook_headers,
            include_markdown=include_markdown,
            include_metadata=include_metadata,
            event_id=event_id
        )
        
        # Analysiere die initiale Antwort
        print(f"[{datetime.now().isoformat()}] Initiale Antwort erhalten:")
        print(f"Status: {response.status}")
        if response.error:
            print(f"Fehler: {response.error.code} - {response.error.message}")
        
        print("Request-Info:")
        # Da response.request möglicherweise kein dict ist, verwenden wir vars() oder __dict__
        request_info = response.request.__dict__ if hasattr(response.request, "__dict__") else vars(response.request)
        for key, value in request_info.items():
            print(f"  {key}: {value}")
        
        # Warte auf die asynchrone Verarbeitung und prüfe periodisch die Webhook-Logs
        print(f"[{datetime.now().isoformat()}] Warte auf die asynchrone Verarbeitung...")
        
        # Wir geben ausreichend Zeit für die Verarbeitung
        wait_time = 120  # 2 Minuten sollten genügen für den Test ohne Attachments
        webhook_received = False
        
        for i in range(wait_time):
            # Alle 5 Sekunden eine Status-Ausgabe und Prüfung der Logs
            if i % 5 == 0:
                print(f"[{datetime.now().isoformat()}] Warte seit {i} Sekunden auf Verarbeitung...")
                logs = get_webhook_logs_from_api(event_id)
                
                if logs and len(logs) > 0:
                    print(f"Webhook empfangen! Verarbeitung abgeschlossen.")
                    webhook_received = True
                    break
                    
            await asyncio.sleep(1)
            
        if not webhook_received:
            print(f"[{datetime.now().isoformat()}] Keine Webhooks empfangen innerhalb der Wartezeit.")
            
        print(f"[{datetime.now().isoformat()}] Test abgeschlossen.")
        
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Fehler beim Test: {str(e)}")
        import traceback
        print(traceback.format_exc())

def get_webhook_logs_from_api(event_id: str) -> List[Dict[str, Any]]:
    """
    Ruft die Webhook-Logs für eine bestimmte Event-ID von der API ab.
    
    Args:
        event_id: Die Event-ID
        
    Returns:
        List[Dict[str, Any]]: Liste der Webhook-Logs
    """
    try:
        response = requests.get(f"{API_BASE_URL}/api/test-webhook-logs/{event_id}")
        
        if response.status_code == 200:
            data = response.json()
            return data.get("logs", [])
        else:
            print(f"Keine Logs für Event-ID {event_id} gefunden.")
            return []
    except Exception as e:
        print(f"Fehler beim Abrufen der Webhook-Logs: {str(e)}")
        return []

def check_webhook_logs():
    """
    Prüft, ob Webhook-Logs vorhanden sind und gibt ihren Inhalt aus.
    """
    print(f"[{datetime.now().isoformat()}] Prüfe Webhook-Logs...")
    
    # Holen der Logs von der API
    logs = get_webhook_logs_from_api(TEST_EVENT_DATA["event_id"])
    
    if not logs:
        print("Keine Webhook-Logs für die Test-Event-ID gefunden.")
        return
    
    print(f"Gefundene Webhook-Logs: {len(logs)}")
    for log in logs:
        print(f"Timestamp: {log.get('timestamp')}")
        print(f"Event-ID: {log.get('event_id')}")
        
        payload = log.get("payload", {})
        print(f"Success: {payload.get('success', False)}")
        if "error" in payload:
            print(f"Fehler: {payload['error']}")
        if "file_path" in payload:
            print(f"Datei: {payload.get('file_path')}")
            
            # Prüfe, ob die Datei existiert
            file_path = payload.get('file_path')
            if file_path and os.path.exists(file_path):
                file_size = os.path.getsize(file_path)
                print(f"Datei existiert: Ja ({file_size} Bytes)")
            else:
                print(f"Datei existiert: Nein")
        
        print("-" * 50)

async def main():
    """Hauptfunktion."""
    await test_event_processor_async()
    
    # Nach dem Test prüfen wir die Webhook-Logs
    check_webhook_logs()

if __name__ == "__main__":
    asyncio.run(main()) 