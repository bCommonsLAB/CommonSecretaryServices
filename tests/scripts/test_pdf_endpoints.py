import requests

# API-URL-Basis
BASE_URL = "http://localhost:5001/api"

def test_pdf_endpoints():
    """
    Testet verschiedene PDF-Endpunkte und Anfragemethoden
    """
    print("=== PDF-Endpunkt-Tests ===")
    
    # Beispiel-URL für ein öffentliches PDF
    pdf_url = "https://fosdem.org/2025/events/attachments/fosdem-2025-5258-forked-communities-project-re-licensing-and-community-impact/slides/238218/FOSDEM_Fo_HyZR9km.pdf"
    
    # Test 1: Einfache GET-Anfrage an den Basis-Endpunkt
    print("\nTest 1: GET-Anfrage an PDF-Basisendpunkt")
    try:
        response = requests.get(f"{BASE_URL}/pdf/")
        print(f"Status Code: {response.status_code}")
        print(f"Antwort: {response.text[:100]}...")
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    # Test 2: POST an /pdf/process-url mit JSON-Daten
    print("\nTest 2: POST an /pdf/process-url mit JSON-Daten")
    try:
        data = {"url": pdf_url, "use_cache": False}
        response = requests.post(f"{BASE_URL}/pdf/process-url", json=data)
        print(f"Status Code: {response.status_code}")
        print(f"Antwort: {response.text[:100]}...")
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    # Test 3: POST an /pdf/process-url mit Form-Daten
    print("\nTest 3: POST an /pdf/process-url mit Form-Daten")
    try:
        data = {"url": pdf_url, "use_cache": "false"}
        response = requests.post(f"{BASE_URL}/pdf/process-url", data=data)
        print(f"Status Code: {response.status_code}")
        print(f"Antwort: {response.text[:100]}...")
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    # Test 4: GET an /pdf/process-url mit URL-Parameter
    print("\nTest 4: GET an /pdf/process-url mit URL-Parameter")
    try:
        params = {"url": pdf_url, "use_cache": "false"}
        response = requests.get(f"{BASE_URL}/pdf/process-url", params=params)
        print(f"Status Code: {response.status_code}")
        print(f"Antwort: {response.text[:100]}...")
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    # Test 5: POST an /pdf/process mit URL im JSON
    print("\nTest 5: POST an /pdf/process mit URL im JSON")
    try:
        data = {"url": pdf_url, "use_cache": False}
        response = requests.post(f"{BASE_URL}/pdf/process", json=data)
        print(f"Status Code: {response.status_code}")
        print(f"Antwort: {response.text[:100]}...")
    except Exception as e:
        print(f"Fehler: {str(e)}")
    
    print("\n=== Tests abgeschlossen ===")

if __name__ == "__main__":
    test_pdf_endpoints() 