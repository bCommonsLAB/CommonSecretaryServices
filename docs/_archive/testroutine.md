# Testroutine für API-Routen

## Übersicht

Dieses Dokument beschreibt einen systematischen Ansatz zum Testen aller API-Routen unserer Common Secretary Services. Ziel ist es, sicherzustellen, dass alle Prozessoren korrekt funktionieren, insbesondere mit der neu vereinheitlichten Cache-Verzeichnisstruktur.

## Vorbereitung

Bevor die Tests ausgeführt werden können, muss der Server korrekt gestartet werden. 
Dazu ist es wichtig, die Python-Umgebung richtig zu konfigurieren:

```powershell
# Aktiviere die virtuelle Umgebung
venv\Scripts\activate

# Setze den PYTHONPATH auf das aktuelle Verzeichnis
$env:PYTHONPATH = "."

# Starte den Server
python src/main.py
```

Der Server läuft dann unter `http://localhost:5001`.

### API-Dokumentation

Die API-Dokumentation (Swagger) ist verfügbar unter:
```
http://localhost:5001/api/doc
```
Diese Dokumentation kann genutzt werden, um die verfügbaren Endpunkte und deren Parameter einzusehen. Die Swagger-JSON-Datei ist unter folgendem Pfad verfügbar:
```
http://localhost:5001/api/swagger.json
```

## Testmatrix

Alle Tests werden nach folgendem Schema durchgeführt:

| Prozessor       | Cache-Optionen | Input-Quellen   | Formate/Optionen |
|-----------------|----------------|-----------------|------------------|
| Transformer     | mit/ohne Cache | Text-Eingabe, URL | Sprachoptionen, Templates |
| Audio           | mit/ohne Cache | Datei-Upload, URL | MP3, WAV, andere Formate |
| Video           | mit/ohne Cache | URL (YouTube, andere) | Verschiedene Quellen |
| ImageOCR        | mit/ohne Cache | Datei-Upload, URL | JPEG, PNG, PDF-Seiten |
| PDF             | mit/ohne Cache | Datei-Upload, URL | Verschiedene PDF-Typen |

## Testdaten

### Lokale Testdateien

*Bitte spezifische Dateien unter `tests/samples` eintragen:*

- Audio: `tests/samples/hello.mp4` (als Audio verwenden)
- Bild: `tests/samples/diagramm.jpg`
- JSON: `tests/samples/notion_blog_sample.json` (für Transformer-Tests)
- JSON: `tests/samples/fosdem-events.json` (für Event-Tests)

### URL-Testquellen

*Hier URLs für verschiedene Tests eintragen:*

- YouTube-Videos: 
  - https://www.youtube.com/watch?v=jNQXAC9IVRw
- Öffentliche Audiodateien:
  - https://examplefiles.org/files/audio/mp3-example-file-download-1min.mp3
- Öffentliche Bilddateien:
  - https://cdn.prod.website-files.com/60646191e49a2a535c20c76b/6182b58704660f1357723c37_bar-min-p-2600.png
- Öffentliche Videos:
  - https://video.fosdem.org/2025/janson/fosdem-2025-6196-rewriting-the-future-of-the-linux-essential-packages-in-rust-.av1.webm  
- Öffentliche PDFs:
  - https://fosdem.org/2025/events/attachments/fosdem-2025-5258-forked-communities-project-re-licensing-and-community-impact/slides/238218/FOSDEM_Fo_HyZR9km.pdf

## Testplan

### 1. Transformer-Prozessor

#### Einfache Texttransformation

**Endpunkt**: `POST /api/transformer/text`

**Testfälle:**

1. **Basis-Transformation ohne Cache**:
   - Request-Body: `{"text": "Hallo Welt", "source_language": "de", "target_language": "en", "use_cache": false}`
   - Erwartetes Ergebnis: Englische Übersetzung

2. **Basis-Transformation mit Cache**:
   - Request-Body: `{"text": "Hallo Welt", "source_language": "de", "target_language": "en", "use_cache": true}`
   - Erwartetes Ergebnis: Englische Übersetzung mit Cache-Info
   - Zweiter Aufruf muss schneller sein und aus dem Cache kommen

#### Template-basierte Transformation

**Endpunkt**: `POST /api/transformer/template`

**Testfälle:**

1. **Template-Transformation**:
   - Request-Body: `{"text": "Berlin ist die Hauptstadt von Deutschland.", "source_language": "de", "target_language": "en", "template": "Gedanken"}`
   - Erwartetes Ergebnis: Transformation basierend auf dem gewählten Template
   - Hinweis: Dieser Endpunkt unterstützt keinen Cache-Parameter

### 2. Audio-Prozessor

#### Lokale Datei

**Endpunkt**: `POST /api/audio/process`

**Testfälle:**

1. **Datei-Upload ohne Cache**:
   - Form-Data: Datei `hello.mp4`, use_cache=false
   - Erwartetes Ergebnis: Transkript der Audiodaten

2. **Datei-Upload mit Cache**:
   - Form-Data: Datei `hello.mp4`, use_cache=true
   - Überprüfung: Cache-Nutzung beim zweiten Aufruf

### 3. Video-Prozessor

**Endpunkt**: `POST /api/video/process`

**Testfälle:**

1. **YouTube-URL ohne Cache**:
   - Request-Body: `{"url": "[YOUTUBE_URL_EINTRAGEN]", "use_cache": false}`
   - Erwartetes Ergebnis: Metadaten und Transkript

2. **YouTube-URL mit Cache**:
   - Request-Body: `{"url": "[YOUTUBE_URL_EINTRAGEN]", "use_cache": true}`
   - Überprüfung: Cache-Nutzung beim zweiten Aufruf

