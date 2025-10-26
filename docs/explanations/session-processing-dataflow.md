# Session Processing: Kompletter Datenfluss

## Überblick

Dieses Dokument erklärt Schritt für Schritt, was bei der Session-Verarbeitung passiert, wie Daten transformiert werden und wie die finale Response aufgebaut wird. Die Erklärung basiert auf einem realen MongoDB Cache-Eintrag und dem Template `Session_en.md`.

## Beispiel-Session

**Session**: "Open Source in EU policy"  
**Event**: "Open Source in EU policy - SFSCON"  
**Template**: `Session_en.md`  
**Zielsprache**: Englisch (en)

---

## Phase 1: Eingabedaten (API Request)

### 1.1 Request-Parameter

Der API-Aufruf `POST /api/session/process` erhält folgende Parameter:

```json
{
  "event": "Open Source in EU policy - SFSCON",
  "session": "Open Source in EU policy",
  "url": "https://www.sfscon.it/talks/open-source-in-eu-policy/",
  "filename": "open-source-in-eu-policy.md",
  "track": "Seminar 1",
  "day": "08/11/2024",
  "starttime": "10:30",
  "endtime": "10:50",
  "speakers": ["Jordan Maris"],
  "video_url": "https://player.vimeo.com/video/1029681888?byline=0&portrait=0&dnt=1",
  "attachments_url": "https://www.sfscon.it/wp-content/uploads/2024/11/1730746598730SFScon-presentatin.pdf",
  "source_language": "en",
  "target_language": "en",
  "template": "Session"
}
```

**Pflichtfelder**: event, session, url, filename, track  
**Optionale Felder**: Alle anderen

### 1.2 SessionInput Dataclass

Diese Parameter werden in eine `SessionInput` Dataclass konvertiert:

```python
SessionInput(
    event="Open Source in EU policy - SFSCON",
    session="Open Source in EU policy",
    url="https://www.sfscon.it/talks/open-source-in-eu-policy/",
    filename="open-source-in-eu-policy.md",
    track="Seminar 1",
    day="08/11/2024",
    starttime="10:30",
    endtime="10:50",
    speakers=["Jordan Maris"],
    video_url="https://player.vimeo.com/video/1029681888...",
    video_transcript=None,  # NEU: Optional vorhandenes Transkript
    attachments_url="https://www.sfscon.it/wp-content/uploads/...",
    source_language="en",
    target_language="en",
    template="Session"
)
```

**Validierung in `__post_init__`**: Pflichtfelder werden geprüft, Zeitformat wird validiert.

---

## Phase 2: Cache-Key Generierung

### 2.1 Cache-Key Berechnung

Der SessionProcessor erstellt einen eindeutigen Cache-Schlüssel:

```python
cache_key = _create_cache_key(input_data)
```

**Basis-Key Komponenten**:
- event: "Open Source in EU policy - SFSCON"
- session: "Open Source in EU policy"
- url: "https://www.sfscon.it/talks/open-source-in-eu-policy/"
- track: "Seminar 1"
- target_language: "en"
- template: "Session_en"
- video_url (optional)
- video_transcript_hash (optional, **NEU**)
- attachments_url (optional)

**Ergebnis**:
```
cache_key = "f80ac1044a5cd4973cd241f851b18e8f101baac6cb25b87a10cd2d78f3b8c9ea"
```

Dieser Key wird für MongoDB-Lookup und Caching verwendet.

---

## Phase 3: Datensammlung (Scraping & Processing)

### 3.1 Webseite Scrapen

**Funktion**: `_fetch_session_page(url)`

**Input**: `https://www.sfscon.it/talks/open-source-in-eu-policy/`

**Output**: `web_text` (6.147 Zeichen)

```
web_text = "Open Source in EU policy - SFSCON\nGo to main menu\n
Go to main content\nSFSCON - Free Software Conference\nHome\n
About\n... [gekürzt] ... Making laws with the Open Source 
community in mind\nSeminar 1\n10:30\n20 mins\n08/11/2024..."
```

**Verarbeitung**:
- HTTP GET Request mit User-Agent Header
- HTML wird mit BeautifulSoup geparst
- Textextraktion (ohne HTML-Tags)
- Bereinigung von Whitespace

### 3.2 Video-Verarbeitung

**Funktion**: `_process_video(video_url, source_language, target_language, use_cache)`

**Input**: 
- video_url: `https://player.vimeo.com/video/1029681888...`
- source_language: "en"
- target_language: "en" (Transkript bleibt in Originalsprache)

