# Implementierung der asynchronen Event-Verarbeitung

Dieses Dokument beschreibt die technische Implementierung der asynchronen Event-Verarbeitung mit Webhook-Callbacks und Ressourcenschutz durch Semaphore.

## Überblick

Die asynchrone Event-Verarbeitung ermöglicht es, Events im Hintergrund zu verarbeiten und nach Abschluss einen Webhook-Callback zu senden. Um eine Überlastung des Systems bei vielen gleichzeitigen Anfragen zu vermeiden, wurde eine Semaphore implementiert, die die Anzahl der gleichzeitig verarbeiteten Events begrenzt.

## Komponenten

Die Implementierung besteht aus folgenden Komponenten:

1. **Datenmodelle** (`src/core/models/event.py`):
   - `WebhookConfig`: Konfiguration für Webhook-Callbacks
   - `AsyncEventInput`: Erweiterte Eingabedaten für asynchrone Event-Verarbeitung
   - `AsyncBatchEventInput`: Erweiterte Eingabedaten für asynchrone Batch-Verarbeitung

2. **EventProcessor** (`src/processors/event_processor.py`):
   - `_processing_semaphore`: Semaphore zur Begrenzung gleichzeitiger Verarbeitungen
   - `process_event_async`: Methode zur asynchronen Verarbeitung eines Events
   - `process_many_events_async`: Methode zur asynchronen Verarbeitung mehrerer Events
   - `_process_event_async_task`: Interne Methode zur asynchronen Verarbeitung eines Events
   - `_process_many_events_async_task`: Interne Methode zur asynchronen Verarbeitung mehrerer Events
   - `_send_webhook_callback`: Methode zum Senden von Webhook-Callbacks

3. **API-Endpunkte** (`src/api/routes.py`):
   - `/process-event-async`: Endpunkt für die asynchrone Verarbeitung eines Events
   - `/process-events-async`: Endpunkt für die asynchrone Verarbeitung mehrerer Events

4. **Konfiguration** (`config/processors/event.yaml`):
   - `max_concurrent_tasks`: Maximale Anzahl gleichzeitiger Verarbeitungen

## Semaphore-Implementierung

Die Semaphore wird im Konstruktor des EventProcessors initialisiert:

```python
def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
    # ...
    
    # Semaphore für die Begrenzung gleichzeitiger asynchroner Verarbeitungen
    max_concurrent_tasks = event_config.get('max_concurrent_tasks', 5)
    self._processing_semaphore = asyncio.Semaphore(max_concurrent_tasks)
    
    # ...
```

Die Semaphore wird in der Methode `_process_event_async_task` verwendet, um die Anzahl gleichzeitiger Verarbeitungen zu begrenzen:

```python
async def _process_event_async_task(self, input_data: AsyncEventInput) -> None:
    # Verwende die Semaphore, um die Anzahl gleichzeitiger Verarbeitungen zu begrenzen
    async with self._processing_semaphore:
        try:
            # Verarbeite das Event
            # ...
        except Exception as e:
            # Fehlerbehandlung
            # ...
```

## Asynchrone Verarbeitung

Die asynchrone Verarbeitung wird durch die Methoden `process_event_async` und `process_many_events_async` initiiert. Diese Methoden erstellen einen asynchronen Task und geben sofort eine Antwort zurück:

```python
async def process_event_async(self, event: str, session: str, ...) -> EventResponse:
    # ...
    
    # Starte die asynchrone Verarbeitung in einem separaten Task
    asyncio.create_task(self._process_event_async_task(input_data))
    
    # Erstelle eine sofortige Antwort
    return ResponseFactory.create_response(...)
```

## Webhook-Callbacks

Nach Abschluss der Verarbeitung wird ein Webhook-Callback an die angegebene URL gesendet:

```python
async def _send_webhook_callback(self, webhook_config: WebhookConfig, ...) -> bool:
    try:
        # Erstelle Payload für den Webhook
        payload = {
            "event_id": webhook_config.event_id or str(uuid.uuid4()),
            "timestamp": datetime.now().isoformat(),
            "success": success,
            # ...
        }
        
        # Sende den Webhook
        response = requests.post(
            webhook_config.url,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        # ...
    except Exception as e:
        # Fehlerbehandlung
        # ...
```

## Batch-Verarbeitung

Bei der Batch-Verarbeitung werden die Events sequentiell verarbeitet, wobei jedes Event die Semaphore verwendet:

```python
async def _process_many_events_async_task(self, input_data: AsyncBatchEventInput) -> None:
    try:
        # Verarbeite die Events sequentiell
        for i, event_data in enumerate(input_data.events):
            # ...
            
            # Verarbeite das Event asynchron
            await self._process_event_async_task(async_event_input)
            
            # ...
    except Exception as e:
        # Fehlerbehandlung
        # ...
```

## Konfiguration

Die maximale Anzahl gleichzeitiger Verarbeitungen kann in der Konfigurationsdatei `config/processors/event.yaml` festgelegt werden:

```yaml
# Maximale Anzahl gleichzeitiger asynchroner Verarbeitungen
max_concurrent_tasks: 5
```

## Vorteile

Die Implementierung bietet folgende Vorteile:

1. **Sofortige Antwort**: Der Client erhält sofort eine Antwort, unabhängig von der Verarbeitungszeit.
2. **Ressourcenschutz**: Die Semaphore verhindert eine Überlastung des Systems bei vielen gleichzeitigen Anfragen.
3. **Skalierbarkeit**: Die maximale Anzahl gleichzeitiger Verarbeitungen kann an die verfügbaren Ressourcen angepasst werden.
4. **Fehlertoleranz**: Fehler bei der Verarbeitung werden protokolliert und über Webhook-Callbacks kommuniziert.
5. **Flexibilität**: Die Webhook-Konfiguration kann für jedes Event oder jeden Batch individuell angepasst werden.

## Mögliche Erweiterungen

Die Implementierung könnte in Zukunft um folgende Funktionen erweitert werden:

1. **Prioritätsbasierte Verarbeitung**: Events mit höherer Priorität werden bevorzugt verarbeitet.
2. **Fortschrittsbenachrichtigungen**: Zwischenbenachrichtigungen über den Fortschritt der Verarbeitung.
3. **Wiederaufnahme nach Fehlern**: Automatische Wiederaufnahme der Verarbeitung nach bestimmten Fehlern.
4. **Externe Aufgabenverwaltung**: Integration mit externen Aufgabenverwaltungssystemen wie Celery, Redis oder RabbitMQ für eine robustere Lösung.
5. **Monitoring und Alarmierung**: Überwachung der Verarbeitungszeiten und Benachrichtigung bei Problemen. 