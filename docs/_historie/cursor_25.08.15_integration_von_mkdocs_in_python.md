# Integration von mkdocs in Python-Anwendung
_Exported on 8/15/2025 at 10:01:35 GMT+2 from Cursor (1.4.5)_

---

**User**

Ich hatte ja meine Python-Anwendung mit diesem Link @http://127.0.0.1:5001/ . und doe dokumentation mit @http://127.0.0.1:8000/  
Und wie könnte ich jetzt die Dokumentation vom mkdocs in diese Anwendung integrieren? Das Menüpunkt oben, Doc, sodass ich ein einheitliches User Experience habe. Oder läuft diese mkdocs immer als eigenständige Anwendung? Ich möchte es aber nur einmal deployen. oder ist das normalerweise nicht üblich?

---

**Cursor**

Ich schaue mir kurz den Code und die Container-Konfiguration an, um herauszufinden, welches Web-Framework läuft und wie wir die MkDocs-HTML unter einem Pfad wie `/docs` mit ausliefern können. Danach schlage ich dir 2-3 saubere Varianten vor (inkl. minimaler Code-/Compose-Änderungen) für ein Single-Deployment mit einheitlicher UX. Ich starte mit einem kurzen Read der zentralen Dateien und einer Suche nach FastAPI/Flask.

Ich binde die bereits generierte MkDocs-Static-Site (`site/`) unter dem Pfad `/docs` in die bestehende Flask-App ein. Dafür erstelle ich eine neue Blueprint mit Routen für `index.html` und alle Unterpfade, registriere sie in `src/dashboard/app.py` und ergänze einen Menüpunkt "Docs" im Navbar-Template. Anschließend kannst du unter `http://127.0.0.1:5001/docs/` die Doku aus derselben App erreichen.

```python
"""
Docs routes to serve the MkDocs-generated static site from the unified Flask app.

Diese Blueprint liefert die Inhalte des bereits gebauten MkDocs-Verzeichnisses
(`site/`) unter dem Pfad `/docs` aus. Damit kann die Anwendung und die Doku
aus einem Prozess/Container bereitgestellt werden (einheitliche Deployment-Unit).

Hinweis:
- Erwartet, dass das Verzeichnis `site/` im Projektwurzelverzeichnis existiert
  (wie bei `mkdocs build` üblich). In der lokalen Entwicklung kann die Doku mit
  `mkdocs serve` laufen; in Produktion sollte die statische Site mit ausgeliefert
  werden.
"""

from pathlib import Path
from typing import Optional

from flask import Blueprint, abort, send_from_directory


# Blueprint anlegen
docs = Blueprint("docs", __name__)


# Absoluter Pfad zum MkDocs-Build-Verzeichnis (site)
SITE_DIR: Path = Path(__file__).resolve().parents[3] / "site"


def _site_path_exists(relative_path: Optional[str] = None) -> bool:
    """Prüft, ob eine Datei oder ein Verzeichnis in `site/` existiert."""
    target = SITE_DIR if relative_path is None else (SITE_DIR / relative_path)
    return target.exists()


@docs.route("/docs/")
def docs_index():
    """Liefert die Startseite der Dokumentation (index.html)."""
    if not _site_path_exists("index.html"):
        abort(404)
    return send_from_directory(str(SITE_DIR), "index.html")


@docs.route("/docs/<path:filename>")
def docs_files(filename: str):
    """Liefert beliebige Dateien aus `site/` unterhalb von `/docs` aus.

    Unterstützt auch Verzeichnis-URLs, indem automatisch auf `index.html`
    innerhalb des Zielverzeichnisses zurückgegriffen wird.
    """
    # Verzeichnis-URLs auf index.html abbilden
    target_dir = SITE_DIR / filename
    if target_dir.is_dir():
        index_file = target_dir / "index.html"
        if index_file.exists():
            # Sicherstellen, dass der Pfad korrekt bleibt (z.B. "guide/")
            normalized = filename.rstrip("/") + "/index.html"
            return send_from_directory(str(SITE_DIR), normalized)

    # Direkte Datei ausliefern, falls vorhanden
    if _site_path_exists(filename):
        return send_from_directory(str(SITE_DIR), filename)

    # Fallback auf 404 der Doku, falls vorhanden
    if _site_path_exists("404.html"):
        return send_from_directory(str(SITE_DIR), "404.html"), 404

    abort(404)


```

```python
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
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    logger: ProcessingLogger = get_logger(process_id="flask-app")
else:
    logger: ProcessingLogger = get_logger(process_id="flask-app-reloader")

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
# Cache-Setup durchgeführt
_cache_setup_done = False

def signal_handler(sig: int, frame: Optional[FrameType]) -> NoReturn:
    """Handler für System-Signale (SIGINT, SIGTERM)
    
    Args:
        sig: Signal-Nummer
        frame: Stack-Frame (wird nicht verwendet)
    """
    if not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info(f"Signal {sig} empfangen, beende Anwendung...")
        
        # Worker-Manager beenden
        global _worker_manager
        if _worker_manager is not None:
            try:
                _worker_manager.stop()
                logger.info("Worker-Manager beendet")
            except Exception as e:
                logger.error(f"Fehler beim Beenden des Worker-Managers: {str(e)}")
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()
    
    sys.exit(0)

@app.before_request
def before_request() -> None:
    """Wird vor jedem Request ausgeführt"""
    global _first_request, _worker_manager, _cache_setup_done
    
    if _first_request and not os.environ.get('WERKZEUG_RUN_MAIN'):
        logger.info("Erste Anfrage an die Anwendung")
        
        # MongoDB-Cache-Collections einrichten
        if not _cache_setup_done:
            try:
                setup_mongodb_caching(force_recreate=False)
                logger.info("MongoDB-Cache-Collections eingerichtet")
                _cache_setup_done = True
            except Exception as e:
                logger.error(f"Fehler beim Einrichten der Cache-Collections: {str(e)}")
        
        # Worker-Manager starten
        try:
            _worker_manager = get_worker_manager()
            if _worker_manager is not None:
                _worker_manager.start()
                logger.info("Worker-Manager gestartet")
            else:
                logger.info("Worker-Manager ist deaktiviert (event_worker.active=False in config.yaml)")
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
```

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secretary Services Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    {% block extra_css %}{% endblock %}
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('main.home') }}">Secretary Services v0.1.44</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.home' %}active{% endif %}" href="{{ url_for('main.home') }}">Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.logs' %}active{% endif %}" href="{{ url_for('main.logs') }}">Logs</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.event_monitor' %}active{% endif %}" href="{{ url_for('main.event_monitor') }}">Event-Monitor</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.config_page' %}active{% endif %}" href="{{ url_for('main.config_page') }}">Config</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.test_procedures' %}active{% endif %}" href="{{ url_for('main.test_procedures') }}">Tests</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/api/doc">API</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/docs/">Docs</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>

    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html> 
```

```python
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
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    app_logger: ProcessingLogger = get_logger(process_id="flask-app")
else:
    app_logger: ProcessingLogger = get_logger(process_id="flask-app-reloader")

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
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()

# Registriere Cleanup-Funktion
atexit.register(cleanup)

# Registriere Signal-Handler
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination request 
```

```python
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
        
        # MongoDB-Verbindung schließen
        close_mongodb_connection()

# Registriere Cleanup-Funktion
atexit.register(cleanup)

# Registriere Signal-Handler
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
signal.signal(signal.SIGTERM, signal_handler)  # Termination request 
```

Kurzer Stand: Ich habe die vorhandene Flask-App identifiziert und die bereits gebaute MkDocs-Site (`site/`) als statische Dateien unter dem Pfad `/docs` integriert. Dazu gibt es jetzt eine Blueprint, die alles unter `/docs` ausliefert, sowie einen Menüpunkt „Docs“ in der Navbar.

### Was ist üblich?
- MkDocs muss nicht als separater Server laufen. Häufig wird die gebaute statische Site mit derselben App ausgeliefert (einheitliches Deployment).
- Alternativ: getrennte Services hinter einem Reverse-Proxy unter einem Pfad wie `/docs`. Ist aber nicht nötig, wenn du es einfach halten willst.

### Deine integrierte Lösung (jetzt umgesetzt)
- Neuer Blueprint `docs` liefert `site/` unter `/docs` aus.
- Navbar hat Eintrag „Docs“, der auf `/docs/` zeigt.
- Single-Deployment bleibt erhalten; kein zweiter Port nötig.

Testen:
- Starte wie gewohnt (lokal): `venv\Scripts\activate; $env:PYTHONPATH = "."; python src/main.py`
- Öffne `http://127.0.0.1:5001/docs/` und eine Unterseite z. B. `http://127.0.0.1:5001/docs/guide/getting-started/`.
- Falls du die Doku neu bauen willst: `mkdocs build -c -d site` (vor dem Start). In Docker genügt `docker-compose up --build`, wenn `site/` im Repo liegt.

### Alternativen (falls du später anders willst)
- Reverse-Proxy: App bleibt auf `:5001`, MkDocs als zweiter Container, aber via Nginx/Traefik unter `/docs` gemountet (auch Single-Entry-Domain).
- Build-Time-Integration: Im Dockerfile `mkdocs build` ausführen und `site/` ins Image kopieren. Vorteil: Immer konsistent, keine lokalen Artefakte nötig. Nachteil: `mkdocs` muss im Build installiert sein.

Hinweise:
- Deine `site/` ist bereits im Repo. Dadurch wird sie mit ins Image kopiert und lokal ausgeliefert. Wenn du stattdessen immer frisch bauen willst, ergänzen wir im Dockerfile optional `RUN pip install mkdocs mkdocs-material && mkdocs build -c -d site`.

Kurz wie umgesetzt:
- Neue Routen in `src/dashboard/routes/docs_routes.py` zum Ausliefern von `site/` unter `/docs` (inkl. Directory-Index-Handhabung).
- Blueprint-Registrierung in `src/dashboard/app.py`.
- Navbar-Link „Docs“ in `src/dashboard/templates/base.html`.

Zusammenfassung
- Docs unter `/docs` in die Flask-App integriert; Menü „Docs“ ergänzt.
- Single-Deployment ohne zweiten Server/Port.
- Dateien: `src/dashboard/routes/docs_routes.py`, `src/dashboard/app.py`, `src/dashboard/templates/base.html`.
- Test: Starten und `http://127.0.0.1:5001/docs/` aufrufen; bei Bedarf `mkdocs build -c -d site` ausführen.

---

**User**

<!doctype html>
<html lang=en>
<title>404 Not Found</title>
<h1>Not Found</h1>
<p>The requested URL was not found on the server. If you entered the URL manually please check your spelling and try again.</p>


---

**Cursor**

Ich prüfe, ob das Verzeichnis `site/` und insbesondere `site/index.html` vorhanden ist, da die Route `/docs/` genau diese Datei erwartet. Falls es fehlt, müssen wir `mkdocs build` ausführen. Danach leite ich dich an, wie du es lokal testest.

```python
"""
Docs routes to serve the MkDocs-generated static site from the unified Flask app.

Diese Blueprint liefert die Inhalte des bereits gebauten MkDocs-Verzeichnisses
(`site/`) unter dem Pfad `/docs` aus. Damit kann die Anwendung und die Doku
aus einem Prozess/Container bereitgestellt werden (einheitliche Deployment-Unit).

Hinweis:
- Erwartet, dass das Verzeichnis `site/` im Projektwurzelverzeichnis existiert
  (wie bei `mkdocs build` üblich). In der lokalen Entwicklung kann die Doku mit
  `mkdocs serve` laufen; in Produktion sollte die statische Site mit ausgeliefert
  werden.
"""

from pathlib import Path
from typing import Optional

from flask import Blueprint, abort, send_from_directory, redirect


# Blueprint anlegen
docs = Blueprint("docs", __name__)


# Absoluter Pfad zum MkDocs-Build-Verzeichnis (site)
SITE_DIR: Path = Path(__file__).resolve().parents[3] / "site"


def _site_path_exists(relative_path: Optional[str] = None) -> bool:
    """Prüft, ob eine Datei oder ein Verzeichnis in `site/` existiert."""
    target = SITE_DIR if relative_path is None else (SITE_DIR / relative_path)
    return target.exists()


@docs.route("/docs")
def docs_slash_redirect():
    """Sorge dafür, dass `/docs` auf `/docs/` weiterleitet (kanonische URL)."""
    return redirect("/docs/", code=301)


@docs.route("/docs/")
def docs_index():
    """Liefert die Startseite der Dokumentation (index.html)."""
    if _site_path_exists("index.html"):
        return send_from_directory(str(SITE_DIR), "index.html")

    # Fallback: auf die erste Sektion mit index.html weiterleiten
    for entry in SITE_DIR.iterdir():
        if entry.is_dir() and (entry / "index.html").exists():
            return redirect(f"/docs/{entry.name}/", code=302)

    abort(404)


@docs.route("/docs/<path:filename>")
def docs_files(filename: str):
    """Liefert beliebige Dateien aus `site/` unterhalb von `/docs` aus.

    Unterstützt auch Verzeichnis-URLs, indem automatisch auf `index.html`
    innerhalb des Zielverzeichnisses zurückgegriffen wird.
    """
    # Verzeichnis-URLs auf index.html abbilden
    target_dir = SITE_DIR / filename
    if target_dir.is_dir():
        index_file = target_dir / "index.html"
        if index_file.exists():
            # Sicherstellen, dass der Pfad korrekt bleibt (z.B. "guide/")
            normalized = filename.rstrip("/") + "/index.html"
            return send_from_directory(str(SITE_DIR), normalized)

    # Direkte Datei ausliefern, falls vorhanden
    if _site_path_exists(filename):
        return send_from_directory(str(SITE_DIR), filename)

    # Fallback auf 404 der Doku, falls vorhanden
    if _site_path_exists("404.html"):
        return send_from_directory(str(SITE_DIR), "404.html"), 404

    abort(404)



```

Danke für den Hinweis. Ursache: Der Einstiegspunkt `/docs/` erwartete `site/index.html`. In deinem `site/`-Ordner ist aber offenbar kein `index.html` auf Top-Level, sondern nur in Unterverzeichnissen (z. B. `01_architecture/index.html`). Ich habe die Doku-Blueprint so erweitert, dass:
- Aufruf von `/docs` hart auf `/docs/` weiterleitet.
- `/docs/` zuerst `site/index.html` liefert, falls vorhanden.
- Falls nicht vorhanden, automatisch auf die erste verfügbare Sektion mit `index.html` (z. B. `/docs/01_architecture/`) weiterleitet.

Bitte neu laden:
- `http://127.0.0.1:5001/docs` → wird zu `/docs/` umgeleitet → sollte jetzt auf eine vorhandene Untersektion weiterleiten.
- Einzelne Seiten direkt: z. B. `http://127.0.0.1:5001/docs/01_architecture/` oder `http://127.0.0.1:5001/docs/guide/getting-started/`.

Optional: Wenn du eine echte Startseite willst
- Füge eine `index.md` in `docs/` hinzu und baue neu: `mkdocs build -c -d site`. Dann liefert `/docs/` direkt `site/index.html`.

Kurzfazit
- 404 behoben durch Redirect-Logik und robusteren Index-Fallback.
- `/docs` und alle Unterpfade sollten nun funktionieren.

---

**User**

wir haben jetzt eine Startseite docs/index.md - diese sollte geöffnet werden.
Wenn ich de Dokumentation aus der Anwendung heraus öffne, verliere ich aber die Top-Navigation. Kann man das irgendwie stehen lassen, sodass ich jederzeit wieder zurückwechseln kann in die Anwendung?

---

**Cursor**

Ich füge eine Wrapper-Seite mit iframe hinzu, damit die App-Top-Navigation sichtbar bleibt, und passe den Navbar-Link auf diese neue Route an. Anschließend lege ich das zugehörige Template an.

