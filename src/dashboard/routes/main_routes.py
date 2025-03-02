"""
Main routes for the dashboard application.
Contains the main dashboard view and test routes.
"""
from flask import Blueprint, render_template, jsonify, request, make_response, redirect, url_for
from datetime import datetime, timedelta
import json
import os
import re
from ..utils import get_system_info
from pathlib import Path
import yaml
from src.core.config import Config
from src.utils.logger import get_logger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test
import ast
import asyncio
import requests  # Neu hinzugefügt für API-Anfragen

# Create the blueprint
main = Blueprint('main', __name__)
logger = get_logger(process_id="dashboard")

def load_logs_for_requests(recent_requests):
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
    request_logs = {}
    
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
                                current_entry['details'] = json.loads(details_text)
                            except json.JSONDecodeError:
                                current_entry['details'] = {'raw': '\n'.join(details_lines)}
                        
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
                        current_entry['details'] = json.loads(details_text)
                    except json.JSONDecodeError:
                        current_entry['details'] = {'raw': '\n'.join(details_lines)}
                
                # Add to request logs if process_id matches
                if current_entry['process_id'] in request_logs:
                    request_logs[current_entry['process_id']].append(current_entry)
                    
    except Exception as e:
        print(f"Error reading log file: {e}")
    
    return request_logs

