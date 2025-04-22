# Event-Processor Async-Test

Dieses Test-Setup ermöglicht das Testen der asynchronen Verarbeitung von Events mit dem EventProcessor, einschließlich der Webhook-Callback-Funktionalität.

## Komponenten

- **test_webhook_server.py**: Ein Mock-Webhook-Server, der die Callbacks vom EventProcessor empfängt und protokolliert.
- **test_event_processor_async.py**: Ein Testskript, das den EventProcessor initialisiert und die asynchrone Verarbeitung startet.
- **run_event_processor_test.py**: Ein Hauptskript, das den gesamten Testprozess steuert und die Ergebnisse analysiert.

## Voraussetzungen

1. Eine funktionierende Installation des Common-Secretary-Services Projekts
2. Python 3.8 oder höher
3. Internetverbindung für die Installation von Abhängigkeiten

## Ausführung des Tests

Der einfachste Weg, den Test auszuführen, ist über das Hauptskript:

```bash
python run_event_processor_test.py
```

Dieses Skript führt automatisch folgende Schritte aus:

1. Installation der benötigten Abhängigkeiten (`fastapi`, `uvicorn`, `requests`)
2. Start des Mock-Webhook-Servers auf Port 5678
3. Ausführung des EventProcessor-Tests mit den vordefinierten Testdaten
4. Analyse und Ausgabe der Testergebnisse
5. Bereinigung (Beenden des Webhook-Servers)

## Testdaten

Der Test verwendet die folgenden Testdaten:

```json
{
  "event": "FOSDEM 2025",
  "session": "Closing FOSDEM 2025",
  "filename": "Closing-FOSDEM-2025.md",
  "track": "Keynotes-13",
  "video_url": "https://video.fosdem.org/2025/janson/fosdem-2025-6713-closing-fosdem-2025.av1.webm",
  "attachments_url": "https://fosdem.org/2025/events/attachments/fosdem-2025-6713-closing-fosdem-2025/slides/238893/2025-02-0_vFd3Z4l.pdf",
  "url": "https://fosdem.org/2025/schedule/event/fosdem-2025-6713-closing-fosdem-2025/",
  "day": "Sunday",
  "starttime": "17:50",
  "endtime": "18:15",
  "speakers": ["FOSDEM Staff"],
  "source_language": "en",
  "target_language": "de",
  "webhook_url": "http://localhost:5678/webhook-test/f7d9f387-4a25-41e2-8316-3bfab4a66229",
  "webhook_headers": {},
  "include_markdown": true,
  "include_metadata": true,
  "event_id": "test-event-001"
}
```

## Logs und Ergebnisse

Die Webhook-Callbacks werden in folgenden Orten protokolliert:

- **Konsole**: Während der Testausführung werden wichtige Informationen in der Konsole ausgegeben.
- **webhook_logs-Verzeichnis**: Der Mock-Webhook-Server speichert alle empfangenen Callbacks als JSON-Dateien in diesem Verzeichnis.

Das finale Testergebnis zeigt:
- Ob der Webhook erfolgreich aufgerufen wurde
- Ob die Verarbeitung erfolgreich war
- Den Pfad zur erzeugten Markdown-Datei (falls erfolgreich)
- Eventuelle Fehler (falls die Verarbeitung fehlgeschlagen ist)

## Manuelles Testen

### Webhook-Server separat starten

Wenn Sie den Webhook-Server separat starten möchten:

```bash
python test_webhook_server.py
```

Der Server ist dann unter `http://localhost:5678` erreichbar.

### EventProcessor-Test separat ausführen

Um den EventProcessor-Test separat auszuführen (Webhook-Server muss bereits laufen):

```bash
python test_event_processor_async.py
```

## Fehlerbehebung

1. **Webhook-Server startet nicht**:
   - Prüfen Sie, ob Port 5678 bereits verwendet wird
   - Installieren Sie die benötigten Abhängigkeiten manuell: `pip install fastapi uvicorn requests`

2. **EventProcessor-Test schlägt fehl**:
   - Prüfen Sie, ob der Common-Secretary-Services korrekt eingerichtet ist
   - Stellen Sie sicher, dass alle erforderlichen Umgebungsvariablen gesetzt sind

3. **Keine Webhook-Logs**:
   - Prüfen Sie, ob der Webhook-Server läuft
   - Überprüfen Sie die Firewall-Einstellungen
   - Sehen Sie sich die Fehlerausgabe des EventProcessors an 