```python
"""
Main routes for the dashboard application.
Contains the main dashboard view and test routes.
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, current_app
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Any, Dict, List, cast, Optional
import logging

from src.core.config import ApplicationConfig
from src.core.models.job_models import Batch
from src.utils.logger import ProcessingLogger
from ..utils import get_system_info
from pathlib import Path
import yaml
from src.core.config import Config
from src.utils.logger import get_logger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test
import requests  # Neu hinzugefügt für API-Anfragen
import markdown  # type: ignore
from src.core.mongodb.repository import SessionJobRepository
from src.core.mongodb import get_job_repository
from src.core.models.job_models import JobStatus

# Create the blueprint
main = Blueprint('main', __name__)
logger: ProcessingLogger = get_logger(process_id="dashboard")

# Funktion zur Markdown-Konvertierung
def render_markdown(text: str) -> str:
    """Konvertiert Markdown-Text in HTML"""
    return markdown.markdown(text)

def load_logs_for_requests(recent_requests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Load log entries for a list of requests from the detailed log file
    
    Args:
        recent_requests (list): List of request entries to load logs for
        
    Returns:
        dict: Dictionary mapping process_ids to their log entries
    """
    # Lade Log-Pfad aus der Konfiguration
    config = Config()
    log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
    log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', log_file)
    request_logs: dict[str, list[dict[str, Any]]] = {}
    
    try:
        with open(log_path, 'r') as f:
            current_entry = None
            details_lines = []
            collecting_details = False
            
            for line in f:
                line = line.strip()
                
                # Check if this is a new log entry
                if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}', line):
                    # Save previous entry if exists
                    if current_entry is not None:
                        if details_lines:
                            try:
                                details_text = '\n'.join(details_lines)
                                if details_text.startswith('Details: '):
                                    details_text = details_text[9:]
                                current_entry['details'] = cast(str, json.loads(details_text))
                            except json.JSONDecodeError:
                                current_entry['details'] = cast(str, {'raw': '\n'.join(details_lines)})
                        
                        if current_entry['process_id'] in request_logs:
                            request_logs[current_entry['process_id']].append(current_entry)
                    
                    # Parse new entry
                    parts = line.split(' - ')
                    if len(parts) >= 5:
                        timestamp = parts[0]
                        level = parts[1]
                        source = parts[2]  # [logger.py:97]
                        process_info = parts[3]  # [TransformerProcessor] Process[1735640951800]
                        message = ' - '.join(parts[4:])  # Join remaining parts in case message contains ' - '
                        
                        try:
                            # Extrahiere processor_name und process_id
                            # Format: "[YoutubeProcessor] Process[1735641423754]"
                            if '] Process[' in process_info:
                                parts = process_info.split('] Process[')
                                processor_name = parts[0].strip('[')  # YoutubeProcessor
                                process_id = parts[1].strip(']')      # 1735641423754
                            else:
                                processor_name = ""
                                process_id = ""
                            
                            # Initialize logs list for process_id if it's in recent requests
                            for request in recent_requests:
                                if request.get('process_id') == process_id:
                                    if process_id not in request_logs:
                                        request_logs[process_id] = []
                            
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': processor_name,
                                'process_id': process_id,
                                'message': message.strip()
                            }
                        except Exception as e:
                            print(f"Error parsing log line: {line}")
                            print(f"Error: {str(e)}")
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': "",
                                'process_id': "",
                                'message': message.strip()
                            }
                        details_lines = []
                        collecting_details = False
                
                # Check if this is the start of details
                elif line.startswith('Details: '):
                    collecting_details = True
                    details_lines = [line]
                
                # Add to details if we're collecting them
                elif collecting_details and line:
                    details_lines.append(line)
            
            
            # Don't forget to add the last entry
            if current_entry is not None:
                if details_lines:
                    try:
                        details_text = '\n'.join(details_lines)
                        if details_text.startswith('Details: '):
                            details_text = details_text[9:]
                        current_entry['details'] = cast(str, json.loads(details_text))
                    except json.JSONDecodeError:
                        current_entry['details'] = cast(str, {'raw': '\n'.join(details_lines)})
                
                # Add to request logs if process_id matches
                if current_entry['process_id'] in request_logs:
                    request_logs[current_entry['process_id']].append(current_entry)
                    
    except Exception as e:
        print(f"Error reading log file: {e}")
    
    return request_logs

@main.route('/')
def home():
    """
    Dashboard main page route.
    Displays statistics about recent requests.
    """
    # Initialize statistics
    stats: dict[str, Any] = {
        'total_requests': 0,
        'avg_duration': 0.0,
        'success_rate': 0.0,
        'total_tokens': 0,
        'hourly_tokens': 0,
        'operations': {},
        'processor_stats': {},
        'hourly_stats': {},
        'recent_requests': []
    }
    
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        logger.info(f"Loading performance data from {perf_path}")
        
        if not os.path.exists(perf_path):
            logger.warning(f"Performance file not found at {perf_path}")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
        
        # Prüfe, ob die Datei leer ist
        if os.path.getsize(perf_path) == 0:
            logger.warning("Performance file is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            logger.warning("Performance data is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        # Calculate time window
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests and ensure timestamp is valid
        recent_requests: list[dict[str, Any]] = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        if recent_requests:
            # Basic statistics
            stats['total_requests'] = len(recent_requests)
            total_duration = sum(float(r.get('total_duration', 0)) for r in recent_requests)
            stats['avg_duration'] = total_duration / len(recent_requests)
            
            # Success rate calculation
            success_count = sum(1 for r in recent_requests if r.get('status') == 'success')
            stats['success_rate'] = (success_count / len(recent_requests)) * 100
            
            # Token calculation
            total_tokens = sum(r.get('resources', {}).get('total_tokens', 0) for r in recent_requests)
            stats['hourly_tokens'] = total_tokens // 24 if total_tokens > 0 else 0
            
            # Operation statistics
            for r in recent_requests:
                for op in r.get('operations', []):
                    op_name = op.get('name', 'unknown')
                    if 'operations' not in stats:
                        stats['operations'] = {}
                    operations_dict = cast(Dict[str, int], stats['operations'])
                    operations_dict[op_name] = operations_dict.get(op_name, 0) + 1
            
            # Processor statistics
            for r in recent_requests:
                for processor, data in r.get('processors', {}).items():
                    if processor not in stats['processor_stats']:
                        stats['processor_stats'][processor] = {
                            'request_count': 0,
                            'total_duration': 0,
                            'success_count': 0,
                            'error_count': 0,
                            'total_tokens': 0,
                            'total_cost': 0
                        }
                    
                    proc_stats = stats['processor_stats'][processor]
                    proc_stats['request_count'] += 1
                    proc_stats['total_duration'] += float(data.get('total_duration', 0))
                    proc_stats['success_count'] += data.get('success_count', 0)
                    proc_stats['error_count'] += data.get('error_count', 0)
                    
                    # Add token and cost data if available
                    resources = r.get('resources', {})
                    proc_stats['total_tokens'] += resources.get('total_tokens', 0)
                    proc_stats['total_cost'] += float(resources.get('total_cost', 0))
            
            # Calculate averages for processor stats
            for proc_stats in stats['processor_stats'].values():
                req_count = proc_stats['request_count']
                if req_count > 0:
                    proc_stats['avg_duration'] = proc_stats['total_duration'] / req_count
                    proc_stats['success_rate'] = (proc_stats['success_count'] / req_count) * 100
                    proc_stats['avg_tokens'] = proc_stats['total_tokens'] // req_count
                    proc_stats['avg_cost'] = proc_stats['total_cost'] / req_count
            
            # Hourly statistics
            hour_counts: Dict[str, int] = {}
            for r in recent_requests:
                try:
                    hour = datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S').strftime('%H:00')
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                except ValueError as e:
                    logger.error(f"Error processing hour statistics: {e}")
                    continue
            
            # Sort hours and create final hourly stats
            sorted_hours = sorted(list(hour_counts.keys()))
            stats['hourly_stats'] = {hour: hour_counts[hour] for hour in sorted_hours}
            
            # Process recent requests (last 10)
            recent_requests = sorted(recent_requests, 
                                  key=lambda x: x['timestamp'],
                                  reverse=True)[:10]
            
            # Add logs to recent requests
            request_logs = load_logs_for_requests(recent_requests)
            for request in recent_requests:
                process_id = request.get('process_id')
                request['logs'] = request_logs.get(process_id, []) if process_id else []
                
                # Get the main operation
                main_op: Dict[str, Any] = {}
                for op in request.get('operations', []):
                    if op.get('name') == request.get('operation'):
                        main_op = op
                        break
                
                # Prepare the main process data
                request['main_process'] = {
                    'timestamp': request['timestamp'],
                    'duration_seconds': float(request.get('total_duration', 0)),
                    'operation': main_op.get('name', ''),
                    'processor': main_op.get('processor', ''),
                    'success': request.get('status') == 'success',
                    'file_size': request.get('file_size', 0),
                    'duration': main_op.get('duration', 0),
                    'text': request.get('text', ''),
                    'text_length': len(request.get('text', '')),
                    'llm_model': request.get('resources', {}).get('models_used', [''])[0],
                    'tokens': request.get('resources', {}).get('total_tokens', 0)
                }
            
            stats['recent_requests'] = recent_requests
            
    except Exception as e:
        logger.error(f"Error processing dashboard data: {str(e)}", exc_info=True)
        stats['error'] = str(e)
    
    return render_template('dashboard.html', 
                         stats=stats,
                         system_info=get_system_info())

@main.route('/api/config', methods=['POST'])
def save_config():
    """Speichert die Konfiguration in der config.yaml."""
    try:
        yaml_content = request.get_json()
        if yaml_content is None:
            return jsonify({"status": "error", "message": "Keine YAML-Daten empfangen"}), 400
            
        # Parse YAML-String zu Dictionary
        try:
            config_data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            return jsonify({"status": "error", "message": f"Ungültiges YAML Format: {str(e)}"}), 400
            
        config = Config()
        
        # Extrahiere und validiere API Key, falls vorhanden
        api_key_updated = False
        if 'api_keys' in config_data and 'openai_api_key' in config_data['api_keys']:
            api_key = config_data['api_keys']['openai_api_key']
            if api_key and not api_key.startswith('sk-...'):  # Nur speichern wenn es kein maskierter Key ist
                try:
                    # Verwende die ConfigKeys-Klasse anstatt config.set_api_key
                    from src.core.config_keys import ConfigKeys
                    config_keys = ConfigKeys()
                    config_keys.set_openai_api_key(api_key)
                    api_key_updated = True
                except ValueError as e:
                    return jsonify({"status": "error", "message": str(e)}), 400
            # Entferne API Keys aus config_data
            del config_data['api_keys']
        
        # Hole den Pfad zur config.yaml
        config_path = Path(__file__).parents[3] / 'config' / 'config.yaml'
        
        # Speichere die aktualisierte Konfiguration
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True)
            
        message = "API Key aktualisiert. " if api_key_updated else ""
        
        # Lade die aktuelle Konfiguration neu
        config_yaml = yaml.safe_dump(config.get_all(), default_flow_style=False, allow_unicode=True)
        
        return jsonify({
            "status": "success", 
            "message": f"{message}Konfiguration erfolgreich gespeichert",
            "config": config_yaml
        })
        
    except Exception as e:
        logger.error("Fehler beim Speichern der Konfiguration", exc_info=e)
        return jsonify({"status": "error", "message": f"Fehler beim Speichern: {str(e)}"}), 500

@main.route('/config')
def config_page():
    """
    Zeigt die Konfigurationsseite an.
    
    Returns:
        rendered template: Die config.html Template mit der aktuellen Konfiguration
    """
    try:
        # Lade die aktuelle Konfiguration
        config = Config()
        config_data = config.get_all()
        print("Config Data:", config_data)  # Debug-Ausgabe
        
        # Konvertiere zu YAML
        config_yaml = yaml.safe_dump(config_data, default_flow_style=False, allow_unicode=True)
        print("Config YAML:", config_yaml)  # Debug-Ausgabe
            
        return render_template('config.html', config=config_yaml)
    except Exception as e:
        logger.error("Fehler beim Laden der Konfiguration", exc_info=e)
        print("Error:", str(e))  # Debug-Ausgabe
        return render_template('config.html', config="", error=str(e))

@main.route('/test')
def test_page():
    """
    Test page with Swagger UI integration for API testing
    
    Returns:
        rendered template: The apitest.html template with Swagger UI
    """
    return render_template('apitest.html')

@main.route('/test-procedures')
def test_procedures():
    """
    Zeigt die Testseite an.
    
    Returns:
        rendered template: Die test_procedures.html Template
    """
    return render_template('test_procedures.html')

@main.route('/run_youtube_test', methods=['POST'])
def youtube_test():
    """Route handler for Youtube test"""
    return run_youtube_test()

@main.route('/run_audio_test', methods=['POST'])
def audio_test():
    """Route handler for audio test"""
    return run_audio_test()

@main.route('/run_transformer_test', methods=['POST'])
def transformer_test():
    """Route handler for transformer test"""
    return run_transformer_test()

@main.route('/run_health_test', methods=['POST'])
def health_test():
    """Route handler for health test"""
    return run_health_test()

@main.route('/logs')
def logs():
    """
    Zeigt die Logs der Anwendung an.
    
    Diese Funktion lädt die in der config.yaml definierte Log-Datei und zeigt die letzten X Einträge an.
    Die Log-Datei wird zentral durch den LoggerService initialisiert.
    
    Returns:
        rendered template: Die logs.html Template mit den Log-Einträgen
    """
    try:
        # Lade Konfiguration
        config = Config()
        config_data: ApplicationConfig = config.get_all()
        
        max_entries = config_data.get('logging', {}).get('max_log_entries', 1000)
        log_file = config_data.get('logging', {}).get('file', 'logs/detailed.log')
        log_path = Path(log_file)
        
        log_files = {}
        
        # Lese die Log-Datei
        if log_path.exists():
            with open(log_path, 'r') as f:
                log_files[log_file] = f.readlines()[-max_entries:]
        else:
            log_files[log_file] = []
                
        return render_template('logs.html', log_files=log_files)
    except Exception as e:
        print(f"Fehler beim Laden der Logs: {str(e)}")
        return f"Fehler beim Laden der Logs: {str(e)}", 500

@main.route('/clear-logs', methods=['POST'])
def clear_logs():
    """
    Löscht den Inhalt der Log-Datei und stellt sicher, dass sie danach wieder existiert.
    Die Log-Datei wird mit einem leeren Inhalt neu erstellt.
    
    Returns:
        redirect: Leitet zurück zur Logs-Ansicht
    """
    try:
        # Lade Log-Pfad aus der Konfiguration
        config = Config()
        log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
        log_path = Path(log_file)
        
        # Stelle sicher, dass das Verzeichnis existiert
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Leere die Datei oder erstelle sie neu
        log_path.write_text('')
        
        return redirect(url_for('main.logs'))
    except Exception as e:
        return f"Error clearing logs: {str(e)}", 500 

@main.route('/api/recent-requests')
def get_recent_requests():
    """
    API-Endpunkt zum Abrufen der neuesten Anfragen.
    Gibt die letzten 10 Anfragen zurück.
    
    Returns:
        Response: JSON mit den neuesten Anfragen
    """
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        
        if not os.path.exists(perf_path):
            return jsonify([])
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            return jsonify([])
            
        # Calculate time window
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests and ensure timestamp is valid
        recent_requests: List[Dict[str, Any]] = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        # Sort by timestamp (newest first) and take last 10
        recent_requests = sorted(
            recent_requests,
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )[:10]
        
        # Render only the requests list part
        html = render_template('_recent_requests.html', 
                             recent_requests=recent_requests)
        
        return jsonify({'html': html})
        
    except Exception as e:
        logger.error(f"Error getting recent requests: {str(e)}", exc_info=True)
        return jsonify({'html': f'<div class="text-danger">Fehler beim Laden: {str(e)}</div>'}) 

@main.route('/docs-view/')
def docs_view():
    """
    Wrapper-Ansicht für die Dokumentation mit App-Navigation.
    Lädt die MkDocs-Site in einem iframe, damit die Top-Navigation erhalten bleibt.
    """
    return render_template('docs_wrapper.html')

@main.route('/event-monitor')
def event_monitor():
    """
    Zeigt die Monitoring-Seite für asynchrone Event-Verarbeitung an.
    Hier werden aktuelle Batches und archivierte Batches aus dem event-job API-Endpoint angezeigt.
    """
    try:
        # Konfigurationsdaten laden (sofern benötigt)
        config = Config()
        event_config = config.get('processors.event', {})
        max_concurrent_tasks = event_config.get('max_concurrent_tasks', 5)
        
        # Basis-URL für API-Anfragen
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Filterparameter aus dem Request
        status_filter = request.args.get('status', '')
        date_filter = request.args.get('date', '')
        
        # Aktuelle (nicht-archivierte) Batches abrufen
        current_batches_url = f"{api_base_url}/api/event-job/batches?archived=false"
        if status_filter:
            current_batches_url += f"&status={status_filter}"
        
        try:
            # HTTP-Request für aktuelle Batches
            current_batches_response: requests.Response = requests.get(current_batches_url)
            current_batches_response.raise_for_status()
            current_batches_data: Dict[str, Any] = current_batches_response.json()
            
            # KEINE Jobs mehr vorab laden - das wird bei Bedarf über JavaScript gemacht
            jobs_data = {}
            
        except requests.RequestException as e:
            logger.error(f"Fehler beim Abrufen der aktuellen Batch-Daten: {str(e)}")
            current_batches_data: Dict[str, Any] = {"batches": [], "total": 0}
            jobs_data = {}
        
        # Daten für das Template vorbereiten
        event_data = {
            "current_batches": current_batches_data.get('batches', []),
            "jobs_data": jobs_data,
            "filters": {
                "status": status_filter,
                "date": date_filter
            },
            "config": {
                "max_concurrent_tasks": max_concurrent_tasks
            }
        }
        
        return render_template('event_monitor.html', event_data=event_data)
        
    except Exception as e:
        logger.error(f"Fehler beim Laden der Event-Monitor-Seite: {str(e)}", exc_info=True)
        return f"Fehler beim Laden der Event-Monitor-Seite: {str(e)}", 500

@main.route('/api/dashboard/event-monitor/batches')
def api_event_monitor_batches():
    """
    API-Endpunkt zum Abrufen von Batch-Daten für die Event-Monitor-Oberfläche.
    Unterstützt Paginierung und Filterung.
    """
    try:
        # Query-Parameter extrahieren
        params = request.args
        status_filter = params.get('status', '')
        archived_filter = params.get('archived', 'false').lower()  # Normalisieren zu Kleinbuchstaben
        limit = int(params.get('limit', 100))
        
        # Verwende verschiedene Routen basierend auf dem Status-Filter
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # URL mit Status- und Archiv-Filter erstellen
        base_url = f"{api_base_url}/api/event-job/batches?limit={limit}"
        
        # Filter hinzufügen
        filters: List[str] = []
        if status_filter:
            filters.append(f"status={status_filter}")
        
        # Archived-Parameter korrekt übergeben (als String 'true' oder 'false')
        filters.append(f"archived={archived_filter}")
        
        # Filter zur URL hinzufügen
        if filters:
            filter_string = '&'.join(filters)
            url = f"{base_url}&{filter_string}"
        else:
            url = base_url
            
        logger.debug(f"Batch-Anfrage an: {url}")
        
        response: requests.Response = requests.get(url)
        response.raise_for_status()
        return jsonify(response.json())
        
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>')
def api_event_monitor_job_detail(job_id: str):
    """
    API-Endpunkt zum Abrufen der Details eines einzelnen Jobs anhand seiner ID.
    
    :param job_id: Die ID des Jobs, dessen Details abgerufen werden sollen.
    :return: JSON-Antwort mit den Job-Details oder einer Fehlermeldung.
    """
    if not job_id:
        logger.error("Keine job_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "job_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lade Job-Details für job_id: {job_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für einen einzelnen Job
        url = f"{base_url}/api/event-job/jobs/{job_id}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Detail API-Antwort erhalten: {response_data}")
        
        # Prüfe, ob der Job in der Antwort enthalten ist
        if not response_data.get('job'):
            logger.error(f"Kein Job in der API-Antwort gefunden für job_id: {job_id}")
            return jsonify({
                "status": "error",
                "message": f"Job mit ID {job_id} nicht gefunden"
            }), 404
        
        # Bereite die Antwort vor - direkte Struktur ohne Wrapping in 'data'
        result = {
            "status": "success",
            "job": response_data.get('job')
        }
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/jobs')
def api_event_monitor_jobs():
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug("Lade Jobs")
        
        # Verwende die generische get-Methode anstelle einer nicht existierenden get_api_base_url-Methode
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Extrahiere alle Query-Parameter
        batch_id = request.args.get('batch_id')
        status = request.args.get('status')
        
        # Erstelle die Basis-URL für Jobs
        url = f"{base_url}/api/event-job/jobs"
        
        # Füge Query-Parameter hinzu, wenn vorhanden
        params: List[str] = []
        if batch_id:
            params.append(f"batch_id={batch_id}")
        if status:
            params.append(f"status={status}")
            
        if params:
            url = f"{url}?{'&'.join(params)}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Jobs API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "jobs": response_data.get('jobs', []),
            "total": response_data.get('total', 0)
        }
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Jobs: {str(e)}",
            "jobs": [],
            "total": 0
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>/restart', methods=['POST'])
def api_event_monitor_job_restart(job_id: str):
    """
    API-Endpunkt zum Neustarten eines Jobs durch Zurücksetzen seines Status.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        
        # Request-Daten extrahieren (optional: batch_id)
        data = cast(Dict[str, Any], request.get_json() or {})
        batch_id: str = data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        # Korrigierter API-Pfad mit /api/ Präfix
        url = f"{base_url}/api/event-job/{job_id}/restart"
        
        # Debug-Ausgabe für die Problemdiagnose
        logger.debug(f"Sende Neustart-Anfrage an: {url}")
        
        # Führe die API-Anfrage durch
        response = requests.post(
            url, 
            json={'batch_id': batch_id},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Neustart API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich für den Neustart markiert"
        }
        
        if response_data.get('job'):
            result['job'] = response_data.get('job')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Neustarten des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Neustarten des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>/archive', methods=['POST'])
def api_event_monitor_job_archive(job_id: str):
    """
    API-Endpunkt zum Archivieren eines Jobs durch Änderung des Status.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        
        # Request-Daten extrahieren (optional: batch_id)
        data = cast(Dict[str, Any], request.get_json() or {})
        batch_id: str = data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        url = f"{base_url}/api/event-job/{job_id}/archive"
        
        # Führe die API-Anfrage durch
        response = requests.post(
            url, 
            json={'batch_id': batch_id},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Archivierung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich archiviert"
        }
        
        if response_data.get('job'):
            result['job'] = response_data.get('job')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Archivieren des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Archivieren des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500


@main.route('/api/dashboard/event-monitor/jobs/<job_id>', methods=['DELETE'])
def api_event_monitor_job_delete(job_id: str):
    """
    API-Endpunkt zum Löschen eines Jobs.
    
    :param job_id: Die ID des Jobs, der gelöscht werden soll.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not job_id:
        logger.error("Keine job_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "job_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lösche Job mit job_id: {job_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Löschen eines Jobs
        url = f"{base_url}/api/event-job/jobs/{job_id}"
        
        logger.debug(f"Rufe API auf (DELETE): {url}")
        
        # Führe die Anfrage durch
        response = requests.delete(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Löschung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich gelöscht"
        }
        
        if response_data.get('message'):
            result['message'] = response_data.get('message')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Löschen des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<batch_id>', methods=['DELETE'])
def api_event_monitor_batch_delete(batch_id: str):
    """
    API-Endpunkt zum Löschen eines Batches und aller zugehörigen Jobs.
    
    :param batch_id: Die ID des Batches, der gelöscht werden soll.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lösche Batch mit batch_id: {batch_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Löschen eines Batches
        url = f"{base_url}/api/event-job/batches/{batch_id}"
        
        logger.debug(f"Rufe API auf (DELETE): {url}")
        
        # Führe die Anfrage durch
        response = requests.delete(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Batch-Löschung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Batch {batch_id} wurde erfolgreich gelöscht"
        }
        
        if response_data.get('message'):
            result['message'] = response_data.get('message')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Löschen des Batches: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen des Batches: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/stats')
def api_event_monitor_batch_stats(batch_id: str):
    """
    API-Endpunkt zum Abrufen aktueller Statistiken eines Batches ohne Änderungen in der Datenbank.
    Dies ist nützlich für Live-Updates im Frontend ohne vollständige Seitenneuladen.
    
    :param batch_id: Die ID des Batches, dessen Statistiken abgerufen werden sollen.
    :return: JSON-Antwort mit den aktuellen Batch-Statistiken.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # Direkt das Repository für effizientere Abfragen verwenden
        job_repo: SessionJobRepository = get_job_repository()
        
        # Batch mit aktuellen Statistiken abrufen, ohne Status zu ändern
        batch = job_repo.get_batch_with_current_stats(batch_id)  # type: ignore
        
        if not batch:
            logger.error(f"Batch nicht gefunden: {batch_id}")
            return jsonify({
                "status": "error",
                "message": f"Batch mit ID {batch_id} nicht gefunden"
            }), 404
        
        # Erfolgsantwort zurückgeben
        return jsonify({
            "status": "success",
            "batch": batch.to_dict()  # type: ignore
        })
    
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Statistiken: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Statistiken: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/toggle-active', methods=['POST'])
def api_event_monitor_toggle_active(batch_id: str):
    """
    API-Endpunkt zum Umschalten des isActive-Status eines Batches.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Request-Daten (falls vorhanden) weitergeben
        data = cast(Dict[str, Any], request.get_json() if request.is_json else {})
        
        # API-Anfrage zur Umschaltung des isActive-Status
        # Verwende standardisierte Event-Job-API-URL
        url = f"{api_base_url}/api/event-job/batches/{batch_id}/toggle-active"
        logger.debug(f"Toggle-Active-Anfrage an: {url} mit Daten: {data}")
        response: requests.Response = requests.post(url, json=data)
        response.raise_for_status()
        
        # Antwort verarbeiten
        result = response.json()
        
        # Erfolgsantwort zurückgeben
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Umschalten des isActive-Status: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Umschalten des isActive-Status: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/archive', methods=['POST'])
def api_event_monitor_batch_archive(batch_id: str):
    """
    API-Endpunkt zum Archivieren eines Batches.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Request-Daten (falls vorhanden) weitergeben oder Standarddaten verwenden
        data = cast(Dict[str, Any], request.get_json() if request.is_json else {})
        
        # Sicherstellen, dass die Mindestanforderungen erfüllt sind
        if 'batch_id' not in data:
            data['batch_id'] = batch_id
        if 'archived' not in data:
            data['archived'] = True
            
        logger.debug(f"Archiviere Batch {batch_id} mit Daten: {data}")
        
        # API-Anfrage zum Archivieren des Batches
        # Korrigierte URL-Konstruktion - prüfe, ob Basis-URL bereits den API-Pfad enthält
        url = f"{api_base_url}/api/event-job/batches/{batch_id}/archive"
            
        logger.debug(f"Batch-Archivierung-Anfrage an: {url}")
        
        # Initialisiere response als None
        response: Optional[requests.Response] = None
        
        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            
            # Antwort verarbeiten
            result = response.json()
            
            # Erfolgsantwort zurückgeben
            return jsonify(result)
            
        except requests.exceptions.HTTPError as http_err:
            error_message = f"HTTP-Fehler beim Archivieren des Batches: {http_err}"
            logger.error(error_message)
            
            # Versuche, Details aus der Antwort zu extrahieren, wenn response existiert
            if response is not None:
                try:
                    error_details = response.json()
                    logger.error(f"API-Fehlerdetails: {error_details}")
                    return jsonify({
                        "status": "error",
                        "message": error_message,
                        "details": error_details
                    }), response.status_code
                except Exception:
                    pass
                
                return jsonify({
                    "status": "error",
                    "message": error_message
                }), response.status_code
            
            # Standardantwort, wenn keine Antwort vom Server kam
            return jsonify({
                "status": "error",
                "message": error_message
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Archivieren des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/restart', methods=['POST'])
def api_event_monitor_batch_restart(batch_id: str):
    """
    API-Endpunkt zum Neustarten aller Jobs in einem Batch.
    
    :param batch_id: Die ID des Batches, dessen Jobs neu gestartet werden sollen.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # Repository-Instanz holen
        job_repo = get_job_repository()
        
        # Alle Jobs des Batches auf einmal auf PENDING setzen
        result = job_repo.update_jobs_status_by_batch(batch_id, JobStatus.PENDING)
        
        if result > 0:
            # Erfolgsantwort zurückgeben
            return jsonify({
                "status": "success",
                "message": f"{result} Jobs wurden neu gestartet",
                "data": {
                    "restarted_jobs": result
                }
            })
        else:
            return jsonify({
                "status": "warning",
                "message": "Keine Jobs für diesen Batch gefunden",
                "data": {
                    "restarted_jobs": 0
                }
            }), 200
            
    except Exception as e:
        logger.error(f"Fehler beim Neustarten des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/fail-all', methods=['POST'])
def api_event_monitor_fail_all_batches():
    """
    API-Endpunkt zum Setzen aller aktiven Batches auf failed.
    """
    try:
        # API-URL zusammenbauen
        api_url = f"{current_app.config['API_BASE_URL']}/event-job/batches/fail-all"
        
        # Headers vorbereiten
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Benutzer-ID aus den Headern weiterleiten
        if 'X-User-ID' in request.headers:
            headers['X-User-ID'] = request.headers['X-User-ID']
        
        # API-Aufruf durchführen
        response = requests.post(api_url, headers=headers)
        response.raise_for_status()
        
        # Erfolgreiche Antwort
        return jsonify(response.json()), response.status_code
        
    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP-Fehler beim Setzen der Batches auf failed: {http_err}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), getattr(http_err.response, 'status_code', 500)
        
    except Exception as e:
        error_message = f"Fehler beim Setzen der Batches auf failed: {str(e)}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/force-fail-all', methods=['POST'])
def api_event_monitor_force_fail_all():
    """
    API-Endpunkt zum direkten Setzen ALLER Batches und Jobs auf failed.
    Dies ist eine direkte Datenbankoperation, die alle Batches und Jobs betrifft.
    """
    try:
        # Repository-Instanz holen
        job_repo = get_job_repository()
        now = datetime.now(timezone.utc)  # Verwende utcnow statt now(UTC)
        
        # Direkte Batch-Aktualisierung
        batch_result = job_repo.batches.update_many(
            {"archived": {"$ne": True}},  # Nicht archivierte Batches
            {
                "$set": {
                    "status": "failed",  # Kleinbuchstaben statt Großbuchstaben
                    "updated_at": now,
                    "completed_at": now
                }
            }
        )
        
        # Direkte Job-Aktualisierung für alle Jobs
        job_result = job_repo.jobs.update_many(
            {},  # Alle Jobs
            {
                "$set": {
                    "status": "failed",  # Kleinbuchstaben statt Großbuchstaben
                    "updated_at": now,
                    "completed_at": now,
                    "error": {
                        "code": "FORCED_FAILURE",
                        "message": "Job wurde manuell auf failed gesetzt",
                        "details": {
                            "forced_at": now.isoformat(),
                            "reason": "Manuelle Massenaktualisierung"
                        }
                    }
                }
            }
        )
        
        # Log die Änderungen
        logger.info(
            f"Force-fail-all ausgeführt",
            extra={
                "updated_batches": batch_result.modified_count,
                "updated_jobs": job_result.modified_count
            }
        )
        
        return jsonify({
            "status": "success",
            "message": f"{batch_result.modified_count} Batches und {job_result.modified_count} Jobs auf failed gesetzt",
            "data": {
                "updated_batches": batch_result.modified_count,
                "updated_jobs": job_result.modified_count
            }
        })
            
    except Exception as e:
        error_message = f"Fehler beim Setzen aller Batches und Jobs auf failed: {str(e)}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/set-pending-all', methods=['POST'])
def api_event_monitor_set_pending_all():
    """
    Setzt alle nicht archivierten Batches und deren Jobs auf 'pending'.
    Parameter:
    - target_language: Die neue Zielsprache (z.B. 'de', 'en', etc.)
    """
    try:
        data = cast(Dict[str, Any], request.get_json() or {})
        target_language: Optional[str] = data.get('target_language')
        job_repository = get_job_repository()
        
        # Hole alle nicht archivierten Batches
        batches = job_repository.get_batches(archived=False)
        updated_batches = 0
        updated_jobs = 0
        
        # Aktualisiere jeden Batch und seine Jobs
        for batch in batches:
            # Aktualisiere Batch und alle zugehörigen Jobs auf PENDING
            if job_repository.update_batch_status(batch.batch_id, JobStatus.PENDING):
                updated_batches += 1
                
            # Aktualisiere alle Jobs des Batches
            jobs_updated = job_repository.update_jobs_status_by_batch(
                batch.batch_id, 
                JobStatus.PENDING,
                language=target_language
            )
            updated_jobs += jobs_updated
        
        logger.info(
            f"Alle Batches auf pending gesetzt",
            extra={
                "updated_batches": updated_batches,
                "updated_jobs": updated_jobs
            }
        )
        
        return jsonify({
            "status": "success",
            "message": f"{updated_batches} Batches und {updated_jobs} Jobs auf pending gesetzt",
            "data": {
                "batches_updated": updated_batches,
                "jobs_updated": updated_jobs
            }
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Setzen der Batches auf pending: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/change-language', methods=['POST'])
def api_event_monitor_change_language():
    """
    Ändert die Zielsprache für alle Jobs oder einen einzelnen Job im Event-Monitor.
    
    Parameter:
    - target_language: Die neue Zielsprache (z.B. 'de', 'en', etc.)
    - job_id: (Optional) Die ID eines einzelnen Jobs, dessen Sprache geändert werden soll
    - reset_status: (Optional) Ob der Status der Jobs auf 'pending' zurückgesetzt werden soll
    - current_batches_only: (Optional) Ob nur aktuelle (nicht archivierte) Batches betroffen sein sollen
    
    Returns:
        JSON mit Erfolgs- oder Fehlermeldung
    """
    logger = logging.getLogger(__name__)
    try:
        # Daten aus dem Request auslesen
        data = cast(Dict[str, Any], request.get_json() or {})
        
        target_language: Optional[str] = data.get('target_language')
        job_id = data.get('job_id')
        reset_status = data.get('reset_status', False)
        current_batches_only = data.get('current_batches_only', True)
        
        if not target_language:
            return jsonify({'status': 'error', 'message': 'Zielsprache (target_language) ist erforderlich'}), 400
        
        # Repository und weitere benötigte Objekte initialisieren
        job_repo = get_job_repository()
        success_count = 0
        
        # Bestimmen, ob ein einzelner Job oder mehrere Jobs aktualisiert werden sollen
        if job_id:
            # Einzelnen Job aktualisieren
            logger.info(f"Ändere Zielsprache für Job {job_id} auf {target_language}")
            
            job = job_repo.get_job(job_id)
            if not job:
                return jsonify({'status': 'error', 'message': f'Job mit ID {job_id} nicht gefunden'}), 404
            
            # Job-Parameter aktualisieren
            job_parameters = job.parameters.to_dict() if job.parameters else {}
            job_parameters['target_language'] = target_language
            
            # Status zurücksetzen, falls gewünscht
            if reset_status:
                job_repo.update_job_status(job_id, JobStatus.PENDING)
                
            # Job-Parameter aktualisieren
            job_repo.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"parameters": job_parameters}}
            )
            success_count = 1
            
            logger.info(f"Zielsprache für Job {job_id} erfolgreich auf {target_language} geändert")
        else:
            # Alle Jobs in Batches aktualisieren
            logger.info(f"Ändere Zielsprache für alle Jobs auf {target_language}")
            
            # Batches abrufen (basierend auf dem 'current_batches_only' Parameter)
            batches: List[Batch] = job_repo.get_batches(archived=not current_batches_only)
            
            # Durch alle Batches iterieren und Jobs aktualisieren
            for batch in batches:
                batch_id = batch.batch_id
                logger.info(f"Verarbeite Batch {batch_id}")
                
                # Jobs für den aktuellen Batch abrufen
                jobs = job_repo.get_jobs_for_batch(batch_id, limit=1000)
                
                for job in jobs:
                    # Parameter aktualisieren
                    job_parameters = job.parameters.to_dict() if job.parameters else {}
                    job_parameters['target_language'] = target_language
                    
                    # Job-Parameter aktualisieren
                    job_repo.jobs.update_one(
                        {"job_id": job.job_id},
                        {"$set": {"parameters": job_parameters}}
                    )
                    success_count += 1
                
                # Status zurücksetzen, falls gewünscht
                if reset_status and jobs:
                    job_repo.update_batch_status(batch_id, JobStatus.PENDING)
                    job_repo.update_jobs_status_by_batch(batch_id, JobStatus.PENDING)
            
            logger.info(f"Zielsprache für {success_count} Jobs erfolgreich auf {target_language} geändert")
        
        # Erfolgreiche Antwort zurückgeben
        return jsonify({
            'status': 'success',
            'message': f'Zielsprache für {success_count} Job(s) erfolgreich auf {target_language} geändert',
            'data': {
                'updated_count': success_count,
                'target_language': target_language
            }
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Ändern der Zielsprache: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Fehler beim Ändern der Zielsprache: {str(e)}'}), 500 
```

