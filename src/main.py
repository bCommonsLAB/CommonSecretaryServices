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

@fileoverview Server Entry Point - Starts the Flask application

@description
Main module for starting the Common Secretary Services server. This file is the entry
point for the application and performs the following initialization steps:
1. Loads environment variables from .env file
2. Configures SSL verification for Windows (optional)
3. Imports and starts the Flask app from dashboard.app
4. Starts the server on port 5001

The file handles special Windows configurations for SSL/TLS and yt-dlp.

@module main

@exports
- (no direct exports, executed as script)

@usedIn
- Direct execution: python src/main.py
- Docker container: CMD ["python", "-m", "src.main"]

@dependencies
- External: dotenv - Loading environment variables
- Internal: src.dashboard.app - Main Flask application
- Internal: src.utils.logger - Logging system
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