3. **Andere Video-URL ohne Cache**:
   - Request-Body: `{"url": "[VIDEO_URL_EINTRAGEN]", "use_cache": false}`
   - Erwartetes Ergebnis: Metadaten und Transkript

### 4. ImageOCR-Prozessor

**Endpunkt**: `POST /api/imageocr/process`

**Testfälle:**

1. **Bild-Upload ohne Cache**:
   - Form-Data: Datei `diagramm.jpg`, use_cache=false
   - Erwartetes Ergebnis: Extrahierter Text aus dem Bild

2. **Bild-Upload mit Cache**:
   - Form-Data: Datei `diagramm.jpg`, use_cache=true
   - Überprüfung: Cache-Nutzung beim zweiten Aufruf

**Endpunkt**: `POST /api/imageocr/process-url`

**Testfälle:**

1. **URL-Verarbeitung ohne Cache**:
   - Request-Body: `{"url": "[BILD_URL_EINTRAGEN]", "use_cache": false}`
   - Erwartetes Ergebnis: Extrahierter Text aus dem Bild

2. **URL-Verarbeitung mit Cache**:
   - Request-Body: `{"url": "[BILD_URL_EINTRAGEN]", "use_cache": true}`
   - Überprüfung: Cache-Nutzung beim zweiten Aufruf

### 5. PDF-Prozessor

**Endpunkt**: `POST /api/pdf/process`

**Testfälle:**

1. **PDF-Upload ohne Cache**:
   - Form-Data: PDF-Datei (muss noch hinzugefügt werden), use_cache=false
   - Erwartetes Ergebnis: Extrahierter Text und Metadaten

2. **PDF-Upload mit Cache**:
   - Form-Data: PDF-Datei, use_cache=true
   - Überprüfung: Cache-Nutzung beim zweiten Aufruf

**Endpunkt**: `POST /api/pdf/process-url`

**Testfälle:**

1. **URL-Verarbeitung ohne Cache**:
   - Request-Body: `{"url": "[PDF_URL_EINTRAGEN]", "use_cache": false}`
   - Erwartetes Ergebnis: Extrahierter Text und Metadaten

2. **URL-Verarbeitung mit Cache**:
   - Request-Body: `{"url": "[PDF_URL_EINTRAGEN]", "use_cache": true}`
   - Überprüfung: Cache-Nutzung beim zweiten Aufruf

## Automatisierte Testskripte

Die Tests können mit den folgenden Skripten automatisiert werden:

```python
# test_transformer.py
import requests
import json
import time

BASE_URL = "http://localhost:5001/api"  # Kein /v1 in der URL

def test_transformer_without_cache():
    data = {
        "text": "Hallo Welt",
        "source_language": "de",
        "target_language": "en",
        "use_cache": False
    }
    start_time = time.time()
    response = requests.post(f"{BASE_URL}/transformer/text", json=data)  # Korrekter Pfad
    duration = time.time() - start_time
    
    print(f"Response without cache (duration: {duration:.2f}s):")
    print(json.dumps(response.json(), indent=2))
    return duration

def test_transformer_with_cache():
    data = {
        "text": "Hallo Welt",
        "source_language": "de",
        "target_language": "en",
        "use_cache": True
    }
    
    # First call (should write to cache)
    start_time = time.time()
    response1 = requests.post(f"{BASE_URL}/transformer/text", json=data)  # Korrekter Pfad
    duration1 = time.time() - start_time
    
    # Second call (should read from cache)
    start_time = time.time()
    response2 = requests.post(f"{BASE_URL}/transformer/text", json=data)  # Korrekter Pfad
    duration2 = time.time() - start_time
    
    print(f"First call (duration: {duration1:.2f}s):")
    print(json.dumps(response1.json(), indent=2))
    
    print(f"Second call (duration: {duration2:.2f}s):")
    print(json.dumps(response2.json(), indent=2))
    
    # Verify it's from cache
    is_from_cache = response2.json().get("data", {}).get("is_from_cache", False)
    print(f"Is from cache: {is_from_cache}")
    print(f"Speed improvement: {(duration1/duration2):.2f}x faster")

if __name__ == "__main__":
    print("Testing transformer without cache...")
    no_cache_duration = test_transformer_without_cache()
    
    print("\nTesting transformer with cache...")
    test_transformer_with_cache()
```

## Überwachung der Verzeichnisstruktur

Während der Tests sollten wir die Cache-Verzeichnisstruktur überwachen:

```powershell
# Temporäres Verzeichnis anzeigen
dir cache\transformer\temp

# Cache-Verzeichnis anzeigen
dir cache\transformer
```

## Auswertung und Protokollierung

Für jeden Test sollten folgende Metriken protokolliert werden:

1. Antwortzeit (mit und ohne Cache)
2. Korrektheit der Ausgabe
3. Prozessor-spezifische Metriken (z.B. Genauigkeit der Transkription)
4. Cache-Effizienz (Geschwindigkeitsverbesserung in Prozent)
5. Verzeichnisstruktur (Ordnung und Klarheit)

## Fehlerbehandlung testen

Zusätzlich sollten wir Tests für Fehlerfälle durchführen:

1. Ungültige Eingabedaten
2. Zu große Dateien
3. Nicht unterstützte Formate
4. Ungültige URLs
5. Unerreichbare Server

## Nächste Schritte

1. Testdaten sammeln und in die entsprechenden Verzeichnisse legen
2. URLs für externe Testdaten identifizieren und eintragen
3. Testskripte für alle Prozessoren erstellen
4. Tests durchführen und Ergebnisse dokumentieren
5. Bei Bedarf Optimierungen vornehmen 