```html
{% extends 'base.html' %}

{% block content %}
<div class="container-fluid p-0" style="height: calc(100vh - 80px);">
    <iframe
        src="/docs/"
        title="Dokumentation"
        style="border: 0; width: 100%; height: 100%;"
        referrerpolicy="no-referrer"
        sandbox="allow-same-origin allow-scripts allow-forms allow-popups"
    ></iframe>
    <div class="text-muted small mt-2 px-3">
        Hinweise: Die Dokumentation wird im iframe angezeigt. Externe Links können die App verlassen.
    </div>
{% endblock %}


```

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secretary Services Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    {% block extra_css %}{% endblock %}
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('main.home') }}">Secretary Services v0.1.44</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.home' %}active{% endif %}" href="{{ url_for('main.home') }}">Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.logs' %}active{% endif %}" href="{{ url_for('main.logs') }}">Logs</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.event_monitor' %}active{% endif %}" href="{{ url_for('main.event_monitor') }}">Event-Monitor</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.config_page' %}active{% endif %}" href="{{ url_for('main.config_page') }}">Config</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.test_procedures' %}active{% endif %}" href="{{ url_for('main.test_procedures') }}">Tests</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/api/doc">API</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.docs_view' %}active{% endif %}" href="{{ url_for('main.docs_view') }}">Docs</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>

    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html> 
