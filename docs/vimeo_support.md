# Vimeo-Unterstützung im VideoProcessor

## Überblick

Der VideoProcessor unterstützt jetzt vollständig Vimeo-Videos, einschließlich Player-URLs und direkter Vimeo-URLs.

## Unterstützte URL-Formate

### 1. Vimeo-Player-URLs
```
https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1
```

### 2. Direkte Vimeo-URLs
```
https://vimeo.com/1029641432
```

### 3. Vimeo-URLs mit Parametern
```
https://vimeo.com/1029641432?h=abc123
```

## Implementierte Funktionen

### URL-Normalisierung
```python
def _normalize_vimeo_url(self, url: str) -> str:
    """
    Konvertiert Vimeo-Player-URLs in direkte Vimeo-URLs.
    
    Args:
        url: Die ursprüngliche URL
        
    Returns:
        str: Die normalisierte Vimeo-URL
    """
```

**Beispiel:**
- Input: `https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1`
- Output: `https://vimeo.com/1029641432`

### Erweiterte yt-dlp Konfiguration

```python
self.ydl_opts = {
    # ... Standard-Optionen ...
    
    # Vimeo-spezifische Optionen
    'extractor_args': {
        'vimeo': {
            'password': None,
            'access_token': None
        }
    },
    # Fallback-Formate für Vimeo
    'format_sort': ['ext:mp4:m4a', 'ext:webm:webma', 'ext:mp3'],
    'prefer_ffmpeg': True,
    'keepvideo': False
}
```

## Verwendung

### Über die API
```bash
curl -X POST "http://localhost:5000/api/video/process" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1",
    "target_language": "de",
    "template": "youtube"
  }'
```

### Über Python
```python
from src.processors.video_processor import VideoProcessor
from src.core.resource_tracking import ResourceCalculator
from src.core.models.video import VideoSource

# Processor erstellen
processor = VideoProcessor(ResourceCalculator(), process_id="test")

# VideoSource erstellen
video_source = VideoSource(url="https://player.vimeo.com/video/1029641432?byline=0&portrait=0&dnt=1")

# Video verarbeiten
response = await processor.process(
    source=video_source,
    target_language="de",
    template="youtube"
)
```

## Fehlerbehandlung

### Häufige Fehler und Lösungen

1. **"Keine Video-Informationen gefunden"**
   - Ursache: Video ist privat oder nicht verfügbar
   - Lösung: Prüfen Sie die URL und die Verfügbarkeit des Videos

2. **"Video zu lang"**
   - Ursache: Video überschreitet die maximale Dauer (Standard: 3600 Sekunden)
   - Lösung: Konfiguration anpassen oder kürzeres Video verwenden

3. **Download-Fehler**
   - Ursache: Netzwerkprobleme oder Vimeo-API-Änderungen
   - Lösung: yt-dlp aktualisieren oder später erneut versuchen

## Tests

### Unit-Tests
```bash
python -m pytest tests/test_vimeo_processor.py -v
```

### Integration-Test
```bash
python tests/test_vimeo_real.py
```

## Konfiguration

### VideoProcessor-Konfiguration
```yaml
processors:
  video:
    max_duration: 3600  # Maximale Videolänge in Sekunden
    ydl_opts:
      format: bestaudio/best
      postprocessors:
        - key: FFmpegExtractAudio
          preferredcodec: mp3
```

## Technische Details

### URL-Erkennung
- Regulärer Ausdruck: `r'https?://player\.vimeo\.com/video/(\d+)'`
- Extrahiert Video-ID aus Player-URLs
- Konvertiert in direkte Vimeo-URL

### Metadaten-Extraktion
- Titel des Videos
- Dauer in Sekunden
- Video-ID
- Zusätzliche Metadaten über yt-dlp

### Audio-Extraktion
- Automatische Konvertierung zu MP3
- FFmpeg-basierte Audio-Extraktion
- Optimierte Qualitätseinstellungen

## Bekannte Einschränkungen

1. **Private Videos**: Können nicht verarbeitet werden
2. **Passwort-geschützte Videos**: Erfordern zusätzliche Konfiguration
3. **Sehr lange Videos**: Können die maximale Dauer überschreiten
4. **Rate-Limiting**: Vimeo kann Downloads bei zu vielen Anfragen einschränken

## Troubleshooting

### Debug-Logging aktivieren
```python
import logging
logging.getLogger('src.processors.video_processor').setLevel(logging.DEBUG)
```

### yt-dlp aktualisieren
```bash
pip install --upgrade yt-dlp
```

### FFmpeg prüfen
```bash
ffmpeg -version
```

## Changelog

### Version 1.0.0
- ✅ Vimeo-Player-URL-Unterstützung
- ✅ URL-Normalisierung
- ✅ Erweiterte yt-dlp Konfiguration
- ✅ Umfassende Tests
- ✅ Dokumentation 