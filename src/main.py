"""
Hauptmodul für den Start des Servers.
"""

import sys
import os

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# Jetzt können wir die Module importieren
from src.dashboard.app import app
from src.utils.logger import get_logger, logger_service

# Reset Logger beim Start
logger_service.reset()
logger = get_logger(process_id="main")

if __name__ == '__main__':
    # Nur loggen, wenn es nicht der Reloader-Prozess ist
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Anwendung wird gestartet")
    app.run(host='0.0.0.0', port=5001, debug=False)