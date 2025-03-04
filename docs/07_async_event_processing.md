# Asynchrone Event-Verarbeitung mit Webhook-Callbacks

Dieses Dokument beschreibt die asynchrone Verarbeitung von Events mit Webhook-Callbacks im Event-Processor.

## Übersicht

Die asynchrone Event-Verarbeitung ermöglicht es, lange laufende Event-Verarbeitungsprozesse im Hintergrund auszuführen, während dem Client sofort eine Antwort zurückgegeben wird. Nach Abschluss der Verarbeitung wird ein Webhook-Callback an eine angegebene URL gesendet, um den Client über das Ergebnis zu informieren.

Diese Funktionalität ist besonders nützlich für:
- Verarbeitung großer Mengen von Events
- Integration mit externen Systemen wie N8n
- Vermeidung von Timeout-Problemen bei langen Verarbeitungszeiten

## Ressourcenschutz durch Semaphore

Um eine Überlastung des Systems bei vielen gleichzeitigen Anfragen zu vermeiden, verwendet der EventProcessor eine Semaphore, die die Anzahl der gleichzeitig verarbeiteten Events begrenzt. Die maximale Anzahl gleichzeitiger Verarbeitungen kann in der Konfigurationsdatei `config/processors/event.yaml` über den Parameter `max_concurrent_tasks` festgelegt werden:

```yaml
# Maximale Anzahl gleichzeitiger asynchroner Verarbeitungen
max_concurrent_tasks: 5
```

Wenn mehr Anfragen eingehen als gleichzeitig verarbeitet werden können, werden die überzähligen Anfragen in eine Warteschlange gestellt und erst bearbeitet, wenn ein Slot frei wird. Dies gewährleistet eine optimale Ressourcennutzung und verhindert eine Überlastung des Systems.

## API-Endpunkte

### Einzelnes Event asynchron verarbeiten

**Endpunkt:** `/api/v1/process-event-async`

**Methode:** `POST`

**Anfrage-Beispiel:**
```json
{
  "event": "FOSDEM 2025",
  "session": "Welcome to FOSDEM 2025",
  "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6712-welcome-to-fosdem-2025/",
  "filename": "Welcome-to-FOSDEM-2025.md",
  "track": "Keynotes",
  "day": "2025-02-01",
  "starttime": "09:30",
  "endtime": "09:50",
  "speakers": ["FOSDEM Staff", "Richard Hartmann"],
  "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6712-welcome-to-fosdem-2025.av1.webm",
  "attachments_url": "https://fosdem.org/2025/events/attachments/fosdem-2025-6712-welcome-to-fosdem-2025/slides/236658/2025-02-0_6CcRbRi.pdf",
  "source_language": "en",
  "target_language": "de",
  "webhook_url": "https://n8n.example.com/webhook/event-processed",
  "webhook_headers": {
    "Authorization": "Bearer your-token",
    "X-Custom-Header": "custom-value"
  },
  "include_markdown": true,
  "include_metadata": true,
  "event_id": "custom-event-id-123"
}
```

**Antwort-Beispiel:**
```json
{
  "status": "success",
  "request": {
    "event": "FOSDEM 2025",
    "session": "Welcome to FOSDEM 2025",
    "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6712-welcome-to-fosdem-2025/",
    "filename": "Welcome-to-FOSDEM-2025.md",
    "track": "Keynotes",
    "day": "2025-02-01",
    "starttime": "09:30",
    "endtime": "09:50",
    "speakers": ["FOSDEM Staff", "Richard Hartmann"],
    "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6712-welcome-to-fosdem-2025.av1.webm",
    "attachments_url": "https://fosdem.org/2025/events/attachments/fosdem-2025-6712-welcome-to-fosdem-2025/slides/236658/2025-02-0_6CcRbRi.pdf",
    "source_language": "en",
    "target_language": "de",
    "webhook_url": "https://n8n.example.com/webhook/event-processed",
    "event_id": "custom-event-id-123",
    "async_processing": true
  },
  "process": {
    "id": "1735641423754",
    "processor": "EventProcessor",
    "start_time": "2025-02-01T09:30:00.000Z",
    "end_time": "2025-02-01T09:30:00.100Z",
    "duration_ms": 100
  }
}
```

