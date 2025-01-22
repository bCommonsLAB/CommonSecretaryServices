# Troubleshooting

## Überblick

Diese Dokumentation bietet Anleitungen zur Diagnose und Behebung häufiger Probleme im Common Secretary Services System.

## Diagnose-Werkzeuge

### Log-Analyse
```python
def analyze_logs(log_file: Path, error_pattern: str) -> List[Dict]:
    """Analysiert Logs nach spezifischen Fehlermustern."""
    errors = []
    with open(log_file) as f:
        for line in f:
            if re.search(error_pattern, line):
                errors.append(parse_log_entry(line))
    return errors
```

### System-Status
```python
def check_system_status() -> Dict[str, Any]:
    """Prüft den Status aller Systemkomponenten."""
    return {
        'api': check_api_status(),
        'processors': check_processor_status(),
        'storage': check_storage_status(),
        'external_services': check_external_services()
    }
```

## Häufige Probleme

### 1. API-Verbindungsfehler

#### Symptome
- 502 Bad Gateway
- Connection Refused
- Timeout-Fehler

#### Diagnose
```bash
# API-Erreichbarkeit prüfen
curl -v http://localhost:5000/health

# Service-Status prüfen
systemctl status secretary

# Log-Analyse
tail -f /var/log/secretary/error.log
```

#### Lösung
```bash
# Service neustarten
systemctl restart secretary

# Port-Konflikte prüfen
netstat -tulpn | grep 5000

# Firewall-Regeln prüfen
ufw status
```

### 2. Verarbeitungsfehler

#### Symptome
- Fehlgeschlagene Transkriptionen
- Unvollständige Ausgaben
- Timeout bei der Verarbeitung

#### Diagnose
```python
def diagnose_processing_error(job_id: str) -> Dict[str, Any]:
    """Analysiert Verarbeitungsfehler."""
    return {
        'job_status': get_job_status(job_id),
        'processor_logs': get_processor_logs(job_id),
        'resource_usage': get_resource_usage(),
        'temp_files': check_temp_files(job_id)
    }
```

#### Lösung
```python
def resolve_processing_error(job_id: str):
    """Behebt häufige Verarbeitungsfehler."""
    # Temporäre Dateien bereinigen
    cleanup_temp_files(job_id)
    
    # Prozessor neustarten
    restart_processor()
    
    # Job neu einreihen
    requeue_job(job_id)
```

### 3. Speicherprobleme

#### Symptome
- Disk Space Low
- Temporäre Dateien häufen sich
- I/O-Fehler

#### Diagnose
```bash
# Speichernutzung analysieren
df -h
du -sh temp-processing/*

# I/O-Performance prüfen
iostat -x 1
```

#### Lösung
```python
def manage_storage():
    """Verwaltet Speicherplatz."""
    # Alte temporäre Dateien löschen
    cleanup_old_files()
    
    # Logs rotieren
    rotate_logs()
    
    # Cache bereinigen
    clear_cache()
```

### 4. Externe Service-Fehler

#### Symptome
- OpenAI API-Fehler
- YouTube API-Fehler
- Rate Limiting

#### Diagnose
```python
def check_external_services() -> Dict[str, str]:
    """Prüft externe Dienste."""
    return {
        'openai': test_openai_connection(),
        'youtube': test_youtube_connection(),
        'rate_limits': check_rate_limits()
    }
```

#### Lösung
```python
def handle_service_error(service: str, error: Exception):
    """Behandelt Fehler externer Dienste."""
    if isinstance(error, RateLimitError):
        # Warte und versuche erneut
        implement_exponential_backoff()
    elif isinstance(error, AuthenticationError):
        # API-Keys prüfen
        validate_api_keys()
    else:
        # Alternativen Service verwenden
        use_fallback_service()
```

## Performance-Probleme

### CPU-Auslastung
```python
def analyze_cpu_usage():
    """Analysiert CPU-Auslastung."""
    # Prozesse identifizieren
    top_processes = get_top_cpu_processes()
    
    # Worker-Auslastung prüfen
    worker_stats = get_worker_stats()
    
    # Empfehlungen generieren
    return generate_optimization_recommendations()
```

### Speicher-Leaks
```python
def detect_memory_leaks():
    """Erkennt Speicher-Leaks."""
    # Memory-Profile erstellen
    memory_profile = create_memory_profile()
    
    # Große Objekte identifizieren
    large_objects = find_large_objects()
    
    # Leak-Kandidaten identifizieren
    return analyze_memory_growth()
```

## Monitoring-Tools

### Prometheus Metriken
```python
# Metriken definieren
PROCESSING_DURATION = Counter(
    'processing_duration_seconds',
    'Zeit für die Verarbeitung'
)

ERROR_COUNT = Counter(
    'error_count',
    'Anzahl der Fehler',
    ['type']
)

QUEUE_SIZE = Gauge(
    'job_queue_size',
    'Aktuelle Größe der Job-Warteschlange'
)
```

### Grafana Dashboards
```yaml
# dashboard.yml
panels:
  - title: "System Health"
    type: graph
    metrics:
      - "cpu_usage"
      - "memory_usage"
      - "disk_usage"
  
  - title: "Error Rates"
    type: graph
    metrics:
      - "error_count"
      - "failure_rate"
```

## Recovery-Prozeduren

### Daten-Recovery
```python
def recover_data(backup_path: Path):
    """Stellt Daten aus Backup wieder her."""
    # Backup validieren
    validate_backup(backup_path)
    
    # Daten wiederherstellen
    restore_from_backup(backup_path)
    
    # Integrität prüfen
    verify_data_integrity()
```

### Service-Recovery
```python
def recover_service():
    """Stellt Service nach Ausfall wieder her."""
    # Abhängigkeiten prüfen
    check_dependencies()
    
    # Konfiguration validieren
    validate_config()
    
    # Services neustarten
    restart_services()
    
    # Status verifizieren
    verify_service_health()
```

## Wartungsmodus

### Aktivierung
```python
def enable_maintenance_mode():
    """Aktiviert den Wartungsmodus."""
    # Neue Jobs pausieren
    pause_job_queue()
    
    # Laufende Jobs beenden
    graceful_shutdown()
    
    # Wartungsseite aktivieren
    enable_maintenance_page()
```

### Deaktivierung
```python
def disable_maintenance_mode():
    """Deaktiviert den Wartungsmodus."""
    # System-Status prüfen
    verify_system_ready()
    
    # Services hochfahren
    start_services()
    
    # Warteschlange aktivieren
    resume_job_queue()
``` 