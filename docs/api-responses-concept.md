# API Response Konzept

## Grundprinzipien

1. **Nutzerorientierung**
   - Responses fokussieren sich auf relevante Ausgaben
   - Interne Prozesse werden transparent dokumentiert
   - Klare, logische Strukturierung der Daten

2. **Konsistenz**
   - Einheitliche Struktur über alle Prozessoren
   - Standardisierte Feldnamen
   - Vorhersehbare Datentypen
   - Durchgängiges LLM-Tracking

3. **Klarheit**
   - Logische Gruppierung von Informationen
   - Selbsterklärende Feldnamen
   - Minimale Verschachtelung

## Aktuelle Implementierung

### Basis-Response-Struktur (BaseResponse)
```json
{
  "status": "success",
  "request": {
    "processor": "transformer",
    "timestamp": "2024-03-20T15:30:00Z",
    "parameters": {
      "task": "translation",
      "source_language": "en",
      "target_language": "de"
    }
  },
  "process": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "main_processor": "transformer",
    "sub_processors": [],
    "duration": 1500,
    "started": "2024-03-20T15:30:00Z",
    "completed": "2024-03-20T15:30:01Z",
    "llm_info": {
      "requests_count": 1,
      "total_tokens": 150,
      "total_duration": 1500,
      "requests": [
        {
          "model": "gpt-4",
          "purpose": "translation",
          "tokens": 150,
          "duration": 1500,
          "timestamp": "2024-03-20T15:30:01Z"
        }
      ]
    }
  },
  "data": {
    // Response-spezifische Daten
  }
}
```

### Transformer-Response-Struktur (TransformerResponse)
```json
{
  "status": "success",
  "request": {
    "processor": "transformer",
    "timestamp": "2024-03-20T15:30:00Z",
    "source_text": "Hello W...",
    "source_language": "en",
    "target_language": "de",
    "task": "translation"
  },
  "process": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "main_processor": "transformer",
    "sub_processors": [],
    "duration": 1500,
    "started": "2024-03-20T15:30:00Z",
    "completed": "2024-03-20T15:30:01Z",
    "llm_info": {
      "requests_count": 1,
      "total_tokens": 150,
      "total_duration": 1500,
      "requests": [
        {
          "model": "gpt-4",
          "purpose": "translation",
          "tokens": 150,
          "duration": 1500,
          "timestamp": "2024-03-20T15:30:01Z"
        }
      ]
    }
  },
  "data": {
    "input": {
      "text": "Hello World",
      "language": "en"
    },
    "output": {
      "text": "Hallo Welt",
      "language": "de"
    }
  }
}
```

### Template-Transformation Response
```json
{
  "status": "success",
  "request": {
    "processor": "transformer",
    "timestamp": "2024-03-20T15:30:00Z",
    "source_text": "Meeting N...",
    "template": "meeting",
    "context": {
      "title": "Team Meeting",
      "date": "2024-03-20"
    }
  },
  "process": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "main_processor": "transformer",
    "sub_processors": [],
    "duration": 1200,
    "started": "2024-03-20T15:30:00Z",
    "completed": "2024-03-20T15:30:01Z",
    "llm_info": {
      "requests_count": 1,
      "total_tokens": 150,
      "total_duration": 1200,
      "requests": [
        {
          "model": "gpt-4",
          "purpose": "template_transform",
          "tokens": 150,
          "duration": 1200,
          "timestamp": "2024-03-20T15:30:01Z"
        }
      ]
    }
  },
  "data": {
    "input": {
      "text": "Meeting Notizen",
      "template": "meeting",
      "variables": {
        "title": "Team Meeting",
        "date": "2024-03-20"
      }
    },
    "output": {
      "text": "# Team Meeting\n\nDatum: 2024-03-20\n\nNotizen:\nMeeting Notizen",
      "format": "markdown"
    }
  }
}
```

### Fehlerfall-Response
```json
{
  "status": "error",
  "request": {
    "processor": "transformer",
    "timestamp": "2024-03-20T15:30:00Z",
    "source_text": "Test t..."
  },
  "process": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "main_processor": "transformer",
    "sub_processors": [],
    "duration": 100,
    "started": "2024-03-20T15:30:00Z",
    "completed": "2024-03-20T15:30:00Z",
    "llm_info": {
      "requests_count": 0,
      "total_tokens": 0,
      "total_duration": 0,
      "requests": []
    }
  },
  "error": {
    "code": "TRANSFORM_ERROR",
    "message": "Transformation fehlgeschlagen",
    "details": {
      "reason": "Invalid input format"
    }
  }
}
```

## Implementierungsdetails

