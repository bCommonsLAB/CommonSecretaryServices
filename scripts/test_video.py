import requests
import time
import os
import argparse

# API-URL-Basis
BASE_URL = "http://localhost:5001/api"

def test_video_file_without_cache():
    """
    Testet die Video-Verarbeitung einer lokalen Datei ohne Cache.
    """
    print("Test: Video-Datei ohne Cache")
    
    # Prüfe, ob die Testdatei existiert
    video_file = "tests/samples/hello.mp4"
    if not os.path.exists(video_file):
        print(f"Datei nicht gefunden: {video_file}")
        return
    
    try:
        # Bereite Multipart-Formular-Daten vor
        files = {'file': open(video_file, 'rb')}
        data = {
            'use_cache': 'false'
        }
        
        # Sende die Anfrage
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/video/process", files=files, data=data)
        duration = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Dauer: {duration:.2f} Sekunden")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Status: {result.get('status', 'unbekannt')}")
            
            # Extrahiere Metadaten
            metadata = result.get('data', {}).get('metadata', {})
            if metadata:
                print(f"Titel: {metadata.get('title', 'Kein Titel')}")
                print(f"Dauer: {metadata.get('duration', 'Keine Dauer')}")
            
            # Extrahiere Transkript
            transcript = result.get('data', {}).get('transcript', 'Kein Transkript verfügbar')
            print(f"Transkript (gekürzt): {transcript[:100]}...")
            print(f"Cache: {result.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response.text}")
            
        # Schließe die Datei
        files['file'].close()
        
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print()

def test_video_file_with_cache():
    """
    Testet die Video-Verarbeitung einer lokalen Datei mit Cache.
    """
    print("Test: Video-Datei mit Cache")
    
    # Prüfe, ob die Testdatei existiert
    video_file = "tests/samples/hello.mp4"
    if not os.path.exists(video_file):
        print(f"Datei nicht gefunden: {video_file}")
        return
    
    try:
        # Erster Aufruf (sollte in den Cache schreiben)
        print("Erster Aufruf:")
        
        # Bereite Multipart-Formular-Daten vor
        files = {'file': open(video_file, 'rb')}
        data = {
            'use_cache': 'true'
        }
        
        # Sende die Anfrage
        start_time = time.time()
        response1 = requests.post(f"{BASE_URL}/video/process", files=files, data=data)
        duration1 = time.time() - start_time
        
        print(f"Status Code: {response1.status_code}")
        print(f"Dauer: {duration1:.2f} Sekunden")
        
        if response1.status_code == 200:
            result1 = response1.json()
            print(f"Status: {result1.get('status', 'unbekannt')}")
            
            # Extrahiere Metadaten
            metadata = result1.get('data', {}).get('metadata', {})
            if metadata:
                print(f"Titel: {metadata.get('title', 'Kein Titel')}")
                print(f"Dauer: {metadata.get('duration', 'Keine Dauer')}")
            
            # Extrahiere Transkript
            transcript = result1.get('data', {}).get('transcript', 'Kein Transkript verfügbar')
            print(f"Transkript (gekürzt): {transcript[:100]}...")
            print(f"Cache: {result1.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response1.text}")
        
        # Schließe die Datei
        files['file'].close()
        
        # Zweiter Aufruf (sollte aus dem Cache lesen)
        print("\nZweiter Aufruf (sollte aus dem Cache):")
        
        # Bereite erneut Multipart-Formular-Daten vor
        files = {'file': open(video_file, 'rb')}
        data = {
            'use_cache': 'true'
        }
        
        # Sende die Anfrage erneut
        start_time = time.time()
        response2 = requests.post(f"{BASE_URL}/video/process", files=files, data=data)
        duration2 = time.time() - start_time
        
        print(f"Status Code: {response2.status_code}")
        print(f"Dauer: {duration2:.2f} Sekunden")
        
        if response2.status_code == 200:
            result2 = response2.json()
            print(f"Status: {result2.get('status', 'unbekannt')}")
            
            # Extrahiere Transkript
            transcript = result2.get('data', {}).get('transcript', 'Kein Transkript verfügbar')
            print(f"Transkript (gekürzt): {transcript[:100]}...")
            is_from_cache = result2.get('data', {}).get('is_from_cache', False)
            print(f"Cache: {is_from_cache}")
            
            if duration1 > 0 and duration2 > 0:
                print(f"Geschwindigkeitsverbesserung: {(duration1/duration2):.2f}x schneller")
        else:
            print(f"Fehler: {response2.text}")
        
        # Schließe die Datei
        files['file'].close()
        
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print()

