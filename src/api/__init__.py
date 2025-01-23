from flask import Flask
from .routes import blueprint as api_blueprint
from src.dashboard.routes.main_routes import main as dashboard_blueprint
from src.dashboard.routes.config_routes import config as config_blueprint
import os
from flask_restx import Api
from .routes.audio_routes import api as audio_ns
from .routes.youtube_routes import api as youtube_ns
from .routes.metadata_routes import api as metadata_ns

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
    
    api = Api(
        title='Common Secretary Services API',
        version='1.0',
        description='API für die Verarbeitung von Audio, Video und anderen Medien'
    )

    api.add_namespace(audio_ns, path='/api/v1/audio')
    api.add_namespace(youtube_ns, path='/api/v1/youtube')
    api.add_namespace(metadata_ns, path='/api/v1/metadata')
    
    return app

app = create_app()