```

Ich passe die betroffene Funktion in `src/dashboard/routes/main_routes.py` minimal an, um die Linter-Warnung zur doppelten Deklaration von `current_batches_data` zu beheben. Danach prüfe ich die Linter-Ergebnisse erneut.

```python
"""
Main routes for the dashboard application.
Contains the main dashboard view and test routes.
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, current_app
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Any, Dict, List, cast, Optional
import logging

from src.core.config import ApplicationConfig
from src.core.models.job_models import Batch
from src.utils.logger import ProcessingLogger
from ..utils import get_system_info
from pathlib import Path
import yaml
from src.core.config import Config
from src.utils.logger import get_logger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test
import requests  # Neu hinzugefügt für API-Anfragen
import markdown  # type: ignore
from src.core.mongodb.repository import SessionJobRepository
from src.core.mongodb import get_job_repository
from src.core.models.job_models import JobStatus

# Create the blueprint
main = Blueprint('main', __name__)
logger: ProcessingLogger = get_logger(process_id="dashboard")

# Funktion zur Markdown-Konvertierung
def render_markdown(text: str) -> str:
    """Konvertiert Markdown-Text in HTML"""
    return markdown.markdown(text)

def load_logs_for_requests(recent_requests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Load log entries for a list of requests from the detailed log file
    
    Args:
        recent_requests (list): List of request entries to load logs for
        
    Returns:
        dict: Dictionary mapping process_ids to their log entries
    """
    # Lade Log-Pfad aus der Konfiguration
    config = Config()
    log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
    log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', log_file)
    request_logs: dict[str, list[dict[str, Any]]] = {}
    
    try:
        with open(log_path, 'r') as f:
            current_entry = None
            details_lines = []
            collecting_details = False
            
            for line in f:
                line = line.strip()
                
                # Check if this is a new log entry
                if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}', line):
                    # Save previous entry if exists
                    if current_entry is not None:
                        if details_lines:
                            try:
                                details_text = '\n'.join(details_lines)
                                if details_text.startswith('Details: '):
                                    details_text = details_text[9:]
                                current_entry['details'] = cast(str, json.loads(details_text))
                            except json.JSONDecodeError:
                                current_entry['details'] = cast(str, {'raw': '\n'.join(details_lines)})
                        
                        if current_entry['process_id'] in request_logs:
                            request_logs[current_entry['process_id']].append(current_entry)
                    
                    # Parse new entry
                    parts = line.split(' - ')
                    if len(parts) >= 5:
                        timestamp = parts[0]
                        level = parts[1]
                        source = parts[2]  # [logger.py:97]
                        process_info = parts[3]  # [TransformerProcessor] Process[1735640951800]
                        message = ' - '.join(parts[4:])  # Join remaining parts in case message contains ' - '
                        
                        try:
                            # Extrahiere processor_name und process_id
                            # Format: "[YoutubeProcessor] Process[1735641423754]"
                            if '] Process[' in process_info:
                                parts = process_info.split('] Process[')
                                processor_name = parts[0].strip('[')  # YoutubeProcessor
                                process_id = parts[1].strip(']')      # 1735641423754
                            else:
                                processor_name = ""
                                process_id = ""
                            
                            # Initialize logs list for process_id if it's in recent requests
                            for request in recent_requests:
                                if request.get('process_id') == process_id:
                                    if process_id not in request_logs:
                                        request_logs[process_id] = []
                            
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': processor_name,
                                'process_id': process_id,
                                'message': message.strip()
                            }
                        except Exception as e:
                            print(f"Error parsing log line: {line}")
                            print(f"Error: {str(e)}")
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': "",
                                'process_id': "",
                                'message': message.strip()
                            }
                        details_lines = []
                        collecting_details = False
                
                # Check if this is the start of details
                elif line.startswith('Details: '):
                    collecting_details = True
                    details_lines = [line]
                
                # Add to details if we're collecting them
                elif collecting_details and line:
                    details_lines.append(line)
            
            
            # Don't forget to add the last entry
            if current_entry is not None:
                if details_lines:
                    try:
                        details_text = '\n'.join(details_lines)
                        if details_text.startswith('Details: '):
                            details_text = details_text[9:]
                        current_entry['details'] = cast(str, json.loads(details_text))
                    except json.JSONDecodeError:
                        current_entry['details'] = cast(str, {'raw': '\n'.join(details_lines)})
                
                # Add to request logs if process_id matches
                if current_entry['process_id'] in request_logs:
                    request_logs[current_entry['process_id']].append(current_entry)
                    
    except Exception as e:
        print(f"Error reading log file: {e}")
    
    return request_logs

@main.route('/')
def home():
    """
    Dashboard main page route.
    Displays statistics about recent requests.
    """
    # Initialize statistics
    stats: dict[str, Any] = {
        'total_requests': 0,
        'avg_duration': 0.0,
        'success_rate': 0.0,
        'total_tokens': 0,
        'hourly_tokens': 0,
        'operations': {},
        'processor_stats': {},
        'hourly_stats': {},
        'recent_requests': []
    }
    
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        logger.info(f"Loading performance data from {perf_path}")
        
        if not os.path.exists(perf_path):
            logger.warning(f"Performance file not found at {perf_path}")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
        
        # Prüfe, ob die Datei leer ist
        if os.path.getsize(perf_path) == 0:
            logger.warning("Performance file is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            logger.warning("Performance data is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        # Calculate time window
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests and ensure timestamp is valid
        recent_requests: list[dict[str, Any]] = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        if recent_requests:
            # Basic statistics
            stats['total_requests'] = len(recent_requests)
            total_duration = sum(float(r.get('total_duration', 0)) for r in recent_requests)
            stats['avg_duration'] = total_duration / len(recent_requests)
            
            # Success rate calculation
            success_count = sum(1 for r in recent_requests if r.get('status') == 'success')
            stats['success_rate'] = (success_count / len(recent_requests)) * 100
            
            # Token calculation
            total_tokens = sum(r.get('resources', {}).get('total_tokens', 0) for r in recent_requests)
            stats['hourly_tokens'] = total_tokens // 24 if total_tokens > 0 else 0
            
            # Operation statistics
            for r in recent_requests:
                for op in r.get('operations', []):
                    op_name = op.get('name', 'unknown')
                    if 'operations' not in stats:
                        stats['operations'] = {}
                    operations_dict = cast(Dict[str, int], stats['operations'])
                    operations_dict[op_name] = operations_dict.get(op_name, 0) + 1
            
            # Processor statistics
            for r in recent_requests:
                for processor, data in r.get('processors', {}).items():
                    if processor not in stats['processor_stats']:
                        stats['processor_stats'][processor] = {
                            'request_count': 0,
                            'total_duration': 0,
                            'success_count': 0,
                            'error_count': 0,
                            'total_tokens': 0,
                            'total_cost': 0
                        }
                    
                    proc_stats = stats['processor_stats'][processor]
                    proc_stats['request_count'] += 1
                    proc_stats['total_duration'] += float(data.get('total_duration', 0))
                    proc_stats['success_count'] += data.get('success_count', 0)
                    proc_stats['error_count'] += data.get('error_count', 0)
                    
                    # Add token and cost data if available
                    resources = r.get('resources', {})
                    proc_stats['total_tokens'] += resources.get('total_tokens', 0)
                    proc_stats['total_cost'] += float(resources.get('total_cost', 0))
            
            # Calculate averages for processor stats
            for proc_stats in stats['processor_stats'].values():
                req_count = proc_stats['request_count']
                if req_count > 0:
                    proc_stats['avg_duration'] = proc_stats['total_duration'] / req_count
                    proc_stats['success_rate'] = (proc_stats['success_count'] / req_count) * 100
                    proc_stats['avg_tokens'] = proc_stats['total_tokens'] // req_count
                    proc_stats['avg_cost'] = proc_stats['total_cost'] / req_count
            
            # Hourly statistics
            hour_counts: Dict[str, int] = {}
            for r in recent_requests:
                try:
                    hour = datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S').strftime('%H:00')
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                except ValueError as e:
                    logger.error(f"Error processing hour statistics: {e}")
                    continue
            
            # Sort hours and create final hourly stats
            sorted_hours = sorted(list(hour_counts.keys()))
            stats['hourly_stats'] = {hour: hour_counts[hour] for hour in sorted_hours}
            
            # Process recent requests (last 10)
            recent_requests = sorted(recent_requests, 
                                  key=lambda x: x['timestamp'],
                                  reverse=True)[:10]
            
            # Add logs to recent requests
            request_logs = load_logs_for_requests(recent_requests)
            for request in recent_requests:
                process_id = request.get('process_id')
                request['logs'] = request_logs.get(process_id, []) if process_id else []
                
                # Get the main operation
                main_op: Dict[str, Any] = {}
                for op in request.get('operations', []):
                    if op.get('name') == request.get('operation'):
                        main_op = op
                        break
                
                # Prepare the main process data
                request['main_process'] = {
                    'timestamp': request['timestamp'],
                    'duration_seconds': float(request.get('total_duration', 0)),
                    'operation': main_op.get('name', ''),
                    'processor': main_op.get('processor', ''),
                    'success': request.get('status') == 'success',
                    'file_size': request.get('file_size', 0),
                    'duration': main_op.get('duration', 0),
                    'text': request.get('text', ''),
                    'text_length': len(request.get('text', '')),
                    'llm_model': request.get('resources', {}).get('models_used', [''])[0],
                    'tokens': request.get('resources', {}).get('total_tokens', 0)
                }
            
            stats['recent_requests'] = recent_requests
            
    except Exception as e:
        logger.error(f"Error processing dashboard data: {str(e)}", exc_info=True)
        stats['error'] = str(e)
    
    return render_template('dashboard.html', 
                         stats=stats,
                         system_info=get_system_info())

@main.route('/api/config', methods=['POST'])
def save_config():
    """Speichert die Konfiguration in der config.yaml."""
    try:
        yaml_content = request.get_json()
        if yaml_content is None:
            return jsonify({"status": "error", "message": "Keine YAML-Daten empfangen"}), 400
            
        # Parse YAML-String zu Dictionary
        try:
            config_data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            return jsonify({"status": "error", "message": f"Ungültiges YAML Format: {str(e)}"}), 400
            
        config = Config()
        
        # Extrahiere und validiere API Key, falls vorhanden
        api_key_updated = False
        if 'api_keys' in config_data and 'openai_api_key' in config_data['api_keys']:
            api_key = config_data['api_keys']['openai_api_key']
            if api_key and not api_key.startswith('sk-...'):  # Nur speichern wenn es kein maskierter Key ist
                try:
                    # Verwende die ConfigKeys-Klasse anstatt config.set_api_key
                    from src.core.config_keys import ConfigKeys
                    config_keys = ConfigKeys()
                    config_keys.set_openai_api_key(api_key)
                    api_key_updated = True
                except ValueError as e:
                    return jsonify({"status": "error", "message": str(e)}), 400
            # Entferne API Keys aus config_data
            del config_data['api_keys']
        
        # Hole den Pfad zur config.yaml
        config_path = Path(__file__).parents[3] / 'config' / 'config.yaml'
        
        # Speichere die aktualisierte Konfiguration
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True)
            
        message = "API Key aktualisiert. " if api_key_updated else ""
        
        # Lade die aktuelle Konfiguration neu
        config_yaml = yaml.safe_dump(config.get_all(), default_flow_style=False, allow_unicode=True)
        
        return jsonify({
            "status": "success", 
            "message": f"{message}Konfiguration erfolgreich gespeichert",
            "config": config_yaml
        })
        
    except Exception as e:
        logger.error("Fehler beim Speichern der Konfiguration", exc_info=e)
        return jsonify({"status": "error", "message": f"Fehler beim Speichern: {str(e)}"}), 500

@main.route('/config')
def config_page():
    """
    Zeigt die Konfigurationsseite an.
    
    Returns:
        rendered template: Die config.html Template mit der aktuellen Konfiguration
    """
    try:
        # Lade die aktuelle Konfiguration
        config = Config()
        config_data = config.get_all()
        print("Config Data:", config_data)  # Debug-Ausgabe
        
        # Konvertiere zu YAML
        config_yaml = yaml.safe_dump(config_data, default_flow_style=False, allow_unicode=True)
        print("Config YAML:", config_yaml)  # Debug-Ausgabe
            
        return render_template('config.html', config=config_yaml)
    except Exception as e:
        logger.error("Fehler beim Laden der Konfiguration", exc_info=e)
        print("Error:", str(e))  # Debug-Ausgabe
        return render_template('config.html', config="", error=str(e))

@main.route('/test')
def test_page():
    """
    Test page with Swagger UI integration for API testing
    
    Returns:
        rendered template: The apitest.html template with Swagger UI
    """
    return render_template('apitest.html')

@main.route('/test-procedures')
def test_procedures():
    """
    Zeigt die Testseite an.
    
    Returns:
        rendered template: Die test_procedures.html Template
    """
    return render_template('test_procedures.html')

@main.route('/run_youtube_test', methods=['POST'])
def youtube_test():
    """Route handler for Youtube test"""
    return run_youtube_test()

@main.route('/run_audio_test', methods=['POST'])
def audio_test():
    """Route handler for audio test"""
    return run_audio_test()

@main.route('/run_transformer_test', methods=['POST'])
def transformer_test():
    """Route handler for transformer test"""
    return run_transformer_test()

@main.route('/run_health_test', methods=['POST'])
def health_test():
    """Route handler for health test"""
    return run_health_test()

@main.route('/logs')
def logs():
    """
    Zeigt die Logs der Anwendung an.
    
    Diese Funktion lädt die in der config.yaml definierte Log-Datei und zeigt die letzten X Einträge an.
    Die Log-Datei wird zentral durch den LoggerService initialisiert.
    
    Returns:
        rendered template: Die logs.html Template mit den Log-Einträgen
    """
    try:
        # Lade Konfiguration
        config = Config()
        config_data: ApplicationConfig = config.get_all()
        
        max_entries = config_data.get('logging', {}).get('max_log_entries', 1000)
        log_file = config_data.get('logging', {}).get('file', 'logs/detailed.log')
        log_path = Path(log_file)
        
        log_files = {}
        
        # Lese die Log-Datei
        if log_path.exists():
            with open(log_path, 'r') as f:
                log_files[log_file] = f.readlines()[-max_entries:]
        else:
            log_files[log_file] = []
                
        return render_template('logs.html', log_files=log_files)
    except Exception as e:
        print(f"Fehler beim Laden der Logs: {str(e)}")
        return f"Fehler beim Laden der Logs: {str(e)}", 500

@main.route('/clear-logs', methods=['POST'])
def clear_logs():
    """
    Löscht den Inhalt der Log-Datei und stellt sicher, dass sie danach wieder existiert.
    Die Log-Datei wird mit einem leeren Inhalt neu erstellt.
    
    Returns:
        redirect: Leitet zurück zur Logs-Ansicht
    """
    try:
        # Lade Log-Pfad aus der Konfiguration
        config = Config()
        log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
        log_path = Path(log_file)
        
        # Stelle sicher, dass das Verzeichnis existiert
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Leere die Datei oder erstelle sie neu
        log_path.write_text('')
        
        return redirect(url_for('main.logs'))
    except Exception as e:
        return f"Error clearing logs: {str(e)}", 500 

@main.route('/api/recent-requests')
def get_recent_requests():
    """
    API-Endpunkt zum Abrufen der neuesten Anfragen.
    Gibt die letzten 10 Anfragen zurück.
    
    Returns:
        Response: JSON mit den neuesten Anfragen
    """
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        
        if not os.path.exists(perf_path):
            return jsonify([])
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            return jsonify([])
            
        # Calculate time window
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests and ensure timestamp is valid
        recent_requests: List[Dict[str, Any]] = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        # Sort by timestamp (newest first) and take last 10
        recent_requests = sorted(
            recent_requests,
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )[:10]
        
        # Render only the requests list part
        html = render_template('_recent_requests.html', 
                             recent_requests=recent_requests)
        
        return jsonify({'html': html})
        
    except Exception as e:
        logger.error(f"Error getting recent requests: {str(e)}", exc_info=True)
        return jsonify({'html': f'<div class="text-danger">Fehler beim Laden: {str(e)}</div>'}) 

@main.route('/docs-view/')
def docs_view():
    """
    Wrapper-Ansicht für die Dokumentation mit App-Navigation.
    Lädt die MkDocs-Site in einem iframe, damit die Top-Navigation erhalten bleibt.
    """
    return render_template('docs_wrapper.html')

@main.route('/event-monitor')
def event_monitor():
    """
    Zeigt die Monitoring-Seite für asynchrone Event-Verarbeitung an.
    Hier werden aktuelle Batches und archivierte Batches aus dem event-job API-Endpoint angezeigt.
    """
    try:
        # Konfigurationsdaten laden (sofern benötigt)
        config = Config()
        event_config = config.get('processors.event', {})
        max_concurrent_tasks = event_config.get('max_concurrent_tasks', 5)
        
        # Basis-URL für API-Anfragen
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Filterparameter aus dem Request
        status_filter = request.args.get('status', '')
        date_filter = request.args.get('date', '')
        
        # Aktuelle (nicht-archivierte) Batches abrufen
        current_batches_url = f"{api_base_url}/api/event-job/batches?archived=false"
        if status_filter:
            current_batches_url += f"&status={status_filter}"

        # Standardwerte initialisieren, um Schattierung/Redeklaration zu vermeiden
        current_batches_data: Dict[str, Any] = {"batches": [], "total": 0}
        jobs_data: Dict[str, Any] = {}

        try:
            # HTTP-Request für aktuelle Batches
            current_batches_response: requests.Response = requests.get(current_batches_url)
            current_batches_response.raise_for_status()
            current_batches_data = current_batches_response.json()
            # KEINE Jobs mehr vorab laden - das wird bei Bedarf über JavaScript gemacht
        except requests.RequestException as e:
            logger.error(f"Fehler beim Abrufen der aktuellen Batch-Daten: {str(e)}")
        
        # Daten für das Template vorbereiten
        event_data = {
            "current_batches": current_batches_data.get('batches', []),
            "jobs_data": jobs_data,
            "filters": {
                "status": status_filter,
                "date": date_filter
            },
            "config": {
                "max_concurrent_tasks": max_concurrent_tasks
            }
        }
        
        return render_template('event_monitor.html', event_data=event_data)
        
    except Exception as e:
        logger.error(f"Fehler beim Laden der Event-Monitor-Seite: {str(e)}", exc_info=True)
        return f"Fehler beim Laden der Event-Monitor-Seite: {str(e)}", 500

