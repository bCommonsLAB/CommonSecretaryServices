# API-Dokumentation: Track-Processor Endpunkte

## Überblick

Die Track-API ermöglicht das Erstellen von Zusammenfassungen für Event-Tracks basierend auf zugehörigen Sessions. Die API bietet drei Hauptendpunkte:

1. **Track-Zusammenfassung erstellen** (`POST /tracks/{track_name}/summary`)
2. **Verfügbare Tracks abrufen** (`GET /tracks/available`)
3. **Alle Tracks zusammenfassen** (`POST /tracks/{track_name}/summarize_all`)

## Endpunkte im Detail

### 1. Track-Zusammenfassung erstellen

```
POST /tracks/{track_name}/summary
```

Erstellt eine Zusammenfassung für einen einzelnen Track.

#### Parameter

| Parameter | Typ | Ort | Beschreibung | Standard |
|-----------|-----|-----|--------------|----------|
| track_name | String | URL-Pfad | Name des Tracks | (erforderlich) |
| template | String | Query/Body | Template für die Zusammenfassung | "track-eco-social-summary" |
| target_language | String | Query/Body | Zielsprache der Zusammenfassung | "de" |
| useCache | Boolean | Query/Body | Cache-Nutzung aktivieren | false |

#### Beispielanfrage

```json
POST /tracks/sustainability-conference/summary
{
  "template": "track-eco-social-summary",
  "target_language": "de",
  "useCache": true
}
```

#### Erfolgsantwort (200 OK)

```json
{
  "status": "success",
  "request": {
    "processor": "track",
    "timestamp": "2023-05-10T15:30:45.123Z",
    "parameters": {
      "track_name": "sustainability-conference",
      "template": "track-eco-social-summary_de",
      "target_language": "de"
    }
  },
  "process": {
    "id": "4f7c8a9b-1d2e-3f4a-5b6c-7d8e9f0a1b2c",
    "main_processor": "track",
    "sub_processors": ["transformer"],
    "started": "2023-05-10T15:30:45.123Z",
    "completed": "2023-05-10T15:30:47.456Z",
    "duration": 2333.0,
    "llm_info": {
      "tokens": { "prompt": 1200, "completion": 800, "total": 2000 },
      "model": "gpt-4"
    }
  },
  "data": {
    "input": {
      "track_name": "sustainability-conference",
      "template": "track-eco-social-summary_de",
      "target_language": "de"
    },
    "output": {
      "summary": "Zusammenfassungstext...",
      "metadata": {
        "track": "sustainability-conference",
        "event": "Eco Conference 2023",
        "sessions_count": 5,
        "generated_at": "2023-05-10T15:30:47.456Z",
        "template": "track-eco-social-summary_de",
        "language": "de",
        "summary_file": "path/to/summary.md"
      },
      "structured_data": {
        "key_topics": ["Nachhaltigkeit", "Klimaschutz"],
        "speakers": ["Dr. Müller", "Prof. Schmidt"]
      }
    },
    "events": [...],
    "event_count": 5,
    "query": "Markdown-Text der Sessions...",
    "context": { ... }
  }
}
```

#### Fehlerantwort (400 Bad Request)

```json
{
  "status": "error",
  "error": {
    "code": "ValidationError",
    "message": "Fehler bei der Track-Verarbeitung: Keine Sessions für Track 'unknown-track' gefunden",
    "details": {}
  }
}
```

### 2. Verfügbare Tracks abrufen

```
GET /tracks/available
```

Liefert eine Liste aller verfügbaren Tracks im System.

#### Erfolgsantwort (200 OK)

```json
{
  "status": "success",
  "data": {
    "tracks": [
      {
        "track_name": "sustainability-conference",
        "session_count": 5,
        "sessions": ["session-1", "session-2", ...],
        "event": "Eco Conference 2023"
      },
      {
        "track_name": "digital-transformation",
        "session_count": 3,
        "sessions": ["session-a", "session-b", ...],
        "event": "Tech Summit 2023"
      }
    ],
    "track_count": 2,
    "total_session_count": 8,
    "collection_info": { ... },
    "generated_at": "2023-05-10T15:35:45.123Z"
  }
}
```

