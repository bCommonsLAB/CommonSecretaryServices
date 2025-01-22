# Web-Interface

## Überblick

Das Web-Interface bietet eine benutzerfreundliche Oberfläche zur Verwaltung, Überwachung und Konfiguration des Systems. Es ist über verschiedene spezialisierte Routen erreichbar.

## Dashboard (/)

Das Dashboard ist die Hauptansicht des Systems und bietet einen schnellen Überblick über alle wichtigen Funktionen und Metriken.

### Funktionen
- Echtzeit-Übersicht der Systemaktivitäten
- Aktuelle Verarbeitungsjobs und deren Status
- Performance-Metriken und Ressourcenauslastung
- Schnellzugriff auf häufig genutzte Funktionen

### Metriken
- CPU- und Speicherauslastung
- Aktive Jobs und Warteschlange
- Erfolgs- und Fehlerrate
- Durchschnittliche Verarbeitungszeiten

![Dashboard Übersicht](screens/dashboard.jpg)

```mermaid
graph TD
    A[Dashboard] --> B[System Metriken]
    A --> C[Aktive Jobs]
    A --> D[Ressourcen]
    B --> E[Performance]
    B --> F[Auslastung]
    C --> G[Status]
    C --> H[Warteschlange]
    D --> I[CPU/RAM]
    D --> J[Speicher]
```

## Logs (/logs)

Die Logs-Ansicht ermöglicht die detaillierte Analyse von Systemereignissen und Fehlern.

### Funktionen
- Echtzeit-Log-Streaming
- Filterung nach Log-Level und Zeitraum
- Suchfunktion mit regulären Ausdrücken
- Export von Log-Dateien

### Filter-Optionen
- Log-Level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Zeitraum-Auswahl
- Komponenten-Filter
- Volltext-Suche

![Logs Ansicht](screens/logs.jpg)

```mermaid
graph TD
    A[Logs] --> B[Filter]
    A --> C[Anzeige]
    A --> D[Export]
    B --> E[Level]
    B --> F[Zeit]
    B --> G[Komponente]
    C --> H[Echtzeit]
    C --> I[Historie]
    D --> J[Download]
```

## Konfiguration (/config)

Die Konfigurations-Ansicht ermöglicht die Verwaltung aller Systemeinstellungen.

### Funktionen
- Übersicht aller Konfigurationsparameter
- Live-Bearbeitung der Einstellungen
- Validierung der Eingaben
- Konfigurationshistorie

### Bereiche
- Server-Einstellungen
- Prozessor-Konfigurationen
- API-Einstellungen
- Logging-Konfiguration

![Konfigurations Ansicht](screens/config.jpg)

```mermaid
graph TD
    A[Konfiguration] --> B[Editor]
    A --> C[Validierung]
    A --> D[Historie]
    B --> E[Parameter]
    B --> F[Templates]
    C --> G[Syntax]
    C --> H[Werte]
    D --> I[Versionen]
```

## Tests (/test)

Die Test-Ansicht ermöglicht die Ausführung und Überwachung von Systemtests.

### Funktionen
- Ausführung von Testsuiten
- Einzeltest-Ausführung
- Coverage-Berichte
- Fehleranalyse

### Test-Kategorien
- Unit Tests
- Integrationstests
- API Tests
- Performance Tests

![Test Ansicht](screens/test.jpg)

```mermaid
graph TD
    A[Tests] --> B[Ausführung]
    A --> C[Ergebnisse]
    A --> D[Coverage]
    B --> E[Suite]
    B --> F[Einzeln]
    C --> G[Report]
    C --> H[Fehler]
    D --> I[Statistik]
```

## Swagger API (/api)

Die Swagger UI bietet eine interaktive Dokumentation und Testumgebung für die API.

### Funktionen
- Vollständige API-Dokumentation
- Interaktive API-Tests
- Request/Response Beispiele
- Authentifizierung

### Endpunkte
- Audio-Verarbeitung
- YouTube-Integration
- Job-Management
- System-Status

![Swagger UI](screens/api.jpg)

```mermaid
graph TD
    A[Swagger UI] --> B[Dokumentation]
    A --> C[Tests]
    A --> D[Auth]
    B --> E[Endpunkte]
    B --> F[Schemas]
    C --> G[Requests]
    C --> H[Responses]
    D --> I[API Keys]
```

## Navigation und Interaktion

### Hauptmenü
- Dashboard: Systemübersicht
- Logs: Ereignisprotokollierung
- Config: Systemkonfiguration
- Tests: Testausführung
- API: Swagger-Dokumentation

### Benutzerinteraktion
```mermaid
graph LR
    A[Benutzer] --> B[Dashboard]
    A --> C[Logs]
    A --> D[Config]
    A --> E[Tests]
    A --> F[API]
    B --> G[System Status]
    C --> H[Log Analyse]
    D --> I[Konfiguration]
    E --> J[Test Ausführung]
    F --> K[API Tests]
```

## Sicherheit

### Zugriffskontrollen
- Rollenbasierte Berechtigungen
- Session-Management
- CSRF-Schutz
- Rate-Limiting

### Audit-Trail
- Benutzeraktionen
- Konfigurationsänderungen
- Systemzugriffe
- Sicherheitsereignisse 