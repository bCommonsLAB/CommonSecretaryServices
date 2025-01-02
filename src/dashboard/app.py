"""
Main application file for the dashboard.
Initializes the Flask application and registers all blueprints.
"""
from flask import Flask
from .routes.main_routes import main
from .routes.log_routes import logs
from .routes.config_routes import config
from api import api_blueprint

def create_app():
    """
    Create and configure the Flask application
    
    Returns:
        Flask: The configured Flask application instance
    """
    app = Flask(__name__)
    
    # Register blueprints
    app.register_blueprint(main)
    app.register_blueprint(logs)
    app.register_blueprint(config)
    app.register_blueprint(api_blueprint, url_prefix='/api')
    
    return app

# Create the application instance
app = create_app() 