### Mehrere Events asynchron verarbeiten

**Endpunkt:** `/api/v1/process-events-async`

**Methode:** `POST`

**Anfrage-Beispiel:**
```json
{
  "events": [
    {
      "event": "FOSDEM 2025",
      "session": "Welcome to FOSDEM 2025",
      "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6712-welcome-to-fosdem-2025/",
      "filename": "Welcome-to-FOSDEM-2025.md",
      "track": "Keynotes",
      "day": "2025-02-01",
      "starttime": "09:30",
      "endtime": "09:50",
      "speakers": ["FOSDEM Staff", "Richard Hartmann"],
      "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6712-welcome-to-fosdem-2025.av1.webm",
      "attachments_url": "https://fosdem.org/2025/events/attachments/fosdem-2025-6712-welcome-to-fosdem-2025/slides/236658/2025-02-0_6CcRbRi.pdf",
      "source_language": "en",
      "target_language": "de"
    },
    {
      "event": "FOSDEM 2025",
      "session": "State of the Union",
      "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6713-state-of-the-union/",
      "filename": "State-of-the-Union.md",
      "track": "Keynotes",
      "day": "2025-02-01",
      "starttime": "10:00",
      "endtime": "10:30",
      "speakers": ["FOSDEM Staff"],
      "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6713-state-of-the-union.av1.webm",
      "source_language": "en",
      "target_language": "de"
    }
  ],
  "webhook_url": "https://n8n.example.com/webhook/event-processed",
  "webhook_headers": {
    "Authorization": "Bearer your-token",
    "X-Custom-Header": "custom-value"
  },
  "include_markdown": true,
  "include_metadata": true,
  "batch_id": "custom-batch-id-456"
}
```

**Antwort-Beispiel:**
```json
{
  "status": "success",
  "request": {
    "event_count": 2,
    "webhook_url": "https://n8n.example.com/webhook/event-processed",
    "batch_id": "custom-batch-id-456",
    "async_processing": true
  },
  "process": {
    "id": "1735641423755",
    "processor": "EventProcessor",
    "start_time": "2025-02-01T09:30:00.000Z",
    "end_time": "2025-02-01T09:30:00.100Z",
    "duration_ms": 100
  },
  "data": {
    "input": {
      "events": [
        {
          "event": "FOSDEM 2025",
          "session": "Welcome to FOSDEM 2025",
          "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6712-welcome-to-fosdem-2025/",
          "filename": "Welcome-to-FOSDEM-2025.md",
          "track": "Keynotes",
          "day": "2025-02-01",
          "starttime": "09:30",
          "endtime": "09:50",
          "speakers": ["FOSDEM Staff", "Richard Hartmann"],
          "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6712-welcome-to-fosdem-2025.av1.webm",
          "attachments_url": "https://fosdem.org/2025/events/attachments/fosdem-2025-6712-welcome-to-fosdem-2025/slides/236658/2025-02-0_6CcRbRi.pdf",
          "source_language": "en",
          "target_language": "de"
        },
        {
          "event": "FOSDEM 2025",
          "session": "State of the Union",
          "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6713-state-of-the-union/",
          "filename": "State-of-the-Union.md",
          "track": "Keynotes",
          "day": "2025-02-01",
          "starttime": "10:00",
          "endtime": "10:30",
          "speakers": ["FOSDEM Staff"],
          "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6713-state-of-the-union.av1.webm",
          "source_language": "en",
          "target_language": "de"
        }
      ]
    },
    "output": {
      "results": [],
      "summary": {
        "total_events": 2,
        "status": "accepted",
        "batch_id": "custom-batch-id-456",
        "webhook_url": "https://n8n.example.com/webhook/event-processed",
        "async_processing": true
      }
    }
  }
}
```

## Webhook-Callbacks

Nach Abschluss der Verarbeitung eines Events wird ein Webhook-Callback an die angegebene URL gesendet. Der Callback enthält Informationen über das verarbeitete Event und das Ergebnis der Verarbeitung.

### Webhook-Payload für ein einzelnes Event

