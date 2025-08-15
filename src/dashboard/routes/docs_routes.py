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


