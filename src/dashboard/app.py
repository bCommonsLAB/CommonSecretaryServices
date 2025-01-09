"""
Main Flask application module.
"""
from flask import Flask
import signal
import sys
import os
from src.utils.logger import get_logger, logger_service
from .routes.main_routes import main
from .routes.config_routes import config
from .routes.log_routes import logs
from src.api.routes import blueprint as api_blueprint

# Reset Logger beim Start
logger_service.reset()

app = Flask(__name__)

# Nur Logger initialisieren, wenn es nicht der Reloader-Prozess ist
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    logger = get_logger(process_id="flask-app")
else:
    logger = get_logger(process_id="flask-app-reloader")

# Register blueprints
app.register_blueprint(main)
app.register_blueprint(config)
app.register_blueprint(logs)
app.register_blueprint(api_blueprint, url_prefix='/api')

# Flag für den ersten Request
_first_request = True

def signal_handler(sig, frame):
    """Handler für System-Signale (SIGINT, SIGTERM)"""
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info(f"Anwendung wird beendet durch Signal {sig}")
    sys.exit(0)

@app.before_request
def before_request():
    """Wird vor jedem Request ausgeführt"""
    global _first_request
    if _first_request and not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Erste Anfrage an die Anwendung")
        _first_request = False

@app.teardown_appcontext
def teardown_app(exception=None):
    """Wird beim Beenden der Anwendung ausgeführt"""
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        if exception:
            logger.error(f"Anwendung wird mit Fehler beendet: {str(exception)}")

# Registriere Signal-Handler
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination request 