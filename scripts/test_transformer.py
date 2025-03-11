#!/usr/bin/env python3
"""
Testskript für den Transformer-Prozessor.
Testet die API-Endpunkte mit und ohne Cache.
"""
from typing import Dict, Union, Any
import requests
import json
import time
import os
import argparse

# Aktualisierte API-URL-Basis
BASE_URL = "http://localhost:5001/api"

def test_transformer_text_without_cache():
    """
    Testet die Texttransformation ohne Cache.
    """
    print("Test: Einfache Texttransformation ohne Cache")
    data = {
        "text": "Hallo Welt",
        "source_language": "de",
        "target_language": "en",
        "use_cache": False
    }
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/transformer/text", json=data)
    duration = time.time() - start_time
    
    print(f"Status Code: {response.status_code}")
    print(f"Dauer: {duration:.2f} Sekunden")
    
    if response.status_code == 200:
        result = response.json()
        transformed_text = result.get('data', {}).get('transformed_text', 'Keine Transformation')
        print(f"Ergebnis: {transformed_text}")
        print(f"Cache: {result.get('data', {}).get('is_from_cache', False)}")
    else:
        print(f"Fehler: {response.text}")
    
    print()
    return duration

def test_transformer_text_with_cache():
    """
    Testet die Texttransformation mit Cache.
    """
    print("Test: Einfache Texttransformation mit Cache")
    data = {
        "text": "Hallo Welt",
        "source_language": "de",
        "target_language": "en",
        "use_cache": True
    }
    
    # Erster Aufruf (sollte in den Cache schreiben)
    print("Erster Aufruf:")
    start_time = time.time()
    response1 = requests.post(f"{BASE_URL}/transformer/text", json=data)
    duration1 = time.time() - start_time
    
    print(f"Status Code: {response1.status_code}")
    print(f"Dauer: {duration1:.2f} Sekunden")
    
    if response1.status_code == 200:
        result1 = response1.json()
        transformed_text = result1.get('data', {}).get('transformed_text', 'Keine Transformation')
        print(f"Ergebnis: {transformed_text}")
        print(f"Cache: {result1.get('data', {}).get('is_from_cache', False)}")
    else:
        print(f"Fehler: {response1.text}")
    
    # Zweiter Aufruf (sollte aus dem Cache lesen)
    print("\nZweiter Aufruf (sollte aus dem Cache):")
    start_time = time.time()
    response2 = requests.post(f"{BASE_URL}/transformer/text", json=data)
    duration2 = time.time() - start_time
    
    print(f"Status Code: {response2.status_code}")
    print(f"Dauer: {duration2:.2f} Sekunden")
    
    if response2.status_code == 200:
        result2 = response2.json()
        transformed_text = result2.get('data', {}).get('transformed_text', 'Keine Transformation')
        print(f"Ergebnis: {transformed_text}")
        is_from_cache = result2.get('data', {}).get('is_from_cache', False)
        print(f"Cache: {is_from_cache}")
        
        if duration1 > 0 and duration2 > 0:
            print(f"Geschwindigkeitsverbesserung: {(duration1/duration2):.2f}x schneller")
    else:
        print(f"Fehler: {response2.text}")
    
    print()

def test_transformer_template():
    """
    Testet die Template-basierte Transformation.
    """
    print("Test: Template-basierte Transformation")
    data = {
        "text": "Berlin ist die Hauptstadt von Deutschland.",
        "source_language": "de",
        "target_language": "en",
        "template": "Gedanken"
    }
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/transformer/template", json=data)
    duration = time.time() - start_time
    
    print(f"Status Code: {response.status_code}")
    print(f"Dauer: {duration:.2f} Sekunden")
    
    if response.status_code == 200:
        result = response.json()
        transformed_text = result.get('data', {}).get('transformed_text', 'Keine Transformation')
        print(f"Ergebnis: {transformed_text}")
    else:
        print(f"Fehler: {response.text}")
    
    print()

def test_transformer_json_content():
    """
    Testet die Transformation von JSON-Inhalten.
    """
    print("Test: Transformation von JSON-Inhalten")
    
    json_file = "tests/samples/notion_blog_sample.json"
    if not os.path.exists(json_file):
        print(f"Datei nicht gefunden: {json_file}")
        return
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            content: Dict[str, Any] = json.load(f)
        
        # Extrahiere den Text aus dem JSON
        if "content" in content:
            text: str = content["content"]
        else:
            text: str = json.dumps(content)
        
        data: Dict[str, Union[str, bool]] = {
            "text": text[:500],  # Nur die ersten 500 Zeichen für den Test
            "source_language": "auto",
            "target_language": "de",
            "use_cache": True
        }
        
        start_time = time.time()
        response: requests.Response = requests.post(f"{BASE_URL}/transformer/text", json=data)
        duration: float = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Dauer: {duration:.2f} Sekunden")
        
        if response.status_code == 200:
            result = response.json()
            transformed_text = result.get('data', {}).get('transformed_text', 'Keine Transformation')
            print(f"Ergebnis (gekürzt): {transformed_text[:100]}...")
            print(f"Cache: {result.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response.text}")
        
    except Exception as e:
        print(f"Fehler beim Lesen oder Verarbeiten der JSON-Datei: {e}")
    
    print()

def check_cache_directories():
    """
    Überprüft die Cache-Verzeichnisstruktur.
    """
    print("Überprüfung der Cache-Verzeichnisstruktur:")
    
    base_cache_dir = "cache"
    transformer_cache_dir = os.path.join(base_cache_dir, "transformer")
    temp_dir = os.path.join(transformer_cache_dir, "temp")
    
    # Prüfe, ob Basis-Cache-Verzeichnis existiert
    if os.path.exists(base_cache_dir):
        print(f"✓ Basis-Cache-Verzeichnis existiert: {base_cache_dir}")
    else:
        print(f"✗ Basis-Cache-Verzeichnis fehlt: {base_cache_dir}")
    
    # Prüfe, ob Transformer-Cache-Verzeichnis existiert
    if os.path.exists(transformer_cache_dir):
        print(f"✓ Transformer-Cache-Verzeichnis existiert: {transformer_cache_dir}")
    else:
        print(f"✗ Transformer-Cache-Verzeichnis fehlt: {transformer_cache_dir}")
    
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
        'text': test_transformer_text_without_cache,
        'text_cache': test_transformer_text_with_cache,
        'template': test_transformer_template,
        'json': test_transformer_json_content,
        'cache_dirs': check_cache_directories,
    }
    
    # Command Line Parser einrichten
    parser = argparse.ArgumentParser(description='Testskript für Transformer-API')
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
    
    print("=== Transformer API-Tests ===\n")
    
    # API-Verfügbarkeit prüfen (falls nicht übersprungen)
    if not args.skip_api_check:
        if not check_api_availability():
            return
    
    # Ausgewählte Tests in der angegebenen Reihenfolge ausführen
    print(f"Führe folgende Tests aus: {', '.join(selected_tests)}\n")
    for test_name in selected_tests:
        tests[test_name]()
    
    print("=== Tests abgeschlossen ===")

if __name__ == "__main__":
    main() 