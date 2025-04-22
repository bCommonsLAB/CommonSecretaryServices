import requests

url = "http://localhost:5001/api/event-job/files/FOSDEM%202025/Open-Research-22/Beyond-Compliance-Assessing-Modern-Slavery-Statements-using-the-Wikirate-platform/assets/preview_001.png"

try:
    # Versuche einen HEAD-Request
    response = requests.head(url)
    print(f"HEAD-Request Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("Die Datei ist über die API erreichbar!")
        print(f"Content-Type: {response.headers.get('Content-Type')}")
        print(f"Content-Length: {response.headers.get('Content-Length')}")
    else:
        print(f"Fehler: Die Datei konnte nicht erreicht werden. Statuscode: {response.status_code}")
        
        # Versuche mehr Details zu bekommen
        get_response = requests.get(url)
        print(f"GET-Request Status Code: {get_response.status_code}")
        if get_response.status_code != 200:
            print(f"Response Text: {get_response.text[:500]}")  # Erste 500 Zeichen des Antworttextes
            
except Exception as e:
    print(f"Ein Fehler ist aufgetreten: {str(e)}") 