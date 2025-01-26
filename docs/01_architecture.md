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
    C --> K[Transformer Processor]
    C --> L[Metadata Processor]
    
    %% Prozessor-Beziehungen
    J --> I
    I --> K
    I --> L
    J --> L
    L --> K
    end
    
    subgraph "Storage Layer"
    D --> M[Temp Files]
    D --> N[Config]
    D --> O[Templates]
    end
    
    subgraph "External Services"
    E --> P[OpenAI GPT-4]
    E --> Q[YouTube API]
    E --> R[FFmpeg]
    end
```

### Core-Komponenten (`src/core/`)
- BaseProcessor als Grundlage aller Prozessoren:
  - Prozess-ID Management
  - Temporäre Verzeichnisse
  - Performance Tracking
  - LLM-Request Tracking
  - Response-Strukturierung
- Gemeinsame Utilities
- Konfigurationsmanagement
- Fehlerbehandlung

### API Layer (`src/api/`)
- REST-API mit Flask/Flask-RESTX
- Endpunkte für Medienverarbeitung
- Rate-Limiting und Authentifizierung
- Swagger-Dokumentation

### Processors (`src/processors/`)
- AudioProcessor: Hauptprozessor für Audioverarbeitung
  - Transkription und Segmentierung
  - Integration mit TransformerProcessor und MetadataProcessor
- YouTubeProcessor: Video-Download und -Verarbeitung
  - Integration mit AudioProcessor
  - YouTube-Metadaten-Extraktion
- TransformerProcessor: Text-Transformation
  - Template-Anwendung
  - Strukturierung und Zusammenfassung
  - LLM-Integration
- MetadataProcessor: Metadaten-Verarbeitung
  - Technische Metadaten
  - Inhaltliche Analyse via LLM
  - Integration mit TransformerProcessor

### Prozessor-Hierarchie

#### Vereinfachte Prozessor-Beziehungen
```mermaid
graph TD
    classDef main fill:#f9f,stroke:#333,stroke-width:2px;
    classDef sub fill:#bbf,stroke:#333,stroke-width:1px;
    classDef base fill:#dfd,stroke:#333,stroke-width:1px;
    
    %% Prozessoren
    B[AudioProcessor]:::main
    C[YouTubeProcessor]:::main
    D[TransformerProcessor]:::sub
    E[MetadataProcessor]:::sub
    
    %% Haupt-Abhängigkeiten
    C --> |"1. Audio extrahieren"| B
    
    %% Transformer-Abhängigkeiten
    B --> |"2. Text transformieren"| D
    E --> |"2. Metadaten analysieren"| D
    
    %% Metadaten-Abhängigkeiten
    B --> |"3. Metadaten extrahieren"| E
    C --> |"3. Metadaten extrahieren"| E
    
    %% Legende
    subgraph Legende
        M[Hauptprozessor]:::main
        S[Subprozessor]:::sub
    end

    %% Styling
    linkStyle default stroke-width:2px
```

#### Detaillierte Prozessor-Struktur mit Funktionen

```mermaid
graph TD
    classDef main fill:#f9f,stroke:#333,stroke-width:2px;
    classDef sub fill:#bbf,stroke:#333,stroke-width:1px;
    classDef base fill:#dfd,stroke:#333,stroke-width:1px;

    A[BaseProcessor]:::base
    B[AudioProcessor]:::main
    C[YouTubeProcessor]:::main
    D[TransformerProcessor]:::sub
    E[MetadataProcessor]:::sub
    
    %% Basis-Vererbung
    A --> B
    A --> C
    A --> D
    A --> E
    
    %% Prozessor-Abhängigkeiten
    C --> |Audio-Extraktion| B
    B --> |Text-Transformation| D
    E --> |Metadaten-Analyse| D
    B --> |Metadaten-Extraktion| E
    C --> |Metadaten-Extraktion| E
    
    %% Hauptfunktionen
    subgraph "Prozessor-Funktionen"
        B --> G[Audio Segmentierung]
        B --> H[Transkription]
        B --> I[Übersetzung]
        
        D --> J[Template Anwendung]
        D --> K[Text Strukturierung]
        D --> L[Zusammenfassung]
        
        C --> M[Video Download]
        C --> N[Audio Extraktion]
        
        E --> O[Technische Metadaten]
        E --> P[Inhaltliche Metadaten via LLM]
    end
    
    %% LLM-Integration
    subgraph "LLM-Nutzung"
        B --> |Whisper| Q[Transkription]
        B --> |GPT-4| R[Übersetzung]
        D --> |GPT-4| S[Transformation]
        E --> |GPT-4| T[Metadaten-Analyse]
    end

    %% Styling
    linkStyle default stroke-width:2px
