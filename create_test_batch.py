#!/usr/bin/env python
"""
Test-Skript zum Erstellen mehrerer Batches mit Events aus bestimmten Tracks aus der fosdem-events.json Datei.
Dieses Skript liest die Testdaten, filtert nach spezifischen Tracks und erstellt für jeden Track einen neuen Batch in der Datenbank.
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

# Liste der verfügbaren Tracks
AVAILABLE_TRACKS = [
    "Collaboration-and-Content-Management-19",
    "Government-Collaboration-11",
    "Open-Media-12",
    "Open-Research-22",
    "Main-Track-K-Building-18",
    "Open-Source-In-The-European-Legislative-Landscape-and-Beyond-34",
    "Community-17",
    "Social-Web-12",
    "Confidential-Computing-11",
    "Educational-14",
    "Embedded-Mobile-and-Automotive-19",
    "Energy-Accelerating-the-Transition-through-Open-Source-24",
    "FOSDEM-Junior-18",
    "FOSS-on-Mobile-Devices-11",
    "Funding-the-FOSS-Ecosystem-12",
    "Lightning-Talks-38",
    "LibreOffice-21",
    "Main-Track-Janson-7",
    "Keynotes-13",
    "Modern-Email-18",
    "Rust-12",
    "Tool-the-Docs-8",
    "APIs-GraphQL-OpenAPI-AsyncAPI-and-friends-7"
]

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

def process_track(track: str, events: List[JobParameters]) -> None:
    """
    Verarbeitet einen einzelnen Track und erstellt einen Batch.
    
    Args:
        track: Name des zu verarbeitenden Tracks
        events: Liste aller Event-Daten
    """
    print(f"\n=== Verarbeite Track: {track} ===")
    
    # Events nach Track filtern
    filtered_events = filter_events_by_track(events, track)
    
    if not filtered_events:
        print(f"Keine Events für Track '{track}' gefunden. Überspringe...")
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

def main() -> None:
    """Hauptfunktion zum Erstellen mehrerer Test-Batches."""
    try:
        # Tracks entweder aus Kommandozeile oder aus vordefinierten verfügbaren Tracks nehmen
        tracks_to_process: List[str] = []
        
        if len(sys.argv) > 1:
            # Tracks von der Kommandozeile nehmen
            tracks_to_process = sys.argv[1:]
            print(f"Verarbeite {len(tracks_to_process)} Tracks aus Kommandozeilenargumenten")
        else:
            # Alle verfügbaren Tracks verwenden
            tracks_to_process = AVAILABLE_TRACKS
            print(f"Verarbeite alle {len(tracks_to_process)} verfügbaren Tracks")
        
        # Events laden (nur einmal für alle Tracks)
        events = load_events(SAMPLE_FILE)
        
        # Jeden Track einzeln verarbeiten
        successful_tracks = 0
        
        for track in tracks_to_process:
            try:
                process_track(track, events)
                successful_tracks += 1
            except Exception as e:
                print(f"Fehler beim Verarbeiten von Track '{track}': {str(e)}")
        
        # Zusammenfassung anzeigen
        print("\n=== Zusammenfassung ===")
        print(f"Verarbeitete Tracks: {len(tracks_to_process)}")
        print(f"Erfolgreich: {successful_tracks}")
        print(f"Fehlgeschlagen: {len(tracks_to_process) - successful_tracks}")
        
    except Exception as e:
        print(f"Kritischer Fehler: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main() 