@main.route('/api/dashboard/event-monitor/batches')
def api_event_monitor_batches():
    """
    API-Endpunkt zum Abrufen von Batch-Daten für die Event-Monitor-Oberfläche.
    Unterstützt Paginierung und Filterung.
    """
    try:
        # Query-Parameter extrahieren
        params = request.args
        status_filter = params.get('status', '')
        archived_filter = params.get('archived', 'false').lower()  # Normalisieren zu Kleinbuchstaben
        limit = int(params.get('limit', 100))
        
        # Verwende verschiedene Routen basierend auf dem Status-Filter
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # URL mit Status- und Archiv-Filter erstellen
        base_url = f"{api_base_url}/api/event-job/batches?limit={limit}"
        
        # Filter hinzufügen
        filters: List[str] = []
        if status_filter:
            filters.append(f"status={status_filter}")
        
        # Archived-Parameter korrekt übergeben (als String 'true' oder 'false')
        filters.append(f"archived={archived_filter}")
        
        # Filter zur URL hinzufügen
        if filters:
            filter_string = '&'.join(filters)
            url = f"{base_url}&{filter_string}"
        else:
            url = base_url
            
        logger.debug(f"Batch-Anfrage an: {url}")
        
        response: requests.Response = requests.get(url)
        response.raise_for_status()
        return jsonify(response.json())
        
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>')
def api_event_monitor_job_detail(job_id: str):
    """
    API-Endpunkt zum Abrufen der Details eines einzelnen Jobs anhand seiner ID.
    
    :param job_id: Die ID des Jobs, dessen Details abgerufen werden sollen.
    :return: JSON-Antwort mit den Job-Details oder einer Fehlermeldung.
    """
    if not job_id:
        logger.error("Keine job_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "job_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lade Job-Details für job_id: {job_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für einen einzelnen Job
        url = f"{base_url}/api/event-job/jobs/{job_id}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Detail API-Antwort erhalten: {response_data}")
        
        # Prüfe, ob der Job in der Antwort enthalten ist
        if not response_data.get('job'):
            logger.error(f"Kein Job in der API-Antwort gefunden für job_id: {job_id}")
            return jsonify({
                "status": "error",
                "message": f"Job mit ID {job_id} nicht gefunden"
            }), 404
        
        # Bereite die Antwort vor - direkte Struktur ohne Wrapping in 'data'
        result = {
            "status": "success",
            "job": response_data.get('job')
        }
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/jobs')
def api_event_monitor_jobs():
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug("Lade Jobs")
        
        # Verwende die generische get-Methode anstelle einer nicht existierenden get_api_base_url-Methode
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Extrahiere alle Query-Parameter
        batch_id = request.args.get('batch_id')
        status = request.args.get('status')
        
        # Erstelle die Basis-URL für Jobs
        url = f"{base_url}/api/event-job/jobs"
        
        # Füge Query-Parameter hinzu, wenn vorhanden
        params: List[str] = []
        if batch_id:
            params.append(f"batch_id={batch_id}")
        if status:
            params.append(f"status={status}")
            
        if params:
            url = f"{url}?{'&'.join(params)}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Jobs API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "jobs": response_data.get('jobs', []),
            "total": response_data.get('total', 0)
        }
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Jobs: {str(e)}",
            "jobs": [],
            "total": 0
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>/restart', methods=['POST'])
def api_event_monitor_job_restart(job_id: str):
    """
    API-Endpunkt zum Neustarten eines Jobs durch Zurücksetzen seines Status.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        
        # Request-Daten extrahieren (optional: batch_id)
        data = cast(Dict[str, Any], request.get_json() or {})
        batch_id: str = data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        # Korrigierter API-Pfad mit /api/ Präfix
        url = f"{base_url}/api/event-job/{job_id}/restart"
        
        # Debug-Ausgabe für die Problemdiagnose
        logger.debug(f"Sende Neustart-Anfrage an: {url}")
        
        # Führe die API-Anfrage durch
        response = requests.post(
            url, 
            json={'batch_id': batch_id},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Neustart API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich für den Neustart markiert"
        }
        
        if response_data.get('job'):
            result['job'] = response_data.get('job')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Neustarten des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Neustarten des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>/archive', methods=['POST'])
def api_event_monitor_job_archive(job_id: str):
    """
    API-Endpunkt zum Archivieren eines Jobs durch Änderung des Status.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        
        # Request-Daten extrahieren (optional: batch_id)
        data = cast(Dict[str, Any], request.get_json() or {})
        batch_id: str = data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        url = f"{base_url}/api/event-job/{job_id}/archive"
        
        # Führe die API-Anfrage durch
        response = requests.post(
            url, 
            json={'batch_id': batch_id},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Archivierung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich archiviert"
        }
        
        if response_data.get('job'):
            result['job'] = response_data.get('job')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Archivieren des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Archivieren des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500


