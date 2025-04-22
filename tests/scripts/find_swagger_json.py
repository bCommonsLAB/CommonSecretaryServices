import requests
import json

def find_swagger_json():
    base_url = 'http://localhost:5001'
    possible_paths = [
        '/api/doc/swagger.json',
        '/swagger.json',
        '/api/swagger.json',
        '/api/doc/openapi.json',
        '/openapi.json',
        '/api/openapi.json',
        '/api/v1/swagger.json',
        '/api/v1/openapi.json',
        '/swaggerui/swagger.json',
        '/api/doc/swagger-ui.json',
        '/api/spec',
        '/api/docs/swagger.json'
    ]
    
    for path in possible_paths:
        url = base_url + path
        try:
            response = requests.get(url)
            if response.status_code == 200:
                print(f"Swagger/OpenAPI JSON gefunden unter: {url}")
                try:
                    data = response.json()
                    if 'paths' in data:
                        paths = list(data['paths'].keys())
                        print(f"\nAPI-Pfade in {path}:")
                        for api_path in paths:
                            print(f"  - {api_path}")
                    else:
                        print(f"Keine 'paths' in der JSON-Antwort gefunden.")
                except json.JSONDecodeError:
                    print(f"Die Antwort ist kein gültiges JSON.")
            else:
                print(f"Pfad nicht gefunden: {path} (Status: {response.status_code})")
        except Exception as e:
            print(f"Fehler bei {path}: {str(e)}")

if __name__ == "__main__":
    find_swagger_json() 