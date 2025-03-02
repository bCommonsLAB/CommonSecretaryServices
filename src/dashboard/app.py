"""
Main Flask application module.
"""
import os
import signal
import sys
import atexit
from types import FrameType
from typing import NoReturn, Optional, Union

from flask import Flask

from src.api.routes import blueprint as api_blueprint
from src.utils.logger import get_logger, logger_service
from src.core.mongodb import get_worker_manager, close_mongodb_connection

from .routes.config_routes import config
from .routes.log_routes import logs
from .routes.main_routes import main

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
# Worker-Manager-Instanz
_worker_manager = None

def signal_handler(sig: int, frame: Optional[FrameType]) -> NoReturn:
    """Handler für System-Signale (SIGINT, SIGTERM)
    
    Args:
        sig: Signal-Nummer
        frame: Stack-Frame (wird nicht verwendet)
    """
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info(f"Anwendung wird beendet durch Signal {sig}")
        
        # Worker-Manager stoppen
        if _worker_manager:
            logger.info("Worker-Manager wird gestoppt...")
            _worker_manager.stop()
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()
    
    sys.exit(0)

@app.before_request
def before_request() -> None:
    """Wird vor jedem Request ausgeführt"""
    global _first_request, _worker_manager
    
    if _first_request and not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Erste Anfrage an die Anwendung")
        
        # Worker-Manager starten
        try:
            _worker_manager = get_worker_manager()
            _worker_manager.start()
            logger.info("Worker-Manager gestartet")
        except Exception as e:
            logger.error(f"Fehler beim Starten des Worker-Managers: {str(e)}")
        
        _first_request = False

@app.teardown_appcontext
def teardown_app(exception: Optional[Union[Exception, BaseException]] = None) -> None:
    """Wird beim Beenden der Anwendung ausgeführt
    
    Args:
        exception: Optional auftretende Exception
    """
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        if exception:
            logger.error(f"Anwendung wird mit Fehler beendet: {str(exception)}")

# Funktion zum Aufräumen beim Beenden der Anwendung
def cleanup() -> None:
    """Wird beim Beenden der Anwendung ausgeführt"""
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Anwendung wird beendet")
        
        # Worker-Manager stoppen
        if _worker_manager:
            logger.info("Worker-Manager wird gestoppt...")
            _worker_manager.stop()
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()

# Registriere Cleanup-Funktion
atexit.register(cleanup)

# Registriere Signal-Handler
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination request 