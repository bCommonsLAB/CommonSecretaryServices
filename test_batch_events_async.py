"""
Testskript für die asynchrone Batch-Eventverarbeitung.

Dieses Skript testet die asynchrone Verarbeitung mehrerer Events
mit dem EventProcessor und prüft die Webhook-Callbacks.

Voraussetzungen:
---------------
1. Der API-Server muss laufen mit dem Webhook-Endpunkt '/api/test-webhook-callback'
2. Die Environment-Variablen müssen korrekt gesetzt sein

Parameter:
---------
startEvent: Index des ersten zu verarbeitenden Events (0-basiert, Standard: 0)
countEvents: Anzahl der zu verarbeitenden Events (Standard: 3)

Beispiel:
--------
python test_batch_events_async.py --startEvent=5 --countEvents=2
"""

import asyncio
import json
import os
import sys
import requests
import time
import argparse
from datetime import datetime
from typing import Dict, Any, List, TypedDict, Optional, cast

# Füge das src-Verzeichnis zum Pythonpfad hinzu, falls notwendig
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# API-Basis-URL - anpassen, falls die API auf einem anderen Host/Port läuft
API_BASE_URL = "http://localhost:5001"
WEBHOOK_URL = f"{API_BASE_URL}/api/test-webhook-callback"

# Pfad zur FOSDEM-Events-Datei
EVENTS_FILE_PATH = os.path.join("tests", "samples", "fosdem-events.json")

# Definition der Event-Struktur für bessere Typisierung
class EventData(TypedDict, total=False):
    session: str
    filename: str
    track: str
    video_url: Optional[str]
    attachments_url: Optional[str]
    event: str
    url: str
    day: str
    starttime: str
    endtime: str
    speakers: Optional[List[str]]
    source_language: str
    target_language: str

# Definition der Request-Daten-Struktur
class RequestData(TypedDict):
    events: List[EventData]
    webhook_url: str
    webhook_headers: Dict[str, str]
    include_markdown: bool
    include_metadata: bool
    batch_id: str

def load_events(start_event: int = 0, count_events: int = 3) -> List[EventData]:
    """
    Lädt Events aus der JSON-Datei.
    
    Args:
        start_event: Index des ersten zu ladenden Events (0-basiert)
        count_events: Anzahl der zu ladenden Events
        
    Returns:
        Liste der geladenen Events
    """
    try:
        with open(EVENTS_FILE_PATH, 'r', encoding='utf-8') as f:
            all_events = json.load(f)
            
        # Validiere die Indizes
        if start_event < 0:
            start_event = 0
        if start_event >= len(all_events):
            start_event = len(all_events) - 1
            
        # Begrenze die Anzahl der Events
        if count_events <= 0:
            count_events = 1
        if start_event + count_events > len(all_events):
            count_events = len(all_events) - start_event
            
        # Extrahiere die gewünschten Events
        selected_events = all_events[start_event:start_event + count_events]
        
        # Stelle sicher, dass speakers immer eine Liste ist (auch wenn null in JSON)
        for event in selected_events:
            if event.get("speakers") is None:
                event["speakers"] = []
                
        print(f"Geladen: {count_events} Events, beginnend mit Index {start_event}")
        return cast(List[EventData], selected_events)
        
    except Exception as e:
        print(f"Fehler beim Laden der Events: {str(e)}")
        print(f"Arbeitsverzeichnis: {os.getcwd()}")
        print(f"Gesuchte Datei: {EVENTS_FILE_PATH}")
        print("Verwende Beispiel-Events...")
        
        # Fallback: Beispiel-Events
        return [
            {
                "session": "Beispiel-Event 1",
                "filename": "Beispiel-Event-1.md",
                "track": "Beispiel-Track",
                "video_url": None,
                "attachments_url": None,
                "event": "Beispiel-Konferenz",
                "url": "https://example.com/event1",
                "day": "Montag",
                "starttime": "10:00",
                "endtime": "11:00",
                "speakers": ["Beispiel-Sprecher"],
                "source_language": "en",
                "target_language": "de"
            }
        ]

def parse_arguments():
    """
    Parst die Kommandozeilenargumente.
    
    Returns:
        Namespace mit den geparsten Argumenten
    """
    parser = argparse.ArgumentParser(description="Test für asynchrone Batch-Eventverarbeitung")
    parser.add_argument("--startEvent", type=int, default=0, help="Index des ersten zu verarbeitenden Events (0-basiert)")
    parser.add_argument("--countEvents", type=int, default=3, help="Anzahl der zu verarbeitenden Events")
    return parser.parse_args()

def check_api_server():
    """
    Prüft, ob der API-Server läuft und zugänglich ist.
    
    Returns:
        bool: True, wenn der Server läuft, sonst False
    """
    try:
        print(f"[{datetime.now().isoformat()}] Prüfe API-Server...")
        response = requests.get(f"{API_BASE_URL}/api")
        
        if response.status_code == 200:
            print(f"[{datetime.now().isoformat()}] API-Server läuft auf {API_BASE_URL}")
            return True
        else:
            print(f"[{datetime.now().isoformat()}] API-Server antwortet, aber mit Status {response.status_code}")
            return False
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] API-Server nicht erreichbar: {str(e)}")
        return False

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