**Alternativ (NEU)**: Wenn `video_transcript` Parameter gesetzt ist:
```python
if video_transcript:
    video_transcript_text = video_transcript
    logger.info("Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)")
elif video_url:
    video_transcript_text = await self._process_video(...)
```

**Output**: `video_transcript` (8.234 Zeichen)

```
video_transcript = "And now we will have here Jordan, uh, Mari 
from OSI, open Source Initiative, which is an organization in 
the ecosystem of free software organizations..."
```

**Verarbeitung**:
1. VideoProcessor wird aufgerufen
2. Video wird heruntergeladen/gestreamt
3. Audio wird extrahiert
4. Whisper API transkribiert Audio
5. LLM-Nutzung wird getrackt (Whisper-1 Modell)

**LLM-Tracking**:
```python
LLMRequest(
    model="whisper-1",
    purpose="transcription",
    tokens=estimated_tokens,  # ~12.351 tokens
    duration=duration_ms,
    processor="VideoProcessor"
)
```

### 3.3 Anhänge (PDF) Verarbeiten

**Funktion**: `_process_attachments(attachments_url, session_data, target_dir, use_cache)`

**Input**: `https://www.sfscon.it/wp-content/uploads/2024/11/1730746598730SFScon-presentatin.pdf`

**Output**:
- `attachment_paths`: Liste von 18 Bildern (Preview-Seiten)
- `page_texts`: Liste von 18 Texten (OCR von jeder Seite)
- `asset_dir`: Zielverzeichnis für Assets

```python
attachment_paths = [
    "Open Source in EU policy SFSCON/assets/open source in eu policy/preview_001.jpg",
    "Open Source in EU policy SFSCON/assets/open source in eu policy/preview_002.jpg",
    ...
    "Open Source in EU policy SFSCON/assets/open source in eu policy/preview_018.jpg"
]

page_texts = [
    "Open Source in\nEU policy\nSFSCon\nFriday 8th 2024\nJordan Maris...",
    "whoami\n➢\nToday: Policy Analyst for the Open Source Initiative...",
    ...
    "THANKS\n"
]

asset_dir = "Open Source in EU policy SFSCON/assets/open source in eu policy"
```

**Verarbeitung**:
1. PDFProcessor lädt PDF herunter
2. PDF wird in Seiten aufgeteilt (18 Seiten)
3. Jede Seite wird als JPEG gerendert (preview_xxx.jpg)
4. ImageOCRProcessor extrahiert Text von jeder Seite
5. Bilder werden in asset_dir kopiert
6. Gallery-Pfade werden für Markdown generiert

**LLM-Tracking** (pro Seite):
```python
LLMRequest(
    model="gpt-4o",
    purpose="image_ocr",
    tokens=per_page_tokens,
    duration=per_page_duration_ms,
    processor="ImageOCRProcessor"
)
```

---

## Phase 4: Template-Verarbeitung & Markdown-Generierung

### 4.1 Template Laden

**Template-Datei**: `templates/Session_en.md`

**Template-Struktur**:
```markdown
---
tags: {{tags|What are the 10 most important keywords...}}
title: {{title|an appropriate title for the session...}}
subtitle: {{subtitle|an appropriate subtitle...}}
intro: {{intro|how can we briefly introduce this session...}}
speaker: {{speakers|Which speakers are mentioned...}}
date: {{day|Display the date in the format yyyy-mm-dd.}}
place: {{ort|Which location is mentioned...}}
track: {{track}}
topic: {{topic|Which of the following topics...}}
relevance: {{relevance|How important is this session...}}
cacheId: {{cache_key}}
---
# {{title|an appropriate title for the session}}

> [! note]-
> The content of this page is generated by...

Source: [{{url}}]({{url}})

{videoplayer}

## Summary & Highlights:

{{summary|Please analyze the texts...}}

## Importance for an eco-social transformation

{{ecosocial|What is the importance...}}

{slides}
## Links

{{attachment_links|Create a list of all links...}}

--- systemprompt
You are a specialized journalist who researches topics...
```

### 4.2 Template-Variablen Identifizieren

**TransformerProcessor** (`transform_by_template`) identifiziert:

**Strukturierte Variablen** (mit Beschreibung):
```python
{
  "tags": "What are the 10 most important keywords...",
  "title": "an appropriate title for the session...",
  "subtitle": "an appropriate subtitle...",
  "intro": "how can we briefly introduce this session...",
  "speakers": "Which speakers are mentioned...",
  "day": "Display the date in the format yyyy-mm-dd.",
  "ort": "Which location is mentioned...",
  "topic": "Which of the following topics...",
  "relevance": "How important is this session...",
  "summary": "Please analyze the texts...",
  "ecosocial": "What is the importance...",
  "attachment_links": "Create a list of all links..."
}
```

