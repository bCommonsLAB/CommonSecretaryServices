# Event-Verarbeitung mit N8N und Webhooks

Diese Dokumentation beschreibt, wie die Stapelverarbeitung von Events mithilfe von [N8N](https://n8n.io/) und der `/api/process-events-async` API umgesetzt werden kann.

## Übersicht

Die Common Secretary Services bieten eine API zum Verarbeiten von Events, die Informationen aus verschiedenen Quellen extrahiert und in strukturierte Markdown-Dateien umwandelt. Da die Verarbeitung eines einzelnen Events bis zu 10 Minuten dauern kann und wir bis zu 1000 Events verarbeiten müssen, wird ein robuster asynchroner Workflow benötigt.

### Vorteile der Auslagerung an N8N

1. **Fehlerisolierung**: Server-Neustarts beeinträchtigen nicht die gesamte Verarbeitungswarteschlange
2. **Skalierbarkeit**: N8N kann Aufgaben bei Bedarf drosseln oder parallelisieren
3. **Überwachung**: Bessere Sichtbarkeit des Verarbeitungsstatus
4. **Wiederholungsstrategien**: Automatische Wiederholungsversuche bei fehlgeschlagenen Verarbeitungen

## Einrichtung der N8N-Umgebung

### Voraussetzungen

- N8N-Installation (v1.0.0 oder höher)
- Zugriff auf die Common Secretary Services API
- Webhook-Endpunkt für Ergebnisbenachrichtigungen

### Konfiguration des N8N-Servers

1. N8N installieren und starten
2. Die Anwendung als Service einrichten, damit sie nach Server-Neustarts automatisch startet
3. Sicherstellen, dass N8N über das Internet zugänglich ist (für Webhook-Callbacks)

## Implementierung des Workflows

### 1. Workflow-Übersicht

Der vollständige Workflow besteht aus mehreren Komponenten:

1. **Trigger**: Startet den Workflow manuell oder per Zeitplan
2. **Events Laden**: Lädt die zu verarbeitenden Events aus einer JSON-Datei
3. **Batching**: Teilt die Events in kleinere Batches auf
4. **HTTP Request**: Sendet Batches an die `/api/process-events-async` API
5. **Webhook**: Empfängt Verarbeitungsergebnisse von der API
6. **Ergebnisverarbeitung**: Speichert erfolgreiche Ergebnisse und behandelt Fehler
7. **Monitoring**: Überwacht den Fortschritt und sendet Benachrichtigungen

### 2. Webhook-Einrichtung

Zuerst muss ein Webhook-Endpunkt in N8N erstellt werden, der die Callback-Ergebnisse empfängt:

1. Füge einen **Webhook-Knoten** zum Workflow hinzu
2. Wähle "Webhook" als Trigger
3. Aktiviere "Respondent"
4. Notiere die generierte URL (z.B. `https://deine-n8n-domain.de/webhook/abcdef123456`)

![Webhook Konfiguration](webhook_config.png)

### 3. Laden und Batching der Events

Um die große Menge an Events zu verarbeiten, teilen wir sie in Batches auf:

```javascript
// Code für den Function-Knoten in N8N
const events = $input.item.json.events;
const batchSize = 5; // Bearbeite 5 Events pro Batch
const batches = [];

// Teile Events in Batches auf
for (let i = 0; i < events.length; i += batchSize) {
  const batch = events.slice(i, i + batchSize);
  batches.push({
    batchId: `batch-${Date.now()}-${i}`,
    events: batch
  });
}

return batches.map((batch, index) => ({
  json: {
    batch: batch,
    batchNumber: index + 1,
    totalBatches: batches.length
  }
}));
```

### 4. API-Anfrage mit HTTP Request Knoten

Für jeden Batch senden wir eine Anfrage an den API-Endpunkt:

1. Füge einen **HTTP Request** Knoten hinzu
2. Konfiguriere die Anfrage:
   - **Methode**: POST
   - **URL**: `http://deine-api-domain.de/api/process-events-async`
   - **Header**: `Content-Type: application/json`
   - **JSON-Body**:

```json
{
  "events": "={{ $json.batch.events }}",
  "webhook_url": "https://deine-n8n-domain.de/webhook/abcdef123456",
  "webhook_headers": {
    "X-Batch-ID": "={{ $json.batch.batchId }}",
    "X-Batch-Number": "={{ $json.batchNumber }}",
    "X-Total-Batches": "={{ $json.totalBatches }}"
  },
  "include_markdown": true,
  "include_metadata": true,
  "batch_id": "={{ $json.batch.batchId }}"
}
```

### 5. Verarbeitung der Webhook-Callbacks

Für jeden erfolgreich verarbeiteten Event erhält der Webhook einen Callback:

```javascript
// Code für die Verarbeitung der Webhook-Rückgaben
const batchId = $input.item.headers['x-batch-id'];
const eventId = $input.item.json.event_id;
const success = $input.item.json.success;
const filePath = $input.item.json.file_path;
const metadata = $input.item.json.metadata || {};

if (success) {
  // Speichere erfolgreiches Ergebnis in Datenbank oder Datei
  console.log(`Event ${eventId} erfolgreich verarbeitet: ${filePath}`);
} else {
  // Behandle Fehler
  console.error(`Fehler bei Event ${eventId}: ${$input.item.json.error?.message}`);
  // Füge Event zur Wiederholungsliste hinzu
}

// Aktualisiere den Verarbeitungsfortschritt
const progress = {
  batchId,
  eventId,
  success,
  timestamp: new Date().toISOString()
};

// Speichere Fortschritt für Überwachung
$node.context.progress = $node.context.progress || {};
$node.context.progress[eventId] = progress;

return { json: progress };
```

### 6. Timeout-Überwachung

Da Callbacks möglicherweise nie ankommen, müssen wir Timeouts überwachen:

```javascript
// Timeout-Überwachung im Interval-Knoten (läuft alle 10 Minuten)
const now = new Date();
const progressData = $node.context.progress || {};
const timeoutMinutes = 30; // 30 Minuten Timeout

const timedOutEvents = Object.entries(progressData)
  .filter(([eventId, data]) => {
    // Prüfe auf gesendete Events ohne Antwort
    if (data.sent && !data.received) {
      const sentTime = new Date(data.sentTimestamp);
      const diffMinutes = (now - sentTime) / (1000 * 60);
      return diffMinutes > timeoutMinutes;
    }
    return false;
  })
  .map(([eventId, data]) => ({
    eventId,
    batchId: data.batchId,
    sentTimestamp: data.sentTimestamp
  }));

if (timedOutEvents.length > 0) {
  // Benachrichtigung senden oder Events zur Wiederholung einreihen
}

return { json: { timedOutEvents } };
```

## Beispiel mit FOSDEM-Events

Hier ist ein praktisches Beispiel, wie die Events aus der `fosdem-events.json` Datei verarbeitet werden:

### 1. Events laden

```javascript
// Code für den Function-Knoten zum Laden der FOSDEM-Events
const fs = require('fs');
const path = require('path');

const filePath = path.resolve(__dirname, '../tests/samples/fosdem-events.json');
const eventsData = fs.readFileSync(filePath, 'utf8');
const events = JSON.parse(eventsData);

// Füge Trackingfeld hinzu
const eventsWithTracking = events.map(event => ({
  ...event,
  _tracking: {
    attempts: 0,
    status: 'pending'
  }
}));

return { json: { events: eventsWithTracking } };
```

### 2. Kompletter N8N-Workflow

Hier ist die Struktur des vollständigen Workflows für die FOSDEM-Events:

```
[Manueller Trigger] → [FOSDEM Events Laden] → [Batching] → [HTTP Request]
                                                              ↓
[Ergebnisreport] ← [Ergebnisse speichern] ← [Webhook-Empfänger]
```

## Skalierbarkeit und Best Practices

### Verarbeitung von 1000+ Events

Um 1000 oder mehr Events zu verarbeiten, folgen Sie diesen Best Practices:

1. **Progressive Batching**: Beginnen Sie mit kleinen Batches (5-10 Events) und erhöhen Sie die Batchgröße basierend auf der Systemleistung
2. **Zeitliche Staffelung**: Verteilen Sie die Verarbeitung über einen längeren Zeitraum mit Pausen zwischen den Batches
3. **Robuste Fehlerbehandlung**: Implementieren Sie automatische Wiederholungsversuche für fehlgeschlagene Events
4. **Ergebnispersistenz**: Speichern Sie Ergebnisse sofort in einer externen Datenbank

### Überwachung der Verarbeitungszeit

Da einzelne Events bis zu 10 Minuten Verarbeitungszeit benötigen können:

1. **Großzügige Timeouts**: Setzen Sie Timeouts auf mindestens 15-20 Minuten
2. **Asynchrone Verarbeitung**: Nutzen Sie die vollständig asynchrone Verarbeitung
3. **Status-Dashboard**: Erstellen Sie ein Dashboard zur Überwachung der Verarbeitungsfortschritte
4. **E-Mail/Slack-Benachrichtigungen**: Senden Sie Fortschrittsberichte und Fehlermeldungen

## Fehlerbehebung

### Häufige Probleme und Lösungen

1. **Webhook-Callbacks kommen nicht an**:
   - Überprüfen Sie die Netzwerkverbindung zwischen API und N8N
   - Stellen Sie sicher, dass N8N öffentlich zugänglich ist
   - Prüfen Sie die Webhook-URL auf Tippfehler

2. **Event-Verarbeitung hängt**:
   - Implementieren Sie eine Timeout-Logik
   - Starten Sie fehlerhafte Events nach einer bestimmten Zeit neu

3. **Zu viele gleichzeitige Anfragen**:
   - Reduzieren Sie die Batch-Größe
   - Implementieren Sie Pausen zwischen den Batches

## Zusammenfassung

Die Kombination aus N8N-Workflows und der asynchronen Event-Verarbeitung ermöglicht eine robuste und skalierbare Lösung für die Verarbeitung von tausenden Events. Durch die Verwendung von Batching, Webhooks und sorgfältiger Fehlerbehandlung können auch langwierige Verarbeitungsprozesse zuverlässig durchgeführt werden.

Bei richtiger Konfiguration kann das System eine große Menge von Events verarbeiten und ist robust gegenüber Verbindungsabbrüchen, Server-Neustarts und anderen potenziellen Fehlerquellen. 