def get_webhook_logs_from_api() -> List[Dict[str, Any]]:
    """
    Ruft alle Webhook-Logs von der API ab.
    
    Returns:
        List[Dict[str, Any]]: Liste der Webhook-Logs
    """
    try:
        response = requests.get(f"{API_BASE_URL}/api/test-webhook-logs")
        
        if response.status_code == 200:
            data = response.json()
            return data.get("logs", [])
        else:
            print(f"Keine Webhook-Logs gefunden.")
            return []
    except Exception as e:
        print(f"Fehler beim Abrufen der Webhook-Logs: {str(e)}")
        return []

async def test_batch_events_async(start_event: int, count_events: int):
    """
    Führt einen Test der asynchronen Batch-Eventverarbeitung durch.
    
    Args:
        start_event: Index des ersten zu verarbeitenden Events
        count_events: Anzahl der zu verarbeitenden Events
    """
    print(f"[{datetime.now().isoformat()}] Starte Test der asynchronen Batch-Eventverarbeitung...")
    print(f"Parameter: startEvent={start_event}, countEvents={count_events}")
    
    # Prüfe, ob die API erreichbar ist
    if not check_api_server():
        print(f"FEHLER: Die API ist nicht erreichbar unter {API_BASE_URL}")
        print("Bitte stelle sicher, dass der API-Server läuft.")
        return
        
    try:
        # Lösche vorhandene Webhook-Logs
        clear_webhook_logs()
        
        # Lade die Events
        test_events = load_events(start_event, count_events)
        if not test_events:
            print("Keine Events zum Verarbeiten gefunden.")
            return
            
        # Zeige Informationen zu den geladenen Events
        print(f"Verarbeite {len(test_events)} Events:")
        for i, event in enumerate(test_events):
            print(f"  {i+1}. {event.get('event')} - {event.get('session')}")
        
        # Erstelle die Batch-Anfrage
        batch_id = f"batch-test-{int(time.time())}"
        request_data: RequestData = {
            "events": test_events,
            "webhook_url": WEBHOOK_URL,
            "webhook_headers": {},
            "include_markdown": True,
            "include_metadata": True,
            "batch_id": batch_id
        }
        
        # Sende die Anfrage an den API-Server
        print(f"[{datetime.now().isoformat()}] Sende Batch-Anfrage mit {len(test_events)} Events...")
        response = requests.post(
            f"{API_BASE_URL}/api/process-events-async",
            json=request_data
        )
        
        if response.status_code != 200:
            print(f"Fehler bei der Batch-Anfrage: {response.status_code}")
            print(response.text)
            return
            
        # Analysiere die initiale Antwort
        response_data = response.json()
        print(f"[{datetime.now().isoformat()}] Initiale Antwort erhalten:")
        print(f"Status: {response_data.get('status')}")
        if response_data.get('error'):
            print(f"Fehler: {response_data['error'].get('code')} - {response_data['error'].get('message')}")
            return
            
        # Zeige Zusammenfassung der Anfrage
        request_info = response_data.get('request', {})
        print(f"Batch-ID: {batch_id}")
        print(f"Event-Anzahl: {request_info.get('event_count')}")
        
        # Warte auf die asynchrone Verarbeitung und prüfe periodisch die Webhook-Logs
        print(f"[{datetime.now().isoformat()}] Warte auf die asynchrone Verarbeitung...")
        
        # Wir geben ausreichend Zeit für die Verarbeitung
        wait_time = 300  # 5 Minuten sollten genügen für die Events
        webhook_count = 0
        
        for i in range(wait_time):
            # Alle 10 Sekunden eine Status-Ausgabe und Prüfung der Logs
            if i % 10 == 0:
                print(f"[{datetime.now().isoformat()}] Warte seit {i} Sekunden auf Verarbeitung...")
                logs = get_webhook_logs_from_api()
                
                new_count = len(logs)
                if new_count > webhook_count:
                    print(f"Bisher {new_count} Webhooks empfangen (neu: {new_count - webhook_count})")
                    webhook_count = new_count
                
                if webhook_count >= len(test_events):
                    print(f"Alle {len(test_events)} Webhooks empfangen! Verarbeitung abgeschlossen.")
                    break
                    
            await asyncio.sleep(1)
            
        if webhook_count < len(test_events):
            print(f"[{datetime.now().isoformat()}] Nur {webhook_count} von {len(test_events)} Webhooks empfangen innerhalb der Wartezeit.")
            
        print(f"[{datetime.now().isoformat()}] Test abgeschlossen.")
        
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Fehler beim Test: {str(e)}")
        import traceback
        print(traceback.format_exc())

def check_webhook_logs():
    """
    Prüft, ob Webhook-Logs vorhanden sind und gibt ihren Inhalt aus.
    """
    print(f"[{datetime.now().isoformat()}] Prüfe Webhook-Logs...")
    
    # Holen der Logs von der API
    logs = get_webhook_logs_from_api()
    
    if not logs:
        print("Keine Webhook-Logs gefunden.")
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
    # Parse Kommandozeilenargumente
    args = parse_arguments()
    
    # Führe den Test mit den angegebenen Parametern aus
    await test_batch_events_async(args.startEvent, args.countEvents)
    
    # Nach dem Test prüfen wir die Webhook-Logs
    check_webhook_logs()

if __name__ == "__main__":
    asyncio.run(main()) 