```

#### Prozessor-Interaktionen

1. **BaseProcessor**
   - Basisklasse für alle Prozessoren
   - Stellt gemeinsame Funktionalität bereit:
     - Prozess-ID Management
     - Temporäre Verzeichnisse
     - Performance Tracking
     - LLM-Request Tracking
     - Response-Strukturierung

2. **AudioProcessor**
   - Hauptprozessor für Audioverarbeitung
   - Nutzt andere Prozessoren:
     - TransformerProcessor für Text-Transformationen
     - MetadataProcessor für Metadaten-Extraktion
   - Kernfunktionen:
     - Audio-Segmentierung
     - Transkription via Whisper
     - Übersetzung via GPT-4
     - Kapitel-basierte Verarbeitung

3. **TransformerProcessor**
   - Verantwortlich für Text-Transformationen
   - Wird hauptsächlich von AudioProcessor genutzt
   - Funktionen:
     - Template-Anwendung
     - Text-Strukturierung
     - Zusammenfassungen
     - LLM-Integration (GPT-4)

4. **YouTubeProcessor**
   - Nutzt AudioProcessor für Verarbeitung
   - Nutzt MetadataProcessor für Metadaten
   - Funktionen:
     - Video-Download
     - Audio-Extraktion
     - YouTube-Metadaten Integration

5. **MetadataProcessor**
   - Wird von anderen Prozessoren genutzt
   - Extrahiert und strukturiert Metadaten:
     - Technische Informationen
     - Inhaltliche Metadaten
     - LLM-basierte Metadaten-Extraktion

#### Datenfluss zwischen Prozessoren

```mermaid
sequenceDiagram
    participant Client
    participant YT as YouTubeProcessor
    participant Audio as AudioProcessor
    participant Meta as MetadataProcessor
    participant Trans as TransformerProcessor
    
    Client->>YT: Video URL
    YT->>YT: Download Video
    YT->>Audio: Audio Extraktion
    
    par Parallel Processing
        Audio->>Audio: Segmentierung
        Audio->>Audio: Transkription
        and Metadata
        YT->>Meta: Extrahiere Metadaten
    end
    
    Audio->>Trans: Text Transform
    Trans->>Trans: Template Anwendung
    Trans->>Audio: Formatierter Text
    Meta->>Audio: Metadaten
    
    Audio->>Client: Finales Ergebnis
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
    participant API as API Layer
    participant YT as YouTubeProcessor
    participant Audio as AudioProcessor
    participant Meta as MetadataProcessor
    participant Trans as TransformerProcessor
    participant Store as Storage
    participant Ext as External Services

    C->>API: Request
    
    alt YouTube Video
        API->>YT: Process Video URL
        YT->>Store: Save Video
        YT->>Audio: Extract Audio
        par Parallel Processing
            Audio->>Audio: Segmentation
            Audio->>Ext: Whisper Transcription
            YT->>Meta: Extract Metadata
            Meta->>Trans: Analyze Metadata
        end
    else Audio File
        API->>Audio: Process Audio
        par Parallel Processing
            Audio->>Audio: Segmentation
            Audio->>Ext: Whisper Transcription
            Audio->>Meta: Extract Metadata
            Meta->>Trans: Analyze Metadata
        end
    end
    
    Audio->>Trans: Transform Text
    Trans->>Ext: GPT-4 Processing
    Trans->>Audio: Return Formatted
    Audio->>Store: Save Results
    Audio->>API: Return Response
    API->>C: Final Response
```

## Externe Dienste

### OpenAI GPT-4
- Transkription via Whisper
- Text-Transformation und -Analyse:
  - Zusammenfassungen
  - Strukturierung
  - Übersetzung
  - Metadaten-Extraktion

### YouTube API
- Video-Metadaten
- Download-Management
- Playlist-Verarbeitung
- Kanal-Informationen

### FFmpeg
- Audio-Extraktion aus Videos
- Format-Konvertierung
- Audio-Normalisierung
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
    
    H --> P[audio_processor.py]
    H --> Q[youtube_processor.py]
    H --> R[transformer_processor.py]
    H --> S[metadata_processor.py]
    
    C --> J[config.yaml]
    C --> K[config.docker.yaml]
    
    D --> L[Besprechung.md]
    D --> M[Youtube.md]
    D --> N[Gedanken.md]
    
    E --> O[audio/]
    E --> T[video/]
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
    whisper_model: "whisper-1"
  youtube:
    max_duration: 15000
    max_file_size: 104857600
  transformer:
    default_model: "gpt-4"
    max_tokens: 4000
  metadata:
    analyze_content: true
    extract_technical: true

logging:
  level: DEBUG
  file: logs/dev_detailed.log
```

### Umgebungsvariablen
- `OPENAI_API_KEY`: OpenAI API-Schlüssel (Whisper & GPT-4)
- `YOUTUBE_API_KEY`: YouTube API-Schlüssel
- `ENVIRONMENT`: Umgebung (development/staging/production)
- `USE_NEW_RESPONSE_FORMAT`: Feature-Flag für neue API-Responses

## Sicherheitsaspekte

### Datenschutz
- Temporäre Dateispeicherung mit automatischer Bereinigung
- Keine persistente Speicherung von Mediendaten
- Verschlüsselte Übertragung (HTTPS)
- Sichere Handhabung von API-Schlüsseln

### API-Sicherheit
- Rate-Limiting pro Endpunkt
- API-Key Authentifizierung
- Dateigrößenbeschränkungen
- Input-Validierung

### Monitoring
- Detailliertes Logging aller Prozessor-Operationen
- Performance-Tracking:
  - Prozessor-Laufzeiten
  - LLM-Nutzung und Kosten
  - Ressourcenverbrauch
- Fehlerüberwachung und -benachrichtigung

## Erweiterbarkeit

### Neue Prozessoren
- Implementierung von BaseProcessor
- Integration in die Prozessor-Hierarchie
- Standardisierte Response-Struktur
- LLM-Integration über BaseProcessor

### Template-System
- Markdown-basierte Templates
- Variables Substitutionssystem
- Mehrsprachige Templates
- Dynamische Template-Auswahl

### API-Erweiterungen
- Standardisierte Response-Struktur
- Versionierte Endpunkte
- Erweiterte Metadaten-Integration
- Batch-Verarbeitung