### 1. BaseResponse
- Basisklasse für alle API-Responses
- Standardisierte Struktur für Status, Request und Process
- Integriertes LLM-Tracking mit Millisekunden-Genauigkeit
- Validierung von Status und Error-Informationen

#### LLM-Tracking
- Automatische Aggregation von LLM-Nutzungsstatistiken
- Detaillierte Request-Historie mit Zeitstempeln
- Performance-Monitoring in Millisekunden
- Kostenabschätzung basierend auf Token-Nutzung

### 2. TransformerResponse
- Spezialisierte Response für Text-Transformationen
- Klare Trennung von Input, Output und Transform-Daten
- Unterstützung für Template-basierte Transformationen
- Automatische LLM-Integration mit Performance-Tracking

#### Datenstruktur
- **Input**: Eingabetext (gekürzt), Sprache, Template, Variablen
- **Output**: Ausgabetext, Sprache, Format
- **Process**: Task, Modell, Performance-Metriken in ms

### 3. MetadataProcessor Integration

#### Neue Typdefinitionen
```python
class MetadataContent(BaseModel):
    """Inhaltliche Metadaten aus der Analyse."""
    type: str
    created: datetime
    title: str
    authors: List[str]
    language: str
    topics: List[str]
    keywords: List[str]
    summary: str
    
class MetadataTechnical(BaseModel):
    """Technische Metadaten der Datei."""
    file_name: str
    file_size: int
    file_mime: str
    file_extension: str
    
class MetadataResult(BaseModel):
    """Gesamtergebnis der Metadatenanalyse."""
    content: MetadataContent
    technical: MetadataTechnical

class MetadataResponse(BaseResponse):
    """API-Response für Metadatenanalyse."""
    data: MetadataResult
```

#### Integration mit TransformerProcessor
```python
class MetadataProcessor:
    def __init__(self):
        self.transformer = TransformerProcessor()
        
    async def analyze_content(self, text: str) -> MetadataContent:
        """Analysiert Text mit dem TransformerProcessor."""
        # Transformer für Analyse nutzen
        transform_response = await self.transformer.transform(
            text=text,
            task="analyze",
            source_language="auto",
            target_language="de"
        )
        
        # Response auswerten und Metadaten extrahieren
        analysis = transform_response.data["output"]["text"]
        
        # Strukturierte Metadaten erstellen
        return MetadataContent(
            type=analysis["type"],
            created=datetime.now(),
            title=analysis["title"],
            authors=analysis["authors"],
            language=transform_response.data["input"]["language"],
            topics=analysis["topics"],
            keywords=analysis["keywords"],
            summary=analysis["summary"]
        )
```

## Best Practices

### 1. Response-Struktur
- Jede Response MUSS von `BaseResponse` erben
- LLM-Informationen MÜSSEN im `process.llm_info` dokumentiert werden
- Daten MÜSSEN logisch gruppiert werden (input/output)
- Zeiten MÜSSEN in Millisekunden angegeben werden

### 2. LLM-Tracking
- Jeden LLM-Request über `add_llm_request()` dokumentieren
- Performance-Metriken in Millisekunden sammeln
- Request-Historie für Debugging bewahren
- Token-Nutzung für Kostenabschätzung tracken

### 3. Fehlerbehandlung
- Klare Fehlercodes definieren
- Detaillierte Fehlermeldungen bereitstellen
- Kontext für Debugging mitliefern
- Performance-Metriken auch bei Fehlern sammeln

## Nächste Schritte

1. **MetadataProcessor Implementierung**
   - [x] Neue Response-Struktur implementieren
   - [x] Integration mit TransformerProcessor
   - [ ] Tests für Metadatenanalyse
   - [ ] API-Endpunkt erstellen

2. **AudioProcessor Anpassung**
   - [ ] Neue Response-Struktur implementieren
   - [ ] Integration mit MetadataProcessor
   - [ ] Tests aktualisieren
   - [ ] API-Dokumentation anpassen

3. **YouTubeProcessor Update**
   - [ ] Neue Response-Struktur implementieren
   - [ ] Integration mit AudioProcessor
   - [ ] Integration mit MetadataProcessor
   - [ ] Tests aktualisieren

4. **Dokumentation**
   - [ ] OpenAPI/Swagger aktualisieren
   - [ ] Beispiele für alle Response-Typen
   - [ ] Performance-Monitoring dokumentieren
   - [ ] Entwicklerhandbuch erweitern

## Migrationskonzept

### Migrationsstrategie

1. **Grundprinzipien**
   - Fokus auf interne Datenstrukturen
   - Schrittweise Migration, Prozessor für Prozessor
   - Intensive Tests nach jedem Schritt
   - Minimale Änderungen an der Geschäftslogik