@main.route('/api/dashboard/event-monitor/jobs/<job_id>', methods=['DELETE'])
def api_event_monitor_job_delete(job_id: str):
    """
    API-Endpunkt zum Löschen eines Jobs.
    
    :param job_id: Die ID des Jobs, der gelöscht werden soll.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not job_id:
        logger.error("Keine job_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "job_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lösche Job mit job_id: {job_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Löschen eines Jobs
        url = f"{base_url}/api/event-job/jobs/{job_id}"
        
        logger.debug(f"Rufe API auf (DELETE): {url}")
        
        # Führe die Anfrage durch
        response = requests.delete(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Löschung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich gelöscht"
        }
        
        if response_data.get('message'):
            result['message'] = response_data.get('message')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Löschen des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<batch_id>', methods=['DELETE'])
def api_event_monitor_batch_delete(batch_id: str):
    """
    API-Endpunkt zum Löschen eines Batches und aller zugehörigen Jobs.
    
    :param batch_id: Die ID des Batches, der gelöscht werden soll.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lösche Batch mit batch_id: {batch_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Löschen eines Batches
        url = f"{base_url}/api/event-job/batches/{batch_id}"
        
        logger.debug(f"Rufe API auf (DELETE): {url}")
        
        # Führe die Anfrage durch
        response = requests.delete(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Batch-Löschung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Batch {batch_id} wurde erfolgreich gelöscht"
        }
        
        if response_data.get('message'):
            result['message'] = response_data.get('message')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Löschen des Batches: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen des Batches: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/stats')
def api_event_monitor_batch_stats(batch_id: str):
    """
    API-Endpunkt zum Abrufen aktueller Statistiken eines Batches ohne Änderungen in der Datenbank.
    Dies ist nützlich für Live-Updates im Frontend ohne vollständige Seitenneuladen.
    
    :param batch_id: Die ID des Batches, dessen Statistiken abgerufen werden sollen.
    :return: JSON-Antwort mit den aktuellen Batch-Statistiken.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # Direkt das Repository für effizientere Abfragen verwenden
        job_repo: SessionJobRepository = get_job_repository()
        
        # Batch mit aktuellen Statistiken abrufen, ohne Status zu ändern
        batch = job_repo.get_batch_with_current_stats(batch_id)  # type: ignore
        
        if not batch:
            logger.error(f"Batch nicht gefunden: {batch_id}")
            return jsonify({
                "status": "error",
                "message": f"Batch mit ID {batch_id} nicht gefunden"
            }), 404
        
        # Erfolgsantwort zurückgeben
        return jsonify({
            "status": "success",
            "batch": batch.to_dict()  # type: ignore
        })
    
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Statistiken: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Statistiken: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/toggle-active', methods=['POST'])
def api_event_monitor_toggle_active(batch_id: str):
    """
    API-Endpunkt zum Umschalten des isActive-Status eines Batches.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Request-Daten (falls vorhanden) weitergeben
        data = cast(Dict[str, Any], request.get_json() if request.is_json else {})
        
        # API-Anfrage zur Umschaltung des isActive-Status
        # Verwende standardisierte Event-Job-API-URL
        url = f"{api_base_url}/api/event-job/batches/{batch_id}/toggle-active"
        logger.debug(f"Toggle-Active-Anfrage an: {url} mit Daten: {data}")
        response: requests.Response = requests.post(url, json=data)
        response.raise_for_status()
        
        # Antwort verarbeiten
        result = response.json()
        
        # Erfolgsantwort zurückgeben
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Umschalten des isActive-Status: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Umschalten des isActive-Status: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/archive', methods=['POST'])
def api_event_monitor_batch_archive(batch_id: str):
    """
    API-Endpunkt zum Archivieren eines Batches.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Request-Daten (falls vorhanden) weitergeben oder Standarddaten verwenden
        data = cast(Dict[str, Any], request.get_json() if request.is_json else {})
        
        # Sicherstellen, dass die Mindestanforderungen erfüllt sind
        if 'batch_id' not in data:
            data['batch_id'] = batch_id
        if 'archived' not in data:
            data['archived'] = True
            
        logger.debug(f"Archiviere Batch {batch_id} mit Daten: {data}")
        
        # API-Anfrage zum Archivieren des Batches
        # Korrigierte URL-Konstruktion - prüfe, ob Basis-URL bereits den API-Pfad enthält
        url = f"{api_base_url}/api/event-job/batches/{batch_id}/archive"
            
        logger.debug(f"Batch-Archivierung-Anfrage an: {url}")
        
        # Initialisiere response als None
        response: Optional[requests.Response] = None
        
        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            
            # Antwort verarbeiten
            result = response.json()
            
            # Erfolgsantwort zurückgeben
            return jsonify(result)
            
        except requests.exceptions.HTTPError as http_err:
            error_message = f"HTTP-Fehler beim Archivieren des Batches: {http_err}"
            logger.error(error_message)
            
            # Versuche, Details aus der Antwort zu extrahieren, wenn response existiert
            if response is not None:
                try:
                    error_details = response.json()
                    logger.error(f"API-Fehlerdetails: {error_details}")
                    return jsonify({
                        "status": "error",
                        "message": error_message,
                        "details": error_details
                    }), response.status_code
                except Exception:
                    pass
                
                return jsonify({
                    "status": "error",
                    "message": error_message
                }), response.status_code
            
            # Standardantwort, wenn keine Antwort vom Server kam
            return jsonify({
                "status": "error",
                "message": error_message
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Archivieren des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/restart', methods=['POST'])
def api_event_monitor_batch_restart(batch_id: str):
    """
    API-Endpunkt zum Neustarten aller Jobs in einem Batch.
    
    :param batch_id: Die ID des Batches, dessen Jobs neu gestartet werden sollen.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # Repository-Instanz holen
        job_repo = get_job_repository()
        
        # Alle Jobs des Batches auf einmal auf PENDING setzen
        result = job_repo.update_jobs_status_by_batch(batch_id, JobStatus.PENDING)
        
        if result > 0:
            # Erfolgsantwort zurückgeben
            return jsonify({
                "status": "success",
                "message": f"{result} Jobs wurden neu gestartet",
                "data": {
                    "restarted_jobs": result
                }
            })
        else:
            return jsonify({
                "status": "warning",
                "message": "Keine Jobs für diesen Batch gefunden",
                "data": {
                    "restarted_jobs": 0
                }
            }), 200
            
    except Exception as e:
        logger.error(f"Fehler beim Neustarten des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/fail-all', methods=['POST'])
def api_event_monitor_fail_all_batches():
    """
    API-Endpunkt zum Setzen aller aktiven Batches auf failed.
    """
    try:
        # API-URL zusammenbauen
        api_url = f"{current_app.config['API_BASE_URL']}/event-job/batches/fail-all"
        
        # Headers vorbereiten
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Benutzer-ID aus den Headern weiterleiten
        if 'X-User-ID' in request.headers:
            headers['X-User-ID'] = request.headers['X-User-ID']
        
        # API-Aufruf durchführen
        response = requests.post(api_url, headers=headers)
        response.raise_for_status()
        
        # Erfolgreiche Antwort
        return jsonify(response.json()), response.status_code
        
    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP-Fehler beim Setzen der Batches auf failed: {http_err}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), getattr(http_err.response, 'status_code', 500)
        
    except Exception as e:
        error_message = f"Fehler beim Setzen der Batches auf failed: {str(e)}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/force-fail-all', methods=['POST'])
def api_event_monitor_force_fail_all():
    """
    API-Endpunkt zum direkten Setzen ALLER Batches und Jobs auf failed.
    Dies ist eine direkte Datenbankoperation, die alle Batches und Jobs betrifft.
    """
    try:
        # Repository-Instanz holen
        job_repo = get_job_repository()
        now = datetime.now(timezone.utc)  # Verwende utcnow statt now(UTC)
        
        # Direkte Batch-Aktualisierung
        batch_result = job_repo.batches.update_many(
            {"archived": {"$ne": True}},  # Nicht archivierte Batches
            {
                "$set": {
                    "status": "failed",  # Kleinbuchstaben statt Großbuchstaben
                    "updated_at": now,
                    "completed_at": now
                }
            }
        )
        
        # Direkte Job-Aktualisierung für alle Jobs
        job_result = job_repo.jobs.update_many(
            {},  # Alle Jobs
            {
                "$set": {
                    "status": "failed",  # Kleinbuchstaben statt Großbuchstaben
                    "updated_at": now,
                    "completed_at": now,
                    "error": {
                        "code": "FORCED_FAILURE",
                        "message": "Job wurde manuell auf failed gesetzt",
                        "details": {
                            "forced_at": now.isoformat(),
                            "reason": "Manuelle Massenaktualisierung"
                        }
                    }
                }
            }
        )
        
        # Log die Änderungen
        logger.info(
            f"Force-fail-all ausgeführt",
            extra={
                "updated_batches": batch_result.modified_count,
                "updated_jobs": job_result.modified_count
            }
        )
        
        return jsonify({
            "status": "success",
            "message": f"{batch_result.modified_count} Batches und {job_result.modified_count} Jobs auf failed gesetzt",
            "data": {
                "updated_batches": batch_result.modified_count,
                "updated_jobs": job_result.modified_count
            }
        })
            
    except Exception as e:
        error_message = f"Fehler beim Setzen aller Batches und Jobs auf failed: {str(e)}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/set-pending-all', methods=['POST'])
def api_event_monitor_set_pending_all():
    """
    Setzt alle nicht archivierten Batches und deren Jobs auf 'pending'.
    Parameter:
    - target_language: Die neue Zielsprache (z.B. 'de', 'en', etc.)
    """
    try:
        data = cast(Dict[str, Any], request.get_json() or {})
        target_language: Optional[str] = data.get('target_language')
        job_repository = get_job_repository()
        
        # Hole alle nicht archivierten Batches
        batches = job_repository.get_batches(archived=False)
        updated_batches = 0
        updated_jobs = 0
        
        # Aktualisiere jeden Batch und seine Jobs
        for batch in batches:
            # Aktualisiere Batch und alle zugehörigen Jobs auf PENDING
            if job_repository.update_batch_status(batch.batch_id, JobStatus.PENDING):
                updated_batches += 1
                
            # Aktualisiere alle Jobs des Batches
            jobs_updated = job_repository.update_jobs_status_by_batch(
                batch.batch_id, 
                JobStatus.PENDING,
                language=target_language
            )
            updated_jobs += jobs_updated
        
        logger.info(
            f"Alle Batches auf pending gesetzt",
            extra={
                "updated_batches": updated_batches,
                "updated_jobs": updated_jobs
            }
        )
        
        return jsonify({
            "status": "success",
            "message": f"{updated_batches} Batches und {updated_jobs} Jobs auf pending gesetzt",
            "data": {
                "batches_updated": updated_batches,
                "jobs_updated": updated_jobs
            }
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Setzen der Batches auf pending: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/change-language', methods=['POST'])
def api_event_monitor_change_language():
    """
    Ändert die Zielsprache für alle Jobs oder einen einzelnen Job im Event-Monitor.
    
    Parameter:
    - target_language: Die neue Zielsprache (z.B. 'de', 'en', etc.)
    - job_id: (Optional) Die ID eines einzelnen Jobs, dessen Sprache geändert werden soll
    - reset_status: (Optional) Ob der Status der Jobs auf 'pending' zurückgesetzt werden soll
    - current_batches_only: (Optional) Ob nur aktuelle (nicht archivierte) Batches betroffen sein sollen
    
    Returns:
        JSON mit Erfolgs- oder Fehlermeldung
    """
    logger = logging.getLogger(__name__)
    try:
        # Daten aus dem Request auslesen
        data = cast(Dict[str, Any], request.get_json() or {})
        
        target_language: Optional[str] = data.get('target_language')
        job_id = data.get('job_id')
        reset_status = data.get('reset_status', False)
        current_batches_only = data.get('current_batches_only', True)
        
        if not target_language:
            return jsonify({'status': 'error', 'message': 'Zielsprache (target_language) ist erforderlich'}), 400
        
        # Repository und weitere benötigte Objekte initialisieren
        job_repo = get_job_repository()
        success_count = 0
        
        # Bestimmen, ob ein einzelner Job oder mehrere Jobs aktualisiert werden sollen
        if job_id:
            # Einzelnen Job aktualisieren
            logger.info(f"Ändere Zielsprache für Job {job_id} auf {target_language}")
            
            job = job_repo.get_job(job_id)
            if not job:
                return jsonify({'status': 'error', 'message': f'Job mit ID {job_id} nicht gefunden'}), 404
            
            # Job-Parameter aktualisieren
            job_parameters = job.parameters.to_dict() if job.parameters else {}
            job_parameters['target_language'] = target_language
            
            # Status zurücksetzen, falls gewünscht
            if reset_status:
                job_repo.update_job_status(job_id, JobStatus.PENDING)
                
            # Job-Parameter aktualisieren
            job_repo.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"parameters": job_parameters}}
            )
            success_count = 1
            
            logger.info(f"Zielsprache für Job {job_id} erfolgreich auf {target_language} geändert")
        else:
            # Alle Jobs in Batches aktualisieren
            logger.info(f"Ändere Zielsprache für alle Jobs auf {target_language}")
            
            # Batches abrufen (basierend auf dem 'current_batches_only' Parameter)
            batches: List[Batch] = job_repo.get_batches(archived=not current_batches_only)
            
            # Durch alle Batches iterieren und Jobs aktualisieren
            for batch in batches:
                batch_id = batch.batch_id
                logger.info(f"Verarbeite Batch {batch_id}")
                
                # Jobs für den aktuellen Batch abrufen
                jobs = job_repo.get_jobs_for_batch(batch_id, limit=1000)
                
                for job in jobs:
                    # Parameter aktualisieren
                    job_parameters = job.parameters.to_dict() if job.parameters else {}
                    job_parameters['target_language'] = target_language
                    
                    # Job-Parameter aktualisieren
                    job_repo.jobs.update_one(
                        {"job_id": job.job_id},
                        {"$set": {"parameters": job_parameters}}
                    )
                    success_count += 1
                
                # Status zurücksetzen, falls gewünscht
                if reset_status and jobs:
                    job_repo.update_batch_status(batch_id, JobStatus.PENDING)
                    job_repo.update_jobs_status_by_batch(batch_id, JobStatus.PENDING)
            
            logger.info(f"Zielsprache für {success_count} Jobs erfolgreich auf {target_language} geändert")
        
        # Erfolgreiche Antwort zurückgeben
        return jsonify({
            'status': 'success',
            'message': f'Zielsprache für {success_count} Job(s) erfolgreich auf {target_language} geändert',
            'data': {
                'updated_count': success_count,
                'target_language': target_language
            }
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Ändern der Zielsprache: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Fehler beim Ändern der Zielsprache: {str(e)}'}), 500 
```

Verstanden: 
- Es gibt jetzt `docs/index.md` → wird zu `site/index.html`. Ich habe die Doku-Route so angepasst, dass `/docs` auf `/docs/` weiterleitet und `/docs/` bevorzugt `site/index.html` lädt.
- Top-Navigation erhalten: Ich habe eine Wrapper-Seite mit iframe eingebaut, damit die App-Navigation stehen bleibt und die MkDocs-Doku darunter läuft.

Was ich umgesetzt habe:
- Neue Route `GET /docs-view/` in `src/dashboard/routes/main_routes.py` mit Template `docs_wrapper.html`.
- Navbar „Docs“ verweist nun auf `{{ url_for('main.docs_view') }}` statt direkt auf `/docs/`.
- `docs_wrapper.html` lädt die Doku per iframe: Quelle `/docs/` (deine MkDocs-Site). So bleibt die Top-Navigation sichtbar.
- Doku-Blueprint liefert `/docs`, `/docs/` und statische Unterpfade korrekt aus. Falls `site/index.html` fehlt, wird auf die erste Sektion weitergeleitet.

Nutzen:
- Einheitliche UX. Immer die App-Navigation sichtbar.
- Du kannst jederzeit zur App zurückkehren.
- Die Doku bleibt unverändert im MkDocs-Layout.

Test:
- Baue Doku: `mkdocs build -c -d site` (falls noch nicht).
- Starte App und öffne: `http://127.0.0.1:5001/docs-view/`.
- Prüfe, ob `http://127.0.0.1:5001/docs/` direkt funktioniert (ohne Wrapper), falls du die Doku separat brauchst.

Optional:
- Wenn externe Links aus der Doku im selben Tab landen sollen, können wir `rel`/`target` per JS in der Wrapper-Seite anpassen.
- Falls du statt iframe lieber echte Integration willst (gemeinsames Template), ist das deutlich aufwändiger, da MkDocs statisch rendert. Der iframe ist die einfache und saubere Lösung für Single-Deployment.

---

**User**

Okay, irgendwie habe ich jetzt zwei Scrollbars rechts. Das ist sehr verwirrend. Einmal von meiner Anwendung und dann die von mkdocs. Ist es vielleicht möglich, bei mkdocs im Header oben einen Rückverweis zu integrieren zu unserer Anwendung, zu unserer Homepage, sodass man es so belassen kann, wie es vorher war, aber die Navigation nichts verliert?

---

**Cursor**

Ich entferne die iframe-Variante (um die doppelte Scrollbar zu vermeiden), stelle den Navbar-Link wieder direkt auf `/docs/` um und ergänze in `mkdocs.yml` einen prominenten Rück-Link zur Anwendung (als Top-NAV-Eintrag und als Home-Icon). Danach kannst du in der Doku jederzeit zurück zur App, ohne iframe.

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Secretary Services Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    {% block extra_css %}{% endblock %}
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="{{ url_for('main.home') }}">Secretary Services v0.1.44</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.home' %}active{% endif %}" href="{{ url_for('main.home') }}">Dashboard</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.logs' %}active{% endif %}" href="{{ url_for('main.logs') }}">Logs</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.event_monitor' %}active{% endif %}" href="{{ url_for('main.event_monitor') }}">Event-Monitor</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.config_page' %}active{% endif %}" href="{{ url_for('main.config_page') }}">Config</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link {% if request.endpoint == 'main.test_procedures' %}active{% endif %}" href="{{ url_for('main.test_procedures') }}">Tests</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/api/doc">API</a>
                    </li>
                    <li class="nav-item">
                        <a class="nav-link" href="/docs/">Docs</a>
                    </li>
                </ul>
            </div>
        </div>
    </nav>

    <div class="container mt-4">
        {% block content %}{% endblock %}
    </div>

    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html> 
```

```python
"""
Main routes for the dashboard application.
Contains the main dashboard view and test routes.
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for, current_app
from datetime import datetime, timedelta, timezone
import json
import os
import re
from typing import Any, Dict, List, cast, Optional
import logging

from src.core.config import ApplicationConfig
from src.core.models.job_models import Batch
from src.utils.logger import ProcessingLogger
from ..utils import get_system_info
from pathlib import Path
import yaml
from src.core.config import Config
from src.utils.logger import get_logger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test
import requests  # Neu hinzugefügt für API-Anfragen
import markdown  # type: ignore
from src.core.mongodb.repository import SessionJobRepository
from src.core.mongodb import get_job_repository
from src.core.models.job_models import JobStatus

# Create the blueprint
main = Blueprint('main', __name__)
logger: ProcessingLogger = get_logger(process_id="dashboard")

# Funktion zur Markdown-Konvertierung
def render_markdown(text: str) -> str:
    """Konvertiert Markdown-Text in HTML"""
    return markdown.markdown(text)

def load_logs_for_requests(recent_requests: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """
    Load log entries for a list of requests from the detailed log file
    
    Args:
        recent_requests (list): List of request entries to load logs for
        
    Returns:
        dict: Dictionary mapping process_ids to their log entries
    """
    # Lade Log-Pfad aus der Konfiguration
    config = Config()
    log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
    log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', log_file)
    request_logs: dict[str, list[dict[str, Any]]] = {}
    
    try:
        with open(log_path, 'r') as f:
            current_entry = None
            details_lines = []
            collecting_details = False
            
            for line in f:
                line = line.strip()
                
                # Check if this is a new log entry
                if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}', line):
                    # Save previous entry if exists
                    if current_entry is not None:
                        if details_lines:
                            try:
                                details_text = '\n'.join(details_lines)
                                if details_text.startswith('Details: '):
                                    details_text = details_text[9:]
                                current_entry['details'] = cast(str, json.loads(details_text))
                            except json.JSONDecodeError:
                                current_entry['details'] = cast(str, {'raw': '\n'.join(details_lines)})
                        
                        if current_entry['process_id'] in request_logs:
                            request_logs[current_entry['process_id']].append(current_entry)
                    
                    # Parse new entry
                    parts = line.split(' - ')
                    if len(parts) >= 5:
                        timestamp = parts[0]
                        level = parts[1]
                        source = parts[2]  # [logger.py:97]
                        process_info = parts[3]  # [TransformerProcessor] Process[1735640951800]
                        message = ' - '.join(parts[4:])  # Join remaining parts in case message contains ' - '
                        
                        try:
                            # Extrahiere processor_name und process_id
                            # Format: "[YoutubeProcessor] Process[1735641423754]"
                            if '] Process[' in process_info:
                                parts = process_info.split('] Process[')
                                processor_name = parts[0].strip('[')  # YoutubeProcessor
                                process_id = parts[1].strip(']')      # 1735641423754
                            else:
                                processor_name = ""
                                process_id = ""
                            
                            # Initialize logs list for process_id if it's in recent requests
                            for request in recent_requests:
                                if request.get('process_id') == process_id:
                                    if process_id not in request_logs:
                                        request_logs[process_id] = []
                            
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': processor_name,
                                'process_id': process_id,
                                'message': message.strip()
                            }
                        except Exception as e:
                            print(f"Error parsing log line: {line}")
                            print(f"Error: {str(e)}")
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': "",
                                'process_id': "",
                                'message': message.strip()
                            }
                        details_lines = []
                        collecting_details = False
                
                # Check if this is the start of details
                elif line.startswith('Details: '):
                    collecting_details = True
                    details_lines = [line]
                
                # Add to details if we're collecting them
                elif collecting_details and line:
                    details_lines.append(line)
            
            
            # Don't forget to add the last entry
            if current_entry is not None:
                if details_lines:
                    try:
                        details_text = '\n'.join(details_lines)
                        if details_text.startswith('Details: '):
                            details_text = details_text[9:]
                        current_entry['details'] = cast(str, json.loads(details_text))
                    except json.JSONDecodeError:
                        current_entry['details'] = cast(str, {'raw': '\n'.join(details_lines)})
                
                # Add to request logs if process_id matches
                if current_entry['process_id'] in request_logs:
                    request_logs[current_entry['process_id']].append(current_entry)
                    
    except Exception as e:
        print(f"Error reading log file: {e}")
    
    return request_logs

@main.route('/')
def home():
    """
    Dashboard main page route.
    Displays statistics about recent requests.
    """
    # Initialize statistics
    stats: dict[str, Any] = {
        'total_requests': 0,
        'avg_duration': 0.0,
        'success_rate': 0.0,
        'total_tokens': 0,
        'hourly_tokens': 0,
        'operations': {},
        'processor_stats': {},
        'hourly_stats': {},
        'recent_requests': []
    }
    
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        logger.info(f"Loading performance data from {perf_path}")
        
        if not os.path.exists(perf_path):
            logger.warning(f"Performance file not found at {perf_path}")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
        
        # Prüfe, ob die Datei leer ist
        if os.path.getsize(perf_path) == 0:
            logger.warning("Performance file is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            logger.warning("Performance data is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        # Calculate time window
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests and ensure timestamp is valid
        recent_requests: list[dict[str, Any]] = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        if recent_requests:
            # Basic statistics
            stats['total_requests'] = len(recent_requests)
            total_duration = sum(float(r.get('total_duration', 0)) for r in recent_requests)
            stats['avg_duration'] = total_duration / len(recent_requests)
            
            # Success rate calculation
            success_count = sum(1 for r in recent_requests if r.get('status') == 'success')
            stats['success_rate'] = (success_count / len(recent_requests)) * 100
            
            # Token calculation
            total_tokens = sum(r.get('resources', {}).get('total_tokens', 0) for r in recent_requests)
            stats['hourly_tokens'] = total_tokens // 24 if total_tokens > 0 else 0
            
            # Operation statistics
            for r in recent_requests:
                for op in r.get('operations', []):
                    op_name = op.get('name', 'unknown')
                    if 'operations' not in stats:
                        stats['operations'] = {}
                    operations_dict = cast(Dict[str, int], stats['operations'])
                    operations_dict[op_name] = operations_dict.get(op_name, 0) + 1
            
            # Processor statistics
            for r in recent_requests:
                for processor, data in r.get('processors', {}).items():
                    if processor not in stats['processor_stats']:
                        stats['processor_stats'][processor] = {
                            'request_count': 0,
                            'total_duration': 0,
                            'success_count': 0,
                            'error_count': 0,
                            'total_tokens': 0,
                            'total_cost': 0
                        }
                    
                    proc_stats = stats['processor_stats'][processor]
                    proc_stats['request_count'] += 1
                    proc_stats['total_duration'] += float(data.get('total_duration', 0))
                    proc_stats['success_count'] += data.get('success_count', 0)
                    proc_stats['error_count'] += data.get('error_count', 0)
                    
                    # Add token and cost data if available
                    resources = r.get('resources', {})
                    proc_stats['total_tokens'] += resources.get('total_tokens', 0)
                    proc_stats['total_cost'] += float(resources.get('total_cost', 0))
            
            # Calculate averages for processor stats
            for proc_stats in stats['processor_stats'].values():
                req_count = proc_stats['request_count']
                if req_count > 0:
                    proc_stats['avg_duration'] = proc_stats['total_duration'] / req_count
                    proc_stats['success_rate'] = (proc_stats['success_count'] / req_count) * 100
                    proc_stats['avg_tokens'] = proc_stats['total_tokens'] // req_count
                    proc_stats['avg_cost'] = proc_stats['total_cost'] / req_count
            
            # Hourly statistics
            hour_counts: Dict[str, int] = {}
            for r in recent_requests:
                try:
                    hour = datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S').strftime('%H:00')
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                except ValueError as e:
                    logger.error(f"Error processing hour statistics: {e}")
                    continue
            
            # Sort hours and create final hourly stats
            sorted_hours = sorted(list(hour_counts.keys()))
            stats['hourly_stats'] = {hour: hour_counts[hour] for hour in sorted_hours}
            
            # Process recent requests (last 10)
            recent_requests = sorted(recent_requests, 
                                  key=lambda x: x['timestamp'],
                                  reverse=True)[:10]
            
            # Add logs to recent requests
            request_logs = load_logs_for_requests(recent_requests)
            for request in recent_requests:
                process_id = request.get('process_id')
                request['logs'] = request_logs.get(process_id, []) if process_id else []
                
                # Get the main operation
                main_op: Dict[str, Any] = {}
                for op in request.get('operations', []):
                    if op.get('name') == request.get('operation'):
                        main_op = op
                        break
                
                # Prepare the main process data
                request['main_process'] = {
                    'timestamp': request['timestamp'],
                    'duration_seconds': float(request.get('total_duration', 0)),
                    'operation': main_op.get('name', ''),
                    'processor': main_op.get('processor', ''),
                    'success': request.get('status') == 'success',
                    'file_size': request.get('file_size', 0),
                    'duration': main_op.get('duration', 0),
                    'text': request.get('text', ''),
                    'text_length': len(request.get('text', '')),
                    'llm_model': request.get('resources', {}).get('models_used', [''])[0],
                    'tokens': request.get('resources', {}).get('total_tokens', 0)
                }
            
            stats['recent_requests'] = recent_requests
            
    except Exception as e:
        logger.error(f"Error processing dashboard data: {str(e)}", exc_info=True)
        stats['error'] = str(e)
    
    return render_template('dashboard.html', 
                         stats=stats,
                         system_info=get_system_info())

@main.route('/api/config', methods=['POST'])
def save_config():
    """Speichert die Konfiguration in der config.yaml."""
    try:
        yaml_content = request.get_json()
        if yaml_content is None:
            return jsonify({"status": "error", "message": "Keine YAML-Daten empfangen"}), 400
            
        # Parse YAML-String zu Dictionary
        try:
            config_data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            return jsonify({"status": "error", "message": f"Ungültiges YAML Format: {str(e)}"}), 400
            
        config = Config()
        
        # Extrahiere und validiere API Key, falls vorhanden
        api_key_updated = False
        if 'api_keys' in config_data and 'openai_api_key' in config_data['api_keys']:
            api_key = config_data['api_keys']['openai_api_key']
            if api_key and not api_key.startswith('sk-...'):  # Nur speichern wenn es kein maskierter Key ist
                try:
                    # Verwende die ConfigKeys-Klasse anstatt config.set_api_key
                    from src.core.config_keys import ConfigKeys
                    config_keys = ConfigKeys()
                    config_keys.set_openai_api_key(api_key)
                    api_key_updated = True
                except ValueError as e:
                    return jsonify({"status": "error", "message": str(e)}), 400
            # Entferne API Keys aus config_data
            del config_data['api_keys']
        
        # Hole den Pfad zur config.yaml
        config_path = Path(__file__).parents[3] / 'config' / 'config.yaml'
        
        # Speichere die aktualisierte Konfiguration
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(config_data, f, default_flow_style=False, allow_unicode=True)
            
        message = "API Key aktualisiert. " if api_key_updated else ""
        
        # Lade die aktuelle Konfiguration neu
        config_yaml = yaml.safe_dump(config.get_all(), default_flow_style=False, allow_unicode=True)
        
        return jsonify({
            "status": "success", 
            "message": f"{message}Konfiguration erfolgreich gespeichert",
            "config": config_yaml
        })
        
    except Exception as e:
        logger.error("Fehler beim Speichern der Konfiguration", exc_info=e)
        return jsonify({"status": "error", "message": f"Fehler beim Speichern: {str(e)}"}), 500

@main.route('/config')
def config_page():
    """
    Zeigt die Konfigurationsseite an.
    
    Returns:
        rendered template: Die config.html Template mit der aktuellen Konfiguration
    """
    try:
        # Lade die aktuelle Konfiguration
        config = Config()
        config_data = config.get_all()
        print("Config Data:", config_data)  # Debug-Ausgabe
        
        # Konvertiere zu YAML
        config_yaml = yaml.safe_dump(config_data, default_flow_style=False, allow_unicode=True)
        print("Config YAML:", config_yaml)  # Debug-Ausgabe
            
        return render_template('config.html', config=config_yaml)
    except Exception as e:
        logger.error("Fehler beim Laden der Konfiguration", exc_info=e)
        print("Error:", str(e))  # Debug-Ausgabe
        return render_template('config.html', config="", error=str(e))

@main.route('/test')
def test_page():
    """
    Test page with Swagger UI integration for API testing
    
    Returns:
        rendered template: The apitest.html template with Swagger UI
    """
    return render_template('apitest.html')

@main.route('/test-procedures')
def test_procedures():
    """
    Zeigt die Testseite an.
    
    Returns:
        rendered template: Die test_procedures.html Template
    """
    return render_template('test_procedures.html')

@main.route('/run_youtube_test', methods=['POST'])
def youtube_test():
    """Route handler for Youtube test"""
    return run_youtube_test()

@main.route('/run_audio_test', methods=['POST'])
def audio_test():
    """Route handler for audio test"""
    return run_audio_test()

@main.route('/run_transformer_test', methods=['POST'])
def transformer_test():
    """Route handler for transformer test"""
    return run_transformer_test()

@main.route('/run_health_test', methods=['POST'])
def health_test():
    """Route handler for health test"""
    return run_health_test()

@main.route('/logs')
def logs():
    """
    Zeigt die Logs der Anwendung an.
    
    Diese Funktion lädt die in der config.yaml definierte Log-Datei und zeigt die letzten X Einträge an.
    Die Log-Datei wird zentral durch den LoggerService initialisiert.
    
    Returns:
        rendered template: Die logs.html Template mit den Log-Einträgen
    """
    try:
        # Lade Konfiguration
        config = Config()
        config_data: ApplicationConfig = config.get_all()
        
        max_entries = config_data.get('logging', {}).get('max_log_entries', 1000)
        log_file = config_data.get('logging', {}).get('file', 'logs/detailed.log')
        log_path = Path(log_file)
        
        log_files = {}
        
        # Lese die Log-Datei
        if log_path.exists():
            with open(log_path, 'r') as f:
                log_files[log_file] = f.readlines()[-max_entries:]
        else:
            log_files[log_file] = []
                
        return render_template('logs.html', log_files=log_files)
    except Exception as e:
        print(f"Fehler beim Laden der Logs: {str(e)}")
        return f"Fehler beim Laden der Logs: {str(e)}", 500

@main.route('/clear-logs', methods=['POST'])
def clear_logs():
    """
    Löscht den Inhalt der Log-Datei und stellt sicher, dass sie danach wieder existiert.
    Die Log-Datei wird mit einem leeren Inhalt neu erstellt.
    
    Returns:
        redirect: Leitet zurück zur Logs-Ansicht
    """
    try:
        # Lade Log-Pfad aus der Konfiguration
        config = Config()
        log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
        log_path = Path(log_file)
        
        # Stelle sicher, dass das Verzeichnis existiert
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Leere die Datei oder erstelle sie neu
        log_path.write_text('')
        
        return redirect(url_for('main.logs'))
    except Exception as e:
        return f"Error clearing logs: {str(e)}", 500 

@main.route('/api/recent-requests')
def get_recent_requests():
    """
    API-Endpunkt zum Abrufen der neuesten Anfragen.
    Gibt die letzten 10 Anfragen zurück.
    
    Returns:
        Response: JSON mit den neuesten Anfragen
    """
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        
        if not os.path.exists(perf_path):
            return jsonify([])
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            return jsonify([])
            
        # Calculate time window
        now = datetime.now(timezone.utc)
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests and ensure timestamp is valid
        recent_requests: List[Dict[str, Any]] = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        # Sort by timestamp (newest first) and take last 10
        recent_requests = sorted(
            recent_requests,
            key=lambda x: x.get('timestamp', ''),
            reverse=True
        )[:10]
        
        # Render only the requests list part
        html = render_template('_recent_requests.html', 
                             recent_requests=recent_requests)
        
        return jsonify({'html': html})
        
    except Exception as e:
        logger.error(f"Error getting recent requests: {str(e)}", exc_info=True)
        return jsonify({'html': f'<div class="text-danger">Fehler beim Laden: {str(e)}</div>'}) 

## Entfernt: iframe-basierte Docs-Ansicht, um doppelte Scrollbars zu vermeiden

@main.route('/event-monitor')
def event_monitor():
    """
    Zeigt die Monitoring-Seite für asynchrone Event-Verarbeitung an.
    Hier werden aktuelle Batches und archivierte Batches aus dem event-job API-Endpoint angezeigt.
    """
    try:
        # Konfigurationsdaten laden (sofern benötigt)
        config = Config()
        event_config = config.get('processors.event', {})
        max_concurrent_tasks = event_config.get('max_concurrent_tasks', 5)
        
        # Basis-URL für API-Anfragen
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Filterparameter aus dem Request
        status_filter = request.args.get('status', '')
        date_filter = request.args.get('date', '')
        
        # Aktuelle (nicht-archivierte) Batches abrufen
        current_batches_url = f"{api_base_url}/api/event-job/batches?archived=false"
        if status_filter:
            current_batches_url += f"&status={status_filter}"

        # Standardwerte initialisieren, um Schattierung/Redeklaration zu vermeiden
        current_batches_data: Dict[str, Any] = {"batches": [], "total": 0}
        jobs_data: Dict[str, Any] = {}

        try:
            # HTTP-Request für aktuelle Batches
            current_batches_response: requests.Response = requests.get(current_batches_url)
            current_batches_response.raise_for_status()
            current_batches_data = current_batches_response.json()
            # KEINE Jobs mehr vorab laden - das wird bei Bedarf über JavaScript gemacht
        except requests.RequestException as e:
            logger.error(f"Fehler beim Abrufen der aktuellen Batch-Daten: {str(e)}")
        
        # Daten für das Template vorbereiten
        event_data = {
            "current_batches": current_batches_data.get('batches', []),
            "jobs_data": jobs_data,
            "filters": {
                "status": status_filter,
                "date": date_filter
            },
            "config": {
                "max_concurrent_tasks": max_concurrent_tasks
            }
        }
        
        return render_template('event_monitor.html', event_data=event_data)
        
    except Exception as e:
        logger.error(f"Fehler beim Laden der Event-Monitor-Seite: {str(e)}", exc_info=True)
        return f"Fehler beim Laden der Event-Monitor-Seite: {str(e)}", 500

@main.route('/api/dashboard/event-monitor/batches')
def api_event_monitor_batches():
    """
    API-Endpunkt zum Abrufen von Batch-Daten für die Event-Monitor-Oberfläche.
    Unterstützt Paginierung und Filterung.
    """
    try:
        # Query-Parameter extrahieren
        params = request.args
        status_filter = params.get('status', '')
        archived_filter = params.get('archived', 'false').lower()  # Normalisieren zu Kleinbuchstaben
        limit = int(params.get('limit', 100))
        
        # Verwende verschiedene Routen basierend auf dem Status-Filter
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # URL mit Status- und Archiv-Filter erstellen
        base_url = f"{api_base_url}/api/event-job/batches?limit={limit}"
        
        # Filter hinzufügen
        filters: List[str] = []
        if status_filter:
            filters.append(f"status={status_filter}")
        
        # Archived-Parameter korrekt übergeben (als String 'true' oder 'false')
        filters.append(f"archived={archived_filter}")
        
        # Filter zur URL hinzufügen
        if filters:
            filter_string = '&'.join(filters)
            url = f"{base_url}&{filter_string}"
        else:
            url = base_url
            
        logger.debug(f"Batch-Anfrage an: {url}")
        
        response: requests.Response = requests.get(url)
        response.raise_for_status()
        return jsonify(response.json())
        
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>')
def api_event_monitor_job_detail(job_id: str):
    """
    API-Endpunkt zum Abrufen der Details eines einzelnen Jobs anhand seiner ID.
    
    :param job_id: Die ID des Jobs, dessen Details abgerufen werden sollen.
    :return: JSON-Antwort mit den Job-Details oder einer Fehlermeldung.
    """
    if not job_id:
        logger.error("Keine job_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "job_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lade Job-Details für job_id: {job_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für einen einzelnen Job
        url = f"{base_url}/api/event-job/jobs/{job_id}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Detail API-Antwort erhalten: {response_data}")
        
        # Prüfe, ob der Job in der Antwort enthalten ist
        if not response_data.get('job'):
            logger.error(f"Kein Job in der API-Antwort gefunden für job_id: {job_id}")
            return jsonify({
                "status": "error",
                "message": f"Job mit ID {job_id} nicht gefunden"
            }), 404
        
        # Bereite die Antwort vor - direkte Struktur ohne Wrapping in 'data'
        result = {
            "status": "success",
            "job": response_data.get('job')
        }
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/jobs')
def api_event_monitor_jobs():
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug("Lade Jobs")
        
        # Verwende die generische get-Methode anstelle einer nicht existierenden get_api_base_url-Methode
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Extrahiere alle Query-Parameter
        batch_id = request.args.get('batch_id')
        status = request.args.get('status')
        
        # Erstelle die Basis-URL für Jobs
        url = f"{base_url}/api/event-job/jobs"
        
        # Füge Query-Parameter hinzu, wenn vorhanden
        params: List[str] = []
        if batch_id:
            params.append(f"batch_id={batch_id}")
        if status:
            params.append(f"status={status}")
            
        if params:
            url = f"{url}?{'&'.join(params)}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Jobs API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "jobs": response_data.get('jobs', []),
            "total": response_data.get('total', 0)
        }
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Abrufen der Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Jobs: {str(e)}",
            "jobs": [],
            "total": 0
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>/restart', methods=['POST'])
def api_event_monitor_job_restart(job_id: str):
    """
    API-Endpunkt zum Neustarten eines Jobs durch Zurücksetzen seines Status.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        
        # Request-Daten extrahieren (optional: batch_id)
        data = cast(Dict[str, Any], request.get_json() or {})
        batch_id: str = data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        # Korrigierter API-Pfad mit /api/ Präfix
        url = f"{base_url}/api/event-job/{job_id}/restart"
        
        # Debug-Ausgabe für die Problemdiagnose
        logger.debug(f"Sende Neustart-Anfrage an: {url}")
        
        # Führe die API-Anfrage durch
        response = requests.post(
            url, 
            json={'batch_id': batch_id},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Neustart API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich für den Neustart markiert"
        }
        
        if response_data.get('job'):
            result['job'] = response_data.get('job')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Neustarten des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Neustarten des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>/archive', methods=['POST'])
def api_event_monitor_job_archive(job_id: str):
    """
    API-Endpunkt zum Archivieren eines Jobs durch Änderung des Status.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        
        # Request-Daten extrahieren (optional: batch_id)
        data = cast(Dict[str, Any], request.get_json() or {})
        batch_id: str = data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        url = f"{base_url}/api/event-job/{job_id}/archive"
        
        # Führe die API-Anfrage durch
        response = requests.post(
            url, 
            json={'batch_id': batch_id},
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Archivierung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich archiviert"
        }
        
        if response_data.get('job'):
            result['job'] = response_data.get('job')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Archivieren des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Archivieren des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500


@main.route('/api/dashboard/event-monitor/jobs/<job_id>', methods=['DELETE'])
def api_event_monitor_job_delete(job_id: str):
    """
    API-Endpunkt zum Löschen eines Jobs.
    
    :param job_id: Die ID des Jobs, der gelöscht werden soll.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not job_id:
        logger.error("Keine job_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "job_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lösche Job mit job_id: {job_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Löschen eines Jobs
        url = f"{base_url}/api/event-job/jobs/{job_id}"
        
        logger.debug(f"Rufe API auf (DELETE): {url}")
        
        # Führe die Anfrage durch
        response = requests.delete(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Job-Löschung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Job {job_id} wurde erfolgreich gelöscht"
        }
        
        if response_data.get('message'):
            result['message'] = response_data.get('message')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Löschen des Jobs: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen des Jobs: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<batch_id>', methods=['DELETE'])
def api_event_monitor_batch_delete(batch_id: str):
    """
    API-Endpunkt zum Löschen eines Batches und aller zugehörigen Jobs.
    
    :param batch_id: Die ID des Batches, der gelöscht werden soll.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        logger.debug(f"Lösche Batch mit batch_id: {batch_id}")
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Löschen eines Batches
        url = f"{base_url}/api/event-job/batches/{batch_id}"
        
        logger.debug(f"Rufe API auf (DELETE): {url}")
        
        # Führe die Anfrage durch
        response = requests.delete(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Batch-Löschung API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor
        result = {
            "status": "success",
            "message": f"Batch {batch_id} wurde erfolgreich gelöscht"
        }
        
        if response_data.get('message'):
            result['message'] = response_data.get('message')
        
        logger.debug(f"Formatierte Antwort: {result}")
        
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Löschen des Batches: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Löschen des Batches: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/stats')
def api_event_monitor_batch_stats(batch_id: str):
    """
    API-Endpunkt zum Abrufen aktueller Statistiken eines Batches ohne Änderungen in der Datenbank.
    Dies ist nützlich für Live-Updates im Frontend ohne vollständige Seitenneuladen.
    
    :param batch_id: Die ID des Batches, dessen Statistiken abgerufen werden sollen.
    :return: JSON-Antwort mit den aktuellen Batch-Statistiken.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # Direkt das Repository für effizientere Abfragen verwenden
        job_repo: SessionJobRepository = get_job_repository()
        
        # Batch mit aktuellen Statistiken abrufen, ohne Status zu ändern
        batch = job_repo.get_batch_with_current_stats(batch_id)  # type: ignore
        
        if not batch:
            logger.error(f"Batch nicht gefunden: {batch_id}")
            return jsonify({
                "status": "error",
                "message": f"Batch mit ID {batch_id} nicht gefunden"
            }), 404
        
        # Erfolgsantwort zurückgeben
        return jsonify({
            "status": "success",
            "batch": batch.to_dict()  # type: ignore
        })
    
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Statistiken: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Statistiken: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/toggle-active', methods=['POST'])
def api_event_monitor_toggle_active(batch_id: str):
    """
    API-Endpunkt zum Umschalten des isActive-Status eines Batches.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Request-Daten (falls vorhanden) weitergeben
        data = cast(Dict[str, Any], request.get_json() if request.is_json else {})
        
        # API-Anfrage zur Umschaltung des isActive-Status
        # Verwende standardisierte Event-Job-API-URL
        url = f"{api_base_url}/api/event-job/batches/{batch_id}/toggle-active"
        logger.debug(f"Toggle-Active-Anfrage an: {url} mit Daten: {data}")
        response: requests.Response = requests.post(url, json=data)
        response.raise_for_status()
        
        # Antwort verarbeiten
        result = response.json()
        
        # Erfolgsantwort zurückgeben
        return jsonify(result)
    
    except requests.RequestException as e:
        logger.error(f"Fehler beim Umschalten des isActive-Status: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Umschalten des isActive-Status: {str(e)}"
        }), 500
    except Exception as e:
        logger.error(f"Unerwarteter Fehler: {str(e)}")
        return jsonify({
            "status": "error",
            "message": f"Unerwarteter Fehler: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/archive', methods=['POST'])
def api_event_monitor_batch_archive(batch_id: str):
    """
    API-Endpunkt zum Archivieren eines Batches.
    """
    try:
        # Konfiguration laden für API-Basis-URL
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Request-Daten (falls vorhanden) weitergeben oder Standarddaten verwenden
        data = cast(Dict[str, Any], request.get_json() if request.is_json else {})
        
        # Sicherstellen, dass die Mindestanforderungen erfüllt sind
        if 'batch_id' not in data:
            data['batch_id'] = batch_id
        if 'archived' not in data:
            data['archived'] = True
            
        logger.debug(f"Archiviere Batch {batch_id} mit Daten: {data}")
        
        # API-Anfrage zum Archivieren des Batches
        # Korrigierte URL-Konstruktion - prüfe, ob Basis-URL bereits den API-Pfad enthält
        url = f"{api_base_url}/api/event-job/batches/{batch_id}/archive"
            
        logger.debug(f"Batch-Archivierung-Anfrage an: {url}")
        
        # Initialisiere response als None
        response: Optional[requests.Response] = None
        
        try:
            response = requests.post(url, json=data)
            response.raise_for_status()
            
            # Antwort verarbeiten
            result = response.json()
            
            # Erfolgsantwort zurückgeben
            return jsonify(result)
            
        except requests.exceptions.HTTPError as http_err:
            error_message = f"HTTP-Fehler beim Archivieren des Batches: {http_err}"
            logger.error(error_message)
            
            # Versuche, Details aus der Antwort zu extrahieren, wenn response existiert
            if response is not None:
                try:
                    error_details = response.json()
                    logger.error(f"API-Fehlerdetails: {error_details}")
                    return jsonify({
                        "status": "error",
                        "message": error_message,
                        "details": error_details
                    }), response.status_code
                except Exception:
                    pass
                
                return jsonify({
                    "status": "error",
                    "message": error_message
                }), response.status_code
            
            # Standardantwort, wenn keine Antwort vom Server kam
            return jsonify({
                "status": "error",
                "message": error_message
            }), 500
            
    except Exception as e:
        logger.error(f"Fehler beim Archivieren des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/<string:batch_id>/restart', methods=['POST'])
def api_event_monitor_batch_restart(batch_id: str):
    """
    API-Endpunkt zum Neustarten aller Jobs in einem Batch.
    
    :param batch_id: Die ID des Batches, dessen Jobs neu gestartet werden sollen.
    :return: JSON-Antwort mit Erfolgsmeldung oder Fehlermeldung.
    """
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # Repository-Instanz holen
        job_repo = get_job_repository()
        
        # Alle Jobs des Batches auf einmal auf PENDING setzen
        result = job_repo.update_jobs_status_by_batch(batch_id, JobStatus.PENDING)
        
        if result > 0:
            # Erfolgsantwort zurückgeben
            return jsonify({
                "status": "success",
                "message": f"{result} Jobs wurden neu gestartet",
                "data": {
                    "restarted_jobs": result
                }
            })
        else:
            return jsonify({
                "status": "warning",
                "message": "Keine Jobs für diesen Batch gefunden",
                "data": {
                    "restarted_jobs": 0
                }
            }), 200
            
    except Exception as e:
        logger.error(f"Fehler beim Neustarten des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500

@main.route('/api/dashboard/event-monitor/batches/fail-all', methods=['POST'])
def api_event_monitor_fail_all_batches():
    """
    API-Endpunkt zum Setzen aller aktiven Batches auf failed.
    """
    try:
        # API-URL zusammenbauen
        api_url = f"{current_app.config['API_BASE_URL']}/event-job/batches/fail-all"
        
        # Headers vorbereiten
        headers = {
            'Content-Type': 'application/json'
        }
        
        # Benutzer-ID aus den Headern weiterleiten
        if 'X-User-ID' in request.headers:
            headers['X-User-ID'] = request.headers['X-User-ID']
        
        # API-Aufruf durchführen
        response = requests.post(api_url, headers=headers)
        response.raise_for_status()
        
        # Erfolgreiche Antwort
        return jsonify(response.json()), response.status_code
        
    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP-Fehler beim Setzen der Batches auf failed: {http_err}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), getattr(http_err.response, 'status_code', 500)
        
    except Exception as e:
        error_message = f"Fehler beim Setzen der Batches auf failed: {str(e)}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/force-fail-all', methods=['POST'])
def api_event_monitor_force_fail_all():
    """
    API-Endpunkt zum direkten Setzen ALLER Batches und Jobs auf failed.
    Dies ist eine direkte Datenbankoperation, die alle Batches und Jobs betrifft.
    """
    try:
        # Repository-Instanz holen
        job_repo = get_job_repository()
        now = datetime.now(timezone.utc)  # Verwende utcnow statt now(UTC)
        
        # Direkte Batch-Aktualisierung
        batch_result = job_repo.batches.update_many(
            {"archived": {"$ne": True}},  # Nicht archivierte Batches
            {
                "$set": {
                    "status": "failed",  # Kleinbuchstaben statt Großbuchstaben
                    "updated_at": now,
                    "completed_at": now
                }
            }
        )
        
        # Direkte Job-Aktualisierung für alle Jobs
        job_result = job_repo.jobs.update_many(
            {},  # Alle Jobs
            {
                "$set": {
                    "status": "failed",  # Kleinbuchstaben statt Großbuchstaben
                    "updated_at": now,
                    "completed_at": now,
                    "error": {
                        "code": "FORCED_FAILURE",
                        "message": "Job wurde manuell auf failed gesetzt",
                        "details": {
                            "forced_at": now.isoformat(),
                            "reason": "Manuelle Massenaktualisierung"
                        }
                    }
                }
            }
        )
        
        # Log die Änderungen
        logger.info(
            f"Force-fail-all ausgeführt",
            extra={
                "updated_batches": batch_result.modified_count,
                "updated_jobs": job_result.modified_count
            }
        )
        
        return jsonify({
            "status": "success",
            "message": f"{batch_result.modified_count} Batches und {job_result.modified_count} Jobs auf failed gesetzt",
            "data": {
                "updated_batches": batch_result.modified_count,
                "updated_jobs": job_result.modified_count
            }
        })
            
    except Exception as e:
        error_message = f"Fehler beim Setzen aller Batches und Jobs auf failed: {str(e)}"
        logger.error(error_message)
        return jsonify({
            "status": "error",
            "message": error_message
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/set-pending-all', methods=['POST'])
def api_event_monitor_set_pending_all():
    """
    Setzt alle nicht archivierten Batches und deren Jobs auf 'pending'.
    Parameter:
    - target_language: Die neue Zielsprache (z.B. 'de', 'en', etc.)
    """
    try:
        data = cast(Dict[str, Any], request.get_json() or {})
        target_language: Optional[str] = data.get('target_language')
        job_repository = get_job_repository()
        
        # Hole alle nicht archivierten Batches
        batches = job_repository.get_batches(archived=False)
        updated_batches = 0
        updated_jobs = 0
        
        # Aktualisiere jeden Batch und seine Jobs
        for batch in batches:
            # Aktualisiere Batch und alle zugehörigen Jobs auf PENDING
            if job_repository.update_batch_status(batch.batch_id, JobStatus.PENDING):
                updated_batches += 1
                
            # Aktualisiere alle Jobs des Batches
            jobs_updated = job_repository.update_jobs_status_by_batch(
                batch.batch_id, 
                JobStatus.PENDING,
                language=target_language
            )
            updated_jobs += jobs_updated
        
        logger.info(
            f"Alle Batches auf pending gesetzt",
            extra={
                "updated_batches": updated_batches,
                "updated_jobs": updated_jobs
            }
        )
        
        return jsonify({
            "status": "success",
            "message": f"{updated_batches} Batches und {updated_jobs} Jobs auf pending gesetzt",
            "data": {
                "batches_updated": updated_batches,
                "jobs_updated": updated_jobs
            }
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Setzen der Batches auf pending: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500 

@main.route('/api/dashboard/event-monitor/batches/change-language', methods=['POST'])
def api_event_monitor_change_language():
    """
    Ändert die Zielsprache für alle Jobs oder einen einzelnen Job im Event-Monitor.
    
    Parameter:
    - target_language: Die neue Zielsprache (z.B. 'de', 'en', etc.)
    - job_id: (Optional) Die ID eines einzelnen Jobs, dessen Sprache geändert werden soll
    - reset_status: (Optional) Ob der Status der Jobs auf 'pending' zurückgesetzt werden soll
    - current_batches_only: (Optional) Ob nur aktuelle (nicht archivierte) Batches betroffen sein sollen
    
    Returns:
        JSON mit Erfolgs- oder Fehlermeldung
    """
    logger = logging.getLogger(__name__)
    try:
        # Daten aus dem Request auslesen
        data = cast(Dict[str, Any], request.get_json() or {})
        
        target_language: Optional[str] = data.get('target_language')
        job_id = data.get('job_id')
        reset_status = data.get('reset_status', False)
        current_batches_only = data.get('current_batches_only', True)
        
        if not target_language:
            return jsonify({'status': 'error', 'message': 'Zielsprache (target_language) ist erforderlich'}), 400
        
        # Repository und weitere benötigte Objekte initialisieren
        job_repo = get_job_repository()
        success_count = 0
        
        # Bestimmen, ob ein einzelner Job oder mehrere Jobs aktualisiert werden sollen
        if job_id:
            # Einzelnen Job aktualisieren
            logger.info(f"Ändere Zielsprache für Job {job_id} auf {target_language}")
            
            job = job_repo.get_job(job_id)
            if not job:
                return jsonify({'status': 'error', 'message': f'Job mit ID {job_id} nicht gefunden'}), 404
            
            # Job-Parameter aktualisieren
            job_parameters = job.parameters.to_dict() if job.parameters else {}
            job_parameters['target_language'] = target_language
            
            # Status zurücksetzen, falls gewünscht
            if reset_status:
                job_repo.update_job_status(job_id, JobStatus.PENDING)
                
            # Job-Parameter aktualisieren
            job_repo.jobs.update_one(
                {"job_id": job_id},
                {"$set": {"parameters": job_parameters}}
            )
            success_count = 1
            
            logger.info(f"Zielsprache für Job {job_id} erfolgreich auf {target_language} geändert")
        else:
            # Alle Jobs in Batches aktualisieren
            logger.info(f"Ändere Zielsprache für alle Jobs auf {target_language}")
            
            # Batches abrufen (basierend auf dem 'current_batches_only' Parameter)
            batches: List[Batch] = job_repo.get_batches(archived=not current_batches_only)
            
            # Durch alle Batches iterieren und Jobs aktualisieren
            for batch in batches:
                batch_id = batch.batch_id
                logger.info(f"Verarbeite Batch {batch_id}")
                
                # Jobs für den aktuellen Batch abrufen
                jobs = job_repo.get_jobs_for_batch(batch_id, limit=1000)
                
                for job in jobs:
                    # Parameter aktualisieren
                    job_parameters = job.parameters.to_dict() if job.parameters else {}
                    job_parameters['target_language'] = target_language
                    
                    # Job-Parameter aktualisieren
                    job_repo.jobs.update_one(
                        {"job_id": job.job_id},
                        {"$set": {"parameters": job_parameters}}
                    )
                    success_count += 1
                
                # Status zurücksetzen, falls gewünscht
                if reset_status and jobs:
                    job_repo.update_batch_status(batch_id, JobStatus.PENDING)
                    job_repo.update_jobs_status_by_batch(batch_id, JobStatus.PENDING)
            
            logger.info(f"Zielsprache für {success_count} Jobs erfolgreich auf {target_language} geändert")
        
        # Erfolgreiche Antwort zurückgeben
        return jsonify({
            'status': 'success',
            'message': f'Zielsprache für {success_count} Job(s) erfolgreich auf {target_language} geändert',
            'data': {
                'updated_count': success_count,
                'target_language': target_language
            }
        })
        
    except Exception as e:
        logger.error(f"Fehler beim Ändern der Zielsprache: {str(e)}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Fehler beim Ändern der Zielsprache: {str(e)}'}), 500 
```

```yaml
site_name: Common Secretary Services
site_url: https://example.local
repo_url: https://example.local/repo
docs_dir: docs

theme:
  name: material
  language: de
  logo: assets/images/logo.png
  favicon: assets/images/logo.png

plugins:
  - search
  - redirects:
      redirect_maps:
        '01_architecture.md': 'explanations/architecture/overview.md'
        '02_installation.md': 'guide/getting-started/installation.md'
        '03_development.md': 'guide/getting-started/development.md'
        '05_webinterface.md': 'guide/ui/dashboard.md'
        '04_api.md': 'reference/api/overview.md'
        '06_audio_processing.md': 'processors/audio/overview.md'
        'HowToUseimageocr.md': 'processors/image-ocr/overview.md'
        'swagger_llm_ocr_integration.md': 'processors/image-ocr/overview.md'
        '07_youtube.md': 'processors/video/overview.md'

markdown_extensions:
  - admonition
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.superfences

nav:
  - « Zur Anwendung: /
  - Home: index.md
  - Guide:
    - Getting Started:
      - Installation: guide/getting-started/installation.md
      - Development: guide/getting-started/development.md
    - UI:
      - Dashboard: guide/ui/dashboard.md
    - How‑Tos:
      - Session‑Archive: guide/how-tos/session-archive.md
  - Explanations:
    - Architektur:
      - Überblick: explanations/architecture/overview.md
      - Details: explanations/architecture/details.md
    - Async Events:
      - Überblick: explanations/async-events/overview.md
      - n8n: explanations/async-events/how-to-n8n.md
    - Caching: explanations/caching/overview.md
    - Templates: explanations/templates/overview.md
    - Typen & Dataclasses: explanations/types/overview.md
    - Metaprocessor: explanations/metaprocessor/overview.md
    - Metadaten: explanations/metadata/overview.md
    - LLM‑Optimierung: explanations/llm/optimization.md
  - Processors:
    - Audio: processors/audio/overview.md
    - Video: processors/video/overview.md
    - PDF:
      - Überblick: processors/pdf/overview.md
      - OCR-Refactoring: processors/pdf/ocr-refactoring.md
      - PDF/ImageOCR Details: processors/pdf/endpoints.md
    - Image-OCR: processors/image-ocr/overview.md
    - Transformer: processors/transformer/overview.md
    - Session: processors/session/overview.md
    - Event-Job: processors/event-job/overview.md
    - Story: processors/story/overview.md
    - Track: processors/track/overview.md
  - Reference:
    - API Überblick: reference/api/overview.md
    - OpenAPI / Swagger: reference/api/openapi.md
  - Ops:
    - Deployment: ops/deployment.md
    - Sicherheit: ops/security.md
    - Troubleshooting: ops/troubleshooting.md
  - Analysis:
    - Doku-Inventur: _analysis/docs_inventory.md
    - Routes-Index: _analysis/routes_index.md
    - Drift-Audit: _analysis/drift_audit.md
  - Archiv (nur intern):
    - 01_architecture (alt): _archive/01_architecture.md
    - 02_installation (alt): _archive/02_installation.md
    - 03_development (alt): _archive/03_development.md
    - 04_api (alt): _archive/04_api.md
    - 05_webinterface (alt): _archive/05_webinterface.md
    - 06_audio_processing (alt): _archive/06_audio_processing.md
    - 07_youtube (alt): _archive/07_youtube.md
    - 07_async_event_processing (alt): _archive/07_async_event_processing.md
    - 07_async_event_processing_implementation (alt): _archive/07_async_event_processing_implementation.md
    - 08_templates (alt): _archive/08_templates.md
    - template_content_feature (alt): _archive/template_content_feature.md
    - 09_security (alt): _archive/09_security.md
    - 10_development_guidelines (alt): _archive/10_development_guidelines.md
    - 11_security (alt): _archive/11_security.md
    - 11_deployment (alt): _archive/11_deployment.md
    - 12_troubleshooting (alt): _archive/12_troubleshooting.md
    - 13_api_reference (alt): _archive/13_api_reference.md
    - 13_changelog (alt): _archive/13_changelog.md
    - 14_changelog (alt): _archive/14_changelog.md
    - 15_faq (alt): _archive/15_faq.md
    - 15_support (alt): _archive/15_support.md
    - CommonSecretaryServicesAPI (alt): _archive/CommonSecretaryServicesAPI.md
    - HowToUseimageocr (alt): _archive/HowToUseimageocr.md
    - swagger_llm_ocr_integration (alt): _archive/swagger_llm_ocr_integration.md
    - vimeo_support (alt): _archive/vimeo_support.md
    - api-responses-concept (alt): _archive/api-responses-concept.md
    - concept_storytelling_processor (alt): _archive/concept_storytelling_processor.md
    - dataclasses-types (alt): _archive/dataclasses-types.md
    - events (alt): _archive/events.md
    - generic_typing_improvements (alt): _archive/generic_typing_improvements.md
    - historie: _archive/historie/
    - linting_strategy (alt): _archive/linting_strategy.md
    - llm_ocr_configuration (alt): _archive/llm_ocr_configuration.md
    - llm_ocr_integration (alt): _archive/llm_ocr_integration.md
    - llm-optimierung (alt): _archive/llm-optimierung.md
    - localbrain_architecture (alt): _archive/localbrain_architecture.md
    - metadata-concept (alt): _archive/metadata-concept.md
    - metaprocessor-* (alt): _archive/metaprocessor-concept.md
    - mongodb_caching_implementation (alt): _archive/mongodb_caching_implementation.md
    - n8nEventsProcessing (alt): _archive/n8nEventsProcessing.md
    - optimizeProzessWithBaseprocess (alt): _archive/optimizeProzessWithBaseprocess.md
    - process_events (alt): _archive/process_events.md
    - process-events-mongo-db (alt): _archive/process-events-mongo-db.md
    - ProcessorArchitecture (alt): _archive/ProcessorArchitecture.md
    - refact-metaprocessor (alt): _archive/refact-metaprocessor.md
    - scrape-notion (alt): _archive/scrape-notion.md
    - session_archive_usage (alt): _archive/session_archive_usage.md
    - storytelling (alt): _archive/storytelling.md
    - template_content_feature (alt): _archive/template_content_feature.md
    - testroutine (alt): _archive/testroutine.md
    - track_processor (alt): _archive/track_processor.md
    - track-processor-api (alt): _archive/track-processor-api.md
    - transformer_mongodb_caching (alt): _archive/transformer_mongodb_caching.md
    - type-migration (alt): _archive/type-migration.md
    - videoprocessor_typisierung (alt): _archive/videoprocessor_typisierung.md
    - youtubeprocessor_typisierung (alt): _archive/youtubeprocessor_typisierung.md

```

```markdown
> Zur Anwendung zurück: [/](\/)

---
status: draft
last_verified: 2025-08-15
---

# Common Secretary Services

Willkommen zur Dokumentation. Dieses Projekt verarbeitet Medien (Audio, Video, PDF/Bilder) und erzeugt strukturierte Ergebnisse (Markdown/JSON) über eine REST‑API mit Flask‑RESTX.

## Schnellstart
```powershell
# Windows
venv\Scripts\activate
$env:PYTHONPATH = "."
python src/main.py
```
- Swagger UI: `http://127.0.0.1:5000/api/doc`
- OpenAPI JSON: `http://127.0.0.1:5000/api/swagger.json`

## Bereiche
- Guide
  - Getting Started → [Installation](guide/getting-started/installation.md), [Development](guide/getting-started/development.md)
  - How‑Tos → [Session‑Archive](guide/how-tos/session-archive.md)
  - UI → [Dashboard](guide/ui/dashboard.md)
- Explanations
  - Architektur → [Überblick](explanations/architecture/overview.md), [Details](explanations/architecture/details.md)
  - Async Events → [Überblick](explanations/async-events/overview.md), [n8n How‑To](explanations/async-events/how-to-n8n.md)
  - Caching → [Übersicht](explanations/caching/overview.md)
  - Templates → [Übersicht](explanations/templates/overview.md)
  - Typen → [Übersicht](explanations/types/overview.md)
  - Metaprocessor → [Überblick](explanations/metaprocessor/overview.md)
  - Metadaten → [Überblick](explanations/metadata/overview.md)
  - LLM → [Optimierung](explanations/llm/optimization.md)
- Processors
  - Audio → [Overview](processors/audio/overview.md)
  - Video → [Overview](processors/video/overview.md)
  - PDF → [Overview](processors/pdf/overview.md), [OCR‑Refactoring](processors/pdf/ocr-refactoring.md), [Endpoints](processors/pdf/endpoints.md)
  - Image‑OCR → [Overview](processors/image-ocr/overview.md)
  - Transformer → [Overview](processors/transformer/overview.md)
  - Session → [Overview](processors/session/overview.md)
  - Event‑Job → [Overview](processors/event-job/overview.md)
  - Story → [Overview](processors/story/overview.md)
  - Track → [Overview](processors/track/overview.md)
- Reference
  - API → [Überblick](reference/api/overview.md), [OpenAPI](reference/api/openapi.md)
- Ops → [Deployment](ops/deployment.md), [Sicherheit](ops/security.md), [Troubleshooting](ops/troubleshooting.md)
- Analysis → [Inventur](
  _analysis/docs_inventory.md), [Routes‑Index](_analysis/routes_index.md), [Drift‑Audit](_analysis/drift_audit.md)

## Response‑Standard (Kurz)
- `status` (success/error), `request`, `process`, `data`, `error`
- LLM‑Tracking: `process.llm_info`, Zeit in Millisekunden

Viel Erfolg!

```

Gut, wir entfernen die iframe-Variante (doppelte Scrollbar) und lassen MkDocs wieder nativ laufen. Dafür habe ich:

- Navbar „Docs“ wieder auf `/docs/` gesetzt.
- iframe-Route entfernt.
- In `mkdocs.yml` einen Top-Menüpunkt „« Zur Anwendung“ hinzugefügt, der auf `/` verweist.
- Zusätzlich auf der `docs/index.md` oben einen Rück-Link eingefügt.

Bitte einmal `mkdocs build -c -d site` ausführen, dann:
- App öffnen: `http://127.0.0.1:5001/`
- Doku: `http://127.0.0.1:5001/docs/`
- Rücksprung zur App über den neuen Link im MkDocs-Menü oder direkt oben auf der Startseite der Doku.

Kurz:
- Keine doppelte Scrollbar mehr.
- Persistenter Rückweg zur Anwendung in der Doku-Navigation.

