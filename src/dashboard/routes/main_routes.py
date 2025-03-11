"""
Main routes for the dashboard application.
Contains the main dashboard view and test routes.
"""
from flask import Blueprint, render_template, jsonify, request, redirect, url_for
from datetime import datetime, timedelta
import json
import os
import re
from typing import Any, Dict, List, cast, Optional

from core.config import ApplicationConfig
from utils.logger import ProcessingLogger
from ..utils import get_system_info
from pathlib import Path
import yaml
from src.core.config import Config
from src.utils.logger import get_logger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test
import requests  # Neu hinzugefügt für API-Anfragen
import markdown  # type: ignore
from src.core.mongodb.repository import EventJobRepository
from src.core.mongodb import get_job_repository

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
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            logger.warning("Performance data is empty")
            return render_template('dashboard.html', stats=stats, system_info=get_system_info())
            
        # Calculate time window
        now = datetime.now()
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
        now = datetime.now()
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
    # Extrahiere batch_id aus den Query-Parametern
    batch_id = request.args.get('batch_id')
    
    if not batch_id:
        logger.error("Keine batch_id in der Anfrage")
        return jsonify({
            "status": "error",
            "message": "batch_id ist ein erforderlicher Parameter"
        }), 400
    
    try:
        # API-Basis-URL aus der Konfiguration laden
        config = Config()
        # DEBUG: Ausgabe der API-Response
        logger.debug(f"Lade Jobs für batch_id: {batch_id}")
        
        # Verwende die generische get-Methode anstelle einer nicht existierenden get_api_base_url-Methode
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für Jobs für einen bestimmten Batch
        url = f"{base_url}/api/event-job/jobs?batch_id={batch_id}"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
        response = requests.get(url)
        response.raise_for_status()
        
        # Verarbeite die Antwort
        response_data = response.json()
        
        logger.info(f"Jobs API-Antwort erhalten: {response_data}")
        
        # Bereite die Antwort vor - direkte Struktur ohne Wrapping in 'data'
        # Dies passt besser zur erwarteten Verarbeitungslogik im Template
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
        request_data: Dict[str, Any] = request.get_json() or {}
        batch_id: str = request_data.get('batch_id', '')
        
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
        request_data: Dict[str, Any] = request.get_json() or {}
        batch_id: str = request_data.get('batch_id', '')
        
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
        job_repo: EventJobRepository = get_job_repository()
        
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
        data: Dict[str, Any] = request.get_json() if request.is_json else {}
        
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
        data: Dict[str, Any] = request.get_json() if request.is_json else {}
        
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
    API-Endpunkt zum Neustarten aller Jobs in einem Batch, außer completed Jobs.
    
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
        # Alle Jobs für diesen Batch abrufen
        config = Config()
        api_base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        # Jobs für diesen Batch abfragen
        url = f"{api_base_url}/api/dashboard/event-monitor/jobs?batch_id={batch_id}"
        jobs_response: requests.Response = requests.get(url)
        jobs_response.raise_for_status()
        
        jobs_data = jobs_response.json()
        jobs: List[Dict[str, Any]] = []
        
        if 'data' in jobs_data and 'jobs' in jobs_data['data']:
            jobs = jobs_data['data']['jobs']
        elif 'jobs' in jobs_data:
            jobs = jobs_data['jobs']
        
        if not jobs:
            return jsonify({
                "status": "warning",
                "message": "Keine Jobs für diesen Batch gefunden"
            }), 200
        
        # Alle Jobs außer completed neu starten
        results: List[Dict[str, Any]] = []
        success_count = 0
        restartable_jobs_count = 0
        
        for job in jobs:
            job_id = job.get('job_id')
            job_status = job.get('status')
            
            # Nur Jobs neu starten, die nicht completed sind
            if not job_id or job_status == "completed":
                if job_id and job_status == "completed":
                    results.append({
                        "job_id": job_id,
                        "status": "skipped",
                        "message": "Job ist bereits abgeschlossen"
                    })
                continue
                
            restartable_jobs_count += 1
            
            # Direkter Aufruf der Event-Job-API statt rekursivem Dashboard-API-Aufruf
            restart_url = f"{api_base_url}/api/event-job/{job_id}/restart"
            logger.debug(f"Neustart für Job {job_id} (Status: {job_status}) an {restart_url}")
            restart_response: requests.Response = requests.post(restart_url, json={"batch_id": batch_id})
            
            logger.debug(f"Neustart für Job {job_id} an {restart_url}: Status {restart_response.status_code}")
            
            if restart_response.status_code == 200:
                success_count += 1
                results.append({
                    "job_id": job_id,
                    "status": "success",
                    "previous_status": job_status
                })
            else:
                results.append({
                    "job_id": job_id,
                    "status": "error",
                    "message": f"Fehler: Status {restart_response.status_code}",
                    "previous_status": job_status
                })
        
        # Erfolgsantwort zurückgeben
        if restartable_jobs_count == 0:
            return jsonify({
                "status": "warning",
                "message": "Keine neu startbaren Jobs in diesem Batch gefunden (alle sind completed)",
                "data": {
                    "results": results
                }
            })
        else:
            return jsonify({
                "status": "success",
                "message": f"{success_count} von {restartable_jobs_count} Jobs wurden neu gestartet",
                "data": {
                    "results": results
                }
            })
    except Exception as e:
        logger.error(f"Fehler beim Neustarten des Batches {batch_id}: {e}")
        return jsonify({
            "status": "error",
            "message": f"Fehler: {str(e)}"
        }), 500 