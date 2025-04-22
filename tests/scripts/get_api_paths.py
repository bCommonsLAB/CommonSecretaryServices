import requests
import json

def get_api_paths():
    try:
        response = requests.get('http://localhost:5001/api/doc/swagger.json')
        if response.status_code == 200:
            data = response.json()
            paths = list(data['paths'].keys())
            print("Verfügbare API-Pfade:")
            for path in paths:
                print(f"  - {path}")
        else:
            print(f"Fehler beim Abrufen der Swagger-Dokumentation: {response.status_code}")
            
            # Versuche alternative URL
            alt_response = requests.get('http://localhost:5001/swagger.json')
            if alt_response.status_code == 200:
                data = alt_response.json()
                paths = list(data['paths'].keys())
                print("Verfügbare API-Pfade (alternative URL):")
                for path in paths:
                    print(f"  - {path}")
            else:
                print(f"Fehler beim Abrufen der alternativen Swagger-Dokumentation: {alt_response.status_code}")
    except Exception as e:
        print(f"Fehler: {str(e)}")

if __name__ == "__main__":
    get_api_paths() 