"""
@fileoverview Documentation Routes - Dashboard routes for serving MkDocs-generated documentation

@description
Documentation routes for serving the MkDocs-generated static site from the unified
Flask app. This blueprint serves the contents of the built MkDocs directory (`site/`)
under the `/docs` path, allowing the application and documentation to be served
from a single process/container (unified deployment unit).

Main functionality:
- Serve static documentation files from `site/` directory
- Handle documentation routes and redirects
- Serve index pages and static assets
- Fallback handling for missing files

Features:
- Unified deployment (app + docs in one container)
- Static file serving from MkDocs build output
- Automatic index page handling
- Redirect handling for canonical URLs

Note:
- Expects `site/` directory to exist in project root (as created by `mkdocs build`)
- In local development, docs can run with `mkdocs serve`
- In production, static site should be included in deployment

@module dashboard.routes.docs_routes

@exports
- docs: Blueprint - Flask blueprint for documentation routes

@usedIn
- src.dashboard.app: Registers docs blueprint

@dependencies
- External: flask - Flask web framework
- Standard: pathlib - Path handling
"""

from pathlib import Path
from typing import Optional

from flask import Blueprint, abort, send_from_directory, redirect, render_template_string


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
    # Prüfe, ob das site-Verzeichnis existiert
    if not SITE_DIR.exists():
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Documentation Not Available</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
                h1 { color: #d32f2f; }
                code { background: #f5f5f5; padding: 2px 6px; border-radius: 3px; }
                pre { background: #f5f5f5; padding: 15px; border-radius: 5px; overflow-x: auto; }
            </style>
        </head>
        <body>
            <h1>Documentation Not Available</h1>
            <p>The documentation site has not been built yet.</p>
            <p>To build the documentation, run:</p>
            <pre><code>mkdocs build</code></pre>
            <p>This will create the <code>site/</code> directory with the static documentation files.</p>
            <p>Alternatively, for local development, you can run:</p>
            <pre><code>mkdocs serve</code></pre>
            <p>This will start a local development server at <code>http://127.0.0.1:8000</code></p>
        </body>
        </html>
        """), 503
    
    if _site_path_exists("index.html"):
        return send_from_directory(str(SITE_DIR), "index.html")

    # Fallback: auf die erste Sektion mit index.html weiterleiten
    try:
        for entry in SITE_DIR.iterdir():
            if entry.is_dir() and (entry / "index.html").exists():
                return redirect(f"/docs/{entry.name}/", code=302)
    except (OSError, PermissionError) as e:
        return render_template_string("""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Documentation Error</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
                h1 { color: #d32f2f; }
            </style>
        </head>
        <body>
            <h1>Documentation Error</h1>
            <p>Error accessing documentation directory: {{ error }}</p>
        </body>
        </html>
        """, error=str(e)), 500

    abort(404)


@docs.route("/docs/<path:filename>")
def docs_files(filename: str):
    """Liefert beliebige Dateien aus `site/` unterhalb von `/docs` aus.

    Unterstützt auch Verzeichnis-URLs, indem automatisch auf `index.html`
    innerhalb des Zielverzeichnisses zurückgegriffen wird.
    """
    # Prüfe, ob das site-Verzeichnis existiert
    if not SITE_DIR.exists():
        abort(503)
    
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


