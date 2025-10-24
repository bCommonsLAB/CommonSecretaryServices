# Session Processing: Cache & Logging Inspektion

## Überblick

Session-Verarbeitungen werden in zwei Systemen persistent gespeichert:
1. **MongoDB Cache** - Für Prozessergebnisse und Wiederverwendung
2. **Log-Dateien** - Für Debugging und Monitoring

## 1. MongoDB Cache

### Collection-Name
```
session_cache
```

Die Cache-Collection wird in MongoDB gespeichert und enthält alle verarbeiteten Sessions mit ihren Ergebnissen.

### Datenstruktur im Cache

```javascript
{
  "_id": ObjectId("..."),
  "cache_key": "8f3d2a1b...",  // Hash basierend auf Session-Parametern
  "status": "success",
  "processed_at": "2024-10-24T12:34:56.789Z",
  "data": {
    "event": "FOSDEM 2025",
    "session": "Welcome Talk",
    "track": "keynotes",
    "target_language": "de",
    "template": "Session_de"
  },
  "result": {
    "web_text": "...",
    "video_transcript": "...",
    "markdown_content": "...",
    "markdown_file": "/path/to/file.md",
    "target_dir": "/path/to/sessions/...",
    "attachment_paths": [...],
    "page_texts": [...],
    "process_id": "abc-123-...",
    "input_data": {
      "event": "FOSDEM 2025",
      "session": "Welcome Talk",
      "url": "https://...",
      "filename": "welcome.md",
      "track": "keynotes",
      "video_url": "https://...",
      "video_transcript": null,
      "attachments_url": "https://...",
      ...
    },
    "structured_data": {
      "topic": "...",
      "relevance": "...",
      ...
    }
  }
}
```

### Cache-Zugriff über API

#### Alle gecachten Sessions abrufen
```bash
curl http://localhost:5000/api/session/cached
```

Response:
```json
{
  "status": "success",
  "count": 42,
  "sessions": [
    {
      "cache_id": "6543...",
      "processed_at": "2024-10-24T12:34:56.789Z",
      "event": "FOSDEM 2025",
      "session": "Welcome Talk",
      "track": "keynotes",
      "target_language": "de",
      "url": "https://...",
      "filename": "welcome.md",
      "web_text": "...",
      "video_transcript": "...",
      "markdown_file": "/path/to/file.md",
      "target_dir": "/path/to/sessions/...",
      "attachment_count": 3,
      "page_count": 12,
      "process_id": "abc-123-..."
    }
  ]
}
```

### Direkte MongoDB-Abfrage

#### Alle Sessions anzeigen
```bash
mongosh
use <your-database-name>
db.session_cache.find().pretty()
```

#### Sessions nach Event filtern
```javascript
db.session_cache.find({
  "data.event": "FOSDEM 2025"
}).pretty()
```

#### Sessions nach Datum filtern
```javascript
db.session_cache.find({
  "processed_at": {
    $gte: ISODate("2024-10-24T00:00:00Z")
  }
}).sort({ "processed_at": -1 })
```

#### Nur bestimmte Felder anzeigen
```javascript
db.session_cache.find(
  { "data.event": "FOSDEM 2025" },
  { 
    "data.session": 1,
    "data.track": 1,
    "processed_at": 1,
    "result.markdown_file": 1
  }
).pretty()
```

#### Cache-Statistik
```javascript
// Anzahl gecachter Sessions
db.session_cache.countDocuments()

// Sessions pro Event
db.session_cache.aggregate([
  { $group: {
    _id: "$data.event",
    count: { $sum: 1 }
  }}
])

// Neueste Sessions
db.session_cache.find().sort({ "processed_at": -1 }).limit(10)
```

### Cache-Indizes

Die Session-Cache-Collection hat folgende Indizes für schnelle Suchen:
- `event` (1)
- `session` (1)
- `track` (1)
- `processed_at` (1)
- `target_language` (1)

## 2. Logging

### Log-Datei Konfiguration

