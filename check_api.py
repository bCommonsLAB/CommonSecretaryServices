import requests
import json

def check_api_response():
    # Batches aus unserem vorherigen Check
    batch_ids = [
        "batch-5e1d7400-49c2-4be2-8b94-b1f11416120c",
        "batch-67c2dc84d18f4547296011a1"
    ]
    
    # API-Basis-URL
    base_url = "http://localhost:5001/api/event-job"
    
    # Check für jeden Batch
    for batch_id in batch_ids:
        print(f"\nÜberprüfe Batch: {batch_id}")
        
        # Anfrage an die API
        url = f"{base_url}/jobs?batch_id={batch_id}"
        print(f"API-URL: {url}")
        
        try:
            response = requests.get(url)
            response.raise_for_status()
            
            # Response ausgeben
            data = response.json()
            print("API-Antwort:")
            print(json.dumps(data, indent=2))
            
            # Zugänglichkeit der APIs in der Dashboard-Anwendung überprüfen
            dashboard_api_url = f"http://localhost:5000/api/dashboard/event-monitor/jobs?batch_id={batch_id}"
            print(f"\nDashboard-API-URL: {dashboard_api_url}")
            
            dashboard_response = requests.get(dashboard_api_url)
            dashboard_response.raise_for_status()
            
            # Dashboard-Response ausgeben
            dashboard_data = dashboard_response.json()
            print("Dashboard-API-Antwort:")
            print(json.dumps(dashboard_data, indent=2))
            
        except requests.RequestException as e:
            print(f"Fehler bei der Anfrage: {str(e)}")
        except ValueError as e:
            print(f"Fehler beim Parsen der Antwort: {str(e)}")

if __name__ == "__main__":
    check_api_response() 