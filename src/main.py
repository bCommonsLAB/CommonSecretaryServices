from src.dashboard.app import app
from src.utils.logger import get_logger
import os

logger = get_logger(process_id="main")

if __name__ == '__main__':
    # Nur loggen, wenn es nicht der Reloader-Prozess ist
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Anwendung wird gestartet")
    app.run(host='0.0.0.0', port=5001, debug=False)