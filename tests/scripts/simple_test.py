import requests
import time
import os

# API-URL-Basis
BASE_URL = "http://localhost:5001/api"

def test_imageocr():
    """
    Einfacher Test für ImageOCR
    """
    print("Test: ImageOCR")
    
    # Prüfe, ob die Testdatei existiert
    image_file = "tests/samples/diagramm.jpg"
    if not os.path.exists(image_file):
        print(f"Datei nicht gefunden: {image_file}")
        return
    
    try:
        # Bereite Multipart-Formular-Daten vor
        files = {'file': open(image_file, 'rb')}
        data = {
            'use_cache': 'false'
        }
        
        # Sende die Anfrage
        start_time = time.time()
        response = requests.post(f"{BASE_URL}/imageocr/process", files=files, data=data)
        duration = time.time() - start_time
        
        print(f"Status Code: {response.status_code}")
        print(f"Dauer: {duration:.2f} Sekunden")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Status: {result.get('status', 'unbekannt')}")
            
            # Extrahiere erkannten Text
            text = result.get('data', {}).get('text', 'Kein Text erkannt')
            print(f"Erkannter Text (gekürzt): {text[:100] if len(text) > 100 else text}")
            print(f"Cache: {result.get('data', {}).get('is_from_cache', False)}")
        else:
            print(f"Fehler: {response.text}")
            
        # Schließe die Datei
        files['file'].close()
        
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print("Test abgeschlossen.")

if __name__ == "__main__":
    test_imageocr() 