@main.route('/')
def home():
    """
    Home page with dashboard overview
    
    This function:
    1. Loads performance data from the last 24 hours
    2. Calculates statistics (total requests, average duration, success rate)
    3. Aggregates operation statistics
    4. Creates hourly statistics
    5. Processes the most recent requests with their details
    6. Loads associated logs for each request
    
    Returns:
        rendered template: The dashboard.html template with statistics and system information
    """
    # Initialize statistics
    stats = {
        'total_requests': 0,
        'avg_duration': 0.0,
        'success_rate': 0.0,
        'hourly_tokens': 0,
        'operations': {},
        'hourly_stats': {},
        'recent_requests': [],
        'processor_stats': {}
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
        recent_requests = []
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
                    stats['operations'][op_name] = stats['operations'].get(op_name, 0) + 1
            
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
            hour_counts = {}
            for r in recent_requests:
                try:
                    hour = datetime.strptime(r['timestamp'], '%Y-%m-%d %H:%M:%S').strftime('%H:00')
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                except ValueError as e:
                    logger.error(f"Error processing hour statistics: {e}")
                    continue
            
            # Sort hours and create final hourly stats
            sorted_hours = sorted(hour_counts.keys())
            stats['hourly_stats'] = {hour: hour_counts[hour] for hour in sorted_hours}
            
            # Process recent requests (last 10)
            recent_requests = sorted(recent_requests, 
                                  key=lambda x: x['timestamp'],
                                  reverse=True)[:10]
            
            # Add logs to recent requests
            request_logs = load_logs_for_requests(recent_requests)
            for request in recent_requests:
                process_id = request.get('process_id')
                request['logs'] = request_logs.get(process_id, [])
                
                # Get the main operation
                main_op = next((op for op in request.get('operations', []) 
                              if op.get('name') == request.get('operation')), {})
                
                # Get the processor data
                processor_name = main_op.get('processor', '')
                processor_data = request.get('processors', {}).get(processor_name, {})
                
                # Prepare the main process data
                request['main_process'] = {
                    'timestamp': request['timestamp'],
                    'duration_seconds': float(request.get('total_duration', 0)),
                    'operation': main_op.get('name', ''),
                    'processor': processor_name,
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
                    config.set_api_key(api_key)
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
        logger.error("Fehler beim Speichern der Konfiguration", error=str(e))
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
        logger.error("Fehler beim Laden der Konfiguration", error=str(e))
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
        config_data = config.get_all()
        
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
    API endpoint to get the latest requests for auto-refresh
    """
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        
        if not os.path.exists(perf_path):
            return jsonify({'html': '<div class="text-muted">Keine Daten verfügbar</div>'})
            
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        if not perf_data:
            return jsonify({'html': '<div class="text-muted">Keine Anfragen vorhanden</div>'})
            
        # Calculate time window (last 24 hours)
        now = datetime.now()
        day_ago = now - timedelta(days=1)
        
        # Filter and process recent requests
        recent_requests = []
        for r in perf_data:
            try:
                timestamp = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
                if timestamp > day_ago:
                    r['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Check if request is still running (no end_time in operations)
                    operations = r.get('operations', [])
                    if operations:
                        last_op = operations[-1]
                        if 'end_time' not in last_op:
                            r['status'] = 'running'
                            # Calculate current duration
                            start_time = datetime.fromisoformat(last_op['start_time'].replace('Z', '+00:00'))
                            r['total_duration'] = (now - start_time).total_seconds()
                    
                    recent_requests.append(r)
            except (ValueError, KeyError) as e:
                logger.error(f"Error processing request timestamp: {e}")
                continue
        
        # Sort by timestamp (newest first) and take last 10
        recent_requests = sorted(recent_requests, 
                               key=lambda x: x['timestamp'],
                               reverse=True)[:10]
        
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
        api_base_url = request.url_root.rstrip('/') + '/api/event-job'
        
        # Filterparameter aus dem Request
        status_filter = request.args.get('status', '')
        date_filter = request.args.get('date', '')
        
        # Aktuelle (nicht-archivierte) Batches abrufen
        current_batches_url = f"{api_base_url}/batches?archived=false"
        if status_filter:
            current_batches_url += f"&status={status_filter}"
        
        # Da wir im Backend sind, können wir direkt HTTP-Requests senden oder
        # alternativ die Repository-Funktionen direkt aufrufen
        try:
            # HTTP-Request für aktuelle Batches
            current_batches_response = requests.get(current_batches_url)
            current_batches_response.raise_for_status()
            current_batches_data = current_batches_response.json()
            
            # Optional: Auch alle Jobs für diese Batches laden
            jobs_data = {}
            # Anpassen an die tatsächliche API-Struktur (batches anstatt data.batches)
            for batch in current_batches_data.get('batches', []):
                batch_id = batch.get('batch_id')
                if batch_id:
                    jobs_url = f"{api_base_url}/jobs?batch_id={batch_id}"
                    jobs_response = requests.get(jobs_url)
                    if jobs_response.status_code == 200:
                        # API-Antwort im Format: {"status": "success", "jobs": [...], "total": X}
                        # oder: {"status": "success", "data": {"jobs": [...], "total": X}}
                        response_data = jobs_response.json()
                        if 'data' in response_data and 'jobs' in response_data['data']:
                            jobs_data[batch_id] = response_data['data']['jobs']
                        else:
                            jobs_data[batch_id] = response_data.get('jobs', [])
            
        except requests.RequestException as e:
            logger.error(f"Fehler beim Abrufen der aktuellen Batch-Daten: {str(e)}")
            current_batches_data = {"batches": [], "total": 0}
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
    API-Endpunkt zum Abrufen von Batch-Daten für das Event-Monitoring.
    Dieser Endpunkt dient als Proxy für den API-Endpunkt /api/event-job/batches.
    """
    try:
        # Basis-URL für API-Anfragen
        api_base_url = request.url_root.rstrip('/') + '/api/event-job'
        
        # Parameter aus dem Request übernehmen
        params = {k: v for k, v in request.args.items()}
        
        # Unterstützung für archived-Parameter hinzufügen
        archived = request.args.get('archived')
        if archived is not None:
            # Archived in booleschen Wert umwandeln
            archived_bool = archived.lower() in ('true', '1', 'yes')
            params['archived'] = str(archived_bool).lower()
        
        # Wenn es einen status-Parameter gibt, der Kommas enthält, müssen wir
        # mehrere Anfragen senden und die Ergebnisse zusammenführen
        if 'status' in params and ',' in params['status']:
            status_list = params['status'].split(',')
            del params['status']  # Status aus den Parametern entfernen
            
            # Liste für die zusammengeführten Batches
            all_batches = []
            total_count = 0
            
            # Für jeden Status-Wert eine separate Anfrage senden
            for status in status_list:
                # Parameter mit aktuellem Status erstellen
                current_params = params.copy()
                current_params['status'] = status
                
                # Batches für diesen Status abrufen
                batches_url = f"{api_base_url}/batches"
                if current_params:
                    query_string = '&'.join([f"{k}={v}" for k, v in current_params.items()])
                    batches_url += f"?{query_string}"
                
                try:
                    batches_response = requests.get(batches_url)
                    batches_response.raise_for_status()
                    batches_data = batches_response.json()
                    
                    # Batches zur Gesamtliste hinzufügen
                    if batches_data.get('status') == 'success':
                        all_batches.extend(batches_data.get('batches', []))
                        total_count += batches_data.get('total', 0)
                except Exception as e:
                    logger.warning(f"Fehler beim Abrufen der Batches für Status {status}: {str(e)}")
                    # Fehler für einzelne Status ignorieren und mit dem nächsten fortfahren
                    continue
            
            # Sortieren der zusammengeführten Batches nach created_at (neueste zuerst)
            all_batches.sort(key=lambda x: x.get('created_at', ''), reverse=True)
            
            # Limit anwenden, falls vorhanden
            limit = int(params.get('limit', 100))
            all_batches = all_batches[:limit]
            
            # Erfolgsantwort zurückgeben - in dem Format, das vom Template erwartet wird
            return jsonify({
                "status": "success",
                "data": {
                    "batches": all_batches,
                    "total": total_count
                }
            })
        else:
            # Normale Anfrage für einen einzelnen Status
            batches_url = f"{api_base_url}/batches"
            if params:
                query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
                batches_url += f"?{query_string}"
            
            batches_response = requests.get(batches_url)
            batches_response.raise_for_status()
            batches_data = batches_response.json()
            
            # Format an das erwartete Template-Format anpassen
            return jsonify({
                "status": "success",
                "data": {
                    "batches": batches_data.get('batches', []),
                    "total": batches_data.get('total', 0)
                }
            })
        
    except Exception as e:
        logger.error(f"Fehler beim Abrufen der Batch-Daten: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler beim Abrufen der Batch-Daten: {str(e)}",
            "data": {"batches": [], "total": 0}
        }), 500

@main.route('/api/dashboard/event-monitor/job/<job_id>')
def api_event_monitor_job_detail(job_id):
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
def api_event_monitor_job_restart(job_id):
    """
    API-Endpunkt zum Neustarten eines Jobs durch Zurücksetzen seines Status.
    
    :param job_id: Die ID des Jobs, der neu gestartet werden soll.
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
        logger.debug(f"Starte Job neu mit job_id: {job_id}")
        
        # Request-Daten extrahieren (optional: batch_id)
        request_data = request.get_json() or {}
        batch_id = request_data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für den Neustart eines Jobs
        url = f"{base_url}/api/event-job/{job_id}/restart"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
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
def api_event_monitor_job_archive(job_id):
    """
    API-Endpunkt zum Archivieren eines Jobs durch Änderung des Status.
    
    :param job_id: Die ID des Jobs, der archiviert werden soll.
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
        logger.debug(f"Archiviere Job mit job_id: {job_id}")
        
        # Request-Daten extrahieren (optional: batch_id)
        request_data = request.get_json() or {}
        batch_id = request_data.get('batch_id', '')
        
        # Verwende die generische get-Methode für die API-Basis-URL
        base_url = config.get('server.api_base_url', 'http://localhost:5001')
        
        if not base_url:
            logger.error("Keine API-Basis-URL konfiguriert")
            return jsonify({
                "status": "error",
                "message": "API-Basis-URL nicht konfiguriert"
            }), 500
        
        # Erstelle die Anfrage-URL für das Archivieren eines Jobs
        url = f"{base_url}/api/event-job/{job_id}/archive"
        
        logger.debug(f"Rufe API auf: {url}")
        
        # Führe die Anfrage durch
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

@main.route('/api/dashboard/event-monitor/job-repository-test')
def api_event_monitor_job_repository_test():
    """
    Testroutine zum Analysieren der EventJobRepository-Klasse.
    Listet verfügbare Methoden auf und versucht, Jobs zu aktualisieren.
    
    Returns:
        JSON-Antwort mit Informationen über die Repository-Methoden
    """
    try:
        # Job-Repository initialisieren
        from src.core.mongodb import get_job_repository
        from core.mongodb.repository import EventJobRepository
        import inspect
        
        job_repo = get_job_repository()
        
        # Ergebnisse sammeln
        results = {
            "status": "success",
            "repository_class": str(job_repo.__class__),
            "available_methods": [],
            "methods_details": {},
            "update_methods": []
        }
        
        # Alle Methoden auflisten
        all_methods = [method for method in dir(job_repo) 
                      if not method.startswith('_') and callable(getattr(job_repo, method))]
        results["available_methods"] = all_methods
        
        # Methoden mit "update" im Namen finden
        update_methods = [method for method in all_methods if "update" in method]
        results["update_methods"] = update_methods
        
        # Details zu den Update-Methoden sammeln
        for method_name in update_methods:
            method = getattr(job_repo, method_name)
            try:
                signature = str(inspect.signature(method))
                doc = inspect.getdoc(method) or "Keine Dokumentation"
                results["methods_details"][method_name] = {
                    "signature": signature,
                    "doc": doc
                }
            except Exception as method_error:
                results["methods_details"][method_name] = {
                    "error": str(method_error)
                }
        
        # Superklassen und deren Methoden
        try:
            repo_class = job_repo.__class__
            bases = repo_class.__bases__
            results["class_hierarchy"] = {
                "class": repo_class.__name__,
                "bases": [base.__name__ for base in bases],
                "base_methods": {}
            }
            
            for base in bases:
                base_methods = [method for method in dir(base) 
                              if not method.startswith('_') and callable(getattr(base, method))]
                results["class_hierarchy"]["base_methods"][base.__name__] = base_methods
        except Exception as hierarchy_error:
            results["class_hierarchy_error"] = str(hierarchy_error)
        
        # Versuch, einen Job zu aktualisieren (falls Job-ID verfügbar)
        job_id_param = request.args.get('job_id')
        if job_id_param:
            try:
                # Prüfe, ob der Job existiert
                job = job_repo.get_job(job_id_param)
                if job:
                    results["test_job"] = {
                        "job_id": job_id_param,
                        "current_status": job.status,
                        "update_attempts": {}
                    }
                    
                    # Versuche verschiedene Update-Methoden
                    for method_name in update_methods:
                        try:
                            method = getattr(job_repo, method_name)
                            # Verschiedene Aufrufe versuchen (abhängig von der Signatur)
                            if method_name == "update_job_status":
                                method_result = method(job_id_param, "pending")
                                results["test_job"]["update_attempts"][method_name] = {
                                    "success": True,
                                    "result": str(method_result)
                                }
                            elif method_name == "set_job_status":
                                method_result = method(job_id_param, "pending")
                                results["test_job"]["update_attempts"][method_name] = {
                                    "success": True,
                                    "result": str(method_result)
                                }
                            elif method_name == "reset_job":
                                method_result = method(job_id_param)
                                results["test_job"]["update_attempts"][method_name] = {
                                    "success": True,
                                    "result": str(method_result)
                                }
                            else:
                                results["test_job"]["update_attempts"][method_name] = {
                                    "skipped": "Unbekannte Methodensignatur"
                                }
                        except Exception as method_error:
                            results["test_job"]["update_attempts"][method_name] = {
                                "success": False,
                                "error": str(method_error)
                            }
                    
                    # Job nach Update-Versuchen erneut abrufen
                    updated_job = job_repo.get_job(job_id_param)
                    if updated_job:
                        results["test_job"]["new_status"] = updated_job.status
                else:
                    results["test_job_error"] = f"Job mit ID {job_id_param} nicht gefunden"
            except Exception as test_error:
                results["test_job_error"] = str(test_error)
        
        return jsonify(results)
        
    except Exception as e:
        logger.error(f"Fehler bei der Repository-Analyse: {str(e)}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": f"Fehler bei der Repository-Analyse: {str(e)}"
        }), 500 

@main.route('/api/dashboard/event-monitor/jobs/<job_id>', methods=['DELETE'])
def api_event_monitor_job_delete(job_id):
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
def api_event_monitor_batch_delete(batch_id):
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