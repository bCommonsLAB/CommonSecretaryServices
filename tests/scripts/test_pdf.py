import requests
import time
import os
import argparse

# API-URL-Basis
BASE_URL = "http://localhost:5001/api"

def test_pdf_file_without_cache():
    """
    Testet die PDF-Verarbeitung einer lokalen Datei ohne Cache.
    """
    print("Test: PDF-Datei ohne Cache")
    
    # Prüfe, ob die Testdatei existiert
    pdf_file = "tests/samples/sample.pdf"
    if not os.path.exists(pdf_file):
        print(f"Datei nicht gefunden: {pdf_file}")
        print("Hinweis: Bitte eine Test-PDF unter tests/samples/sample.pdf ablegen.")
        return
    
    try:
        # Bereite Multipart-Formular-Daten vor
        files = {'file': open(pdf_file, 'rb')}
        data = {
            'use_cache': 'false'
        }
        
        # Sende die Anfrage
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/pdf/process", files=files, data=data)
        duration = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Dauer: {duration:.2f} Sekunden")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Status: {result.get('status', 'unbekannt')}")
            
            # Extrahiere Text und Metadaten
            text = result.get('data', {}).get('text', 'Kein Text extrahiert')
            metadata = result.get('data', {}).get('metadata', {})
            
            print(f"Extrahierter Text (gekürzt): {text[:100]}...")
            
            if metadata:
                print("Metadaten:")
                for key, value in metadata.items():
                    print(f"  - {key}: {value}")
                    
            print(f"Cache: {result.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response.text}")
            
        # Schließe die Datei
        files['file'].close()
        
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print()

def test_pdf_file_with_cache():
    """
    Testet die PDF-Verarbeitung einer lokalen Datei mit Cache.
    """
    print("Test: PDF-Datei mit Cache")
    
    # Prüfe, ob die Testdatei existiert
    pdf_file = "tests/samples/sample.pdf"
    if not os.path.exists(pdf_file):
        print(f"Datei nicht gefunden: {pdf_file}")
        print("Hinweis: Bitte eine Test-PDF unter tests/samples/sample.pdf ablegen.")
        return
    
    try:
        # Erster Aufruf (sollte in den Cache schreiben)
        print("Erster Aufruf:")
        
        # Bereite Multipart-Formular-Daten vor
        files = {'file': open(pdf_file, 'rb')}
        data = {
            'use_cache': 'true'
        }
        
        # Sende die Anfrage
        start_time = time.time()
        response1 = requests.post(f"{BASE_URL}/pdf/process", files=files, data=data)
        duration1 = time.time() - start_time
        
        print(f"Status Code: {response1.status_code}")
        print(f"Dauer: {duration1:.2f} Sekunden")
        
        if response1.status_code == 200:
            result1 = response1.json()
            print(f"Status: {result1.get('status', 'unbekannt')}")
            
            # Extrahiere Text
            text = result1.get('data', {}).get('text', 'Kein Text extrahiert')
            print(f"Extrahierter Text (gekürzt): {text[:100]}...")
            print(f"Cache: {result1.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response1.text}")
        
        # Schließe die Datei
        files['file'].close()
        
        # Zweiter Aufruf (sollte aus dem Cache lesen)
        print("\nZweiter Aufruf (sollte aus dem Cache):")
        
        # Bereite erneut Multipart-Formular-Daten vor
        files = {'file': open(pdf_file, 'rb')}
        data = {
            'use_cache': 'true'
        }
        
        # Sende die Anfrage erneut
        start_time = time.time()
        response2 = requests.post(f"{BASE_URL}/pdf/process", files=files, data=data)
        duration2 = time.time() - start_time
        
        print(f"Status Code: {response2.status_code}")
        print(f"Dauer: {duration2:.2f} Sekunden")
        
        if response2.status_code == 200:
            result2 = response2.json()
            print(f"Status: {result2.get('status', 'unbekannt')}")
            
            # Extrahiere Text
            text = result2.get('data', {}).get('text', 'Kein Text extrahiert')
            print(f"Extrahierter Text (gekürzt): {text[:100]}...")
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

def test_pdf_url_without_cache():
    """
    Testet die PDF-Verarbeitung einer URL ohne Cache.
    """
    print("Test: PDF-URL ohne Cache")
    
    # Beispiel-URL für ein öffentliches PDF
    pdf_url = "https://fosdem.org/2025/events/attachments/fosdem-2025-5258-forked-communities-project-re-licensing-and-community-impact/slides/238218/FOSDEM_Fo_HyZR9km.pdf"
    
    data = {
        "url": pdf_url,
        "use_cache": False
    }
    
    try:
        # Sende die Anfrage
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/pdf/process-url", json=data)
        duration = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Dauer: {duration:.2f} Sekunden")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Status: {result.get('status', 'unbekannt')}")
            
            # Extrahiere Text und Metadaten
            text = result.get('data', {}).get('text', 'Kein Text extrahiert')
            metadata = result.get('data', {}).get('metadata', {})
            
            print(f"Extrahierter Text (gekürzt): {text[:100]}...")
            
            if metadata:
                print("Metadaten:")
                for key, value in metadata.items():
                    print(f"  - {key}: {value}")
                    
            print(f"Cache: {result.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response.text}")
    
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print()

