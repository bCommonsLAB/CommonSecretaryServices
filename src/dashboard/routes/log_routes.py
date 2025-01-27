"""
Log routes for the dashboard application.
Handles log viewing and filtering functionality.
"""
from flask import Blueprint, render_template, request
import os
import re
import json
from typing import Dict, Any, Optional, List, TypedDict, cast
from src.core.config import Config

# Create the blueprint
logs = Blueprint('logs', __name__)

class LogEntry(TypedDict):
    """Typ-Definition für einen Log-Eintrag."""
    timestamp: str
    level: str
    source: str
    process_id: str
    message: str
    details: Optional[Dict[str, Any]]

class PaginationInfo(TypedDict):
    """Typ-Definition für Pagination-Informationen."""
    current_page: int
    total_pages: int
    total_entries: int
    pages: List[int]

class LogResponse(TypedDict):
    """Typ-Definition für die Log-Response."""
    entries: List[LogEntry]
    pagination: PaginationInfo

def get_log_entries(
    filter_level: Optional[str] = None,
    filter_date: Optional[str] = None,
    search_query: Optional[str] = None,
    session_id: Optional[str] = None,
    page: int = 1,
    per_page: int = 50
) -> LogResponse:
    """
    Liest und filtert Log-Einträge aus der Log-Datei.
    
    Args:
        filter_level: Log-Level Filter (DEBUG, INFO, ERROR)
        filter_date: Datum Filter im Format YYYY-MM-DD
        search_query: Suchbegriff für Volltextsuche
        session_id: Process/Session ID für Filterung zusammengehöriger Logs
        page: Aktuelle Seite für Pagination
        per_page: Einträge pro Seite
        
    Returns:
        LogResponse: Gefilterte Log-Einträge und Pagination-Informationen
    """
    entries: List[LogEntry] = []
    current_entry: Optional[LogEntry] = None
    details_lines: List[str] = []
    collecting_details = False

    def should_include_entry(
        entry: LogEntry,
        level: Optional[str] = None,
        date: Optional[str] = None,
        query: Optional[str] = None,
        sid: Optional[str] = None
    ) -> bool:
        """Prüft, ob ein Log-Eintrag den Filter-Kriterien entspricht."""
        if level and entry['level'] != level:
            return False
        if date and not entry['timestamp'].startswith(date):
            return False
        if query:
            search_text = f"{entry['message']} {entry.get('details', '')}"
            if query.lower() not in search_text.lower():
                return False
        if sid and entry['process_id'] != sid:
            return False
        return True

    try:
        config = Config()
        log_file = config.get('logging.file', 'logs/detailed.log')
        
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    
                    # Check if this is a new log entry (starts with timestamp)
                    if re.match(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}', line):
                        # Save previous entry if exists
                        if current_entry is not None and should_include_entry(current_entry, filter_level, filter_date, search_query, session_id):
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
                            current_entry = cast(LogEntry, {
                                'timestamp': timestamp,
                                'level': level.strip(),
                                'source': source.strip('[]'),
                                'process_id': process.split('[')[1].split(']')[0] if '[' in process else '',
                                'message': message.strip(),
                                'details': None
                            })
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
                if current_entry is not None and should_include_entry(current_entry, filter_level, filter_date, search_query, session_id):
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
    
    return cast(LogResponse, {
        'entries': entries[start_idx:end_idx],
        'pagination': {
            'current_page': page,
            'total_pages': total_pages,
            'total_entries': len(entries),
            'pages': list(range(max(1, page - 2), min(total_pages + 1, page + 3)))
        }
    })

@logs.route('/logs')
def view_logs() -> str:
    """
    Log viewer page with filtering and pagination
    
    Supports filtering by:
    - Log level (ERROR, WARNING, INFO, DEBUG)
    - Date
    - Search text in messages and process IDs
    
    Returns:
        str: The rendered logs.html template with filtered log entries and pagination
    """
    filter_level = request.args.get('level')
    filter_date = request.args.get('date')
    search_query = request.args.get('search')
    session_id = request.args.get('session_id')
    page = int(request.args.get('page', 1))
    
    log_data = get_log_entries(
        filter_level=filter_level,
        filter_date=filter_date,
        search_query=search_query,
        session_id=session_id,
        page=page
    )
    
    return render_template('logs.html',
                         logs=log_data['entries'],
                         pagination=log_data['pagination'],
                         filter_level=filter_level,
                         filter_date=filter_date,
                         search_query=search_query,
                         session_id=session_id) 