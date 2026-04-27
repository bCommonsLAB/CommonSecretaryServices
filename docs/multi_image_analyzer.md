# Multi-Image Analyzer – Designentscheidungen und Migration

Status: Implementiert (siehe Code-Stellen unten). Diese Doku beschreibt die
Erweiterung des `/api/image-analyzer/process`-Endpoints auf **mehrere Bilder
in einem einzigen LLM-Call** (Variante 1) und die parallele Umstellung auf
**In-Memory-Verarbeitung** (kein Temp-File-IO im eigenen Code).

## Ziel

Vorher:

- Genau **ein** Bild pro Request (`file: FileStorage`, required).
- Bild wurde in `src/api/routes/temp_<uuid>.jpeg` auf Disk geschrieben.
- Hash und alle weiteren Schritte arbeiteten mit dem Disk-Pfad.

Nachher:

- **Ein bis N Bilder** pro Request (`files`, `action='append'`).
- `file` (single) bleibt optional erhalten – Backward-Compat.
- Bilder werden **nicht mehr** vom eigenen Code auf Disk geschrieben –
  `uploaded_file.stream.read()` liefert direkt bytes.
- Pro Request **ein** LLM-Vision-Call mit allen Bildern als
  `image_url`-Parts (multipart/multimodal).
- Cache-Key enthält die Liste der Bild-Hashes **reihenfolgeerhaltend**.

## Designentscheidungen

| Frage | Entscheidung | Begründung |
|-------|--------------|------------|
| Multi-Image-Strategie | Variante 1: alle Bilder in einem LLM-Call | Querverweise zwischen Seiten möglich (Tabelle auf Seite 1, Maße auf Seite 2). |
| Multi-File-API-Design | Option B: `action='append'` auf `files` | Backwards-compat zu `file`, beliebig viele Bilder, sauber dokumentiert. |
| Storage | In-Memory (`stream.read()`) | Kein Disk-IO im eigenen Code. Werkzeug-Spooling bleibt unverändert. |
| Cache-Key | `file_hashes` als Liste, Reihenfolge erhalten | Andere Reihenfolge → anderer Cache-Eintrag, weil Reihenfolge dem LLM Kontext gibt. |
| Bild-Limit | 10 pro Request | Pragmatischer Default, leicht änderbar. |
| `max_tokens` | bleibt 4000 | Erstmal nicht parametrisiert. Bei Bedarf nachziehen. |
| Provider-Protocol | `image_data: Union[bytes, List[bytes]]` | Single-Bild = 1-Liste; konsistente Abstraktion. |
| URL-Endpoint | Wird mit umgestellt | Sonst bricht der Aufrufer durch die neue Processor-Signatur. |

## Was sich änderte (Code-Stellen)

### 1. `src/core/llm/protocols.py`

`vision()`-Signatur: `image_data: bytes` → `image_data: Union[bytes, List[bytes]]`.

### 2. `src/core/llm/providers/openrouter_provider.py`

- `vision()`: Eingabe wird intern zur Liste normalisiert.
- `messages[].content` enthält nun N `image_url`-Einträge.
- Logging erweitert um `image_count` und `total_image_bytes`.

### 3. Andere Provider (`openai`, `mistral`, `voyageai`, `ollama`)

- Nur Signatur an Protocol angeglichen (Union-Typ).
- Multi-Image-Support **nicht** implementiert; bei Liste mit `len > 1` wird
  ein `ProcessingError` geworfen. Damit bleiben sie type-konform, ohne
  ungetesteten Multi-Image-Code zu enthalten.

### 4. `src/processors/image_analyzer_processor.py`

- `analyze_by_template()` neue Signatur:
  - `image_data_list: List[bytes]` (Pflicht)
  - `file_hashes: Optional[List[str]]` (Logging + Cache-Key)
  - `file_names: Optional[List[str]]` (nur Logging)
  - `image_urls: Optional[List[str]]` (nur Logging, ersetzt `is_url`)
- `_validate_image_bytes(image_bytes: bytes)` ersetzt `_validate_image(file_path)`.
- `_resize_image_bytes(image_bytes: bytes) -> bytes` ersetzt
  `_convert_image_to_bytes(image_path)`.
- `_download_image()` und das `working_dir`-Setup entfallen.
- `_build_cache_key()` erwartet `file_hashes` (Liste statt Einzelwert).

### 5. `src/api/routes/image_analyzer_routes.py`

- `upload_parser`: `file` jetzt `required=False`, neuer Parameter `files`
  mit `action='append'`. Validierung: mindestens **ein**, maximal **10** Bilder.
- `post()`: liest alle `FileStorage`-Streams direkt zu `bytes`, berechnet
  Hashes in-memory, ruft Processor mit Listen auf.
- `try/finally`-Cleanup für Temp-Files entfällt komplett.
- `/process-url`: liest die URL via `requests.get(url).content` direkt zu
  bytes – keine lokale Datei mehr.

## Cache-Migration / Risiken

- Da `file_hash` zu `file_hashes` wird und der Provider/Modell-Name bereits
  im Key ist (siehe vorhergehende Erweiterung), sind **alle bisherigen
  Single-Image-Cache-Einträge unauffindbar** geworden. Nicht physisch
  gelöscht, aber faktisch invalidiert.
- Bei Frontend-Aufrufen mit mehreren Bildern muss jede Datei mit dem
  gleichen Form-Key `files` gesendet werden (z. B. `FormData.append('files', blob1)`,
  `FormData.append('files', blob2)`).
- Im Swagger UI ist Multi-Upload eingeschränkt: das UI zeigt nur einen
  File-Picker. Tests mit mehreren Bildern am besten via curl/Postman:

  ```bash
  curl -X POST http://localhost:5001/api/image-analyzer/process \
    -F "files=@page_009.jpeg" \
    -F "files=@page_010.jpeg" \
    -F "template_content=---..."
  ```

## RAM-Hinweis

Bei 10 Bildern × ~5 MB Original = ~50 MB RAM, plus Resize (typ. 200-500 KB
pro Bild nach `max_image_size=2048`) plus base64 (~4/3 Faktor). Realistisch
kommen wir bei voller Auslastung auf <20 MB pro Request. Sollte unkritisch
sein.
