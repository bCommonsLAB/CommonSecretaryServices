#!/usr/bin/env python
"""
Test-Skript zum Erstellen eines Batches mit Events aus einem bestimmten Track aus der fosdem-events.json Datei.
Dieses Skript liest die Testdaten, filtert nach einem spezifischen Track und erstellt einen neuen Batch in der Datenbank.
"""

import json
import os
import requests
import sys
from typing import List, Dict, Any, TypedDict, Optional, NotRequired

# Typdefinitionen für bessere Typ-Annotationen
class WebhookConfig(TypedDict, total=False):
    url: str
    headers: Dict[str, str]
    include_markdown: bool
    include_metadata: bool

class JobParameters(TypedDict, total=False):
    session: str
    filename: str
    track: str
    video_url: Optional[str]
    attachments_url: Optional[str]
    event: str
    url: str
    day: Optional[str]
    starttime: Optional[str]
    endtime: Optional[str]
    speakers: Optional[List[str]]
    source_language: str
    target_language: str

class JobData(TypedDict, total=False):
    parameters: JobParameters
    webhook: WebhookConfig
    user_id: str
    batch_id: str
    job_name: NotRequired[str]

class BatchData(TypedDict):
    # Obligatorische Felder
    jobs: List[JobData]
    # Optionale Felder
    webhook: NotRequired[WebhookConfig]
    user_id: NotRequired[str]
    batch_id: NotRequired[str]
    batch_name: NotRequired[str]

class BatchResponse(TypedDict, total=False):
    status: str
    batch: Dict[str, Any]
    message: str

# Initialisierung
SAMPLE_FILE = 'tests/samples/fosdem-events.json'
API_URL = 'http://localhost:5001/api/event-job/batches'
DEFAULT_TRACK = "Open-Research-22"

def load_events(file_path: str) -> List[JobParameters]:
    """
    Lädt die Events aus der JSON-Datei.
    
    Args:
        file_path: Pfad zur JSON-Datei
        
    Returns:
        List[JobParameters]: Liste der Event-Daten
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Die Datei {file_path} wurde nicht gefunden")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        events = json.load(f)
    
    print(f"Erfolgreich {len(events)} Events aus {file_path} geladen")
    return events

def filter_events_by_track(events: List[JobParameters], track: str) -> List[JobParameters]:
    """
    Filtert Events nach einem bestimmten Track.
    
    Args:
        events: Liste der Event-Daten
        track: Zu filternder Track-Name
        
    Returns:
        List[JobParameters]: Gefilterte Liste von Events
    """
    filtered_events = [event for event in events if event.get("track") == track]
    print(f"Gefunden: {len(filtered_events)} Events mit Track '{track}'")
    
    if not filtered_events:
        print(f"Warnung: Keine Events mit Track '{track}' gefunden!")
        # Verfügbare Tracks mit korrekter Typisierung sammeln
        available_tracks: List[str] = []
        for event in events:
            track_name = event.get("track")
            if isinstance(track_name, str):
                available_tracks.append(track_name)
        
        # Duplikate entfernen und sortieren
        unique_tracks = sorted(set(available_tracks))
        print(f"Verfügbare Tracks: {unique_tracks}")
    
    return filtered_events

def prepare_batch_data(events: List[JobParameters], track_name: str) -> BatchData:
    """
    Bereitet die Batch-Daten für die API-Anfrage vor.
    
    Args:
        events: Liste der gefilterten Event-Daten
        track_name: Name des Tracks für den Batch-Namen
        
    Returns:
        BatchData: Batch-Daten für die API-Anfrage
    """
    if not events:
        raise ValueError("Keine Events zum Verarbeiten vorhanden")
    
    # Extrahiere Event-Name aus dem ersten Event
    first_event = events[0]
    event_name = first_event.get("event", "unbekannt")
    
    # Erstelle einen benutzerfreundlichen Batch-Namen mit Track
    batch_name = f"{event_name} - {track_name} ({len(events)} Jobs)"
    
    # Erstelle Job-Daten für jeden Event-Eintrag
    jobs: List[JobData] = []
    for event in events:
        webhook_config: WebhookConfig = {
            "url": "http://localhost:5000/webhook/event-jobs",
            "headers": {
                "Content-Type": "application/json",
                "X-API-Key": "test-key"
            },
            "include_markdown": True,
            "include_metadata": True
        }
        
        # Erstelle einen benutzerfreundlichen Job-Namen
        event_title = event.get("event", "")
        session_title = event.get("session", "")
        parts = [part for part in [event_title, session_title] if part]
        job_name = " - ".join(parts)
        
        job_data: JobData = {
            "parameters": event,
            "webhook": webhook_config,
            "user_id": "test-user",
            "job_name": job_name
        }
        jobs.append(job_data)
    
    # Erstelle Batch-Daten
    batch_webhook: WebhookConfig = {
        "url": "http://localhost:5000/webhook/event-batches",
        "headers": {
            "Content-Type": "application/json",
            "X-API-Key": "test-key"
        }
    }
    
    batch_data: BatchData = {
        "jobs": jobs,
        "webhook": batch_webhook,
        "user_id": "test-user",
        "batch_name": batch_name
    }
    
    return batch_data

def create_batch(batch_data: BatchData) -> BatchResponse:
    """
    Erstellt einen Batch über die API.
    
    Args:
        batch_data: Batch-Daten für die API-Anfrage
        
    Returns:
        BatchResponse: API-Antwort
    """
    headers = {
        "Content-Type": "application/json",
        "X-User-ID": "test-user"
    }
    
    try:
        response = requests.post(API_URL, json=batch_data, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Fehler bei der API-Anfrage: {str(e)}")
        if hasattr(e, 'response') and e.response:
            print(f"Server-Antwort: {e.response.text}")
        raise

def main() -> None:
    """Hauptfunktion zum Erstellen eines Test-Batches."""
    try:
        # Track-Parameter aus der Kommandozeile oder Standardwert verwenden
        track = DEFAULT_TRACK
        if len(sys.argv) > 1:
            track = sys.argv[1]
        
        print(f"Erstelle Batch für Track: {track}")
        
        # Events laden
        events = load_events(SAMPLE_FILE)
        
        # Events nach Track filtern
        filtered_events = filter_events_by_track(events, track)
        
        if not filtered_events:
            print("Keine Events gefunden. Abbruch.")
            return
        
        # Batch-Daten vorbereiten
        batch_data = prepare_batch_data(filtered_events, track)
        
        # Jobs sicher extrahieren (für Typ-Sicherheit)
        jobs = batch_data.get("jobs", [])
        print(f"Batch mit {len(jobs)} Jobs vorbereitet")
        print(f"Batch-Name: {batch_data.get('batch_name')}")
        
        # Batch erstellen
        response: BatchResponse = create_batch(batch_data)
        
        # Ergebnis anzeigen
        batch = response.get('batch', {})
        print(f"Batch erfolgreich erstellt:")
        print(f"Batch-ID: {batch.get('batch_id')}")
        print(f"Batch-Name: {batch.get('batch_name')}")
        print(f"Gesamtzahl Jobs: {batch.get('total_jobs')}")
        
    except Exception as e:
        print(f"Fehler: {str(e)}")

if __name__ == "__main__":
    main() 