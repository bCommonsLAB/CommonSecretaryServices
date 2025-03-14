import requests
import time

# API-URL-Basis
BASE_URL = "http://localhost:5001/api"

def test_pdf_url():
    """
    Einfacher Test für PDF URL-Verarbeitung
    """
    print("Test: PDF URL-Verarbeitung")

    try:
        # Versuche zuerst, die API-Dokumentation abzurufen, um den korrekten Endpunkt zu finden
        print("Prüfe verfügbare API-Endpunkte...")
        swagger = requests.get(f"{BASE_URL}/swagger.json")
        if swagger.status_code == 200:
            paths = swagger.json().get('paths', {})
            pdf_endpoints = [path for path in paths.keys() if '/pdf/' in path]
            print(f"Gefundene PDF-Endpunkte: {pdf_endpoints}")
        else:
            print(f"Konnte Swagger-Dokumentation nicht abrufen: {swagger.status_code}")

        # Versuche mit dem /pdf/process Endpunkt
        print("\nTeste /pdf/process Endpunkt:")
        # Beispiel-URL für ein öffentliches PDF
        pdf_url = "https://fosdem.org/2025/events/attachments/fosdem-2025-5258-forked-communities-project-re-licensing-and-community-impact/slides/238218/FOSDEM_Fo_HyZR9km.pdf"
        
        # Form-Daten mit URL
        data = {
            "url": pdf_url,
            "use_cache": "false"
        }
        
        # Sende die Anfrage an den einfachen process-Endpunkt
        response = requests.post(f"{BASE_URL}/pdf/process", data=data)
        
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            print(f"Status: {result.get('status', 'unbekannt')}")
            text = result.get('data', {}).get('text', 'Kein Text extrahiert')
            print(f"Extrahierter Text (gekürzt): {text[:100] if len(text) > 100 else text}")
        else:
            print(f"Fehler: {response.text[:200]}...")
    
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print("Test abgeschlossen.")

if __name__ == "__main__":
    test_pdf_url() 