### 3. Alle Tracks zusammenfassen

```
POST /tracks/{track_name}/summarize_all
```

Erstellt Zusammenfassungen für mehrere Tracks. Verwendet `*` als `track_name`, um alle Tracks zu verarbeiten, oder einen Teilstring zur Filterung.

#### Parameter

| Parameter | Typ | Ort | Beschreibung | Standard |
|-----------|-----|-----|--------------|----------|
| track_name | String | URL-Pfad | Filter für Track-Namen (verwende "*" für alle) | (erforderlich) |
| template | String | Query/Body | Template für die Zusammenfassung | "track-eco-social-summary" |
| target_language | String | Query/Body | Zielsprache der Zusammenfassung | "de" |
| useCache | Boolean | Query/Body | Cache-Nutzung aktivieren | false |

#### Beispielanfrage

```json
POST /tracks/*/summarize_all
{
  "template": "track-eco-social-summary",
  "target_language": "de",
  "useCache": true
}
```

#### Erfolgsantwort (200 OK)

```json
{
  "status": "success",
  "summary": {
    "total_tracks": 2,
    "successful_tracks": 2,
    "failed_tracks": 0,
    "duration_ms": 4200,
    "template": "track-eco-social-summary",
    "target_language": "de",
    "use_cache": true,
    "track_filter": null
  },
  "successful_tracks": [
    {
      "track_name": "sustainability-conference",
      "response": { ... } // Vollständige Track-Response
    },
    {
      "track_name": "digital-transformation",
      "response": { ... } // Vollständige Track-Response
    }
  ],
  "failed_tracks": [],
  "generated_at": "2023-05-10T15:40:45.123Z"
}
```

## Implementierungsdetails

Der TrackProcessor funktioniert folgendermaßen:

### Funktionsweise `create_track_summary`

1. **Parameter-Validierung**: Überprüfung der Eingabeparameter
2. **Cache-Prüfung**: Suche nach vorhanden Ergebnissen falls `use_cache=true`
3. **Session-Abfrage**: Abruf aller zugehörigen Sessions für den Track
4. **Markdown-Verarbeitung**: Zusammenführung der Session-Inhalte in ein Dokument
5. **Kontext-Erstellung**: Extraktion relevanter Daten aus den Sessions für das LLM
6. **Template-Transformation**: Anwendung des Templates auf die zusammengeführten Inhalte
7. **Speicherung**: Ablage der Zusammenfassung und Metadaten
8. **Rückgabe**: Standardisierte Response mit allen Daten

### Funktionsweise `create_all_track_summaries`

1. **Track-Abfrage**: Abruf aller verfügbaren Tracks
2. **Filterung**: Optionale Filterung basierend auf `track_filter`
3. **Sequentielle Verarbeitung**: Aufruf von `create_track_summary` für jeden passenden Track
4. **Ergebnissammlung**: Trennung in erfolgreiche und fehlgeschlagene Tracks
5. **Statistik-Erstellung**: Zusammenstellung von Verarbeitungsmetriken
6. **Rückgabe**: Gesamtergebnis mit allen Zusammenfassungen und Statistiken

## Hinweise zur Integration

1. **Fehlerbehandlung**: Alle Endpunkte liefern klare Fehlermeldungen mit eindeutigen Codes.
2. **Caching**: Das `useCache`-Flag ermöglicht die Wiederverwendung bereits generierter Zusammenfassungen.
3. **Asynchrone Verarbeitung**: Die Verarbeitung großer Tracks kann einige Zeit in Anspruch nehmen.
4. **Authentifizierung**: Implementieren Sie geeignete Authentifizierungsmechanismen (nicht in dieser Dokumentation beschrieben).
5. **Rate-Limiting**: Beachten Sie mögliche API-Beschränkungen bei häufigen Anfragen.

Für die Integration in externe Anwendungen empfehlen wir die Verwendung von HTTP-Clients mit Retry-Mechanismen und Timeout-Handling. 