**Einfache Variablen** (ohne Beschreibung):
```python
{
  "url": "{{url}}",
  "track": "{{track}}",
  "cache_key": "{{cache_key}}"
}
```

**YAML Frontmatter Variablen**:
```python
{
  "tags": (isFrontmatter=True),
  "title": (isFrontmatter=True),
  "subtitle": (isFrontmatter=True),
  ...
}
```

### 4.3 Kontext-Variablen Ersetzen

**Einfache Variablen** werden sofort ersetzt:

```python
template_content = template_content.replace("{{url}}", input_data.url)
template_content = template_content.replace("{{track}}", input_data.track)
template_content = template_content.replace("{{cache_key}}", cache_key)
```

**Spezielle Platzhalter**:
```python
# {videoplayer} wird ersetzt mit:
video_iframe = f'<iframe src="{video_url}" width="640" height="360" frameborder="0" allowfullscreen></iframe>'
template_content = template_content.replace("{videoplayer}", video_iframe)

# {slides} wird ersetzt mit Galerie-Tabelle:
slides_gallery = _generate_slides_gallery(attachment_paths, page_texts)
template_content = template_content.replace("{slides}", slides_gallery)
```

### 4.4 LLM-Anfrage für Strukturierte Daten

**System-Prompt** (aus Template extrahiert):
```
You are a specialized journalist who researches topics for 
environmental and social organizations and presents them in an 
understandable and applicable way. Your task is to present 
complex developments in open source, software development, 
infrastructure, networks, security and hardware in such a way 
that their significance for sustainable, social and 
community-oriented transformation processes becomes clear.

IMPORTANT: Your response must be a valid JSON object where 
each key corresponds to a template variable.
```

**User-Prompt**:
```
Analyze the following text and extract the information as a JSON object:

TEXT:
[web_text]
[video_transcript]
[page_texts combined]

CONTEXT:
{
  "url": "https://www.sfscon.it/talks/open-source-in-eu-policy/",
  "session": "Open Source in EU policy",
  "event": "Open Source in EU policy - SFSCON",
  "track": "Seminar 1",
  "day": "08/11/2024",
  "starttime": "10:30",
  "endtime": "10:50",
  "speakers": ["Jordan Maris"],
  "video_url": "...",
  "attachment_paths": [...],
  "page_count": 18,
  "cache_key": "f80ac..."
}

REQUIRED FIELDS:
{
  "tags": "What are the 10 most important keywords...",
  "title": "an appropriate title for the session...",
  ...
}

INSTRUCTIONS:
1. Extract all required information from the text
2. Return a single JSON object where each key matches a field name
3. Provide all values in language: en
4. Ensure the response is valid JSON
5. Do not include any text outside the JSON object
```

**LLM Response** (GPT-4o):
```json
{
  "tags": "open-source,eu-policy,ai-act,cyber-resilience-act,product-liability-directive,open-source-ai,openwashing,standardization,community-mobilization,legislation",
  "title": "Open Source in EU Policy and the AI Act Exemption",
  "subtitle": "How the Open Source Community Influences EU Tech Legislation and Faces Challenges",
  "intro": "Explore how the Open Source community has actively shaped EU technology laws, including the AI Act, and the ongoing efforts to ensure these laws support sustainable and ethical software development.",
  "speaker": "Jordan Maris",
  "date": "2024-11-08",
  "place": "NOI Techpark, Bolzano, Italy",
  "topic": "intergovernmental cooperation",
  "relevance": "8",
  "summary": "This session focuses on the evolving relationship... [120+ words per section]",
  "ecosocial": "The session highlights the critical role of open source software as a public good...",
  "attachment_links": "[Open Source in EU policy Presentation PDF](https://www.sfscon.it/wp-content/uploads/2024/11/1730746598730SFScon-presentatin.pdf)",
  "attachment_page_1_summary": "The first slide introduces the session...",
  "attachment_page_2_summary": "This slide presents Jordan Maris's background...",
  ...
  "attachment_page_18_summary": "The final slide expresses thanks..."
}
```

**LLM-Tracking**:
```python
LLMRequest(
    model="gpt-4o",
    purpose="template_transform",
    tokens=19134,  # total_tokens (prompt + completion)
    duration=2500,  # ms
    processor="TransformerProcessor"
)
```

### 4.5 Template-Variablen Füllen

**Strukturierte Variablen** werden ersetzt:

```python
for field_name, field_value in result_json.items():
    pattern = r'\{\{' + re.escape(field_name) + r'\|[^}]+\}\}'
    
    # Für Frontmatter-Felder: YAML-bereinigen
    if field_def.isFrontmatter:
        value = _clean_yaml_value(field_value)  # Entfernt Sonderzeichen
    else:
        value = str(field_value)
    
    template_content = re.sub(pattern, value, template_content)
```

**Beispiel**:
```markdown
VORHER:
tags: {{tags|What are the 10 most important keywords...}}
title: {{title|an appropriate title for the session...}}

NACHHER:
tags: open-source,eu-policy,ai-act,cyber-resilience-act...
title: Open Source in EU Policy and the AI Act Exemption
```

### 4.6 Slides-Galerie Generieren

**Funktion**: `_generate_slides_gallery(attachment_paths, page_texts)`

**Input**:
- 18 Bild-Pfade
- 18 OCR-Texte
- 18 LLM-Zusammenfassungen (aus structured_data)

**Output**: Markdown-Tabelle

```markdown
## Slides:
|  |  | 
| --- | --- | 
| ![[Open Source in EU policy SFSCON/assets/open source in eu policy/preview_001.jpg\|300]] | The first slide introduces the session titled 'Open Source in EU policy' at SFSCon... 
| ![[Open Source in EU policy SFSCON/assets/open source in eu policy/preview_002.jpg\|300]] | This slide presents Jordan Maris's background... 
...
```

**Verarbeitung**:
1. Für jede Seite: Bild-Link + LLM-generierte Zusammenfassung
2. Obsidian-kompatible Bildlinks (`![[path|300]]`)
3. Tabellen-Format für bessere Darstellung

### 4.7 Finales Markdown

**Output**: `markdown_content` (komplettes Markdown)

```markdown
---
tags: open-source,eu-policy,ai-act...
title: Open Source in EU Policy and the AI Act Exemption
subtitle: How the Open Source Community Influences EU Tech Legislation...
intro: Explore how the Open Source community has actively shaped...
speaker: Jordan Maris
date: 2024-11-08
place: Bolzano, Italy
track: Seminar 1
topic: intergovernmental cooperation
relevance: 8
cacheId: f80ac1044a5cd4973cd241f851b18e8f101baac6cb25b87a10cd2d78f3b8c9ea
---
# Open Source in EU Policy and the AI Act Exemption

> [! note]-
> The content of this page is generated by audio/video transcription...

Source: [https://www.sfscon.it/talks/open-source-in-eu-policy/](https://www.sfscon.it/talks/open-source-in-eu-policy/)

<iframe src="https://player.vimeo.com/video/1029681888?byline=0&portrait=0&dnt=1" width="640" height="360" frameborder="0" allowfullscreen></iframe>

## Summary & Highlights:

This session focuses on the evolving relationship between the Open Source community...

**Introduction to EU Open Source Policy Landscape**
Jordan Maris introduces himself and outlines the recent surge in EU tech legislation...

## Importance for an eco-social transformation

The session highlights the critical role of open source software as a public good...

## Slides:
|  |  | 
| --- | --- | 
| ![[Open Source in EU policy SFSCON/assets/open source in eu policy/preview_001.jpg\|300]] | The first slide introduces... 
...

## Links

[Open Source in EU policy Presentation PDF](https://www.sfscon.it/wp-content/uploads/2024/11/1730746598730SFScon-presentatin.pdf)
```

---

## Phase 5: Dateien Speichern & Archiv Erstellen

### 5.1 Markdown-Datei Speichern

**Zielverzeichnis-Struktur**:
```
sessions/
  Open Source in EU policy SFSCON/
    en/
      Seminar 1/
        Open Source in EU Policy.md  ← Markdown-Datei
```

**Pfad-Berechnung**:
```python
target_dir, _, translated_event = await _get_translated_entity_directory(
    event_name="Open Source in EU policy - SFSCON",
    track_name="Seminar 1",
    target_language="en",
    source_language="en",
    use_translated_names=True
)
# Result: sessions/Open Source in EU policy SFSCON/en/Seminar 1

translated_filename = await _translate_filename(
    filename="open-source-in-eu-policy.md",
    target_language="en",
    source_language="en"
)
# Result: Open Source in EU Policy.md

markdown_file = target_dir / translated_filename
```

**Dateischreiben**:
```python
markdown_file.write_text(markdown_content, encoding='utf-8')
```

**Ergebnis**:
```
markdown_file = "sessions\\Open Source in EU policy SFSCON\\en\\Seminar 1\\Open Source in EU Policy.md"
```