**Konfiguration:** `config/config.yaml`
```yaml
logging:
  file: logs/dev_detailed.log
  level: DEBUG
  max_size: 120000000      # 120 MB
  backup_count: 5          # 5 Rotations
```

### Log-Dateien

**Haupt-Log:**
```
logs/dev_detailed.log
```

**Rotierte Logs:**
```
logs/dev_detailed.log.1
logs/dev_detailed.log.2
...
```

### Log-Format

```
2024-10-24 12:34:56,789 - INFO - session_processor - [abc-123] Starte Verarbeitung von Session: Welcome Talk
2024-10-24 12:34:57,123 - DEBUG - session_processor - [abc-123] Session-Seite verarbeitet {"url": "https://...", "text_length": 4521}
2024-10-24 12:35:01,456 - INFO - session_processor - [abc-123] Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)
2024-10-24 12:35:05,789 - DEBUG - session_processor - [abc-123] Anhänge verarbeitet {"gallery_count": 12, "page_count": 12}
2024-10-24 12:35:10,123 - INFO - session_processor - [abc-123] ZIP-Archiv erstellt: welcome_2024-10-24.zip
```

### Log-Zugriff

#### Tail (letzte Einträge live)
```bash
# Linux/Mac
tail -f logs/dev_detailed.log

# Windows PowerShell
Get-Content logs/dev_detailed.log -Wait -Tail 50
```

#### Nach Process-ID filtern
```bash
# Linux/Mac
grep "abc-123" logs/dev_detailed.log

# Windows PowerShell
Select-String -Path logs/dev_detailed.log -Pattern "abc-123"
```

#### Nach Session-Namen filtern
```bash
# Linux/Mac
grep "Welcome Talk" logs/dev_detailed.log

# Windows PowerShell
Select-String -Path logs/dev_detailed.log -Pattern "Welcome Talk"
```

#### Fehler anzeigen
```bash
# Linux/Mac
grep -E "ERROR|CRITICAL" logs/dev_detailed.log

# Windows PowerShell
Select-String -Path logs/dev_detailed.log -Pattern "ERROR|CRITICAL"
```

#### Heute's Logs
```bash
# Linux/Mac
grep "2024-10-24" logs/dev_detailed.log

# Windows PowerShell
Select-String -Path logs/dev_detailed.log -Pattern "2024-10-24"
```

### Log-Levels

- **DEBUG**: Detaillierte technische Informationen (Parameterwerte, Zwischenergebnisse)
- **INFO**: Normale Verarbeitungsschritte (Start/Ende, Erfolge)
- **WARNING**: Potenzielle Probleme (fehlgeschlagene optionale Schritte)
- **ERROR**: Fehler (fehlgeschlagene Verarbeitung)
- **CRITICAL**: Kritische Systemfehler

### Wichtige Log-Events bei Session-Verarbeitung

1. **Start**
   ```
   INFO - Starte Verarbeitung von Session: {session_name}
   ```

2. **Webseite scraped**
   ```
   DEBUG - Session-Seite verarbeitet {"url": "...", "text_length": 4521}
   ```

3. **Video-Verarbeitung**
   ```
   # Mit video_url
   INFO - Verarbeite Video: https://...
   DEBUG - Video verarbeitet {"duration": 1234, "transcript_length": 5678}
   
   # Mit video_transcript
   INFO - Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)
   ```

4. **Anhänge verarbeitet**
   ```
   DEBUG - Anhänge verarbeitet {"gallery_count": 12, "page_count": 12, "asset_dir": "..."}
   ```

5. **Markdown generiert**
   ```
   INFO - Markdown generiert {"file": "...", "content_length": 12345}
   ```

6. **ZIP-Archiv erstellt**
   ```
   INFO - ZIP-Archiv erstellt: welcome_2024-10-24.zip
   ```

7. **Cache-Speicherung**
   ```
   DEBUG - Session-Ergebnis im Cache gespeichert: 8f3d2a1b...
   ```