2. **Reihenfolge der Migration**
   Basierend auf den Abhängigkeiten:
   1. TransformerProcessor (keine Abhängigkeiten)
   2. MetadataProcessor (nutzt nur TransformerProcessor)
   3. AudioProcessor (nutzt Transformer und Metadata)
   4. YouTubeProcessor (nutzt Audio und Metadata)

### Detaillierter Migrationsplan

#### Phase 1: TransformerProcessor
1. **Neue Typdefinitionen**
   ```python
   class TransformerInput(BaseModel):
       text: str
       template: str
       language: str = "de"
       
   class TransformerResult(BaseModel):
       template: str
       content: dict = {
           "tags": List[str],
           "title": str,
           "summary": str,
           "formatted_text": str,
           "language": str
       }

   class TransformerResponse(BaseResponse):
       data: TransformerResult
   ```

2. **Interne Struktur anpassen**
   ```python
   class TransformerProcessor:
       def process(self, text: str, template: str) -> TransformerResponse:
           # Bestehende Logik beibehalten
           result = self._transform_text(text, template)
           
           # Neue Response-Struktur
           return TransformerResponse(
               status="success",
               request={
                   "processor": "transformer",
                   "timestamp": datetime.now().isoformat(),
                   "parameters": {
                       "template": template,
                       "language": "de"
                   }
               },
               process={
                   "id": self.process_id,
                   "main_processor": "transformer",
                   "sub_processors": [],
                   "duration": self.duration,
                   "started": self.start_time,
                   "completed": self.end_time,
                   "llm_info": self.llm_tracking.get_info()
               },
               data=result
           )
   ```

3. **Tests**
   ```python
   def test_transformer_response():
       processor = TransformerProcessor()
       response = processor.process(
           text="Test text",
           template="Gedanken"
       )
       assert isinstance(response, TransformerResponse)
       assert response.status == "success"
       assert "template" in response.data
       assert "content" in response.data
   ```

#### Phase 2: MetadataProcessor
1. **Neue Typdefinitionen**
   ```python
   class MetadataContent(BaseModel):
       type: str
       created: datetime
       title: str
       authors: str
       language: str
       
   class MetadataTechnical(BaseModel):
       file_name: str
       file_size: int
       file_mime: str
       file_extension: str
       
   class MetadataResult(BaseModel):
       content: MetadataContent
       technical: MetadataTechnical

   class MetadataResponse(BaseResponse):
       data: MetadataResult
   ```

2. **Integration mit TransformerProcessor**
   ```python
   class MetadataProcessor:
       def __init__(self):
           self.transformer = TransformerProcessor()
           
       def process(self, file_path: str) -> MetadataResponse:
           # Technische Metadaten extrahieren
           technical = self._extract_technical(file_path)
           
           # Inhaltliche Analyse via Transformer
           content = self._analyze_content(file_path)
           
           return MetadataResponse(
               status="success",
               request={...},
               process={
                   "id": self.process_id,
                   "main_processor": "metadata",
                   "sub_processors": ["transformer"],
                   ...
               },
               data={
                   "content": content,
                   "technical": technical
               }
           )
   ```

#### Phase 3: AudioProcessor
1. **Neue Typdefinitionen**
   ```python
   class AudioTranscription(BaseModel):
       original: dict = {
           "text": str,
           "detected_language": str,
           "segments": List[dict]
       }
       translation: Optional[dict]

   class AudioResult(BaseModel):
       transcription: AudioTranscription
       transform: Optional[TransformerResult]
       metadata: Optional[MetadataResult]

   class AudioResponse(BaseResponse):
       data: AudioResult
   ```

2. **Integration mit anderen Prozessoren**
   ```python
   class AudioProcessor:
       def __init__(self):
           self.transformer = TransformerProcessor()
           self.metadata = MetadataProcessor()
   ```

#### Phase 4: YouTubeProcessor
[... ähnliche Struktur für YouTubeProcessor ...]

### Teststrategie

1. **Unit Tests pro Prozessor**
   - Response-Struktur
   - Datentypen
   - Fehlerszenarien

2. **Integrationstests**
   - Prozessor-Interaktionen
   - End-to-End Flows
   - Fehlerfortpflanzung

3. **Validierungstests**
   - Schema-Validierung
   - Datenintegrität
   - Performance-Vergleich

### Rollout-Plan

1. **Entwicklung**
   - Prozessor für Prozessor implementieren
   - Intensive Tests nach jedem Schritt
   - Code-Review und Dokumentation

2. **Validierung**
   - Vollständige Testsuite ausführen
   - Performance-Messungen
   - Fehlerszenarien prüfen

3. **Deployment**
   - Direkte Umstellung (kein Feature-Flag nötig)
   - Monitoring der Fehlerraten
   - Backup der alten Version 