### 5.2 Assets Kopieren

**Quelle**: Temporäres Verzeichnis (PDFProcessor)  
**Ziel**: `sessions/Open Source in EU policy SFSCON/assets/open source in eu policy/`

**Assets (18 Dateien)**:
```
preview_001.jpg  (Seite 1, ~150 KB)
preview_002.jpg  (Seite 2, ~145 KB)
...
preview_018.jpg  (Seite 18, ~35 KB)
```

**Asset-Verzeichnis**:
```
asset_dir = "Open Source in EU policy SFSCON/assets/open source in eu policy"
```

### 5.3 ZIP-Archiv Erstellen (optional)

**Funktion**: `_create_session_archive(markdown_content, markdown_file_path, attachment_paths, asset_dir, session_data)`

**Archiv-Inhalt**:
```
Open_Source_in_EU_Policy_2024-10-26.zip
├── Open Source in EU Policy.md  (Markdown-Datei)
└── assets/
    ├── preview_001.jpg
    ├── preview_002.jpg
    ...
    └── preview_018.jpg
```

**Verarbeitung**:
1. ZIP-Archiv in Memory erstellen (`BytesIO`)
2. Markdown-Datei hinzufügen
3. Alle Assets hinzufügen (18 Bilder)
4. ZIP zu Base64 kodieren

**Output**:
```python
archive_data = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')
# Result: "UEsDBBQAAAAIAGaB... [~2.5 MB Base64]"

archive_filename = "Open_Source_in_EU_Policy_2024-10-26.zip"
```

---

## Phase 6: Cache Speichern

### 6.1 SessionProcessingResult Erstellen

```python
result = SessionProcessingResult(
    web_text=web_text,
    video_transcript=video_transcript_text,
    attachment_paths=attachment_paths,
    page_texts=page_texts,
    target_dir=str(target_dir),
    markdown_file=str(markdown_file),
    markdown_content=markdown_content,
    process_id=self.process_id,
    input_data=input_data,
    structured_data=structured_data
)
```

### 6.2 MongoDB Cache-Dokument

**Serialisierung**: `serialize_for_cache(result)`

**MongoDB-Dokument-Struktur**:
```json
{
  "_id": ObjectId("68fdea8fadaeafc0cd552dd3"),
  "cache_key": "f80ac1044a5cd4973cd241f851b18e8f101baac6cb25b87a10cd2d78f3b8c9ea",
  "created_at": ISODate("2025-10-26T09:31:59.716Z"),
  "last_accessed": ISODate("2025-10-26T09:31:59.716Z"),
  "status": "success",
  
  "data": {
    "result": {
      "web_text": "Open Source in EU policy - SFSCON...",
      "video_transcript": "And now we will have here Jordan...",
      "attachment_paths": [...],
      "page_texts": [...],
      "target_dir": "sessions\\Open Source in EU policy SFSCON\\en\\Seminar 1",
      "markdown_file": "sessions\\Open Source in EU policy SFSCON\\en\\Seminar 1\\Open Source in EU Policy.md",
      "markdown_content": "---\ntags: open-source,eu-policy...",
      "process_id": "0f99df6d-2fd9-4869-b613-1a6a6fc85640",
      "input_data": {
        "event": "Open Source in EU policy - SFSCON",
        "session": "Open Source in EU policy",
        "url": "https://www.sfscon.it/talks/open-source-in-eu-policy/",
        "filename": "open-source-in-eu-policy.md",
        "track": "Seminar 1",
        "day": "08/11/2024",
        "starttime": "10:30",
        "endtime": "10:50",
        "speakers": ["Jordan Maris"],
        "video_url": "https://player.vimeo.com/video/1029681888...",
        "video_transcript": null,
        "attachments_url": "https://www.sfscon.it/wp-content/uploads/...",
        "source_language": "en",
        "target_language": "en",
        "target": null,
        "template": "Session"
      },
      "structured_data": {
        "tags": "open-source,eu-policy,ai-act...",
        "title": "Open Source in EU Policy and the AI Act Exemption",
        "subtitle": "How the Open Source Community Influences...",
        "intro": "Explore how the Open Source community...",
        "speaker": "Jordan Maris",
        "date": "2024-11-08",
        "place": "Bolzano, Italy",
        "track": "Seminar 1",
        "topic": "intergovernmental cooperation",
        "relevance": "8",
        "summary": "This session focuses on...",
        "ecosocial": "The session highlights...",
        "attachment_links": "[Open Source in EU policy Presentation PDF](...)",
        "attachment_page_1_summary": "The first slide introduces...",
        ...
        "attachment_page_18_summary": "The final slide expresses thanks..."
      }
    },
    "processed_at": "2025-10-26T10:31:59.716389",
    "target": null,
    "event": "Open Source in EU policy - SFSCON",
    "session": "Open Source in EU policy",
    "track": "Seminar 1",
    "target_language": "en",
    "template": "Session",
    "topic": "intergovernmental cooperation",
    "relevance": "8"
  }
}
```

