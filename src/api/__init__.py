"""
@fileoverview API Module - Alternative app factory for API-only deployment

@description
Alternative Flask app factory for the Processing Service. This file provides an
alternative way to create the Flask application, primarily intended for API-only
deployments (without dashboard).

The create_app function creates a Flask app with:
- API routes under /api
- Dashboard routes (optional)
- MongoDB connection initialization
- Configuration for upload limits

Note: The main application uses dashboard.app.py. This file is primarily provided
for alternative deployment scenarios.

@module api

@exports
- create_app(): Flask - Creates and configures Flask app
- run_server(): None - Starts the API server
- app: Flask - Application instance (created on import)

@usedIn
- Alternative deployment scenarios (currently not actively used)
- Can be used for API-only deployments

@dependencies
- External: flask - Flask web framework
- External: dotenv - Loading environment variables
- Internal: src.api.routes - API route blueprint
- Internal: src.dashboard.routes.* - Dashboard route blueprints
- Internal: src.core.mongodb.connection - MongoDB connection
"""
from flask import Flask
from dotenv import load_dotenv
from src.dashboard.routes.main_routes import main as dashboard_blueprint
from src.dashboard.routes.config_routes import config as config_blueprint
from typing import Optional
import logging

# Logger initialisieren
logger = logging.getLogger(__name__)

def create_app(template_dir: Optional[str] = None, static_dir: Optional[str] = None) -> Flask:
    """
    Erstellt und konfiguriert die Flask-App für die API.
    
    Args:
        template_dir: Optionaler Pfad zum Template-Verzeichnis
        static_dir: Optionaler Pfad zum Static-Verzeichnis
        
    Returns:
        Die konfigurierte Flask-App
    """
    # Lade .env sehr früh, damit Auth-Variablen (SECRETARY_SERVICE_API_KEY, ALLOW_*) sicher verfügbar sind
    try:
        load_dotenv()
    except Exception as _:
        pass

    # Importiere die API-Blueprint
    from src.api.routes import blueprint as api_blueprint
    
    # Initialisiere MongoDB und Cache-Indizes früh, bevor die App Anfragen verarbeitet
    try:
        logger.info("Initialisiere MongoDB-Verbindung beim Serverstart...")
        from src.core.mongodb.connection import setup_mongodb_connection
        setup_mongodb_connection()
        logger.info("MongoDB-Verbindung und Cache-Indizes erfolgreich initialisiert")
    except Exception as e:
        logger.error(f"Fehler bei der Initialisierung der MongoDB-Verbindung: {str(e)}")
        logger.warning("Server wird trotzdem gestartet, aber es kann zu Cache-Problemen kommen")
    
    # Erstelle die Flask-App
    app = Flask(__name__, 
                static_folder=static_dir or 'static',
                template_folder=template_dir or 'templates')
    
    # Konfiguriere die App
    app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB upload limit
    app.config['PREFERRED_URL_SCHEME'] = 'http'
    
    # Registriere die API-Routen bei der App
    app.register_blueprint(api_blueprint, url_prefix='/api')
    
    # Registriere die Dashboard-Routen
    app.register_blueprint(dashboard_blueprint)
    
    # Registriere die Konfigurations-Routen
    app.register_blueprint(config_blueprint)

    # Event-Handler für Serverbeendigung
    import atexit
    from src.core.mongodb.connection import close_mongodb_connection
    
    # MongoDB-Verbindung beim Beenden der App schließen
    atexit.register(close_mongodb_connection)
    
    return app

# Funktion zum Erstellen und Starten des Servers
def run_server(host: str = '0.0.0.0', port: int = 5000, debug: bool = False, with_dashboard: bool = True) -> None:
    """
    Erstellt und startet den API-Server.
    
    Args:
        host: Host-Adresse, an die der Server gebunden wird
        port: Port, auf dem der Server läuft
        debug: Ob der Debug-Modus aktiviert sein soll
        with_dashboard: Ob das Dashboard aktiviert sein soll
    """
    app = create_app()
    app.run(host=host, port=port, debug=debug)

# Erstelle die Anwendungsinstanz
app = create_app()


