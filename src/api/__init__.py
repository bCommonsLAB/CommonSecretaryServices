from flask import Flask
from .routes import blueprint as api_blueprint
from src.dashboard.routes.main_routes import main as dashboard_blueprint
from src.dashboard.routes.config_routes import config as config_blueprint
import os

def create_app():
    # Template-Verzeichnis konfigurieren
    template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'templates'))
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'dashboard', 'static'))
    
    app = Flask(__name__,
                template_folder=template_dir,
                static_folder=static_dir)
    
    # Registriere das Dashboard als Hauptanwendung
    app.register_blueprint(dashboard_blueprint)
    
    # Registriere die API unter /api
    app.register_blueprint(api_blueprint, url_prefix='/api')
    
    # Registriere die Konfigurations-Routen
    app.register_blueprint(config_blueprint)
    
    return app

app = create_app()