# Nicht optimiert - sollte nicht automatisch ausgeführt werden
def test_video_youtube():
    """
    Testet die Video-Verarbeitung einer YouTube-URL.
    HINWEIS: Diese Funktion ist noch nicht optimiert und sollte nicht im Standardtestlauf ausgeführt werden.
    """
    print("Test: YouTube-Video")
    print("HINWEIS: Dieser Test ist noch nicht optimiert.")
    
    # YouTube-URL aus der Dokumentation
    video_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    
    data = {
        "url": video_url
    }
    
    try:
        # Sende die Anfrage
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/video/youtube", json=data)
        duration = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Dauer: {duration:.2f} Sekunden")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Status: {result.get('status', 'unbekannt')}")
            
            # Extrahiere Metadaten
            metadata = result.get('data', {}).get('metadata', {})
            if metadata:
                print(f"Titel: {metadata.get('title', 'Kein Titel')}")
                print(f"Kanal: {metadata.get('channel', 'Kein Kanal')}")
                print(f"Dauer: {metadata.get('duration', 'Keine Dauer')}")
            
            # Extrahiere Transkript
            transcript = result.get('data', {}).get('transcript', 'Kein Transkript verfügbar')
            print(f"Transkript (gekürzt): {transcript[:100]}...")
        else:
            print(f"Fehler: {response.text}")
    
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print()

def check_cache_directories():
    """
    Überprüft die Cache-Verzeichnisstruktur für Video.
    """
    print("Überprüfung der Cache-Verzeichnisstruktur für Video:")
    
    base_cache_dir = "cache"
    video_cache_dir = os.path.join(base_cache_dir, "video")
    temp_dir = os.path.join(video_cache_dir, "temp")
    
    # Prüfe, ob Basis-Cache-Verzeichnis existiert
    if os.path.exists(base_cache_dir):
        print(f"✓ Basis-Cache-Verzeichnis existiert: {base_cache_dir}")
    else:
        print(f"✗ Basis-Cache-Verzeichnis fehlt: {base_cache_dir}")
    
    # Prüfe, ob Video-Cache-Verzeichnis existiert
    if os.path.exists(video_cache_dir):
        print(f"✓ Video-Cache-Verzeichnis existiert: {video_cache_dir}")
    else:
        print(f"✗ Video-Cache-Verzeichnis fehlt: {video_cache_dir}")
    
    # Prüfe, ob temporäres Verzeichnis existiert
    if os.path.exists(temp_dir):
        print(f"✓ Temporäres Verzeichnis existiert: {temp_dir}")
    else:
        print(f"✗ Temporäres Verzeichnis fehlt: {temp_dir}")
    
    print()

def check_api_availability():
    """
    Überprüft, ob die API erreichbar ist.
    """
    print("Prüfe API-Erreichbarkeit...")
    
    try:
        # Versuche, die Root-API zu erreichen
        response = requests.get(f"{BASE_URL}/")
        print(f"API-Root: Status {response.status_code}")
        
        # Versuche, die Swagger-Dokumentation zu erreichen
        response = requests.get(f"{BASE_URL}/doc")
        print(f"API-Dokumentation: Status {response.status_code}")
        
        if response.status_code == 200:
            print("✓ API-Server ist erreichbar\n")
            return True
        else:
            print("⚠️ API-Server ist erreichbar, aber gibt unerwarteten Status zurück\n")
            return True
    except requests.exceptions.ConnectionError:
        print("✗ API-Server ist nicht erreichbar. Bitte starten Sie den Server.\n")
        return False

def main():
    """
    Hauptfunktion zum Ausführen der gewünschten Tests.
    """
    # Verfügbare Tests definieren
    tests = {
        'file': test_video_file_without_cache,
        'file_cache': test_video_file_with_cache,
        'cache_dirs': check_cache_directories,
        # 'youtube' ist nicht standardmäßig aktiviert, da noch nicht optimiert
    }
    
    # Command Line Parser einrichten
    parser = argparse.ArgumentParser(description='Testskript für Video-API')
    parser.add_argument('tests', nargs='*', choices=list(tests.keys()) + ['all', 'youtube'],
                      help='Welche Tests sollen ausgeführt werden? (Reihenfolge wird beibehalten)')
    parser.add_argument('--skip-api-check', action='store_true',
                       help='API-Verfügbarkeitsprüfung überspringen')
    
    # Argumente parsen
    args = parser.parse_args()
    
    # Wenn keine Tests angegeben wurden, alle ausführen
    selected_tests = args.tests
    if not selected_tests or 'all' in selected_tests:
        selected_tests = list(tests.keys())
    
    # YouTube-Test explizit hinzufügen, wenn angefordert
    if 'youtube' in selected_tests:
        tests['youtube'] = test_video_youtube
    
    print("=== Video API-Tests ===\n")
    
    # API-Verfügbarkeit prüfen (falls nicht übersprungen)
    if not args.skip_api_check:
        if not check_api_availability():
            return
    
    # Ausgewählte Tests in der angegebenen Reihenfolge ausführen
    print(f"Führe folgende Tests aus: {', '.join(selected_tests)}\n")
    for test_name in selected_tests:
        if test_name in tests:
            tests[test_name]()
    
    print("=== Tests abgeschlossen ===")

if __name__ == "__main__":
    main() 