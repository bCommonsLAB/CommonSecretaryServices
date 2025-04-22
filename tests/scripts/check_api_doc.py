import requests
from bs4 import BeautifulSoup

def check_api_doc():
    try:
        response = requests.get('http://localhost:5001/api/doc')
        if response.status_code == 200:
            print(f"API-Dokumentation ist verfügbar (Status: {response.status_code})")
            
            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Suche nach Links in der Dokumentation
            links = soup.find_all('a')
            if links:
                print("\nGefundene Links in der API-Dokumentation:")
                for link in links:
                    href = link.get('href')
                    if href and not href.startswith('#'):
                        print(f"  - {href}")
            
            # Suche nach Swagger-spezifischen Elementen
            swagger_ui = soup.find(id='swagger-ui')
            if swagger_ui:
                print("\nSwagger UI gefunden")
            
            # Suche nach Script-Tags, die auf Swagger-JSON verweisen könnten
            scripts = soup.find_all('script')
            for script in scripts:
                src = script.get('src')
                if src and ('swagger' in src.lower() or 'openapi' in src.lower()):
                    print(f"\nSwagger/OpenAPI Script gefunden: {src}")
            
            # Suche nach möglichen API-Pfaden im Text
            text = soup.get_text()
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            api_lines = [line for line in lines if '/api/' in line]
            if api_lines:
                print("\nMögliche API-Pfade im Text:")
                for line in api_lines:
                    print(f"  - {line}")
        else:
            print(f"Fehler beim Abrufen der API-Dokumentation: {response.status_code}")
    except Exception as e:
        print(f"Fehler: {str(e)}")

if __name__ == "__main__":
    check_api_doc() 