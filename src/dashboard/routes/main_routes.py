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
from core.config import Config
from utils.logger import ProcessingLogger
from .tests import run_youtube_test, run_audio_test, run_transformer_test, run_health_test

# Create the blueprint
main = Blueprint('main', __name__)
logger = ProcessingLogger(process_id="dashboard")

def load_logs_for_requests(recent_requests):
    """
    Load log entries for a list of requests from the detailed log file
    
    Args:
        recent_requests (list): List of request entries to load logs for
        
    Returns:
        dict: Dictionary mapping process_ids to their log entries
    """
    log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'detailed.log')
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
        config_data = request.get_json()
        
        # Hole den Pfad zur config.yaml
        config_path = Path(__file__).parents[3] / 'config' / 'config.yaml'
        
        # Lade aktuelle Konfiguration
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                current_config = yaml.safe_load(f) or {}
        except Exception:
            current_config = {}
            
        # Aktualisiere die Konfiguration
        def deep_update(source, updates):
            for key, value in updates.items():
                if key in source and isinstance(source[key], dict) and isinstance(value, dict):
                    deep_update(source[key], value)
                else:
                    source[key] = value
            return source
            
        updated_config = deep_update(current_config, config_data)
        
        # Speichere die aktualisierte Konfiguration
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(updated_config, f, default_flow_style=False, allow_unicode=True)
            
        # Aktualisiere auch die .env Datei für API Keys
        if 'openai_api_key' in config_data:
            env_path = Path(__file__).parents[3] / '.env'
            env_content = []
            
            # Lese existierende .env Datei
            if env_path.exists():
                with open(env_path, 'r', encoding='utf-8') as f:
                    env_content = f.readlines()
            
            # Finde und aktualisiere oder füge OpenAI API Key hinzu
            openai_key_found = False
            for i, line in enumerate(env_content):
                if line.startswith('OPENAI_API_KEY='):
                    env_content[i] = f'OPENAI_API_KEY={config_data["openai_api_key"]}\n'
                    openai_key_found = True
                    break
            
            if not openai_key_found:
                env_content.append(f'OPENAI_API_KEY={config_data["openai_api_key"]}\n')
            
            # Schreibe aktualisierte .env Datei
            with open(env_path, 'w', encoding='utf-8') as f:
                f.writelines(env_content)
        
        return jsonify({"status": "success", "message": "Configuration saved successfully"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@main.route('/config')
def config_page():
    """Zeigt die Konfigurationsseite an."""
    config = Config()
    return render_template('config.html', config=config) 

@main.route('/test')
def test_page():
    """
    Test page with Swagger UI integration for API testing
    
    Returns:
        rendered template: The apitest.html template with Swagger UI
    """
    return render_template('apitest.html')

@main.route('/test_procedures')
def test_procedures():
    """
    Test procedures page for running various system tests
    
    Returns:
        rendered template: The test.html template with test options and results
    """
    return render_template('test.html', test_results=None)

@main.route('/run_youtube_test', methods=['POST'])
def youtube_test():
    """Route handler for YouTube test"""
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
    """Show system logs with filtering options"""
    log_path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'logs', 'detailed.log')
    logs = []
    
    try:
        with open(log_path, 'r') as f:
            current_entry = None
            details_lines = []
            
            for line in f:
                line = line.strip()
                
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
                        logs.append(current_entry)
                    
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
                            if '] Process[' in process_info:
                                parts = process_info.split('] Process[')
                                processor_name = parts[0].strip('[')
                                process_id = parts[1].strip(']')
                            else:
                                processor_name = ""
                                process_id = ""
                            
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'processor_name': processor_name,
                                'process_id': process_id,
                                'message': message.strip(),
                                'details': None  # Initialize details as None
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
                                'message': message.strip(),
                                'details': None  # Initialize details as None
                            }
                    details_lines = []
                
                elif line.startswith('Details: '):
                    details_lines = [line]
                elif details_lines:
                    details_lines.append(line)
            
            # Add last entry
            if current_entry is not None:
                if details_lines:
                    try:
                        details_text = '\n'.join(details_lines)
                        if details_text.startswith('Details: '):
                            details_text = details_text[9:]
                        current_entry['details'] = json.loads(details_text)
                    except json.JSONDecodeError:
                        current_entry['details'] = {'raw': '\n'.join(details_lines)}
                logs.append(current_entry)
        
        # Apply filters
        filter_level = request.args.get('level')
        filter_date = request.args.get('date')
        search_query = request.args.get('search')
        
        if filter_level:
            logs = [log for log in logs if log['level'] == filter_level]
        if filter_date:
            logs = [log for log in logs if log['timestamp'].startswith(filter_date)]
        if search_query:
            logs = [log for log in logs if search_query.lower() in log['message'].lower()]
        
        # Sort logs by timestamp (newest first)
        logs.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return render_template('logs.html', 
                             logs=logs, 
                             filter_level=filter_level,
                             filter_date=filter_date,
                             search_query=search_query)
                             
    except Exception as e:
        return f"Error reading logs: {str(e)}", 500 

@main.route('/clear-logs', methods=['POST'])
def clear_logs():
    """
    Löscht den Inhalt der detailed.log Datei
    """
    try:
        with open('logs/detailed.log', 'w') as f:
            f.write('')
        return redirect(url_for('main.logs'))
    except Exception as e:
        return f"Error clearing logs: {str(e)}", 500 