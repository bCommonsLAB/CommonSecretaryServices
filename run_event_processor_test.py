"""
Führt den EventProcessor-Test aus.

Dieses Skript startet den Test der asynchronen Eventverarbeitung
mit integriertem Webhook-Callback über die API.

Voraussetzungen:
---------------
1. Die API muss laufen mit den neuen Webhook-Callback-Endpunkten
2. Die Environment-Variablen müssen korrekt gesetzt sein
"""

import sys
import subprocess
import requests
from datetime import datetime

def check_api_server():
    """
    Prüft, ob der API-Server läuft und zugänglich ist.
    
    Returns:
        bool: True, wenn der Server läuft, sonst False
    """
    try:
        print(f"[{datetime.now().isoformat()}] Prüfe API-Server...")
        response = requests.get("http://localhost:5001/api")
        
        if response.status_code == 200:
            print(f"[{datetime.now().isoformat()}] API-Server läuft auf http://localhost:5001")
            return True
        else:
            print(f"[{datetime.now().isoformat()}] API-Server antwortet, aber mit Status {response.status_code}")
            return False
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] API-Server nicht erreichbar: {str(e)}")
        return False

def clear_webhook_logs():
    """
    Löscht vorhandene Webhook-Logs vor dem Test.
    """
    try:
        print(f"[{datetime.now().isoformat()}] Lösche vorhandene Webhook-Logs...")
        response = requests.post("http://localhost:5001/api/test-webhook-clear")
        
        if response.status_code == 200:
            print(f"[{datetime.now().isoformat()}] Webhook-Logs erfolgreich gelöscht.")
        else:
            print(f"[{datetime.now().isoformat()}] Fehler beim Löschen der Webhook-Logs: {response.status_code}")
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] Fehler beim Löschen der Webhook-Logs: {str(e)}")

def run_event_processor_test():
    """
    Führt den EventProcessor-Test aus und zeigt die Ausgabe in Echtzeit an.
    """
    print(f"[{datetime.now().isoformat()}] Starte EventProcessor-Test...")
    
    # Setze Timeout für den Test
    timeout_seconds = 300  # 5 Minuten Timeout
    process = None
    
    try:
        # Starte den Test mit Echtzeit-Ausgabe
        process = subprocess.Popen(
            ["python", "test_event_processor_async.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1
        )
        
        # Zeige die Ausgabe in Echtzeit an
        if process.stdout:
            for line in process.stdout:
                print(line, end='')
                sys.stdout.flush()
        
        # Warte auf den Abschluss des Prozesses mit Timeout
        exit_code = process.wait(timeout=timeout_seconds)
        
        print(f"[{datetime.now().isoformat()}] Test abgeschlossen mit Exit-Code {exit_code}")
        return exit_code == 0
        
    except subprocess.TimeoutExpired:
        if process:
            process.terminate()
        print(f"[{datetime.now().isoformat()}] FEHLER: Test überschritt das Timeout von {timeout_seconds} Sekunden")
        return False
    except Exception as e:
        print(f"[{datetime.now().isoformat()}] FEHLER beim Ausführen des Tests: {str(e)}")
        return False

def main():
    """Hauptfunktion."""
    # Prüfe, ob der API-Server läuft
    if not check_api_server():
        print(f"[{datetime.now().isoformat()}] FEHLER: Der API-Server ist nicht erreichbar.")
        print("Bitte stelle sicher, dass der API-Server läuft mit dem Befehl:")
        print("  python src/main.py")
        return
    
    # Lösche vorhandene Webhook-Logs
    clear_webhook_logs()
    
    # Führe den EventProcessor-Test aus
    success = run_event_processor_test()
    
    if success:
        print(f"[{datetime.now().isoformat()}] Test erfolgreich abgeschlossen.")
    else:
        print(f"[{datetime.now().isoformat()}] Test fehlgeschlagen.")

if __name__ == "__main__":
    main() 