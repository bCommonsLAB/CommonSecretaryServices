# PDF- und ImageOCR-Prozessoren Dokumentation

## Übersicht

Die CommonSecretaryServices bieten zwei spezialisierte Prozessoren für die Verarbeitung von Dokumenten und Bildern:

- **PDF-Processor**: Verarbeitet PDF-Dateien und extrahiert Text, Metadaten und Vorschaubilder
- **ImageOCR-Processor**: Führt OCR (Optical Character Recognition) auf Bildern durch

Beide Prozessoren unterstützen:
- Upload von lokalen Dateien
- Verarbeitung von URLs
- Template-basierte Transformation
- Caching für bessere Performance
- Verschiedene Extraktionsmethoden

## PDF-Processor

### Verfügbare Endpoints

#### 1. `/pdf/process` - Datei-Upload
Verarbeitet eine hochgeladene PDF-Datei.

**HTTP-Methode**: POST  
**Content-Type**: multipart/form-data

**Parameter**:
- `file` (required): PDF-Datei
- `extraction_method` (optional): Extraktionsmethode (default: "native")
  - `native`: Nur Textextraktion
  - `ocr`: Nur OCR-Verarbeitung
  - `both`: Text und OCR
  - `preview`: Nur Vorschaubilder
  - `preview_and_native`: Vorschaubilder und Text
- `template` (optional): Template für Transformation
- `context` (optional): JSON-Kontext für Verarbeitung
- `useCache` (optional): Cache verwenden (default: true)

#### 2. `/pdf/process-url` - URL-Verarbeitung
Verarbeitet eine PDF-Datei von einer URL.

**HTTP-Methode**: POST  
**Content-Type**: application/x-www-form-urlencoded

**Parameter**:
- `url` (required): URL zur PDF-Datei
- Weitere Parameter wie bei `/pdf/process`

#### 3. `/pdf/text-content/<path:file_path>` - Textinhalt abrufen
Ruft den Inhalt einer durch den PDF-Prozessor erstellten Textdatei ab.

**HTTP-Methode**: GET

### Anwendungsbeispiele PDF-Processor

#### Beispiel 1: Einfache PDF-Textextraktion

```bash
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@dokument.pdf" \
  -F "extraction_method=native"
```

#### Beispiel 2: PDF mit OCR und Template

```bash
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@gescanntes_dokument.pdf" \
  -F "extraction_method=ocr" \
  -F "template=Metadata" \
  -F "context={\"document_type\": \"invoice\"}"
```

#### Beispiel 3: PDF von URL mit Vorschaubildern

```bash
curl -X POST "http://localhost:8000/pdf/process-url" \
  -d "url=https://example.com/dokument.pdf" \
  -d "extraction_method=preview_and_native"
```

#### Beispiel 4: PowerPoint-Datei von URL

```bash
curl -X POST "http://localhost:8000/pdf/process-url" \
  -d "url=https://example.com/presentation.pptx" \
  -d "extraction_method=both"
```

### Antwortformat PDF-Processor

```json
{
  "status": "success",
  "request": {
    "processor": "PDFProcessor",
    "timestamp": "2024-01-15T10:30:00Z",
    "parameters": {
      "file_name": "dokument.pdf",
      "extraction_method": "native"
    }
  },
  "process": {
    "id": "pdf_12345",
    "main_processor": "PDFProcessor",
    "started": "2024-01-15T10:30:00Z",
    "completed": "2024-01-15T10:30:05Z",
    "sub_processors": ["text_extractor"],
    "llm_info": {
      "model": "gpt-4",
      "tokens_used": 150
    }
  },
  "data": {
    "metadata": {
      "file_name": "dokument.pdf",
      "file_size": 1024000,
      "page_count": 10,
      "format": "PDF",
      "process_dir": "cache/pdf_12345/",
      "text_contents": [
        {
          "page": 1,
          "content": "Seite 1 Textinhalt..."
        }
      ],
      "extraction_method": "native"
    },
    "extracted_text": "Vollständiger extrahierter Text...",
    "process_id": "pdf_12345"
  }
}
```

## ImageOCR-Processor

### Verfügbare Endpoints

#### 1. `/imageocr/process` - Datei-Upload
Verarbeitet ein hochgeladenes Bild mit OCR.

**HTTP-Methode**: POST  
**Content-Type**: multipart/form-data

**Parameter**:
- `file` (required): Bilddatei
- `extraction_method` (optional): Extraktionsmethode (default: "ocr")
- `template` (optional): Template für Transformation
- `context` (optional): JSON-Kontext für Verarbeitung
- `useCache` (optional): Cache verwenden (default: true)

#### 2. `/imageocr/process-url` - URL-Verarbeitung
Verarbeitet ein Bild von einer URL mit OCR.

**HTTP-Methode**: POST  
**Content-Type**: application/x-www-form-urlencoded

**Parameter**:
- `url` (required): URL zum Bild
- Weitere Parameter wie bei `/imageocr/process`

