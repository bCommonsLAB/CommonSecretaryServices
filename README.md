# Anonyme Verarbeitungsdienste

Eine Flask-basierte API für die anonyme Verarbeitung von PDFs, Bildern und YouTube-Videos.

## Features

- PDF-Textextraktion mit OCR
- Bildtext-Extraktion
- YouTube-Video-Download und Audio-Extraktion
- Ressourcen-Tracking
- Rate Limiting
- Dateigrößen-Beschränkungen

## Installation
1. Repository klonen:
```bash
git clone https://github.com/yourusername/anonymous-processing-services.git
cd anonymous-processing-services
```

2. Virtual Environment erstellen und aktivieren:
```bash
Unter Linux/Mac:
python -m venv venv
source venv/bin/activate
Unter Windows:
python -m venv venv
.\venv\Scripts\activate
```

evtl. muss man in Microsoft Powershell die Kommandos ausführen:
```bash
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

3. Abhängigkeiten installieren:
```bash
pip install -r requirements.txt
pip install -e .
```


## Konfiguration
Die Konfiguration erfolgt über `config/config.yaml`:

```yaml
server:
    host: "0.0.0.0"
    port: 5000
    debug: true

rate_limiting:
    requests_per_hour: 100
    max_file_size: 52428800 # 50MB

processors:
    pdf:
        enabled: true
        max_pages: 100
    image:
        enabled: true
        max_resolution: 4096
    youtube:
        enabled: true
        max_duration: 3600 # 1 Stunde
```


## .Env Datei erstellen und OPENAI_API_KEY setzen



## Dashboard

Das Dashboard bietet eine Echtzeit-Übersicht über die Verarbeitungsdienste und ist unter `http://localhost:5000/dashboard` verfügbar.

### Features

- **Performance-Metriken:**
  - Gesamtanzahl der Anfragen (24h)
  - Durchschnittliche Verarbeitungszeit
  - Erfolgsrate

- **Visualisierungen:**
  - Verteilung der Operationen (Pie Chart)
  - Stündliche Anfragen (Line Chart)

- **Fehler-Monitoring:**
  - Live-Anzeige der letzten Fehler
  - Zeitstempel und Details

### Zugriff auf das Dashboard

1. Starten Sie die Anwendung:
```bash
# Aktivieren Sie zuerst das Virtual Environment
source venv/bin/activate  # Linux/Mac
# oder
.\venv\Scripts\activate  # Windows

# ein (venv) sollte in console erscheinen
# Setzen Sie die PYTHONPATH Variable
# z.B. $env:PYTHONPATH = "C:\Users\username\projekte\CommonSecretaryServices"
$env:PYTHONPATH = "<pfad des Projektes>"  
# Starten Sie die Anwendung
python src/main.py
```

2. Öffnen Sie einen Browser und navigieren Sie zu:
```
http://localhost:5000/dashboard
```

### Abhängigkeiten

Das Dashboard benötigt zusätzliche Python-Pakete, die bereits in `requirements.txt` enthalten sind:
- pandas: Für Datenanalyse
- flask: Für das Web-Interface

### Log-Dateien

Das Dashboard liest Daten aus folgenden Log-Dateien:
- `logs/performance.json`: Performance-Metriken und Statistiken
- `logs/detailed.log`: Detaillierte Logs und Fehler

Die Logs werden automatisch im `logs`-Verzeichnis erstellt.

### Automatische Aktualisierung

Das Dashboard aktualisiert sich nicht automatisch. Drücken Sie F5 oder die Reload-Taste im Browser, um die neuesten Daten zu sehen.


## API-Endpunkte

### 1. PDF-Verarbeitung

**Endpoint:** `/api/process-pdf`  
**Methode:** POST  
**Content-Type:** multipart/form-data

```bash
curl -X POST -F "file=@document.pdf" http://localhost:5000/api/process-pdf
```


**Beispielantwort:**
```json
{
    "text": "Extrahierter Text...",
    "page_count": 1,
    "resources_used": [
        {
        "type": "storage",
        "amount": 1.5,
        "unit": "MB"
        },
        {
        "type": "compute",
        "amount": 2.3,
        "unit": "seconds"
        }
    ],
    "total_units": {
    "storage_mb": 1.5,
    "compute_seconds": 2.3,
    "total_cost": 0.00023
    }
}
```



### 2. Bild-Verarbeitung

**Endpoint:** `/api/process-image`  
**Methode:** POST  
**Content-Type:** multipart/form-data

```bash
curl -X POST -F "file=@image.jpg" http://localhost:5000/api/process-image
```