**Collection**: `session_cache`

**Indizes** (für schnelle Suche):
- `cache_key` (unique)
- `event`
- `session`
- `track`
- `processed_at`
- `target_language`

---

## Phase 7: Response Erstellen

### 7.1 SessionOutput Dataclass

```python
output_data = SessionOutput(
    web_text=web_text,
    video_transcript=video_transcript_text,
    attachments=attachment_paths,
    page_texts=page_texts,
    input_data=input_data,
    target_dir=str(target_dir),
    markdown_file=str(markdown_file),
    markdown_content=markdown_content,
    structured_data=structured_data,
    archive_data=archive_data,  # Base64 ZIP
    archive_filename=archive_filename,
    asset_dir=asset_dir
)
```

### 7.2 SessionData Container

```python
session_data = SessionData(
    input=input_data,   # SessionInput
    output=output_data  # SessionOutput
)
```

### 7.3 ProcessInfo (Performance & LLM-Tracking)

**BaseProcessor** aggregiert alle LLM-Requests:

```python
ProcessInfo(
    id="0f99df6d-2fd9-4869-b613-1a6a6fc85640",
    main_processor="session",
    started="2025-10-26T09:31:45.123Z",
    completed="2025-10-26T09:31:59.716Z",
    duration=14.593,  # Sekunden
    is_from_cache=False,
    cache_key="f80ac...",
    sub_processors=["VideoProcessor", "PDFProcessor", "ImageOCRProcessor", "TransformerProcessor"],
    llm_info={
        "total_calls": 22,  # 1 Video + 18 OCR + 3 Transformer
        "total_prompt_tokens": 45234,
        "total_completion_tokens": 12456,
        "total_tokens": 57690,
        "total_cost_usd": 0.2345,
        "by_model": {
            "whisper-1": {
                "calls": 1,
                "prompt_tokens": 0,
                "completion_tokens": 12351,
                "cost_usd": 0.0370
            },
            "gpt-4o": {
                "calls": 21,  # 18 OCR + 3 Transformer
                "prompt_tokens": 45234,
                "completion_tokens": 105,
                "cost_usd": 0.1975
            }
        }
    }
)
```

### 7.4 SessionResponse (Finale API-Response)

```python
response = SessionResponse(
    status=ProcessingStatus.SUCCESS,  # "success"
    request=RequestInfo(
        processor="session",
        timestamp="2025-10-26T09:31:45.123Z",
        parameters={
            "event": "Open Source in EU policy - SFSCON",
            "session": "Open Source in EU policy",
            "url": "https://www.sfscon.it/talks/open-source-in-eu-policy/",
            "track": "Seminar 1"
        }
    ),
    process=process_info,  # Siehe 7.3
    data=session_data,     # Siehe 7.2
    error=None
)
```

### 7.5 JSON Response (an Client)

**Serialisierung**: `response.to_dict()`

