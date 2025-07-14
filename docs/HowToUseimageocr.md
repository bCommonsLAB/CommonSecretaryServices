# Image-OCR API Dokumentation

## POST /api/imageocr/process

**Bild mit OCR verarbeiten** - Extrahiert Text aus Bildern mittels OCR oder LLM-basierter Analyse.

### Request

**Content-Type:** `multipart/form-data`

| Parameter | Typ | Pflicht | Beschreibung |
|-----------|-----|---------|--------------|
| `file` | File | ✅ | Bilddatei (JPG, PNG, etc.) |
| `extraction_method` | string | ❌ | Extraktionsmethode (Standard: `ocr`) |
| `context` | string | ❌ | JSON-Kontext für LLM-Optimierung |
| `useCache` | boolean | ❌ | Cache verwenden (Standard: `true`) |

**Verfügbare Extraktionsmethoden:**
- `ocr` - Tesseract OCR (Standard)
- `llm` - **LLM-basierte OCR mit Markdown**
- `llm_and_ocr` - LLM + Tesseract OCR
- `native` - Native Bildanalyse
- `both` - OCR + Native Analyse
- `preview` - Nur Vorschaubilder
- `preview_and_native` - Vorschaubilder + Native Analyse

### Beispiel Request

```bash
curl -X POST "http://localhost:8000/api/imageocr/process" \
  -F "file=@diagram.jpg" \
  -F "extraction_method=llm" \
  -F "context={\"document_type\":\"technical\",\"language\":\"de\"}" \
  -F "useCache=false"
```

### Response

```json
{
  "status": "success",
  "request": {
    "processor": "imageocr",
    "timestamp": "2025-07-14T11:00:15.298525",
    "parameters": {
      "file_path": "C:\\Users\\peter.aichner\\projects\\CommonSecretaryServices\\src\\api\\routes\\temp_1fd7842f-b7b2-48d6-a069-85c5708e748f.jpg",
      "template": null,
      "context": null,
      "extraction_method": "llm"
    }
  },
  "process": {
    "id": "5f78ab61-9d9a-49f2-8aa5-6fd3899c6bf3",
    "main_processor": "ImageOCRProcessor",
    "started": "2025-07-14T10:59:55.081376",
    "sub_processors": [
      "TransformerProcessor"
    ],
    "completed": null,
    "duration": null,
    "is_from_cache": false,
    "cache_key": "",
    "llm_info": {
      "requests": [
        {
          "model": "gpt-4o-mini",
          "purpose": "image_to_markdown",
          "tokens": 37966,
          "duration": 18591.046810150146,
          "processor": "ImageOCRProcessor-5f78ab61-9d9a-49f2-8aa5-6fd3899c6bf3",
          "timestamp": "2025-07-14T11:00:15.298525"
        }
      ],
      "requests_count": 1,
      "total_tokens": 37966,
      "total_duration": 18591.046810150146
    }
  },
  "error": null,
  "data": {
    "metadata": {
      "file_name": "temp_1fd7842f-b7b2-48d6-a069-85c5708e748f.jpg",
      "file_size": 977509,
      "dimensions": "2359x3188",
      "format": "JPEG",
      "color_mode": "RGB",
      "dpi": [
        96,
        96
      ],
      "process_dir": "cache\\imageocr\\temp\\working",
      "extraction_method": "llm",
      "preview_paths": []
    },
    "extracted_text": "# ALLGEMEINER TEIL\n\n## NATURRÄUMLICHE VORAUSSETZUNGEN, LEBENSRÄUME\n\n![Bildbeschreibung](placeholder.jpg)\nDie weltberühmten Dolomiten entstanden im Laufe von Millionen von Jahren aus Sedimenten des ehemaligen Meeresbodens.\n\n### Topographie\n\nSüdtirol ist mit seinen 7.400,43 km² Gesamtfläche eines der landschaftlich vielfältigsten Länder Europas. Die extrem unterschiedliche naturräumliche Gliederung wird durch hohe Gebirge und tief eingeschnittene Täler reflektiert und die Höhenstreckung reicht von höchsten Gipfel der Ostalpen, dem 3902 m hohen Ortler, bis zu 210 m  vulkanischen Gesteinen dominiert, dem durch seine rötliche Färbung auffallenden Bozner Quarzporphyr.",
    "process_id": "5f78ab61-9d9a-49f2-8aa5-6fd3899c6bf3",
    "processed_at": "2025-07-14T09:00:15.298525+00:00",
    "status": "success"
  }
}
```

### Wichtige Felder

- **`data.extracted_text`**: Extrahierter Text (Markdown bei LLM-Methoden)
- **`process.llm_info`**: LLM-Nutzungsdaten (nur bei LLM-Methoden)
- **`data.metadata.extraction_method`**: Verwendete Extraktionsmethode
- **`data.process_id`**: Eindeutige Prozess-ID für Tracking

### Fehler

```json
{
  "status": "error",
  "error": {
    "code": "ValidationError",
    "message": "Keine Datei hochgeladen"
  }
}
```

**Status Codes:** 200 (Erfolg), 400 (Validierungsfehler), 500 (Server-Fehler)

### Weitere Beispiele

#### PowerShell
```powershell
$form = @{
    file = Get-Item "diagram.jpg"
    extraction_method = "llm"
    context = '{"document_type":"technical","language":"de"}'
    useCache = "false"
}
$result = Invoke-RestMethod -Uri "http://localhost:8000/api/imageocr/process" -Method Post -Form $form
$result.data.extracted_text
```

#### Python
```python
import requests

with open('diagram.jpg', 'rb') as f:
    files = {'file': f}
    data = {
        'extraction_method': 'llm',
        'context': '{"document_type":"technical","language":"de"}',
        'useCache': 'false'
    }
    response = requests.post('http://localhost:8000/api/imageocr/process', files=files, data=data)
    result = response.json()
    print(result['data']['extracted_text'])
```

#### JavaScript
```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('extraction_method', 'llm');
formData.append('context', JSON.stringify({document_type: 'technical', language: 'de'}));
formData.append('useCache', 'false');

fetch('http://localhost:8000/api/imageocr/process', {
    method: 'POST',
    body: formData
})
.then(response => response.json())
.then(data => console.log(data.data.extracted_text));
``` 