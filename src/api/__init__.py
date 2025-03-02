"""
API-Modul für den Processing Service.
"""
from flask import Flask
from src.dashboard.routes.main_routes import main as dashboard_blueprint
from src.dashboard.routes.config_routes import config as config_blueprint
from typing import Optional

def create_app(template_dir: Optional[str] = None, static_dir: Optional[str] = None) -> Flask:
    """
    Erstellt und konfiguriert die Flask-App für die API.
    
    Args:
        template_dir: Optionaler Pfad zum Template-Verzeichnis
        static_dir: Optionaler Pfad zum Static-Verzeichnis
        
    Returns:
        Die konfigurierte Flask-App
    """
    # Importiere die API-Blueprint
    from src.api.routes import blueprint as api_blueprint
    
    # Importiere Dashboard Blueprint
    
    # Importiere Config Blueprint
    
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


