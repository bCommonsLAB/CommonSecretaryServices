"""
Test-Skript für die Story-Generation-API.
"""
import json
import requests

def test_story_generation():
    """Testet die Story-Generation-API."""
    print("Sende Anfrage an Story-Generation-Endpunkt...")
    
    url = "http://localhost:5000/api/story/generate"
    headers = {"Content-Type": "application/json"}
    data = {
        "topic_id": "nachhaltigkeit-2023",
        "event": "forum-2023",
        "target_group": "politik",
        "languages": ["de", "en"],
        "detail_level": 3
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        
        # Ausgabe der Antwort
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            json_response = response.json()
            print("\nErfolgreiche Antwort:")
            print(json.dumps(json_response, indent=2, ensure_ascii=False))
            
            # Prüfen, ob Markdown-Dateien erstellt wurden
            if "data" in json_response and "output" in json_response["data"]:
                output = json_response["data"]["output"]
                if "markdown_files" in output:
                    print("\nGenerierte Markdown-Dateien:")
                    for language, file_path in output["markdown_files"].items():
                        print(f"- {language}: {file_path}")
        else:
            print("\nFehler in der Antwort:")
            try:
                print(json.dumps(response.json(), indent=2, ensure_ascii=False))
            except:
                print(response.text)
    
    except Exception as e:
        print(f"Fehler beim Senden der Anfrage: {str(e)}")

if __name__ == "__main__":
    test_story_generation() 