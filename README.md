# Common Secretary Services

Ein Python-basierter Service für die automatisierte Verarbeitung von Audio-, Video- und anderen Mediendateien mit Fokus auf Transkription und strukturierte Ausgabe mittels Templates.

## Features

- 🎵 **Audio-Verarbeitung**: Unterstützung für MP3, WAV, M4A
- 🎥 **YouTube-Integration**: Download und Verarbeitung von Videos
- 📝 **Template-System**: Flexible Ausgabeformatierung
- 🚀 **RESTful API**: Vollständige API mit Swagger UI
- 🌐 **Web-Interface**: Benutzerfreundliche Verwaltung

## Dokumentation

### A. Grundlagen & Einstieg
1. [Architektur](docs/01_architecture.md)
2. [Installation & Setup](docs/02_installation.md)
3. [Entwicklungsrichtlinien](docs/03_development.md)

### B. Core-Funktionalität
4. [API & Server](docs/04_api.md)
5. [Typdefinitionen](docs/05_types.md)
6. [Template-System](docs/06_templates.md)
7. [Audio-Prozessor](docs/07_audio.md)
8. [Web-Interface](docs/08_web_interface.md)

### C. Betrieb & Wartung
9. [Deployment](docs/09_deployment.md)
10. [Troubleshooting](docs/10_troubleshooting.md)
11. [Sicherheit & Datenschutz](docs/11_security.md)
12. [Monitoring](docs/12_monitoring.md)

### D. Projekt & Support
13. [Changelog & Roadmap](docs/13_changelog.md)
14. [FAQ](docs/14_faq.md)
15. [Kontakt, Support & Lizenz](docs/15_support.md)

## Schnellstart



### Installation

```bash
# Repository klonen
git clone https://github.com/yourusername/CommonSecretaryServices.git
cd CommonSecretaryServices

# Virtuelle Umgebung erstellen und aktivieren
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\\Scripts\\activate   # Windows

# Abhängigkeiten installieren
pip install -r requirements.txt

# Konfiguration anpassen
cp config/config.example.yaml config/config.yaml
# Bearbeiten Sie config.yaml mit Ihren API-Keys und Einstellungen
```

### Dashboard
```bash	
# ein (venv) sollte in console erscheinen
# Setzen Sie die PYTHONPATH Variable
# z.B. $env:PYTHONPATH = "<pfad des Projektes>"  
$env:PYTHONPATH = "."
# Starten Sie die Anwendung
python src/main.py

### API-Nutzung

```python
import requests

# Audio-Datei verarbeiten
response = requests.post(
    'http://localhost:5000/api/v1/audio/process',
    files={'file': open('audio.mp3', 'rb')},
    headers={'Authorization': 'Bearer your-api-key'}
)

# YouTube-Video verarbeiten
response = requests.post(
    'http://localhost:5000/api/v1/youtube/process',
    json={'url': 'https://youtube.com/watch?v=...'},
    headers={'Authorization': 'Bearer your-api-key'}
)
```

## Systemanforderungen

- Python 3.11+
- FFmpeg
- 10GB+ freier Speicherplatz
- Schnelle Internetverbindung für API-Zugriff

## Externe Dienste

- OpenAI API (für GPT-4)
- YouTube Data API

## Lizenz

Copyright (c) 2024 Peter Aichner. Alle Rechte vorbehalten.

## Support

Bei Fragen oder Problemen:
- GitHub Issues für Bug Reports und Feature Requests
- E-Mail Support: support@common-secretary.com
- [Dokumentation](docs/) für detaillierte Informationen

## Beitragen

Wir freuen uns über Beiträge! Bitte lesen Sie unsere [Entwicklungsrichtlinien](docs/10_development.md) für Details.

## Status

![Build Status](build-status-badge-url)
![Test Coverage](test-coverage-badge-url)
![License](license-badge-url)

