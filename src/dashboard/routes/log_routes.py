"""
Log routes for the dashboard application.
Handles log viewing and filtering functionality.
"""
from flask import Blueprint, render_template, request
import json
import os
import re
from datetime import datetime
import yaml
from src.core.config import Config
from pathlib import Path

# Create the blueprint
logs = Blueprint('logs', __name__)

def get_log_entries(filter_level=None, filter_date=None, search_query=None, page=1, per_page=50):
    """
    Get log entries with filtering and pagination.
    
    Args:
        filter_level (str, optional): Filter logs by level (ERROR, WARNING, INFO, DEBUG)
        filter_date (str, optional): Filter logs by date (YYYY-MM-DD)
        search_query (str, optional): Search text in log messages and process IDs
        page (int, optional): Current page number for pagination. Defaults to 1.
        per_page (int, optional): Number of entries per page. Defaults to 50.
    
    Returns:
        dict: Dictionary containing:
            - entries: List of log entries for the current page
            - pagination: Dictionary with pagination information
    """
    # Lade Log-Pfad aus der Konfiguration
    config = Config()
    log_file = config.get_all().get('logging', {}).get('file', 'logs/detailed.log')
    log_path = Path(log_file)
    entries = []
    
    try:
        if log_path.exists():
            with open(log_path, 'r') as f:
                current_entry = None
                details_lines = []
                collecting_details = False
                
                for line in f:
                    line = line.strip()
                    
                    # Check if this is a new log entry (starts with timestamp)
                    if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}', line):
                        # Save previous entry if exists
                        if current_entry is not None and should_include_entry(current_entry, filter_level, filter_date, search_query):
                            if details_lines:
                                try:
                                    details_text = '\n'.join(details_lines)
                                    if details_text.startswith('Details: '):
                                        details_text = details_text[9:]  # Remove "Details: " prefix
                                    current_entry['details'] = json.loads(details_text)
                                except json.JSONDecodeError:
                                    current_entry['details'] = {'raw': '\n'.join(details_lines)}
                            entries.append(current_entry)
                        
                        # Parse new entry
                        parts = line.split(' - ', 4)
                        if len(parts) >= 5:
                            timestamp, level, source, process, message = parts
                            current_entry = {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'process_id': process.split('[')[1].split(']')[0] if '[' in process else '',
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
                if current_entry is not None and should_include_entry(current_entry, filter_level, filter_date, search_query):
                    if details_lines:
                        try:
                            details_text = '\n'.join(details_lines)
                            if details_text.startswith('Details: '):
                                details_text = details_text[9:]  # Remove "Details: " prefix
                            current_entry['details'] = json.loads(details_text)
                        except json.JSONDecodeError:
                            current_entry['details'] = {'raw': '\n'.join(details_lines)}
                    entries.append(current_entry)
                
    except Exception as e:
        print(f"Error reading log file: {e}")
    
    # Sort entries by timestamp in reverse order
    entries.sort(key=lambda x: x['timestamp'], reverse=True)
    
    # Paginate results
    total_pages = (len(entries) + per_page - 1) // per_page
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    return {
        'entries': entries[start_idx:end_idx],
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'total_entries': len(entries),
            'pages': list(range(max(1, page - 2), min(total_pages + 1, page + 3)))
        }
    }

def should_include_entry(entry, filter_level=None, filter_date=None, search_query=None):
    """
    Helper function to determine if a log entry should be included based on filters
    
    Args:
        entry (dict): The log entry to check
        filter_level (str, optional): Level to filter by
        filter_date (str, optional): Date to filter by (YYYY-MM-DD)
        search_query (str, optional): Text to search for in message and process_id
    
    Returns:
        bool: True if entry should be included, False otherwise
    """
    # Level filter
    if filter_level and entry['level'] != filter_level:
        return False
    
    # Date filter
    if filter_date:
        entry_date = entry['timestamp'].split()[0]
        if entry_date != filter_date:
            return False
    
    # Search filter
    if search_query:
        search_lower = search_query.lower()
        # Search in message and process_id
        if (search_lower not in entry['message'].lower() and 
            search_lower not in entry['process_id'].lower()):
            return False
    
    return True

@logs.route('/logs')
def view_logs():
    """
    Log viewer page with filtering and pagination
    
    Supports filtering by:
    - Log level (ERROR, WARNING, INFO, DEBUG)
    - Date
    - Search text in messages and process IDs
    
    Returns:
        rendered template: The logs.html template with filtered log entries and pagination
    """
    filter_level = request.args.get('level')
    filter_date = request.args.get('date')
    search_query = request.args.get('search')
    page = int(request.args.get('page', 1))
    
    log_data = get_log_entries(
        filter_level=filter_level,
        filter_date=filter_date,
        search_query=search_query,
        page=page
    )
    
    return render_template('logs.html',
                         logs=log_data['entries'],
                         pagination=log_data['pagination'],
                         filter_level=filter_level,
                         filter_date=filter_date,
                         search_query=search_query) 