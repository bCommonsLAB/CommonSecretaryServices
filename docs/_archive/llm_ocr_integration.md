# LLM-basierte OCR Integration

## Übersicht

Die CommonSecretaryServices unterstützen jetzt LLM-basierte OCR (Optical Character Recognition) mit OpenAI Vision API. Diese neue Funktionalität bietet hochwertige Textextraktion mit strukturiertem Markdown-Output.

## Vorteile der LLM-basierten OCR

### Gegenüber traditioneller OCR (Tesseract):
- **Strukturierte Ausgabe**: Automatische Markdown-Formatierung
- **Bessere Layout-Erkennung**: Versteht Dokumentstrukturen und Hierarchien
- **Intelligente Textanordnung**: Verarbeitet mehrspaltige Texte korrekt
- **Tabellenerkennung**: Konvertiert Tabellen automatisch zu Markdown-Tabellen
- **Bildbeschreibungen**: Erstellt Platzhalter mit detaillierten Beschreibungen für Bilder
- **Kontextverständnis**: Erkennt logische Zusammenhänge im Dokument

### Neue Extraktionsmethoden:

| Methode | Beschreibung | Verwendung |
|---------|-------------|------------|
| `llm` | Reine LLM-basierte OCR | Für hochwertige Markdown-Extraktion |
| `llm_and_native` | LLM + Native PDF-Text | Kombination für beste Abdeckung |
| `llm_and_ocr` | LLM + Tesseract OCR | Fallback-Strategie für schwierige Dokumente |

## Architektur

### Image2TextService
- **Zentrale Klasse**: `src/utils/image2text_utils.py`
- **OpenAI Integration**: Nutzt `gpt-4o` Vision API
- **Bildverarbeitung**: Automatische Größenanpassung und Optimierung
- **Prompt-Engineering**: Kontextabhängige Prompts für verschiedene Dokumenttypen

### Integration in bestehende Prozessoren
- **PDFProcessor**: Erweitert um LLM-OCR für PDF-Seiten
- **ImageOCRProcessor**: Erweitert um LLM-OCR für Einzelbilder
- **Caching**: Vollständig in das bestehende Cache-System integriert
- **LLM-Tracking**: Automatisches Tracking aller Vision API-Aufrufe

## Konfiguration

### config.yaml
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o"  # Modell für Vision API
    max_image_size: 2048    # Maximale Bildgröße für Vision API
    image_quality: 85       # JPEG-Qualität für Bildkompression
```

### Umgebungsvariablen
```bash
OPENAI_API_KEY=your_openai_api_key_here
```

## API-Nutzung

### PDF-Verarbeitung mit LLM-OCR

#### Einfache LLM-OCR
```bash
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@dokument.pdf" \
  -F "extraction_method=llm"
