"""
Copyright (C) 2025 Peter Aichner (b*commonsLAB)

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

# WICHTIG: .env explizit laden, BEVOR irgendwas anderes passiert.
# override=True: Werte aus .env überschreiben bereits gesetzte Umgebungsvariablen (z. B. alten OPENAI_API_KEY).
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path, override=True)
print(f"[MAIN] .env geladen: {env_path}")
print(f"[MAIN] PYTHONHTTPSVERIFY={os.getenv('PYTHONHTTPSVERIFY')}")
print(f"[MAIN] YTDLP_COOKIES_FILE={os.getenv('YTDLP_COOKIES_FILE')}")
print(f"[MAIN] YTDLP_COOKIES_FROM_BROWSER={os.getenv('YTDLP_COOKIES_FROM_BROWSER')}")
print(f"[MAIN] YTDLP_YOUTUBE_COOKIES_FILE={os.getenv('YTDLP_YOUTUBE_COOKIES_FILE')}")

# TLS-Regel (AP-04) MUSS vor allen anderen Imports angewendet werden, damit yt-dlp/requests
# den Kontext nutzen. PYTHONHTTPSVERIFY=0 wirkt nur zusammen mit FLASK_ENV=development.
from src.core.security import apply_tls_policy
_tls_state = apply_tls_policy()
if _tls_state == "disabled":
    print("[MAIN] WARNUNG: TLS-Prüfung global deaktiviert (PYTHONHTTPSVERIFY=0, FLASK_ENV=development)")
elif _tls_state == "ignored":
    print("[MAIN] WARNUNG: PYTHONHTTPSVERIFY=0 wird ignoriert, TLS-Prüfung bleibt aktiv "
          "(nur zusammen mit FLASK_ENV=development wirksam)")

# Jetzt können wir die Module importieren
from src.dashboard.app import app
from src.utils.logger import get_logger, logger_service

# Reset Logger beim Start
logger_service.reset()
logger = get_logger(process_id="main")

def _check_security_config() -> None:
    """
    Fail-closed beim Start (AP-01/AP-02): ohne Service-Token startet der Server nicht.
    Eine unvollstaendige Dashboard-Anmeldung wird gemeldet und sperrt nur das Dashboard.
    Details: docs/deployment/dashboard-anmeldung.md
    """
    from src.api.auth import api_security_problems, api_security_warnings
    from src.dashboard.auth import dashboard_security_problems
    from src.core.security import format_problems

    for warning in api_security_warnings():
        logger.warning(warning)
    # Eine unvollstaendige Dashboard-Anmeldung sperrt nur das Dashboard (503 mit Hinweis),
    # damit die API fuer Clients wie KnowledgeScout weiterlaeuft.
    dashboard_problems = dashboard_security_problems()
    if dashboard_problems:
        logger.error("Dashboard bleibt gesperrt, Anmeldung unvollstaendig:\n" + format_problems(dashboard_problems))
        print("[MAIN] Dashboard gesperrt, Anmeldung unvollstaendig:\n" + format_problems(dashboard_problems), file=sys.stderr)
    problems = api_security_problems()
    if problems:
        message = "Start abgebrochen, Sicherheitskonfiguration unvollstaendig:\n" + format_problems(problems)
        logger.error(message)
        print(f"[MAIN] {message}", file=sys.stderr)
        sys.exit(2)


if __name__ == '__main__':
    _check_security_config()
    # Nur loggen, wenn es nicht der Reloader-Prozess ist
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Anwendung wird gestartet")
    app.run(host='0.0.0.0', port=5001, debug=False)