```json
{
  "status": "success",
  
  "request": {
    "processor": "session",
    "timestamp": "2025-10-26T09:31:45.123Z",
    "parameters": {
      "event": "Open Source in EU policy - SFSCON",
      "session": "Open Source in EU policy",
      "url": "https://www.sfscon.it/talks/open-source-in-eu-policy/",
      "track": "Seminar 1"
    }
  },
  
  "process": {
    "id": "0f99df6d-2fd9-4869-b613-1a6a6fc85640",
    "main_processor": "session",
    "started": "2025-10-26T09:31:45.123Z",
    "completed": "2025-10-26T09:31:59.716Z",
    "duration": 14.593,
    "is_from_cache": false,
    "cache_key": "f80ac1044a5cd4973cd241f851b18e8f101baac6cb25b87a10cd2d78f3b8c9ea",
    "sub_processors": ["VideoProcessor", "PDFProcessor", "ImageOCRProcessor", "TransformerProcessor"],
    "llm_info": {
      "total_calls": 22,
      "total_tokens": 57690,
      "total_cost_usd": 0.2345,
      "by_model": {
        "whisper-1": { "calls": 1, "tokens": 12351, "cost_usd": 0.0370 },
        "gpt-4o": { "calls": 21, "tokens": 45339, "cost_usd": 0.1975 }
      }
    }
  },
  
  "data": {
    "input": {
      "event": "Open Source in EU policy - SFSCON",
      "session": "Open Source in EU policy",
      "url": "https://www.sfscon.it/talks/open-source-in-eu-policy/",
      "filename": "open-source-in-eu-policy.md",
      "track": "Seminar 1",
      "day": "08/11/2024",
      "starttime": "10:30",
      "endtime": "10:50",
      "speakers": ["Jordan Maris"],
      "video_url": "https://player.vimeo.com/video/1029681888...",
      "video_transcript": null,
      "attachments_url": "https://www.sfscon.it/wp-content/uploads/...",
      "source_language": "en",
      "target_language": "en",
      "target": null,
      "template": "Session"
    },
    
    "output": {
      "web_text": "Open Source in EU policy - SFSCON...",
      "video_transcript": "And now we will have here Jordan...",
      "attachments": [
        "Open Source in EU policy SFSCON/assets/open source in eu policy/preview_001.jpg",
        ...
      ],
      "page_texts": [
        "Open Source in\nEU policy\nSFSCon...",
        ...
      ],
      "target_dir": "sessions\\Open Source in EU policy SFSCON\\en\\Seminar 1",
      "markdown_file": "sessions\\Open Source in EU policy SFSCON\\en\\Seminar 1\\Open Source in EU Policy.md",
      "markdown_content": "---\ntags: open-source,eu-policy...",
      "structured_data": {
        "tags": "open-source,eu-policy,ai-act...",
        "title": "Open Source in EU Policy and the AI Act Exemption",
        "subtitle": "How the Open Source Community Influences...",
        "intro": "Explore how the Open Source community...",
        "summary": "This session focuses on...",
        "ecosocial": "The session highlights...",
        ...
      },
      "archive_data": "UEsDBBQAAAAIAGaB...",  // Base64 ZIP
      "archive_filename": "Open_Source_in_EU_Policy_2024-10-26.zip",
      "asset_dir": "Open Source in EU policy SFSCON/assets/open source in eu policy"
    }
  },
  
  "error": null
}
```

---

## Zusammenfassung: Datenfluss-Übersicht

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. API REQUEST                                                   │
│ POST /api/session/process                                        │
│ {event, session, url, filename, track, video_url, ...}          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 2. SESSIONINPUT DATACLASS                                        │
│ Validierung, Typisierung                                         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 3. CACHE-KEY GENERIERUNG                                         │
│ SHA256(event+session+url+track+lang+template+...)               │
│ → f80ac1044a5cd4973cd241f851b18e8f101baac6cb25b87a10cd2d78f3b8c9ea│
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. DATEN SAMMELN                                                 │
│                                                                   │
│ ┌────────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│ │ Web Scraping   │  │ Video Processing │  │ PDF Processing   │ │
│ │ BeautifulSoup  │  │ Whisper API      │  │ ImageOCR (GPT)   │ │
│ │ → web_text     │  │ → video_transcript│  │ → page_texts     │ │
│ │ (6KB)          │  │ (8KB)            │  │ → attachment_    │ │
│ └────────────────┘  └──────────────────┘  │   paths (18x)    │ │
│                                            └──────────────────┘ │
│ LLM-Tracking: Whisper-1 (1x), GPT-4o (18x OCR)                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 5. TEMPLATE PROCESSING                                           │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Session_en.md Template laden                                 │ │
│ │ - Strukturierte Variablen extrahieren ({{var|description}}) │ │
│ │ - Einfache Variablen extrahieren ({{var}})                  │ │
│ │ - Systemprompt extrahieren (--- systemprompt)               │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ LLM-Anfrage (GPT-4o): Template Transform                    │ │
│ │ Input: web_text + video_transcript + page_texts + context   │ │
│ │ Output: JSON mit allen strukturierten Feldern               │ │
│ │ {tags, title, subtitle, summary, ecosocial, ...}            │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │ Template-Variablen ersetzen                                  │ │
│ │ {{tags|...}} → "open-source,eu-policy,ai-act,..."          │ │
│ │ {{title|...}} → "Open Source in EU Policy and..."          │ │
│ │ {videoplayer} → <iframe src="..."></iframe>                 │ │
│ │ {slides} → Markdown-Tabelle mit Bildern + Zusammenfassungen │ │
│ └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│ LLM-Tracking: GPT-4o (3x Transform)                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. DATEIEN SPEICHERN                                             │
│                                                                   │
│ Markdown: sessions/.../Open Source in EU Policy.md              │
│ Assets:   sessions/.../assets/preview_001-018.jpg (18 Dateien)  │
│ ZIP:      Base64-kodiertes Archiv (Markdown + Assets)           │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 7. MONGODB CACHE                                                 │
│                                                                   │
│ Collection: session_cache                                        │
│ {                                                                │
│   cache_key: "f80ac...",                                         │
│   data: {                                                        │
│     result: {web_text, video_transcript, markdown_content, ...},│
│     structured_data: {tags, title, summary, ...}                │
│   },                                                             │
│   processed_at: "2025-10-26T10:31:59.716Z"                       │
│ }                                                                │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 8. SESSION RESPONSE                                              │
│                                                                   │
│ SessionResponse {                                                │
│   status: "success",                                             │
│   request: {processor, timestamp, parameters},                   │
│   process: {                                                     │
│     id, duration: 14.6s,                                         │
│     llm_info: {                                                  │
│       total_calls: 22,                                           │
│       total_tokens: 57690,                                       │
│       total_cost_usd: 0.23,                                      │
│       by_model: {whisper-1, gpt-4o}                              │
│     }                                                             │
│   },                                                             │
│   data: {                                                        │
│     input: SessionInput,                                         │
│     output: SessionOutput {                                      │
│       markdown_content,                                          │
│       structured_data,                                           │
│       archive_data (Base64)                                      │
│     }                                                             │
│   }                                                              │
│ }                                                                │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. JSON RESPONSE → CLIENT                                        │
│ HTTP 200 OK                                                      │
│ Content-Type: application/json                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## LLM-Nutzung: Detaillierte Aufschlüsselung

