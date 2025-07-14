# Swagger Integration für LLM-OCR

## Übersicht

Die LLM-basierte OCR-Integration ist vollständig in die Swagger-UI integriert. Alle neuen Extraktionsmethoden sind als Dropdown-Menüs verfügbar, was die API-Nutzung erheblich vereinfacht.

## Verfügbare Dropdown-Optionen

### **PDF-Verarbeitung (`/api/pdf/process` und `/api/pdf/process-url`)**

| Option | Beschreibung | Verwendung |
|--------|-------------|------------|
| `native` | Nur native PDF-Text-Extraktion | Standard für Text-basierte PDFs |
| `ocr` | Nur Tesseract OCR | Für gescannte PDFs |
| `both` | OCR + Native Text | Kombinierte Extraktion |
| `preview` | Nur Vorschaubilder | Für Bildgenerierung |
| `preview_and_native` | Vorschaubilder + Native Text | Kombinierte Bild- und Textextraktion |
| `llm` | **LLM-basierte OCR** | **Neue Methode: Strukturierte Markdown-Ausgabe** |
| `llm_and_native` | **LLM + Native Text** | **Neue Methode: LLM + PDF-Text** |
| `llm_and_ocr` | **LLM + Tesseract OCR** | **Neue Methode: LLM + OCR** |

### **Image-OCR (`/api/imageocr/process` und `/api/imageocr/process-url`)**

| Option | Beschreibung | Verwendung |
|--------|-------------|------------|
| `ocr` | Nur Tesseract OCR | Standard für Bild-OCR |
| `native` | Native Bildanalyse | Für einfache Bildverarbeitung |
| `both` | OCR + Native Analyse | Kombinierte Bildverarbeitung |
| `preview` | Nur Vorschaubilder | Für Bildgenerierung |
| `preview_and_native` | Vorschaubilder + Native Analyse | Kombinierte Verarbeitung |
| `llm` | **LLM-basierte OCR** | **Neue Methode: Intelligente Bildanalyse** |
| `llm_and_ocr` | **LLM + Tesseract OCR** | **Neue Methode: LLM + OCR** |

## Swagger-UI Features

### **1. Dropdown-Menüs**
- Alle `extraction_method` Parameter sind als Dropdown-Menüs implementiert
- Klare Beschreibungen für jede Option
- Standardwerte sind vorausgewählt

### **2. Erweiterte Hilfe**
- Detaillierte Beschreibungen für jede Extraktionsmethode
- Verwendungshinweise direkt in der UI
- Beispiele für verschiedene Anwendungsfälle

### **3. Kontext-Parameter**
- JSON-Kontext für LLM-Optimierung
- Unterstützung für verschiedene Dokumenttypen
- Sprachspezifische Einstellungen

## Beispiel-Kontexte für LLM-OCR

### **Wissenschaftliche Dokumente**
```json
{
  "document_type": "scientific",
  "language": "de",
  "expected_content": "research_paper",
  "focus_areas": ["abstract", "methodology", "results", "conclusions"]
}
```

### **Technische Dokumentation**
```json
{
  "document_type": "technical",
  "language": "de",
  "expected_content": "technical_documentation",
  "focus_areas": ["diagrams", "tables", "code_blocks", "procedures"]
}
```

### **Präsentationen**
```json
{
  "document_type": "presentation",
  "language": "de",
  "expected_content": "slides",
  "focus_areas": ["bullet_points", "charts", "key_messages"]
}
```

### **Diagramme und Grafiken**
```json
{
  "document_type": "diagram",
  "language": "de",
  "expected_content": "technical_diagram",
  "focus_areas": ["flow_charts", "system_architecture", "data_flows"]
}
```

## Swagger-UI Navigation

### **1. PDF-Verarbeitung testen**
1. Öffne Swagger-UI: `http://localhost:8000/`
2. Navigiere zu `pdf` → `POST /api/pdf/process`
3. Klicke auf "Try it out"
4. Wähle eine Datei aus
5. Wähle `extraction_method` aus dem Dropdown
6. Füge optional einen Kontext hinzu
7. Klicke auf "Execute"

### **2. Image-OCR testen**
1. Navigiere zu `imageocr` → `POST /api/imageocr/process`
2. Klicke auf "Try it out"
3. Wähle eine Bilddatei aus
4. Wähle `extraction_method` aus dem Dropdown
5. Füge optional einen Kontext hinzu
6. Klicke auf "Execute"

### **3. URL-basierte Verarbeitung**
1. Verwende `POST /api/pdf/process-url` oder `POST /api/imageocr/process-url`
2. Gib eine URL ein
3. Wähle die gewünschte Extraktionsmethode
4. Führe den Test aus

## Vorteile der Swagger-Integration

### **Benutzerfreundlichkeit**
- ✅ Keine manuelle Eingabe von Extraktionsmethoden
- ✅ Klare Beschreibungen für jede Option
- ✅ Standardwerte sind vorausgewählt
- ✅ Fehlerfreie Parameter-Eingabe

### **Entwicklerfreundlichkeit**
- ✅ Automatische API-Dokumentation
- ✅ Interaktive Tests direkt in der UI
- ✅ Sofortige Validierung von Parametern
- ✅ Einfache Integration in andere Systeme

### **Qualitätssicherung**
- ✅ Validierung aller Eingabeparameter
- ✅ Konsistente API-Nutzung
- ✅ Klare Fehlermeldungen
- ✅ Vollständige Dokumentation

## Beispiel-Responses

### **LLM-OCR Response (PDF)**
```json
{
  "status": "success",
  "data": {
    "pages": [
      {
        "page_number": 1,
        "llm_text": "# Dokumententitel\n\nDies ist ein strukturierter Markdown-Text...",
        "native_text": "Roher PDF-Text...",
        "ocr_text": "OCR-extrahiertes Text..."
      }
    ],
    "process": {
      "llm_info": {
        "model": "gpt-4-vision-preview",
        "tokens_used": 1250,
        "processing_time_ms": 3200
      }
    }
  }
}
```

### **LLM-OCR Response (Image)**
```json
{
  "status": "success",
  "data": {
    "llm_text": "## Technisches Diagramm\n\nDas Diagramm zeigt einen Datenfluss...",
    "extracted_text": "OCR-Text...",
    "metadata": {
      "file_name": "diagram.jpg",
      "dimensions": "800x600"
    }
  }
}
```

## Troubleshooting

### **Häufige Probleme**

1. **"Invalid extraction_method"**
   - Verwende nur die verfügbaren Dropdown-Optionen
   - Überprüfe die Schreibweise

2. **"LLM service not available"**
   - Überprüfe OpenAI API-Key in der Konfiguration
   - Stelle sicher, dass der Service läuft

3. **"Timeout error"**
   - LLM-Verarbeitung kann länger dauern
   - Erhöhe Timeout-Werte bei Bedarf

### **Debugging**
- Überprüfe die Logs: `logs/app.log`
- Verwende `useCache=false` für Tests
- Teste zuerst mit einfachen Dokumenten

## Nächste Schritte

1. **Teste die neuen LLM-Methoden** in der Swagger-UI
2. **Vergleiche Ergebnisse** zwischen traditioneller OCR und LLM-OCR
3. **Experimentiere mit verschiedenen Kontexten** für optimale Ergebnisse
4. **Integriere in eigene Anwendungen** über die API

Die Swagger-Integration macht die LLM-OCR-Features einfach zugänglich und testbar! 