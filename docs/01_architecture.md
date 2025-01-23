# Systemarchitektur

## Überblick

Das Common Secretary Services System ist eine Python-basierte Anwendung zur automatisierten Verarbeitung von Audio-, Video- und anderen Mediendateien. Der Fokus liegt auf der Transkription und strukturierten Ausgabe unter Verwendung von Templates.

## Kernkomponenten

```mermaid
graph TD
    A[Client] --> B[API Layer]
    B --> C[Processor Layer]
    C --> D[Storage Layer]
    C --> E[External Services]
    
    subgraph "API Layer"
    B --> F[REST Endpoints]
    B --> G[Rate Limiting]
    B --> H[Auth]
    end
    
    subgraph "Processor Layer"
    C --> I[Audio Processor]
    C --> J[YouTube Processor]
    C --> K[Template Processor]
    end
    
    subgraph "Storage Layer"
    D --> L[Temp Files]
    D --> M[Config]
    D --> N[Templates]
    end
    
    subgraph "External Services"
    E --> O[OpenAI GPT-4]
    E --> P[YouTube API]
    E --> Q[FFmpeg]
    end
```

### Core-Komponenten (`src/core/`)
- Basisklassen für Prozessoren
- Gemeinsame Utilities
- Konfigurationsmanagement
- Fehlerbehandlung

### API Layer (`src/api/`)
- REST-API mit Flask/Flask-RESTX
- Endpunkte für Medienverarbeitung
- Rate-Limiting und Authentifizierung
- Swagger-Dokumentation

### Processors (`src/processors/`)
- Audio-Prozessor für Medienverarbeitung
- YouTube-Integration
- Template-Verarbeitung
- PDF- und Bildverarbeitung

### Prozessor-Hierarchie

Die Prozessoren sind in einer hierarchischen Struktur organisiert:

```mermaid
graph TD
    A[BaseProcessor] --> B[AudioProcessor]
    A --> C[YouTubeProcessor]
    A --> D[TransformerProcessor]
    A --> E[PDFProcessor]
    A --> F[ImageProcessor]
    
    B --> D
    C --> B
    
    subgraph "Prozessor-Funktionen"
    B --> G[Audio Segmentierung]
    B --> H[Transkription]
    D --> I[Text Transformation]
    D --> J[Template Anwendung]
    C --> K[Video Download]
    C --> L[Metadaten]
    end
```

#### Prozessor-Interaktionen

1. **BaseProcessor**
   - Basisklasse für alle Prozessoren
   - Stellt gemeinsame Funktionalität bereit:
     - Prozess-ID Management
     - Temporäre Verzeichnisse
     - Performance Tracking

2. **AudioProcessor**
   - Hauptprozessor für Audioverarbeitung
   - Ruft TransformerProcessor für Text-Transformationen auf
   - Kernfunktionen:
     - Audio-Segmentierung
     - Transkription via Whisper
     - Kapitel-basierte Verarbeitung
     - Ressourcen-Management

3. **TransformerProcessor**
   - Verantwortlich für Text-Transformationen
   - Wird von anderen Prozessoren aufgerufen
   - Funktionen:
     - Template-Anwendung
     - Übersetzungen
     - Text-Formatierung
     - LLM-Integration (GPT-4)

4. **YouTubeProcessor**
   - Integriert mit AudioProcessor
   - Verarbeitet YouTube-Videos zu Audio
   - Extrahiert Metadaten
   - Handhabt Download und Konvertierung

5. **Weitere Prozessoren**
   - PDFProcessor: PDF-Verarbeitung
   - ImageProcessor: Bildverarbeitung
   - Alle erben von BaseProcessor

#### Datenfluss zwischen Prozessoren

```mermaid
sequenceDiagram
    participant API
    participant YT as YouTubeProcessor
    participant Audio as AudioProcessor
    participant Trans as TransformerProcessor
    
    API->>YT: Video URL
    YT->>YT: Download
    YT->>Audio: Audio Extraktion
    Audio->>Audio: Segmentierung
    Audio->>Audio: Transkription
    Audio->>Trans: Text Transform
    Trans->>Trans: Template Anwendung
    Trans->>Audio: Formatierter Text
    Audio->>API: Finales Ergebnis
```

### Utils (`src/utils/`)
- Hilfsfunktionen
- Typdefinitionen
- Logging-Utilities
- Gemeinsam genutzte Funktionen

## Datenfluss

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API
    participant P as Processor
    participant S as Storage
    participant E as External

    C->>A: Request
    A->>P: Process
    P->>S: Save Temp
    P->>E: External Request
    E->>P: Response
    P->>S: Update
    P->>A: Result
    A->>C: Response
```

## Externe Dienste

### OpenAI GPT-4
- Transkription von Audio
- Textverarbeitung
- Übersetzung
- Strukturierung

### YouTube API
- Video-Informationen
- Download-Management
- Metadaten-Extraktion

### FFmpeg
- Audio-Konvertierung
- Format-Transformation
- Qualitätsoptimierung

## Speicherstruktur

```mermaid
graph TD
    A[Root] --> B[src/]
    A --> C[config/]
    A --> D[templates/]
    A --> E[temp-processing/]
    
    B --> F[core/]
    B --> G[api/]
    B --> H[processors/]
    B --> I[utils/]
    
    C --> J[config.yaml]
    C --> K[config.docker.yaml]
    
    D --> L[Besprechung.md]
    D --> M[Youtube.md]
    D --> N[Gedanken.md]
    
    E --> O[audio/]
    E --> P[video/]
```

## Konfigurationsmanagement

### Hauptkonfiguration (`config/config.yaml`)
```yaml
server:
  host: "127.0.0.1"
  port: 5000
  debug: true

processors:
  audio:
    segment_duration: 300
    export_format: mp3
  youtube:
    max_duration: 15000
    max_file_size: 104857600

logging:
  level: DEBUG
  file: logs/dev_detailed.log
```

### Umgebungsvariablen
- `OPENAI_API_KEY`: OpenAI API-Schlüssel
- `YOUTUBE_API_KEY`: YouTube API-Schlüssel
- Weitere API-Schlüssel nach Bedarf

## Sicherheitsaspekte

### Datenschutz
- Temporäre Dateispeicherung
- Automatische Bereinigung
- Keine persistente Speicherung von Mediendaten

### API-Sicherheit
- Rate-Limiting
- API-Key Authentifizierung
- Dateigrößenbeschränkungen

### Monitoring
- Ausführliche Logging
- Performance-Überwachung
- Fehlerbehandlung

## Erweiterbarkeit

### Neue Prozessoren
- Implementierung der Basis-Prozessorklasse
- Registrierung in der Konfiguration
- Integration in die API

### Template-System
- Markdown-basierte Templates
- Variables Substitutionssystem
- Erweiterbare Ausgabeformate

### API-Erweiterungen
- Neue Endpunkte
- Zusätzliche Verarbeitungsoptionen
- Erweiterte Metadaten