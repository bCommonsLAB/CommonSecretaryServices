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
    # Get statistics for the dashboard
    stats = {
        'total_requests': 0,
        'avg_duration': 0.0,
        'success_rate': 0.0,
        'operations': {},
        'hourly_stats': {},
        'recent_requests': []
    }
    
    try:
        # Load performance data
        perf_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'performance.json')
        with open(perf_path, 'r') as f:
            perf_data = json.load(f)
            
        # Calculate statistics
        now = datetime.now()
        day_ago = now - timedelta(days=1)
        
        # Filter recent requests
        recent_requests = [r for r in perf_data 
                         if datetime.fromisoformat(r['timestamp']) > day_ago]
        
        if recent_requests:
            stats['total_requests'] = len(recent_requests)
            stats['avg_duration'] = sum(r['duration_seconds'] for r in recent_requests) / len(recent_requests)
            success_count = sum(1 for r in recent_requests if r.get('details', {}).get('success', False))
            stats['success_rate'] = (success_count / len(recent_requests)) * 100
            
            # Operation statistics
            for r in recent_requests:
                op = r.get('operation', '')
                stats['operations'][op] = stats['operations'].get(op, 0) + 1
            
            # Hourly statistics
            for hour in range(24):
                hour_start = now - timedelta(hours=hour)
                hour_requests = [r for r in recent_requests 
                               if datetime.fromisoformat(r['timestamp']) > hour_start]
                stats['hourly_stats'][hour_start.strftime('%H:00')] = len(hour_requests)
            
            # Recent requests (last 10)
            recent_requests = sorted(recent_requests, 
                                  key=lambda x: x['timestamp'], 
                                  reverse=True)[:10]
            
            # Process each request to structure the data
            for request in recent_requests:
                # Extract main process details
                request['main_process'] = {
                    'timestamp': request['timestamp'],
                    'duration_seconds': request['duration_seconds'],
                    'operation': request['operation'],
                    'processor': request.get('processor', ''),
                    'success': request.get('details', {}).get('success', False),
                    'function': request.get('details', {}).get('function', ''),
                    'file_size': request.get('details', {}).get('file_size', 0),
                    'duration': request.get('details', {}).get('duration', 0),
                    'text': request.get('details', {}).get('text', 0),
                    'text_length': request.get('details', {}).get('text_length', 0),
                    'llm_model': request.get('details', {}).get('llm_model', ''),
                    'token_count': request.get('details', {}).get('token_count', 0)
                }
            
            # Load logs for each request
            request_logs = load_logs_for_requests(recent_requests)
            
            # Add logs to each request
            for request in recent_requests:
                process_id = request.get('process_id')
                request['logs'] = request_logs.get(process_id, [])
            
            stats['recent_requests'] = recent_requests
            
    except Exception as e:
        print(f"Error loading performance data: {e}")
    
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