from flask import Flask
from src.api.routes import blueprint as api_blueprint
from src.utils.logger import get_logger
import os
from pathlib import Path
import argparse
import requests
import json

logger = get_logger(process_id="test_api")

# Pfade für statische Dateien und Templates definieren
static_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'dashboard', 'static'))
template_folder = os.path.abspath(os.path.join(os.path.dirname(__file__), 'src', 'dashboard', 'templates'))

# Überprüfen und ausgeben der Pfade
logger.info(f"Statischer Ordner: {static_folder}")
logger.info(f"Template-Ordner: {template_folder}")

# Erstelle die Flask-Anwendung
app = Flask(__name__, 
           static_folder=static_folder,
           template_folder=template_folder)

# Swagger-UI Ordner überprüfen
swagger_path = os.path.join(static_folder, 'swaggerui')
if os.path.exists(swagger_path):
    logger.info(f"Swagger-UI-Ordner gefunden: {swagger_path}")
else:
    logger.warning(f"Swagger-UI-Ordner nicht gefunden: {swagger_path}")

# API-Blueprint registrieren
app.register_blueprint(api_blueprint, url_prefix='/api')

# Füge Dashboard-Blueprint hinzu, wenn --with-dashboard angegeben ist
def add_dashboard_blueprint():
    try:
        from src.dashboard.routes.main_routes import main as dashboard_blueprint
        from src.dashboard.routes.config_routes import config as config_blueprint
        app.register_blueprint(dashboard_blueprint)
        app.register_blueprint(config_blueprint)
        logger.info("Dashboard-Blueprints erfolgreich registriert")
        return True
    except Exception as e:
        logger.error(f"Fehler beim Registrieren der Dashboard-Blueprints: {e}")
        return False

if __name__ == '__main__':
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Starte den API- und/oder Dashboard-Server')
    parser.add_argument('--port', type=int, default=5001, help='Port, auf dem der Server laufen soll (Standard: 5001)')
    parser.add_argument('--with-dashboard', action='store_true', help='Dashboard-Komponenten laden und aktivieren')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host-Adresse für den Server (Standard: 0.0.0.0)')
    
    args = parser.parse_args()
    
    # Dashboard-Komponenten laden, wenn gewünscht
    if args.with_dashboard:
        if add_dashboard_blueprint():
            logger.info("Server startet mit API und Dashboard")
        else:
            logger.warning("Server startet nur mit API (Dashboard konnte nicht geladen werden)")
    else:
        logger.info("Server startet nur mit API (Dashboard wurde nicht angefordert)")
    
    # Server starten
    logger.info(f"Server wird gestartet auf {args.host}:{args.port}...")
    app.run(debug=True, port=args.port, host=args.host)
    logger.info("Server beendet.")

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