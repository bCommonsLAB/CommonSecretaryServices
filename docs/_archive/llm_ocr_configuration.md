# LLM-OCR Konfiguration

## Übersicht

Die LLM-basierte OCR-Integration ist vollständig über die `config.yaml` konfigurierbar. Alle wichtigen Parameter können zentral verwaltet werden.

## Konfigurationssektion: `processors.openai`

```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}        # OpenAI API Key (aus .env)
    vision_model: "gpt-4o"            # Vision API Modell
    max_image_size: 2048              # Maximale Bildgröße
    image_quality: 85                 # JPEG-Qualität
```

### **Verfügbare Parameter:**

| Parameter | Typ | Standard | Beschreibung |
|-----------|-----|----------|--------------|
| `api_key` | string | - | OpenAI API Key (erforderlich) |
| `vision_model` | string | `gpt-4o` | Vision API Modell |
| `max_image_size` | int | `2048` | Maximale Bildgröße in Pixeln |
| `image_quality` | int | `85` | JPEG-Kompressionsqualität (1-100) |

### **Unterstützte Vision-Modelle:**

| Modell | Beschreibung | Kosten | Empfehlung |
|--------|-------------|--------|------------|
| `gpt-4o` | Neuestes Modell, beste Qualität | Hoch | ✅ **Empfohlen** |
| `gpt-4o-mini` | Schneller, günstiger | Mittel | Für Tests |
| `gpt-4-vision-preview` | Älteres Modell | Hoch | Legacy |

## Umgebungsvariablen

### **`.env` Datei:**
```env
# OpenAI API Key
OPENAI_API_KEY=sk-your-openai-api-key-here

# Optional: Überschreibe Standard-Modell
OPENAI_VISION_MODEL=gpt-4o
```

### **Umgebungsvariablen:**
```bash
# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-key-here"

# Linux/macOS
export OPENAI_API_KEY="sk-your-key-here"
```

## Konfigurationsbeispiele

### **1. Standard-Konfiguration (empfohlen)**
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o"
    max_image_size: 2048
    image_quality: 85
```

### **2. Optimiert für Geschwindigkeit**
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o-mini"
    max_image_size: 1024
    image_quality: 75
```

### **3. Optimiert für Qualität**
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o"
    max_image_size: 4096
    image_quality: 95
```

### **4. Kostenoptimiert**
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o-mini"
    max_image_size: 1024
    image_quality: 80
```

## Performance-Einstellungen

### **Bildgröße (`max_image_size`)**
- **Klein (1024px)**: Schneller, günstiger, weniger Details
- **Mittel (2048px)**: Ausgewogen, empfohlen
- **Groß (4096px)**: Langsamer, teurer, beste Qualität

### **Bildqualität (`image_quality`)**
- **Niedrig (60-75)**: Schneller Upload, kleinere Dateien
- **Mittel (80-90)**: Ausgewogen, empfohlen
- **Hoch (95-100)**: Langsamer Upload, größere Dateien

## Kostenoptimierung

### **Modell-Auswahl:**
```yaml
# Günstigste Option
vision_model: "gpt-4o-mini"

# Ausgewogen
vision_model: "gpt-4o"

# Beste Qualität
vision_model: "gpt-4o"
```

### **Bildoptimierung:**
```yaml
# Kostenoptimiert
max_image_size: 1024
image_quality: 75

# Standard
max_image_size: 2048
image_quality: 85

# Qualitätsoptimiert
max_image_size: 4096
image_quality: 95
```

## Troubleshooting

### **Häufige Konfigurationsfehler:**

1. **"OpenAI API Key nicht gefunden"**
   ```yaml
   # ❌ Falsch
   processors:
     openai:
       api_key: ""  # Leerer Key
   
   # ✅ Richtig
   processors:
     openai:
       api_key: ${OPENAI_API_KEY}  # Aus .env
   ```

2. **"Invalid model"**
   ```yaml
   # ❌ Falsch
   vision_model: "gpt-4"  # Kein Vision-Modell
   
   # ✅ Richtig
   vision_model: "gpt-4o"  # Vision-Modell
   ```

3. **"Image too large"**
   ```yaml
   # ❌ Falsch
   max_image_size: 8192  # Zu groß
   
   # ✅ Richtig
   max_image_size: 2048  # Standard
   ```

### **Debugging:**
```yaml
# Aktiviere Debug-Logging
logging:
  level: DEBUG
  file: logs/llm_ocr_debug.log
```

## Erweiterte Konfiguration

### **Custom Prompts:**
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o"
    # Custom Prompts (optional)
    prompts:
      scientific: "Extrahiere wissenschaftlichen Text mit Formeln..."
      technical: "Extrahiere technische Dokumentation..."
      general: "Extrahiere allgemeinen Text..."
```

### **Rate Limiting:**
```yaml
processors:
  openai:
    api_key: ${OPENAI_API_KEY}
    vision_model: "gpt-4o"
    # Rate Limiting
    rate_limit:
      requests_per_minute: 10
      max_concurrent: 5
```

## Monitoring und Logging

### **LLM-Usage Tracking:**
Die Konfiguration wird automatisch in den API-Responses getrackt:

```json
{
  "process": {
    "llm_info": {
      "model": "gpt-4o",
      "tokens_used": 1250,
      "processing_time_ms": 3200,
      "image_size": "2048x1536",
      "image_quality": 85
    }
  }
}
```

### **Logging:**
```yaml
logging:
  level: DEBUG
  file: logs/llm_ocr.log
  # Spezielle LLM-Logs
  llm_ocr:
    enabled: true
    log_requests: true
    log_responses: false  # Aus Datenschutzgründen
```

## Nächste Schritte

1. **Konfiguriere deinen API-Key** in der `.env` Datei
2. **Wähle das passende Modell** für deine Anforderungen
3. **Optimiere Bildgröße und Qualität** nach Bedarf
4. **Überwache die Kosten** über die LLM-Info in den Responses
5. **Teste verschiedene Konfigurationen** für optimale Ergebnisse

Die Konfiguration ist flexibel und kann an deine spezifischen Anforderungen angepasst werden! 