```json
{
  "event_id": "custom-event-id-123",
  "timestamp": "2025-02-01T09:35:00.000Z",
  "success": true,
  "event": "FOSDEM 2025",
  "session": "Welcome to FOSDEM 2025",
  "track": "Keynotes",
  "day": "2025-02-01",
  "filename": "Welcome-to-FOSDEM-2025.md",
  "file_path": "/path/to/events/Welcome-to-FOSDEM-2025.md",
  "markdown_content": "# Welcome to FOSDEM 2025\n\n...",
  "metadata": {
    "event": "FOSDEM 2025",
    "session": "Welcome to FOSDEM 2025",
    "track": "Keynotes",
    "day": "2025-02-01",
    "starttime": "09:30",
    "endtime": "09:50",
    "speakers": ["FOSDEM Staff", "Richard Hartmann"],
    "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6712-welcome-to-fosdem-2025.av1.webm",
    "attachments_url": "https://fosdem.org/2025/events/attachments/fosdem-2025-6712-welcome-to-fosdem-2025/slides/236658/2025-02-0_6CcRbRi.pdf",
    "processing_time": 300000
  }
}
```

### Webhook-Payload für ein fehlgeschlagenes Event

```json
{
  "event_id": "custom-event-id-123",
  "timestamp": "2025-02-01T09:35:00.000Z",
  "success": false,
  "event": "FOSDEM 2025",
  "session": "Welcome to FOSDEM 2025",
  "track": "Keynotes",
  "day": "2025-02-01",
  "filename": "Welcome-to-FOSDEM-2025.md",
  "error": "Fehler beim Abrufen der Event-Seite: 404 Not Found"
}
```

## Webhook-Konfiguration

Die Webhook-Konfiguration kann für jedes Event oder jeden Batch individuell angepasst werden:

- `webhook_url`: Die URL, an die der Webhook-Callback gesendet wird
- `webhook_headers`: HTTP-Header für den Webhook-Request (z.B. für Authentifizierung)
- `include_markdown`: Ob der Markdown-Inhalt im Webhook enthalten sein soll (Standard: true)
- `include_metadata`: Ob die Metadaten im Webhook enthalten sein soll (Standard: true)
- `event_id` / `batch_id`: Eine eindeutige ID für das Event oder den Batch

## Integration mit N8n

Die asynchrone Event-Verarbeitung kann leicht mit N8n integriert werden:

1. Erstelle einen Webhook-Node in N8n, der die Callback-Daten empfängt
2. Verwende die URL des Webhook-Nodes als `webhook_url` in der Anfrage
3. Verarbeite die empfangenen Daten in N8n weiter (z.B. Speichern in einer Datenbank, Senden einer E-Mail, etc.)

### Beispiel-Workflow in N8n

1. **HTTP Request Node**: Sendet die Anfrage an `/api/v1/process-event-async`
2. **Webhook Node**: Empfängt den Callback vom Event-Processor
3. **IF Node**: Prüft, ob die Verarbeitung erfolgreich war
4. **Write File Node**: Speichert die Markdown-Datei, wenn erfolgreich
5. **Send Email Node**: Sendet eine Benachrichtigung über das Ergebnis

## Fehlerbehandlung

Wenn bei der Verarbeitung eines Events ein Fehler auftritt, wird ein Webhook-Callback mit `success: false` und einer Fehlermeldung gesendet. Der Client kann diese Informationen verwenden, um entsprechend zu reagieren.

## Sicherheitshinweise

- Verwende HTTPS für Webhook-URLs
- Füge Authentifizierungs-Header hinzu, um die Webhook-Endpunkte zu schützen
- Validiere die empfangenen Daten im Webhook-Handler

## Leistungsoptimierung

Die asynchrone Verarbeitung verbessert die Leistung und Skalierbarkeit des Systems:

- Sofortige Antwort an den Client, unabhängig von der Verarbeitungszeit
- Parallele Verarbeitung mehrerer Events (begrenzt durch `max_concurrent_tasks`)
- Reduzierte Serverlast durch kontrollierte Verarbeitung
- Vermeidung von Ressourcenengpässen durch Begrenzung gleichzeitiger Verarbeitungen 