def test_pdf_url_with_cache():
    """
    Testet die PDF-Verarbeitung einer URL mit Cache.
    """
    print("Test: PDF-URL mit Cache")
    
    # Beispiel-URL für ein öffentliches PDF
    pdf_url = "https://fosdem.org/2025/events/attachments/fosdem-2025-5258-forked-communities-project-re-licensing-and-community-impact/slides/238218/FOSDEM_Fo_HyZR9km.pdf"
    
    data = {
        "url": pdf_url,
        "use_cache": True
    }
    
    try:
        # Erster Aufruf (sollte in den Cache schreiben)
        print("Erster Aufruf:")
        
        # Sende die Anfrage
        start_time = time.time()
        response1 = requests.post(f"{BASE_URL}/pdf/process-url", json=data)
        duration1 = time.time() - start_time
        
        print(f"Status Code: {response1.status_code}")
        print(f"Dauer: {duration1:.2f} Sekunden")
        
        if response1.status_code == 200:
            result1 = response1.json()
            print(f"Status: {result1.get('status', 'unbekannt')}")
            
            # Extrahiere Text
            text = result1.get('data', {}).get('text', 'Kein Text extrahiert')
            print(f"Extrahierter Text (gekürzt): {text[:100]}...")
            print(f"Cache: {result1.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response1.text}")
        
        # Zweiter Aufruf (sollte aus dem Cache lesen)
        print("\nZweiter Aufruf (sollte aus dem Cache):")
        
        # Sende die Anfrage erneut
        start_time = time.time()
        response2 = requests.post(f"{BASE_URL}/pdf/process-url", json=data)
        duration2 = time.time() - start_time
        
        print(f"Status Code: {response2.status_code}")
        print(f"Dauer: {duration2:.2f} Sekunden")
        
        if response2.status_code == 200:
            result2 = response2.json()
            print(f"Status: {result2.get('status', 'unbekannt')}")
            
            # Extrahiere Text
            text = result2.get('data', {}).get('text', 'Kein Text extrahiert')
            print(f"Extrahierter Text (gekürzt): {text[:100]}...")
            is_from_cache = result2.get('data', {}).get('is_from_cache', False)
            print(f"Cache: {is_from_cache}")
            
            if duration1 > 0 and duration2 > 0:
                print(f"Geschwindigkeitsverbesserung: {(duration1/duration2):.2f}x schneller")
        else:
            print(f"Fehler: {response2.text}")
    
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print()

def check_cache_directories():
    """
    Überprüft die Cache-Verzeichnisstruktur für PDF.
    """
    print("Überprüfung der Cache-Verzeichnisstruktur für PDF:")
    
    base_cache_dir = "cache"
    pdf_cache_dir = os.path.join(base_cache_dir, "pdf")
    temp_dir = os.path.join(pdf_cache_dir, "temp")
    
    # Prüfe, ob Basis-Cache-Verzeichnis existiert
    if os.path.exists(base_cache_dir):
        print(f"✓ Basis-Cache-Verzeichnis existiert: {base_cache_dir}")
    else:
        print(f"✗ Basis-Cache-Verzeichnis fehlt: {base_cache_dir}")
    
    # Prüfe, ob PDF-Cache-Verzeichnis existiert
    if os.path.exists(pdf_cache_dir):
        print(f"✓ PDF-Cache-Verzeichnis existiert: {pdf_cache_dir}")
    else:
        print(f"✗ PDF-Cache-Verzeichnis fehlt: {pdf_cache_dir}")
    
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
        'file': test_pdf_file_without_cache,
        'file_cache': test_pdf_file_with_cache,
        'url': test_pdf_url_without_cache,
        'url_cache': test_pdf_url_with_cache,
        'cache_dirs': check_cache_directories,
    }
    
    # Command Line Parser einrichten
    parser = argparse.ArgumentParser(description='Testskript für PDF-API')
    parser.add_argument('tests', nargs='*', choices=list(tests.keys()) + ['all'],
                      help='Welche Tests sollen ausgeführt werden? (Reihenfolge wird beibehalten)')
    parser.add_argument('--skip-api-check', action='store_true',
                       help='API-Verfügbarkeitsprüfung überspringen')
    
    # Argumente parsen
    args = parser.parse_args()
    
    # Wenn keine Tests angegeben wurden, alle ausführen
    selected_tests = args.tests
    if not selected_tests or 'all' in selected_tests:
        selected_tests = list(tests.keys())
    
    print("=== PDF API-Tests ===\n")
    
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