import requests
import json

def test_tracks_endpoint():
    """Testet den Tracks-Endpunkt."""
    url = "http://localhost:5001/api/tracks/available"
    print(f"Sende GET-Anfrage an: {url}")
    
    try:
        response = requests.get(url)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            # JSON formatieren und ausgeben
            data = response.json()
            print(json.dumps(data, indent=2, ensure_ascii=False))
        else:
            print(f"Fehler: {response.text}")
    except Exception as e:
        print(f"Fehler bei der Anfrage: {e}")

if __name__ == "__main__":
    test_tracks_endpoint() 