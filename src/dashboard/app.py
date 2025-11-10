"""
Copyright (C) 2025 Peter Aichner (B*commonsLAB)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

@fileoverview Main Flask Application - Central app initialization and lifecycle management

@description
Central Flask application for Common Secretary Services. This file creates and configures
the Flask app instance and manages the entire application lifecycle:
- Registers all blueprints (API, Dashboard, Config, Logs, Docs)
- Initializes MongoDB connection and cache setup
- Starts worker managers for asynchronous job processing
- Manages signal handlers for clean shutdown (SIGINT, SIGTERM)
- Configures request handlers for lazy initialization

The app is initialized on the first request (lazy loading) and manages worker managers
for session and secretary job processing.

@module dashboard.app

@exports
- app: Flask - Main Flask application instance

@usedIn
- src.main.py: Imports app and starts server
- Docker container: Loaded as main module

@dependencies
- External: flask - Flask web framework
- External: dotenv - Loading environment variables
- Internal: src.api.routes - API route blueprint
- Internal: src.utils.logger - Logging system
- Internal: src.core.mongodb - MongoDB connection and worker managers
- Internal: src.dashboard.routes.* - Dashboard route blueprints
"""
import os
import signal
import sys
import atexit
from types import FrameType
from typing import NoReturn, Optional, Union

from flask import Flask
from dotenv import load_dotenv

# .env früh laden, bevor die API-Routen (mit Env-Auswertung) importiert werden
try:
    load_dotenv()
except Exception:
    pass

from src.api.routes import blueprint as api_blueprint
from src.utils.logger import get_logger, logger_service
from src.core.mongodb import get_worker_manager, get_secretary_worker_manager, close_mongodb_connection
from src.core.mongodb.cache_setup import setup_mongodb_caching
from src.utils.logger import ProcessingLogger

from .routes.config_routes import config
from .routes.log_routes import logs
from .routes.main_routes import main
from .routes.docs_routes import docs

# Reset Logger beim Start
logger_service.reset()

app = Flask(__name__)

# Nur Logger initialisieren, wenn es nicht der Reloader-Prozess ist
app_logger: ProcessingLogger = get_logger(process_id="flask-app")
if os.environ.get('WERKZEUG_RUN_MAIN'):
    app_logger = get_logger(process_id="flask-app-reloader")

# Logge Auth-relevante Env-Parameter beim Start, um effektive Konfiguration zu verifizieren
try:
    def _parse_ip_whitelist(raw_value: str) -> list[str]:
        separators = [',', ';', ' ']
        normalized = raw_value
        for sep in separators[:-1]:
            normalized = normalized.replace(sep, ' ')
        return [p.strip() for p in normalized.split(' ') if p.strip()]

    _service_token_present = bool(os.environ.get('SECRETARY_SERVICE_API_KEY'))
    _allow_localhost = os.environ.get('ALLOW_LOCALHOST_NO_AUTH', 'false').lower() in {'1', 'true', 'yes'}
    _whitelist_raw = os.environ.get('ALLOW_SWAGGER_WHITELIST', '')
    _whitelist_list = _parse_ip_whitelist(_whitelist_raw)
    _auth_log_decisions = os.environ.get('AUTH_LOG_DECISIONS', 'false').lower() in {'1', 'true', 'yes'}

    app_logger.info(
        "Auth-Startup-Konfiguration",
        service_token_present=_service_token_present,
        allow_localhost_no_auth=_allow_localhost,
        allow_swagger_whitelist_raw=_whitelist_raw,
        allow_swagger_whitelist=_whitelist_list,
        auth_log_decisions=_auth_log_decisions
    )
except Exception:
    pass

# Register blueprints
app.register_blueprint(main)
app.register_blueprint(config)
app.register_blueprint(logs)
app.register_blueprint(api_blueprint, url_prefix='/api')
app.register_blueprint(docs)

# Flag für den ersten Request
_first_request = True
# Worker-Manager-Instanz (Typ: SessionWorkerManager oder None)
_worker_manager = None
# Neuer Secretary Worker
_secretary_worker = None
# Cache-Setup durchgeführt
_cache_setup_done = False

def signal_handler(sig: int, frame: Optional[FrameType]) -> NoReturn:
    """Handler für System-Signale (SIGINT, SIGTERM)
    
    Args:
        sig: Signal-Nummer
        frame: Stack-Frame (wird nicht verwendet)
    """
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        app_logger.info(f"Signal {sig} empfangen, beende Anwendung...")
        
        # Worker-Manager beenden
        global _worker_manager
        if _worker_manager is not None:
            try:
                _worker_manager.stop()
                app_logger.info("Worker-Manager beendet")
            except Exception as e:
                app_logger.error(f"Fehler beim Beenden des Worker-Managers: {str(e)}")
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()
    
    sys.exit(0)

@app.before_request
def before_request() -> None:
    """Wird vor jedem Request ausgeführt"""
    global _first_request, _worker_manager, _cache_setup_done
    
    if _first_request and not os.environ.get('WERKZEUG_RUN_MAIN'):
        app_logger.info("Erste Anfrage an die Anwendung")
        
        # MongoDB-Cache-Collections einrichten
        if not _cache_setup_done:
            try:
                setup_mongodb_caching(force_recreate=False)
                app_logger.info("MongoDB-Cache-Collections eingerichtet")
                _cache_setup_done = True
            except Exception as e:
                app_logger.error(f"Fehler beim Einrichten der Cache-Collections: {str(e)}")
        
        # Worker-Manager starten
        try:
            _worker_manager = get_worker_manager()
            if _worker_manager is not None:
                _worker_manager.start()
                app_logger.info("Worker-Manager gestartet")
            else:
                app_logger.info("Worker-Manager ist deaktiviert (event_worker.active=False in config.yaml)")
        except Exception as e:
            app_logger.error(f"Fehler beim Starten des Worker-Managers: {str(e)}")
        
        # Neuer Secretary Worker starten (optional separat konfigurierbar)
        try:
            global _secretary_worker
            _secretary_worker = get_secretary_worker_manager()
            if _secretary_worker is not None:
                _secretary_worker.start()
                app_logger.info("SecretaryWorkerManager gestartet")
            else:
                app_logger.info("SecretaryWorkerManager ist deaktiviert (generic_worker.active=False in config.yaml)")
        except Exception as e:
            app_logger.error(f"Fehler beim Starten des SecretaryWorkerManager: {str(e)}")
        
        _first_request = False

@app.teardown_appcontext
def teardown_app(exception: Optional[Union[Exception, BaseException]] = None) -> None:
    """Wird beim Beenden der Anwendung ausgeführt
    
    Args:
        exception: Optional auftretende Exception
    """
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        if exception:
            app_logger.error(f"Anwendung wird mit Fehler beendet: {str(exception)}")

# Funktion zum Aufräumen beim Beenden der Anwendung
def cleanup() -> None:
    """Wird beim Beenden der Anwendung ausgeführt"""
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        app_logger.info("Anwendung wird beendet")
        
        # Worker-Manager stoppen
        if _worker_manager:
            app_logger.info("Worker-Manager wird gestoppt...")
            _worker_manager.stop()
        if _secretary_worker:
            app_logger.info("SecretaryWorkerManager wird gestoppt...")
            _secretary_worker.stop()
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()

# Registriere Cleanup-Funktion
atexit.register(cleanup)

# Registriere Signal-Handler
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination request 