```

#### LLM-OCR mit Kontext
```bash
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@scientific_paper.pdf" \
  -F "extraction_method=llm" \
  -F "context={\"document_type\": \"scientific_paper\", \"language\": \"de\", \"extract_formulas\": true}"
```

#### Kombinierte Extraktion (LLM + Native)
```bash
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@dokument.pdf" \
  -F "extraction_method=llm_and_native"
```

### Bild-OCR mit LLM

#### LLM-OCR für Einzelbilder
```bash
curl -X POST "http://localhost:8000/imageocr/process" \
  -F "file=@screenshot.png" \
  -F "extraction_method=llm"
```

#### LLM + Tesseract Kombination
```bash
curl -X POST "http://localhost:8000/imageocr/process" \
  -F "file=@complex_document.jpg" \
  -F "extraction_method=llm_and_ocr"
```

## Erweiterte Prompt-Konfiguration

### Dokumenttyp-spezifische Prompts

```bash
# Wissenschaftliche Dokumente
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@paper.pdf" \
  -F "extraction_method=llm" \
  -F "context={\"document_type\": \"scientific_paper\"}"

# Präsentationen
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@slides.pdf" \
  -F "extraction_method=llm" \
  -F "context={\"document_type\": \"presentation\"}"

# Technische Dokumentation
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@manual.pdf" \
  -F "extraction_method=llm" \
  -F "context={\"document_type\": \"technical_document\"}"
```

### Spezielle Extraktionsoptionen

```bash
# Mit Formel-Extraktion
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@math_document.pdf" \
  -F "extraction_method=llm" \
  -F "context={\"extract_formulas\": true, \"preserve_formatting\": true}"

# Fokus auf Tabellen
curl -X POST "http://localhost:8000/pdf/process" \
  -F "file=@data_report.pdf" \
  -F "extraction_method=llm" \
  -F "context={\"focus_on_tables\": true}"
```

## Response-Format

### Erfolgreiche LLM-OCR Response
```json
{
  "status": "success",
  "request": {
    "processor": "PDFProcessor",
    "timestamp": "2024-01-15T10:30:00Z",
    "parameters": {
      "file_name": "document.pdf",
      "extraction_method": "llm"
    }
  },
  "process": {
    "id": "pdf_12345",
    "main_processor": "PDFProcessor",
    "started": "2024-01-15T10:30:00Z",
    "completed": "2024-01-15T10:30:15Z",
    "sub_processors": ["Image2TextService"],
    "llm_info": {
      "total_tokens": 2500,
      "total_duration": 12000,
      "total_requests": 3,
      "total_cost": 0.125,
      "requests": [
        {
          "model": "gpt-4o",
          "purpose": "image_to_markdown",
          "tokens": 850,
          "duration": 4000,
          "processor": "PDFProcessor-abc123"
        }
      ]
    }
  },
  "data": {
    "metadata": {
      "file_name": "document.pdf",
      "file_size": 1024000,
      "page_count": 3,
      "extraction_method": "llm"
    },
    "extracted_text": "# Dokumenttitel\n\n## Einleitung\n\nDies ist ein strukturiertes Markdown-Dokument...\n\n| Spalte 1 | Spalte 2 |\n|----------|----------|\n| Wert A   | Wert B   |\n\n![Diagramm zeigt Wachstumstrend](placeholder.jpg)"
  }
}
```

## Performance und Kosten

### Verarbeitungszeiten
- **LLM-OCR**: ~3-8 Sekunden pro Seite (abhängig von Komplexität)
- **Tesseract OCR**: ~1-2 Sekunden pro Seite
- **Native PDF**: ~0.1 Sekunden pro Seite

### Token-Verbrauch
- **Einfache Seite**: ~500-1000 Tokens
- **Komplexe Seite mit Tabellen**: ~1500-3000 Tokens
- **Seite mit vielen Bildern**: ~2000-4000 Tokens

### Kostenabschätzung (OpenAI gpt-4o)
- **Input**: $5.00 / 1M Tokens
- **Output**: $15.00 / 1M Tokens
- **Durchschnittliche Seite**: ~$0.01-0.05 pro Seite

## Fallback-Strategien

### Automatische Fallbacks
1. **LLM-Fehler**: Automatischer Fallback auf Tesseract OCR
2. **API-Limits**: Warteschlange mit Retry-Mechanismus
3. **Bildgröße**: Automatische Komprimierung bei Überschreitung

### Kombinierte Methoden
- **llm_and_native**: Nutzt beide Methoden für maximale Abdeckung
- **llm_and_ocr**: Vergleicht LLM und Tesseract Ergebnisse
- **Qualitätsbewertung**: Automatische Auswahl der besten Extraktion

## Debugging und Monitoring

### LLM-Request Tracking
- Alle Vision API-Aufrufe werden automatisch getrackt
- Token-Verbrauch und Kosten werden erfasst
- Performance-Metriken für jede Seite

### Debug-Ausgaben
- Bildkomprimierung und -optimierung
- Prompt-Generierung und -anpassung
- API-Response-Analyse

### Cache-Integration
- Vollständige Integration in MongoDB-Cache
- Cache-Keys berücksichtigen Extraktionsmethode und Kontext
- Effiziente Wiederverwendung bei identischen Anfragen

## Best Practices

### Wann LLM-OCR verwenden?
- **Strukturierte Dokumente**: Präsentationen, Berichte, wissenschaftliche Arbeiten
- **Komplexe Layouts**: Mehrspaltige Texte, Tabellen, Diagramme
- **Markdown-Output gewünscht**: Für weitere Verarbeitung oder Darstellung
- **Hohe Qualitätsanforderungen**: Wenn Genauigkeit wichtiger als Geschwindigkeit ist

### Wann traditionelle OCR verwenden?
- **Einfache Texte**: Reine Textdokumente ohne komplexe Struktur
- **Batch-Verarbeitung**: Große Mengen einfacher Dokumente
- **Kostenoptimierung**: Bei begrenztem Budget für API-Aufrufe
- **Offline-Verarbeitung**: Wenn keine Internetverbindung verfügbar

### Optimierungen
- **Dokumenttyp angeben**: Für bessere Prompt-Anpassung
- **Kontext nutzen**: Spezifische Extraktionsanforderungen definieren
- **Cache aktivieren**: Für Wiederverwendung bei identischen Dokumenten
- **Kombinierte Methoden**: Für maximale Abdeckung und Qualität

## Troubleshooting

### Häufige Probleme

#### OpenAI API-Fehler
```bash
# Fehler: "OpenAI API Key nicht gefunden"
# Lösung: OPENAI_API_KEY in .env setzen
echo "OPENAI_API_KEY=your_key_here" >> .env
```

#### Bildgröße-Probleme
```bash
# Fehler: "Bild zu groß für Vision API"
# Lösung: max_image_size in config.yaml anpassen
```

#### Token-Limits
```bash
# Fehler: "Token-Limit überschritten"
# Lösung: Dokument in kleinere Teile aufteilen oder max_tokens erhöhen
```

### Logging
- **Debug-Level**: Detaillierte Informationen über Bildverarbeitung
- **Info-Level**: API-Aufrufe und Verarbeitungszeiten
- **Error-Level**: Fehler und Fallback-Aktivierungen

## Migration von bestehenden Systemen

### Schrittweise Einführung
1. **Testen**: Neue Methoden parallel zu bestehenden testen
2. **Vergleichen**: Qualität und Performance bewerten
3. **Migrieren**: Schrittweise auf LLM-OCR umstellen
4. **Optimieren**: Prompts und Konfiguration anpassen

### Kompatibilität
- **API-Kompatibilität**: Bestehende Endpoints bleiben unverändert
- **Response-Format**: Identische Struktur wie bisherige OCR-Responses
- **Cache-Migration**: Bestehende Caches bleiben gültig 