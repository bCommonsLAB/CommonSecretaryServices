"""
Hauptmodul für den Start des Servers.
"""

import sys
import os

# Füge das Projektverzeichnis zum Pythonpfad hinzu
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

# WICHTIG: .env explizit laden, BEVOR irgendwas anderes passiert
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)
print(f"[MAIN] .env geladen: {env_path}")
print(f"[MAIN] PYTHONHTTPSVERIFY={os.getenv('PYTHONHTTPSVERIFY')}")
print(f"[MAIN] YTDLP_COOKIES_FILE={os.getenv('YTDLP_COOKIES_FILE')}")

# WICHTIG: Windows-TLS-Workaround für yt-dlp MUSS ganz am Anfang stehen
# Deaktiviere SSL-Verifikation, wenn PYTHONHTTPSVERIFY=0 gesetzt ist
# Dies muss VOR allen anderen Imports passieren, damit yt-dlp/requests es nutzen
if os.getenv('PYTHONHTTPSVERIFY', '').lower() in {'0', 'false'}:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # type: ignore
    print("[MAIN] SSL-Verifikation global deaktiviert (PYTHONHTTPSVERIFY=0)")

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