### Gesamt-Übersicht

| Prozessor | Modell | Calls | Purpose | Tokens | Cost (USD) |
|-----------|--------|-------|---------|--------|------------|
| VideoProcessor | whisper-1 | 1 | transcription | 12.351 | $0.037 |
| ImageOCRProcessor | gpt-4o | 18 | image_ocr | ~900 each | $0.162 |
| TransformerProcessor | gpt-4o | 3 | template_transform | ~14.000 | $0.036 |
| **Total** | - | **22** | - | **57.690** | **$0.235** |

### Detaillierte Aufschlüsselung

**1. Video-Transkription** (1 Call):
- Model: whisper-1
- Input: 20 Minuten Video
- Output: 8.234 Zeichen Text
- Tokens: ~12.351 (geschätzt basierend auf Textlänge)
- Duration: ~15 Sekunden
- Cost: ~$0.037

**2. PDF-Seiten OCR** (18 Calls):
- Model: gpt-4o (Vision)
- Input pro Call: 1 PDF-Seite als JPEG
- Output pro Call: ~50-150 Zeichen Text
- Tokens pro Call: ~800-1.000 (Bild + Text)
- Duration pro Call: ~2-3 Sekunden
- Total Cost: ~$0.162

**3. Template-Transformation** (3 Calls):
- Model: gpt-4o
- Call 1: Hauptfeld-Extraktion (summary, ecosocial, etc.)
  - Input: web_text + video_transcript + context
  - Tokens: ~12.000
- Call 2: Slide-Zusammenfassungen (attachment_page_X_summary)
  - Input: 18x page_texts
  - Tokens: ~1.500
- Call 3: Metadaten-Extraktion (tags, title, etc.)
  - Input: Gesamtkontext
  - Tokens: ~500
- Total Cost: ~$0.036

---

## Fazit

Dieser komplette Datenfluss zeigt:

1. **Eingabe**: Strukturierte API-Parameter werden validiert und typisiert
2. **Datensammlung**: Parallele Verarbeitung von Web, Video und PDF
3. **Template-Verarbeitung**: LLM extrahiert strukturierte Informationen
4. **Generierung**: Template wird mit LLM-Daten gefüllt
5. **Speicherung**: Markdown, Assets und Cache werden persistiert
6. **Response**: Vollständige Transparenz über Verarbeitung, LLM-Nutzung und Kosten

**Wichtige Features**:
- ✅ Vollständige Rückverfolgbarkeit (ProcessInfo, LLM-Tracking)
- ✅ Transparente Kostenberechnung (LLMInfo mit per-model Breakdown)
- ✅ Wiederverwendbarkeit (MongoDB Cache mit cache_key)
- ✅ Flexibilität (Video-Transkript kann vorverarbeitet übergeben werden)
- ✅ Strukturierte Daten (YAML Frontmatter + JSON structured_data)
- ✅ Archivierung (ZIP mit Markdown + Assets)