### Anwendungsbeispiele ImageOCR-Processor

#### Beispiel 1: Einfache Bild-OCR

```bash
curl -X POST "http://localhost:8000/imageocr/process" \
  -F "file=@screenshot.png"
```

#### Beispiel 2: Bild mit Template-Transformation

```bash
curl -X POST "http://localhost:8000/imageocr/process" \
  -F "file=@rechnung.jpg" \
  -F "template=Metadata" \
  -F "context={\"document_type\": \"invoice\"}"
```

#### Beispiel 3: Bild von URL verarbeiten

```bash
curl -X POST "http://localhost:8000/imageocr/process-url" \
  -d "url=https://example.com/image.png"
```

#### Beispiel 4: Mit deaktiviertem Cache

```bash
curl -X POST "http://localhost:8000/imageocr/process" \
  -F "file=@dynamic_content.png" \
  -F "useCache=false"
```

### Antwortformat ImageOCR-Processor

```json
{
  "status": "success",
  "request": {
    "processor": "ImageOCRProcessor",
    "timestamp": "2024-01-15T10:30:00Z",
    "parameters": {
      "file_name": "screenshot.png",
      "extraction_method": "ocr"
    }
  },
  "process": {
    "id": "ocr_12345",
    "main_processor": "ImageOCRProcessor",
    "started": "2024-01-15T10:30:00Z",
    "completed": "2024-01-15T10:30:03Z",
    "sub_processors": ["tesseract_ocr"],
    "llm_info": {
      "model": "gpt-4",
      "tokens_used": 80
    }
  },
  "data": {
    "metadata": {
      "file_name": "screenshot.png",
      "file_size": 512000,
      "dimensions": "1920x1080",
      "format": "PNG",
      "process_dir": "cache/ocr_12345/"
    },
    "extracted_text": "Extrahierter Text aus dem Bild...",
    "formatted_text": "Formatierter Text (wenn Template verwendet)...",
    "process_id": "ocr_12345",
    "model": "tesseract"
  }
}
```

## Template-System

Beide Prozessoren unterstützen Templates zur Transformation der extrahierten Daten:

### Verfügbare Templates

- `Metadata`: Strukturierte Metadaten-Extraktion
- `Blogeintrag`: Blog-Artikel Format
- `Besprechung`: Besprechungsprotokoll
- `Session_de`: Deutsche Session-Beschreibung
- `Youtube`: YouTube-Video Beschreibung

### Template-Verwendung

```bash
# Mit Metadata-Template
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@dokument.pdf" \
  -F "template=Metadata" \
  -F "context={\"language\": \"de\", \"category\": \"technical\"}"
```

## Unterstützte Dateiformate

### PDF-Processor
- **PDF-Dateien**: .pdf
- **PowerPoint-Dateien**: .ppt, .pptx (werden automatisch zu PDF konvertiert)
- **URLs**: HTTP/HTTPS-Links zu unterstützten Dateien

### ImageOCR-Processor
- **Bildformate**: .png, .jpg, .jpeg, .gif, .bmp, .tiff
- **URLs**: HTTP/HTTPS-Links zu Bildern

## Extraktionsmethoden

### PDF-Processor Extraktionsmethoden

| Methode | Beschreibung | Verwendung |
|---------|-------------|------------|
| `native` | Nur Textextraktion | Für digitale PDFs mit vorhandenem Text |
| `ocr` | Nur OCR-Verarbeitung | Für gescannte Dokumente |
| `both` | Text und OCR | Für gemischte Dokumente |
| `preview` | Nur Vorschaubilder | Für visuelle Analyse |
| `preview_and_native` | Vorschaubilder und Text | Für komplette Dokumentanalyse |

### ImageOCR-Processor Extraktionsmethoden

| Methode | Beschreibung | Verwendung |
|---------|-------------|------------|
| `ocr` | Standard-OCR | Für die meisten Bildtypen |

## Caching

Beide Prozessoren verwenden intelligentes Caching:

- **Cache-Key**: Basiert auf Datei-Hash (MD5) oder URL-Hash
- **Cache-Dauer**: Konfigurierbar über `config.yaml`
- **Cache-Deaktivierung**: `useCache=false` Parameter
- **Cache-Speicherort**: `cache/` Verzeichnis

### Cache-Beispiele

```bash
# Mit Cache (Standard)
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@dokument.pdf"

# Ohne Cache
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@dokument.pdf" \
  -F "useCache=false"
```

## Performance-Optimierung

### Best Practices

1. **Cache nutzen**: Für wiederkehrende Verarbeitungen
2. **Richtige Extraktionsmethode wählen**: 
   - `native` für digitale PDFs
   - `ocr` nur wenn nötig
3. **Template-Verwendung**: Für strukturierte Ausgaben
4. **Dateigrößen beachten**: Große Dateien länger Verarbeitungszeit
5. **URL-Verarbeitung**: Für entfernte Dateien ohne lokalen Download

