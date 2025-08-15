# Common Secretary Services API Dokumentation

## Übersicht
Die Common Secretary Services API bietet eine umfangreiche Sammlung von Endpoints für die Verarbeitung und Analyse verschiedener Medientypen. Die API ist in mehrere Hauptkategorien unterteilt, die jeweils spezifische Funktionalitäten abdecken.

## API-Basis
- **Base URL**: `http://127.0.0.1:5001/api`
- **Swagger UI**: `http://127.0.0.1:5001/api/doc`

## Endpoint-Kategorien

### 1. Audio-Verarbeitung (`/audio`)

#### POST /audio/process
Verarbeitet eine Audio-Datei. Mit dem Parameter useCache=false kann die Cache-Nutzung deaktiviert werden.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| file | file (formData) | Audio-Datei | - |
| source_language | string (formData) | Quellsprache (ISO 639-1 code, z.B. "en", "de") | "de" |
| target_language | string (formData) | Zielsprache (ISO 639-1 code, z.B. "en", "de") | "de" |
| template | string (formData) | Optional Template für die Verarbeitung | "" |
| useCache | boolean (formData) | Cache verwenden | true |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/audio/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@audio.mp3" \
     -F "source_language=de" \
     -F "target_language=en" \
     -F "template=custom_template" \
     -F "useCache=true"
```

#### GET /audio/{audio_id}
Ruft Informationen zu einer verarbeiteten Audio-Datei ab.

**Parameter:**
| Name | Typ | Beschreibung |
|------|-----|--------------|
| audio_id | string (path) | ID der Audio-Datei |

**Beispielanfrage:**
```bash
curl -X GET "http://127.0.0.1:5001/api/audio/12345" \
     -H "Authorization: Bearer YOUR_TOKEN"
```

### 2. Bild-OCR (`/imageocr`)

#### POST /imageocr/process
Verarbeitet ein Bild für die optische Zeichenerkennung.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| file | file (formData) | Bilddatei | - |
| language | string (formData) | Sprache für OCR (ISO 639-1 code) | "de" |
| enhance | boolean (formData) | Bildverbesserung aktivieren | true |
| useCache | boolean (formData) | Cache verwenden | true |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/imageocr/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@image.jpg" \
     -F "language=de" \
     -F "enhance=true" \
     -F "useCache=true"
```

### 3. PDF-Verarbeitung (`/pdf`)

#### POST /pdf/process
Verarbeitet ein PDF-Dokument.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| file | file (formData) | PDF-Datei | - |
| extract_text | boolean (formData) | Text extrahieren | true |
| extract_images | boolean (formData) | Bilder extrahieren | false |
| useCache | boolean (formData) | Cache verwenden | true |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/pdf/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@document.pdf" \
     -F "extract_text=true" \
     -F "extract_images=false" \
     -F "useCache=true"
```

### 4. Video-Verarbeitung (`/video`)

#### POST /video/process
Verarbeitet eine Video-Datei.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| file | file (formData) | Video-Datei | - |
| extract_audio | boolean (formData) | Audio extrahieren | true |
| extract_frames | boolean (formData) | Frames extrahieren | false |
| frame_interval | integer (formData) | Intervall für Frame-Extraktion (in Sekunden) | 1 |
| useCache | boolean (formData) | Cache verwenden | true |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/video/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "file=@video.mp4" \
     -F "extract_audio=true" \
     -F "extract_frames=true" \
     -F "frame_interval=1" \
     -F "useCache=true"
```

### 5. Story-Verarbeitung (`/story`)

#### POST /story/process
Verarbeitet eine Story.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| text | string (formData) | Story-Text | - |
| language | string (formData) | Sprache (ISO 639-1 code) | "de" |
| analyze_sentiment | boolean (formData) | Sentiment-Analyse durchführen | true |
| extract_keywords | boolean (formData) | Schlüsselwörter extrahieren | true |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/story/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "text=Story-Text" \
     -F "language=de" \
     -F "analyze_sentiment=true" \
     -F "extract_keywords=true"
```

### 6. Session-Management (`/session`)

#### POST /session/create
Erstellt eine neue Session.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| user_id | string (formData) | Benutzer-ID | - |
| preferences | object (formData) | Benutzereinstellungen | {} |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/session/create" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "user_id=123" \
     -F "preferences={\"language\":\"de\"}"
```

### 7. Event-Job-Verarbeitung (`/eventjob`)

#### POST /eventjob/create
Erstellt einen neuen Verarbeitungsauftrag.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| job_type | string (formData) | Auftragstyp | - |
| parameters | object (formData) | Auftragsparameter | {} |
| priority | integer (formData) | Priorität (1-10) | 5 |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/eventjob/create" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "job_type=audio_processing" \
     -F "parameters={\"file_id\":\"123\"}" \
     -F "priority=5"
```

### 8. Track-Verarbeitung (`/track`)

#### POST /track/create
Erstellt einen neuen Track.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| track_type | string (formData) | Track-Typ | - |
| metadata | object (formData) | Track-Metadaten | {} |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/track/create" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "track_type=audio" \
     -F "metadata={\"duration\":120}"
```

### 9. Transformer-Verarbeitung (`/transformer`)

#### POST /transformer/process
Verarbeitet Text mit einem Transformer-Modell.

**Parameter:**
| Name | Typ | Beschreibung | Standardwert |
|------|-----|--------------|--------------|
| text | string (formData) | Eingabetext | - |
| model | string (formData) | Modellname | "default" |
| parameters | object (formData) | Modellparameter | {} |

**Beispielanfrage:**
```bash
curl -X POST "http://127.0.0.1:5001/api/transformer/process" \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -F "text=Eingabetext" \
     -F "model=default" \
     -F "parameters={\"max_length\":100}"
```

## Allgemeine API-Eigenschaften

### Authentifizierung
- Die API verwendet JWT-Token für die Authentifizierung
- Token müssen im Authorization-Header mitgeführt werden

### Fehlerbehandlung
- Standardisierte Fehlerantworten
- HTTP-Statuscodes entsprechend der REST-Konventionen
- Detaillierte Fehlermeldungen

### Rate Limiting
- Implementierte Rate-Limits pro Endpoint
- Informationen in den Response-Headern

## Best Practices

### API-Nutzung
1. Immer die neueste API-Version verwenden
2. Fehlerbehandlung implementieren
3. Rate-Limits beachten
4. Asynchrone Verarbeitung nutzen

### Performance
- Große Dateien in Chunks hochladen
- Asynchrone Verarbeitung für lange Tasks
- Caching wo möglich

## Support und Kontakt
Bei Fragen oder Problemen wenden Sie sich bitte an das Support-Team.

## Versionierung
- Aktuelle Version: 1.0.0
- API-Versionierung über URL-Pfad
- Changelog verfügbar unter `/api/changelog` 