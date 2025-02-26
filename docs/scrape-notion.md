# Notion-Scraping Endpoint Konzept

## Übersicht

Der neue `/scrape-notion-page` Endpoint ermöglicht das Verarbeiten von Notion-Blocks und transformiert diese in eine mehrsprachige Newsfeed-Struktur. Die Quellsprache ist dabei fest auf Deutsch eingestellt, die Zielsprache ist Italienisch.

## Datenmodelle

### Eingabestruktur (NotionBlock)

```python
@dataclass(frozen=True)
class NotionBlock:
    object: str
    id: str
    parent_id: str
    type: str
    has_children: bool
    archived: bool
    in_trash: bool
    content: Optional[str] = None
    image: Optional[Dict[str, Any]] = None
    caption: Optional[str] = None
```

### Ausgabestruktur (Newsfeed)

```python
@dataclass(frozen=True)
class Newsfeed:
    title_DE: str
    intro_DE: str
    title_IT: str
    intro_IT: str
    image: Optional[str]
    content_DE: str
    content_IT: str
```

### Response-Struktur

Die Response-Struktur folgt dem Standard-Format:

```python
@dataclass(frozen=True)
class NotionData:
    input: List[NotionBlock]
    output: Newsfeed

@dataclass(frozen=True)
class NotionResponse(BaseResponse):
    data: Optional[NotionData] = None
```

## API Endpoint

```python
@api.route('/scrape-notion-page')
class NotionEndpoint(Resource):
    @api.expect(api.model('NotionRequest', {
        'blocks': fields.List(fields.Raw(description='Notion Block Struktur'))
    }))
    @api.response(200, 'Erfolg', notion_response)
    @api.response(400, 'Validierungsfehler', error_model)
    @api.doc(description='Verarbeitet Notion Blocks und erstellt mehrsprachigen Newsfeed-Inhalt (DE->IT)')
    def post(self):
        # Implementation
```

## Processor-Logik

Der EventProcessor wird um folgende Methode erweitert:

```python
async def process_notion_blocks(
    self,
    blocks: List[Dict[str, Any]]
) -> NotionResponse:
    """
    Verarbeitet Notion Blocks und erstellt mehrsprachigen Newsfeed-Inhalt.
    Die Quellsprache ist fest auf Deutsch eingestellt, die Zielsprache ist Italienisch.
    
    Args:
        blocks: Liste der Notion Blocks
        
    Returns:
        NotionResponse mit verarbeitetem Newsfeed-Inhalt
    """
```

### Verarbeitungsschritte

1. Validierung der Eingabeblöcke
2. Extraktion von Titel und Intro aus den ersten Blöcken
3. Extraktion von Bildern und deren URLs
4. Sammeln des restlichen Inhalts
5. Übersetzung der deutschen Texte ins Italienische
6. Erstellung der Newsfeed-Struktur
7. Rückgabe als NotionResponse

## Integration

1. Neue Dataclasses in `src/core/models/notion.py`
2. Erweiterung des EventProcessors in `src/processors/event_processor.py`
3. Neuer Endpoint in `src/api/routes.py`
4. Tests in `tests/processors/test_notion_processor.py`

## Fehlerbehandlung

- Validierung der Block-Struktur
- Prüfung auf fehlende Pflichtfelder
- Behandlung von Übersetzungsfehlern
- Fehlerhafte Block-Typen

## Tests

```python
def test_notion_block_processing():
    # Test der Block-Verarbeitung
    
def test_notion_translation():
    # Test der DE->IT Übersetzung
    
def test_notion_error_handling():
    # Test der Fehlerbehandlung
```

## Beispiel-Request

```json
{
  "blocks": [
    {
      "object": "block",
      "id": "1147d8db-6cf8-80bb-b347-e0bc29484385",
      "type": "paragraph",
      "content": "Der Erlebnisspielplatz in Brixen..."
    }
  ]
}
```

## Beispiel-Response

```json
{
  "status": "success",
  "request": {
    "processor": "notion",
    "timestamp": "2025-02-25T11:14:16.926Z",
    "parameters": {
      "block_count": 1
    }
  },
  "process": {
    "id": "proc_xyz",
    "main_processor": "notion",
    "started": "2025-02-25T11:14:16.926Z",
    "completed": "2025-02-25T11:14:17.926Z",
    "duration": 1000,
    "llm_info": {
      "model": "gpt-4",
      "tokens": 1234
    }
  },
  "data": {
    "input": [...],
    "output": {
      "title_DE": "Erlebnisspielplatz Brixen",
      "intro_DE": "Der Erlebnisspielplatz in Brixen...",
      "title_IT": "Parco giochi avventura Bressanone",
      "intro_IT": "Il parco giochi avventura a Bressanone...",
      "image": "https://...",
      "content_DE": "...",
      "content_IT": "..."
    }
  }
}
``` 