8. **Abschluss**
   ```
   INFO - Session-Verarbeitung beendet
   ```

## 3. Performance-Tracking

Jede Session-Response enthält detaillierte Performance-Informationen:

```json
{
  "status": "success",
  "process": {
    "id": "abc-123-def-456",
    "main_processor": "session",
    "started": "2024-10-24T12:34:56.789Z",
    "completed": "2024-10-24T12:35:10.123Z",
    "duration": 13.334,
    "is_from_cache": false,
    "cache_key": "8f3d2a1b...",
    "llm_info": {
      "total_calls": 5,
      "total_prompt_tokens": 12345,
      "total_completion_tokens": 6789,
      "total_tokens": 19134,
      "total_cost_usd": 0.1234,
      "by_model": {
        "gpt-4o": {
          "calls": 3,
          "prompt_tokens": 8000,
          "completion_tokens": 4000,
          "cost_usd": 0.0800
        },
        "gpt-4o-mini": {
          "calls": 2,
          "prompt_tokens": 4345,
          "completion_tokens": 2789,
          "cost_usd": 0.0434
        }
      }
    }
  }
}
```

## 4. Monitoring-Queries

### Heute verarbeitete Sessions
```javascript
db.session_cache.find({
  "processed_at": {
    $gte: new Date(new Date().setHours(0,0,0,0))
  }
}).count()
```

### Durchschnittliche Verarbeitungszeit
```javascript
db.session_cache.aggregate([
  {
    $project: {
      duration: {
        $divide: [
          { $subtract: [
            { $toDate: "$result.processed_at" },
            { $toDate: "$data.started" }
          ]},
          1000
        ]
      }
    }
  },
  {
    $group: {
      _id: null,
      avg_duration_sec: { $avg: "$duration" }
    }
  }
])
```

### Cache-Hit-Rate (approximiert)
```javascript
// Zähle Duplikate (gleiche Session mehrfach verarbeitet)
db.session_cache.aggregate([
  {
    $group: {
      _id: {
        event: "$data.event",
        session: "$data.session"
      },
      count: { $sum: 1 }
    }
  },
  {
    $match: { count: { $gt: 1 } }
  }
])
```

### Sessions mit Video-Transkript (neu)
```javascript
db.session_cache.find({
  "result.input_data.video_transcript": { $ne: null }
}).count()
```

## 5. Entwickler-Tools

### Cache leeren (für Testing)
```javascript
// Alle Sessions
db.session_cache.deleteMany({})

// Nur für ein Event
db.session_cache.deleteMany({ "data.event": "FOSDEM 2025" })

// Nur alte Einträge (älter als 7 Tage)
db.session_cache.deleteMany({
  "processed_at": {
    $lt: new Date(Date.now() - 7*24*60*60*1000)
  }
})
```

### Log-Rotation manuell triggern
```bash
# Alte Logs archivieren
mv logs/dev_detailed.log logs/dev_detailed.log.$(date +%Y%m%d)

# Service neu starten (erstellt neue Log-Datei)
# bzw. der Service erkennt die fehlende Datei und erstellt sie neu
```

## 6. Troubleshooting

### Session nicht im Cache
```javascript
// Prüfe, ob Session verarbeitet wurde
db.session_cache.find({
  "data.event": "FOSDEM 2025",
  "data.session": "Welcome Talk"
})

// Wenn leer: Prüfe Logs nach Fehlern
```

### Cache-Key ermitteln
Der Cache-Key wird aus folgenden Parametern berechnet:
- event
- session
- url
- track
- target_language
- template
- video_url (optional)
- video_transcript_hash (optional, wenn Transkript gesetzt)
- attachments_url (optional)

### Performance-Probleme identifizieren
```bash
# In Logs nach langen Verarbeitungszeiten suchen
grep -E "duration.*[0-9]{3,}" logs/dev_detailed.log
```

### Disk-Space prüfen
```bash
# Log-Größe
du -h logs/

# Cache-Größe (MongoDB)
mongosh --eval "db.stats()"
```

