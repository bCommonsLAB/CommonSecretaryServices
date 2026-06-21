"""
@fileoverview Main Routes - Dashboard routes for main application views

@description
Main routes for the dashboard application. This module provides the primary web
routes for the dashboard, including the main dashboard view, log viewing,
test endpoints, and system monitoring.

Main functionality:
- Main dashboard view with statistics overview
- Test endpoints for processors
- Log viewing and clearing
- Recent-requests API for live dashboard updates

Features:
- Real-time request statistics from MongoDB
- Processor test endpoints (audio, video, transformer, YouTube, health)
- Log aggregation
- Markdown rendering support

@module dashboard.routes.main_routes

@exports
- main: Blueprint - Flask blueprint for main routes

@usedIn
- src.dashboard.app: Registers main blueprint

@dependencies
- External: flask - Flask web framework
- External: markdown - Markdown to HTML conversion
- Internal: src.core.config - Config for configuration access
- Internal: src.utils.logger - Logging system
"""
from flask import Blueprint, render_template, jsonify, redirect, url_for
from typing import Any
from src.core.config import ApplicationConfig
from src.utils.logger import ProcessingLogger
from ..utils import get_system_info
from pathlib import Path
from src.core.config import Config
from src.utils.logger import get_logger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test
import markdown  # type: ignore

# Create the blueprint
main = Blueprint('main', __name__)
logger: ProcessingLogger = get_logger(process_id="dashboard")

# Funktion zur Markdown-Konvertierung
def render_markdown(text: str) -> str:
    """Konvertiert Markdown-Text in HTML"""
    return markdown.markdown(text)

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
        # Kennzahlen kommen aus MongoDB (RequestMetricsRepository, Variante B).
        # Die frühere Implementierung las/parste logs/performance.json, das im
        # Normalbetrieb nie befüllt wurde (complete_tracking() ohne Aufrufer).
        from src.core.mongodb import get_metrics_repository
        stats = get_metrics_repository().get_stats(hours=24, recent_limit=10)
    except Exception as e:
        logger.error(f"Fehler beim Laden der Dashboard-Statistiken: {str(e)}", exc_info=True)
        stats['error'] = str(e)
    
    return render_template('dashboard.html', 
                         stats=stats,
                         system_info=get_system_info())

# Hinweis: Das frühere YAML-Konfigurations-Modul (Web-Editor für config.yaml)
# wurde entfernt. Die config.yaml wird in der Entwicklungsumgebung gepflegt und
# per Docker publiziert – sie wird bewusst nicht mehr über das Frontend bearbeitet.

@main.route('/health')
def health_dashboard():
    """
    Zeigt die LLM-Health-Check-Seite an.

    Die Seite lädt ihre Daten clientseitig über GET /api/health/ (siehe
    health.html). Sie wurde aus der Startseite (dashboard.html) in einen
    eigenen Menüpunkt ausgelagert, um die Startseite schlank zu halten.

    Returns:
        rendered template: Die health.html Template
    """
    return render_template('health.html')

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
        # Letzte Requests aus MongoDB (RequestMetricsRepository, Variante B).
        from src.core.mongodb import get_metrics_repository
        recent_requests = get_metrics_repository().get_recent(limit=10)
        
        # Render only the requests list part
        html = render_template('_recent_requests.html', 
                             recent_requests=recent_requests)
        
        return jsonify({'html': html})
        
    except Exception as e:
        logger.error(f"Error getting recent requests: {str(e)}", exc_info=True)
        return jsonify({'html': f'<div class="text-danger">Fehler beim Laden: {str(e)}</div>'}) 

## Entfernt: iframe-basierte Docs-Ansicht, um doppelte Scrollbars zu vermeiden

# Hinweis: Die frühere "Event-Monitor"-Logik (Dashboard-Seite + alle
# /api/dashboard/event-monitor/*-Proxy-Routen) wurde als veraltet entfernt.
# Die zugrunde liegende /api/event-job-API wurde ebenfalls entfernt.