### Performance-Monitoring

Jede Antwort enthält `process.llm_info` mit:
- Verwendetem Modell
- Token-Verbrauch
- Verarbeitungszeit

## Fehlerbehandlung

### Häufige Fehler

| Fehlercode | Beschreibung | Lösung |
|------------|-------------|---------|
| `ProcessingError` | Allgemeiner Verarbeitungsfehler | Datei und Parameter prüfen |
| `FileNotFoundError` | Datei nicht gefunden | Pfad und Berechtigung prüfen |
| `ValidationError` | Ungültige Parameter | Parameter-Format prüfen |
| `NetworkError` | URL nicht erreichbar | URL und Internetverbindung prüfen |

### Fehler-Antwortformat

```json
{
  "status": "error",
  "error": {
    "code": "ProcessingError",
    "message": "Datei konnte nicht verarbeitet werden",
    "details": {
      "error_type": "ProcessingError",
      "traceback": "Detaillierte Fehlerinformationen..."
    }
  }
}
```

## Integration und Workflow

### Typischer Workflow

1. **Datei hochladen/URL angeben**
2. **Extraktionsmethode wählen**
3. **Template und Kontext definieren** (optional)
4. **Verarbeitung starten**
5. **Ergebnis abrufen**
6. **Bei Bedarf Textinhalte über separate Endpoints abrufen**

### Python-Integration

```python
import requests

# PDF verarbeiten
with open('dokument.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:8000/pdf/process',
        files={'file': f},
        data={
            'extraction_method': 'native',
            'template': 'Metadata'
        }
    )
    
result = response.json()
extracted_text = result['data']['extracted_text']
```

### JavaScript-Integration

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('extraction_method', 'ocr');

fetch('/imageocr/process', {
    method: 'POST',
    body: formData
})
.then(response => response.json())
.then(data => {
    console.log('OCR Result:', data.data.extracted_text);
});
```

## Konfiguration

### Umgebungsvariablen

```yaml
# config.yaml
pdf_processor:
  temp_dir: "./cache/pdf/"
  max_file_size: 100MB
  ocr_engine: "tesseract"
  
imageocr_processor:
  temp_dir: "./cache/imageocr/"
  max_file_size: 50MB
  ocr_language: "deu"
  
cache:
  enabled: true
  ttl: 3600  # 1 Stunde
```

### Sicherheitshinweise

1. **Dateigröße begrenzen**: Maximal 100MB für PDFs, 50MB für Bilder
2. **Pfad-Validierung**: Nur Cache-Verzeichnis-Zugriff erlaubt
3. **URL-Validierung**: Nur HTTP/HTTPS-URLs erlaubt
4. **Temporäre Dateien**: Werden automatisch nach Verarbeitung gelöscht

## Monitoring und Logging

### Log-Ausgaben

```
2024-01-15 10:30:00 INFO [PDFProcessor] Started processing: dokument.pdf
2024-01-15 10:30:02 INFO [PDFProcessor] Extracted text: 1500 characters
2024-01-15 10:30:05 INFO [PDFProcessor] Completed processing: pdf_12345
```

### Performance-Metriken

- Verarbeitungszeit pro Datei
- Cache-Trefferquote
- Token-Verbrauch
- Speichernutzung

## Erweiterte Funktionen

### Batch-Verarbeitung

Für mehrere Dateien können Sie die Endpoints in Schleifen aufrufen:

```bash
#!/bin/bash
for file in *.pdf; do
    curl -X POST "http://localhost:8000/pdf/process" \
      -F "file=@$file" \
      -F "extraction_method=native"
done
```

### Asynchrone Verarbeitung

Beide Prozessoren unterstützen asynchrone Verarbeitung für bessere Performance bei großen Dateien.

## Support und Troubleshooting

### Häufige Probleme

1. **Lange Verarbeitungszeiten**: 
   - Dateigröße reduzieren
   - Cache aktivieren
   - Richtige Extraktionsmethode wählen

2. **OCR-Qualität schlecht**:
   - Bildqualität verbessern
   - Kontrast erhöhen
   - Richtige Sprache konfigurieren

3. **Template-Fehler**:
   - Template-Syntax prüfen
   - Kontext-Parameter validieren
   - Logs für Details prüfen

### Debugging

```bash
# Verbose Logging aktivieren
export LOG_LEVEL=DEBUG

# Test mit kleiner Datei
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@test.pdf" \
  -F "extraction_method=native" \
  -v
```

## Fazit

Die PDF- und ImageOCR-Prozessoren bieten eine umfassende Lösung für die Verarbeitung von Dokumenten und Bildern. Durch die flexible API, das Template-System und die verschiedenen Extraktionsmethoden können sie für eine Vielzahl von Anwendungsfällen eingesetzt werden.

Weitere Informationen finden Sie in der allgemeinen API-Dokumentation und den Processor-spezifischen Dokumentationen. 