### 3. Audio-Verarbeitung

**Endpoint:** `/api/process-audio`  
**Methode:** POST  
**Content-Type:** multipart/form-data

```bash
curl -X POST -F "file=@audio.mp3" http://localhost:5000/api/process-audio
```


### 4. YouTube-Verarbeitung

**Endpoint:** `/api/process-youtube`  
**Methode:** POST  
**Content-Type:** application/json

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"url":"https://www.youtube.com/watch?v=example"}' \
http://localhost:5000/api/process-youtube
```

### 5. Text-Transformation

**Endpoint:** `/api/transform-text`  
**Methode:** POST  
**Content-Type:** application/json

```bash
curl -X POST -H "Content-Type: application/json" \
-d '{"text":"Dies ist ein Test"}' \
http://localhost:5000/api/transform-text
```

## Beispiele

### Python-Beispiele

1. PDF-Verarbeitung:
```python
import requests

def process_pdf(file_path: str) -> dict:
    with open(file_path, 'rb') as f:
    response = requests.post(
        'http://localhost:5000/api/process-pdf',
        files={'file': f}
    )
    return response.json()
```

Verwendung
```python   
result = process_pdf('dokument.pdf')
print(f"Extrahierter Text: {result['text'][:100]}...")
print(f"Seitenanzahl: {result['page_count']}")
```
2. Bild-Verarbeitung:

```python
import requests
from PIL import Image, ImageDraw, ImageFont

def create_test_image(text: str, output_path: str):
    """Erstellt ein Testbild mit Text"""
    img = Image.new('RGB', (800, 600), color='white')
    d = ImageDraw.Draw(img)
    d.text((10,10), text, fill='black')
    img.save(output_path)

def process_image(file_path: str) -> dict:
    with open(file_path, 'rb') as f:
    response = requests.post(
        'http://localhost:5000/api/process-image',
        files={'file': f}
    )
    return response.json()
```

Verwendung
```python   
create_test_image("Dies ist ein Test", "test.png")
result = process_image("test.png")
print(f"Extrahierter Text: {result['text'][:100]}...")
```


3. YouTube-Verarbeitung:

```python
import requests

def process_youtube(url: str) -> dict:
    response = requests.post(
        'http://localhost:5000/api/process-youtube',
        json={'url': url}
    )
    return response.json()
```

Verwendung
url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
result = process_youtube(url)


## Tests

Tests ausführen:
```bash
#Alle Tests
pytest tests/

# Nur Unit-Tests (ohne Integration)
pytest tests/ -m "not integration"

#Spezifische Tests
pytest tests/test_pdf_processor.py
pytest tests/test_image_processor.py
pytest tests/test_youtube_processor.py

# Nur Integrationstests ausführen
pytest tests/test_youtube_processor.py -v -m integration

# Mit detaillierter Ausgabe
pytest tests/test_youtube_processor.py -v -m integration --capture=no

# Mit Anzeige der print-Ausgaben
pytest tests/test_youtube_processor.py -v -m integration -s


#Mit detaillierter Ausgabe
pytest -v tests/
```


## Fehlerbehandlung

Die API verwendet standardisierte HTTP-Statuscodes:

- 200: Erfolgreiche Verarbeitung
- 400: Ungültige Anfrage (z.B. falsche Datei, ungültige URL)
- 429: Rate Limit überschritten
- 500: Interner Serverfehler

Fehlerantworten haben folgendes Format:

```json
{
"error": "Beschreibung des Fehlers"
}
```


## Ressourcen-Tracking

Das System trackt zwei Arten von Ressourcen:

1. **Speicher** (in MB)
   - Dateigröße der verarbeiteten Medien
   - Zwischengespeicherte Daten

2. **Rechenzeit** (in Sekunden)
   - Verarbeitungszeit
   - CPU-Nutzung

Die Kosten werden wie folgt berechnet:
- Speicher: 0.00001 EUR pro MB
- Rechenzeit: 0.0001 EUR pro Sekunde

## Sicherheitshinweise

- Alle temporären Dateien werden nach der Verarbeitung gelöscht
- Rate Limiting verhindert Überlastung
- Maximale Dateigrößen sind beschränkt
- Keine persistente Speicherung von Mediendaten

## Lizenz

MIT License

## Beitragen

1. Fork erstellen
2. Feature Branch erstellen (`git checkout -b feature/AmazingFeature`)
3. Änderungen committen (`git commit -m 'Add some AmazingFeature'`)
4. Branch pushen (`git push origin feature/AmazingFeature`)
5. Pull Request erstellen

