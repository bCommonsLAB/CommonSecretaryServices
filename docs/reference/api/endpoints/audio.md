# Audio API Endpoints

Endpoints for audio file processing with transcription and optional translation.

## POST /api/audio/process

Process an audio file with transcription and optional template-based transformation.

### Request

**Content-Type**: `multipart/form-data`

**Parameters**:

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `file` | File | Yes | - | Audio file (MP3, WAV, M4A, FLAC, OGG, etc.) |
| `source_language` | String | No | `de` | Source language (ISO 639-1 code, e.g., "en", "de") |
| `target_language` | String | No | `de` | Target language for translation (ISO 639-1 code) |
| `template` | String | No | `""` | Optional template name for text transformation |
| `useCache` | Boolean | No | `true` | Whether to use cache |
| `callback_url` | String | No | - | If set, processing is **asynchronous** and results are delivered via webhook (HTTP 202 response) |
| `callback_token` | String | No | - | Optional token sent as `Authorization: Bearer ...` and `X-Callback-Token` to the webhook |
| `jobId` | String | No | - | Optional external job id (client-generated). Returned in the 202 ACK `job.id` |

### Supported Formats

- FLAC, M4A, MP3, MP4, MPEG, MPGA, OGA, OGG, WAV, WEBM

### Request Example

```bash
curl -X POST "http://localhost:5001/api/audio/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@audio.mp3" \
  -F "source_language=en" \
  -F "target_language=de" \
  -F "template=MeetingMinutes" \
  -F "useCache=true"
```

### Request Example (Async via Webhook)

If you provide a `callback_url`, the endpoint returns immediately with `202 Accepted`
and the worker sends the result to the webhook URL.

```bash
curl -X POST "http://localhost:5001/api/audio/process" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@audio.mp3" \
  -F "source_language=en" \
  -F "target_language=de" \
  -F "template=MeetingMinutes" \
  -F "useCache=true" \
  -F "callback_url=https://your-client.example.com/webhook/audio" \
  -F "callback_token=YOUR_WEBHOOK_TOKEN" \
  -F "jobId=client-job-123"
```

### Response (Success)

**Status Code**: `200 OK`

```json
{
  "status": "success",
  "request": {
    "id": "process-id-123",
    "timestamp": "2024-01-01T00:00:00Z"
  },
  "process": {
    "duration_ms": 5000,
    "llm_info": {
      "total_tokens": 1500,
      "total_cost": 0.015,
      "requests": [
        {
          "model": "whisper-1",
          "purpose": "transcription",
          "tokens": 1500,
          "duration_ms": 4500
        }
      ]
    }
  },
  "data": {
    "transcription": {
      "text": "Transcribed (and translated or transformed) text...",
      "source_language": "de",
      "detected_language": "de",
      "segments": [ "…same entries as data.segments…" ]
    },
    "segments": [
      {
        "segment_id": 0,
        "start": 0.0,
        "end": 7.0,
        "text": "Guten Tag. Heute sprechen wir über den Sozialstaat.",
        "speaker": null,
        "title": null,
        "avg_logprob": -0.29,
        "compression_ratio": 1.14,
        "no_speech_prob": 0.0026,
        "confidence": 0.75,
        "quality_source": "whisper"
      }
    ],
    "language": "de",
    "metadata": { "duration": 120.5, "format": "mp3", "channels": 2, "process_dir": "/path/to/process/dir" },
    "process_id": "process-id-123",
    "status": "success"
  }
}
```

#### Verlässlichkeit je Abschnitt (`data.segments[]`, `data.language`)

Ein Transkript ist nur etwas wert, wenn der Client sehen kann, wo das Modell
geraten hat. Deshalb liegen die Segmente des Modells flach in `data.segments[]`
(Zeitmarken `start`/`end` in Sekunden, bezogen auf die ganze Datei, auch bei
Stückelung langer Aufnahmen) und tragen je Abschnitt die Rohwerte des
Whisper-Decoders:

| Feld | Bedeutung | Erfahrungswert für „verdächtig" |
|---|---|---|
| `avg_logprob` | mittlere Log-Wahrscheinlichkeit der Tokens; je näher an 0, desto sicherer | unter −1.0 |
| `compression_ratio` | gzip-Verhältnis des Texts; hoch = Wiederholungen (Schleife) | über 2.4 |
| `no_speech_prob` | Wahrscheinlichkeit, dass gar nicht gesprochen wurde; hoch zusammen mit schlechtem `avg_logprob` = erfundener Text bei Stille | über 0.6 |
| `confidence` | `exp(avg_logprob)`, auf 0–1 begrenzt; `null` ohne `avg_logprob` | – |
| `quality_source` | woher die Werte stammen: `whisper`, `logprobs` oder `none` | – |

`null` heißt „nicht geliefert" — nie 0.0 als stiller Ersatz. Der Dienst wendet
keine Schwellen an; das macht der Client aus den Rohwerten. Was ankommt, hängt
vom Modell im Use-Case `transcription` ab (Probe 09.10.2026):

| Modell | `quality_source` | Segmente | Werte |
|---|---|---|---|
| `whisper-1` | `whisper` | die Abschnitte des Modells (`verbose_json`) | alle drei; Whisper berechnet sie je 30-s-Decoder-Fenster, Segmente innerhalb eines Fensters teilen sich die Werte |
| `gpt-transcribe`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` | `logprobs` | ein Segment je Anfrage (je Stück bei langen Dateien) | `avg_logprob` als Mittel der Token-Logprobs (`include=["logprobs"]`), `compression_ratio` aus dem Text berechnet, `no_speech_prob` `null` |
| `gpt-4o-transcribe-diarize` | `none` | ein Segment je Anfrage | keine — das Modell weist `include=["logprobs"]` ab |

`data.language` ist die vom Modell selbst erkannte Sprache (ISO 639-1) für die
Sprachdrift-Prüfung im Client — `null`, wenn das Modell keine gemeldet hat
(`gpt-4o-transcribe`, `gpt-4o-mini-transcribe`, Sprecher-Modell). Sie ist nicht
dasselbe wie `transcription.source_language`, das die Arbeitssprache (Vorgabe des
Aufrufers oder bei `auto` die erkannte) nennt. Bei Stückelung gewinnt die am
häufigsten gemeldete Sprache. Die Segmenttexte bleiben die des Modells, auch wenn
`transcription.text` übersetzt oder per Template umgeformt wurde.

### Response (Accepted, Async)

**Status Code**: `202 Accepted`

```json
{
  "status": "accepted",
  "worker": "secretary",
  "process": {
    "id": "process-id-123",
    "main_processor": "audio",
    "started": "2026-01-01T00:00:00Z",
    "is_from_cache": false
  },
  "job": { "id": "client-job-123" },
  "webhook": { "delivered_to": "https://your-client.example.com/webhook/audio" },
  "error": null
}
```

### Webhook Payload (Async Completion)

The webhook receives one final message when finished.
**Webhook schema is standardized** and uses `phase` = `progress` | `completed` | `error`.

```json
{
  "phase": "completed",
  "message": "Audio-Verarbeitung abgeschlossen",
  "data": {
    "transcription": { "text": "..." },
    "output_text": "..."
  }
}
```

`transcription.text` bleibt. Liegt am Job ein `data`-Block (`structured_data`), kommen
`output_text` und — nur wenn der Processor sie gesetzt hat — `segments`, `language`,
`speakers`, `dropped_context`, `detected_language`, `duration`, `llm_model`,
`chunk_count` und `from_cache` flach dazu. `segments` haben dieselbe Form wie in der
Sync-Antwort: `start`, `end`, `text`, `speaker` (nur Sprecher-Weg) und die
Verlässlichkeitswerte `avg_logprob`, `compression_ratio`, `no_speech_prob`,
`confidence`, `quality_source` (siehe oben) — unverändert durchgereicht, auch die
`null`-Werte. `language` ist die vom Modell erkannte Sprache oder `null`.

```json
{
  "phase": "completed",
  "message": "Audio-Verarbeitung abgeschlossen",
  "job": { "id": "client-job-123" },
  "data": {
    "transcription": { "text": "..." },
    "output_text": "...",
    "language": "de",
    "segments": [
      { "segment_id": 0, "start": 0.0, "end": 7.0, "text": "…", "speaker": null, "title": null,
        "avg_logprob": -0.29, "compression_ratio": 1.14, "no_speech_prob": 0.0026,
        "confidence": 0.75, "quality_source": "whisper" }
    ]
  }
}
```

Fehlt `structured_data` oder `data` darin, bleibt der Payload bei
`transcription.text`. Es werden keine leeren `speakers`- oder `segments`-Listen
ergänzt. Am Job steht dann der Log-Eintrag
`Webhook ohne Sprecherdaten: structured_data fehlt`.

Beim Sprecher-Weg (`mode=diarized`) schickt der Worker zusätzlich nach jedem
fertigen Stück ein `phase=progress`. `message` nennt Index, Dauer und Sprecherzahl,
zum Beispiel `Stück 2/3 transkribiert (1200 s, 4 Sprecher)`.

Solange ein Stück beim Anbieter liegt, kommt alle **120 s** ein Lebenszeichen
(Heartbeat), ebenfalls als `phase=progress`. `data.progress` bleibt dabei auf dem
zuletzt gemeldeten Wert; die Meldung nennt die verstrichene Zeit in ganzen Minuten:

```json
{
  "phase": "progress",
  "message": "Stück 1/2 läuft seit 4 min",
  "job": { "id": "client-job-123" },
  "data": { "progress": 20 }
}
```

Hintergrund: Ein 20-Minuten-Stück darf beim Anbieter bis 900 s dauern
(`CHUNK_TIMEOUT_SECONDS`). Der Client-Watchdog in KnowledgeScout setzt einen Job
nach 600 s ohne Callback auf `failed`. Der Heartbeat (`CHUNK_HEARTBEAT_SECONDS`)
hält den Job in dieser Lücke am Leben. Im Sync-Weg ohne `callback_url` gibt es
keinen Heartbeat.

### Webhook Payload (Progress)

```json
{
  "phase": "progress",
  "message": "Job initialisiert",
  "job": { "id": "client-job-123" },
  "data": { "progress": 5 }
}
```

On failure:

```json
{
  "phase": "error",
  "message": "Audio-Verarbeitung fehlgeschlagen",
  "job": { "id": "client-job-123" },
  "error": {
    "code": "SomeError",
    "message": "Details...",
    "details": { "traceback": "..." }
  },
  "data": null
}
```

### Job Status / Full Results

For async jobs you can query the job status and full stored results via:

- `GET /api/jobs/<job_id>`

### Response (Error)

**Status Code**: `400 Bad Request`

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_FORMAT",
    "message": "The format 'xyz' is not supported. Supported formats: flac, m4a, mp3...",
    "details": {
      "error_type": "INVALID_FORMAT",
      "supported_formats": ["flac", "m4a", "mp3", ...]
    }
  }
}
```

### Processing Flow

1. Audio file is uploaded and validated
2. File is segmented into manageable chunks (if large)
3. Each segment is transcribed using OpenAI Whisper API
4. Optional: Text is transformed using template (via TransformerProcessor)
5. Optional: Text is translated to target language
6. Results are aggregated and returned

### LLM Tracking

The response includes detailed LLM usage information:
- Total tokens used
- Total cost
- Individual requests with model, purpose, tokens, duration

### Caching

Results are cached based on:
- File hash
- Source language
- Target language
- Template name

Use `useCache=false` to bypass cache and force reprocessing.


---

## POST /api/audio/process-diarized

Datei-Transkription **mit Sprecher-Erkennung**. Eigener Endpunkt statt Schalter an
`/audio/process`, weil es ein anderer Vertrag ist:

| | `/audio/process` | `/audio/process-diarized` |
|---|---|---|
| Antwortformat beim Anbieter | `verbose_json` / `json` | `diarized_json` |
| Antwortform | ein Volltext | `segments` mit `speaker`, `start`, `end`, `text` |
| `prompt`, `keywords` | ja | **nein** — werden als `dropped_context` gemeldet |
| Übersetzung, `template` | ja | nein |
| Stücke | `segment_duration` (300 s), hart nach Zeit | bis 20 Minuten, **an Sprechpausen** geschnitten |
| Modell | Use-Case `transcription` | Use-Case `diarized_transcription` (Seed: `gpt-4o-transcribe-diarize`) |

**Grenzen laut Anbieter (OpenAI, Stand 06.10.2026):** 25 MB und 1500 s je Anfrage. Der
Dienst schneidet Stücke bis 20 Minuten an Sprechpausen (Suchfenster 3 Minuten vor der
Marke; ohne Pause harter Schnitt) und lehnt ein Stück ab, das die Grenzen überschreitet
(`CHUNK_TOO_LARGE`, `CHUNK_TOO_LONG`), statt still zu kürzen.

**Sprecher-Labels gelten nur innerhalb einer Anfrage.** „A" in Stück 1 ist nicht
zwingend „A" in Stück 2. Deshalb heißen die Labels bei mehreren Stücken
`Stück 1 Sprecher A`, `Stück 2 Sprecher A` … (bei einem Stück `Sprecher A`). Die
Zuordnung über Stückgrenzen übernimmt der Korrektur-Schritt mit dem Menschen
(`POST /api/transcript/korrekturvorschlag`). Keine Stimmproben.

### Request

**Content-Type**: `multipart/form-data`

| Parameter | Typ | Pflicht | Default | Beschreibung |
|-----------|-----|---------|---------|--------------|
| `file` | File | ja | – | Audio-Datei (flac, m4a, mp3, mp4, mpeg, mpga, oga, ogg, opus, wav, webm) |
| `source_language` | String | nein | `auto` | Sprache der Aufnahme (ISO 639-1) oder `auto` |
| `languages` | String | nein | – | Mögliche Sprachen (kommagetrennt oder JSON-Liste); das Sprecher-Modell nimmt nur eine → `dropped_context` |
| `prompt` | String | nein | – | Wird **nicht** angenommen; erscheint mit Begründung in `dropped_context` |
| `keywords` | String | nein | – | Wird **nicht** angenommen; erscheint mit Begründung in `dropped_context` |
| `useCache` | Boolean | nein | `true` | Cache verwenden. Der Schlüssel kennt den Modus — kein Treffer aus `/audio/process` |
| `callback_url`, `callback_token`, `jobId` | String | nein | – | Wie bei `/audio/process`: mit `callback_url` asynchron (202, Job `audio` mit `mode=diarized`) |

```bash
curl -X POST "$SECRETARY_SERVICE_URL/api/audio/process-diarized" \
  -H "X-Secretary-Api-Key: $SECRETARY_SERVICE_API_KEY" \
  -F "file=@diskussion.mp3" \
  -F "source_language=de"
```

### Response (Success)

```json
{
  "status": "success",
  "request": { "processor": "audio", "timestamp": "…", "parameters": { "mode": "diarized", "…": "…" } },
  "process": { "id": "…", "llm_info": { "requests": [ { "model": "gpt-4o-transcribe-diarize", "purpose": "diarized_transcription" } ] } },
  "data": {
    "output_text": "**Stück 1 Sprecher A:** Guten Morgen …\n\n**Stück 1 Sprecher B:** Danke für die Einladung …",
    "original_text": "…identisch mit output_text…",
    "speakers": ["Stück 1 Sprecher A", "Stück 1 Sprecher B", "Stück 2 Sprecher A"],
    "segments": [
      { "segment_id": 0, "speaker": "Stück 1 Sprecher A", "start": 0.0, "end": 3.2, "text": "Guten Morgen …",
        "title": null, "avg_logprob": null, "compression_ratio": null, "no_speech_prob": null,
        "confidence": null, "quality_source": "none" },
      { "segment_id": 1, "speaker": "Stück 1 Sprecher B", "start": 3.4, "end": 7.9, "text": "Danke für die Einladung …",
        "title": null, "avg_logprob": null, "compression_ratio": null, "no_speech_prob": null,
        "confidence": null, "quality_source": "none" }
    ],
    "language": "de",
    "detected_language": "de",
    "duration": 2880.5,
    "llm_model": "gpt-4o-transcribe-diarize",
    "chunk_count": 3,
    "dropped_context": ["prompt: 'gpt-4o-transcribe-diarize' erkennt Sprecher und nimmt dafuer keinen Freitext-Kontext"],
    "transcription": { "text": "…wie output_text…", "source_language": "de", "segments": [ "…mit segment_id, speaker…" ] },
    "from_cache": false
  }
}
```

`output_text` ist Markdown: ein Absatz je Sprecherwechsel, aufeinanderfolgende Segmente
desselben Sprechers zusammengefasst, Zeitmarken nur in `segments`. Der Webhook
(`phase=completed`) trägt denselben Text unter `data.transcription.text` und
`data.output_text`. Dazu flach, wenn der Lauf sie geliefert hat: `data.speakers`,
`data.segments`, `data.language` und `data.dropped_context` (dieselben Felder wie in
der Sync-Antwort, nicht nur unter `transcription`).

**Keine Verlässlichkeitswerte im Sprecher-Weg.** `gpt-4o-transcribe-diarize` weist
`include=["logprobs"]` ab (Probe 09.10.2026: „Logprobs are not supported for
diarization models", auch mit `response_format=json`). Die Segmente tragen deshalb
`quality_source: "none"` und `null` in `avg_logprob`, `compression_ratio`,
`no_speech_prob`, `confidence`; im Dienst-Log steht je Lauf
`Sprecher-Transkription ohne Verlässlichkeitswerte`. Schleifen, Sprachdrift und
kaputte Labels prüft der Client hier am Text — `data.language` hilft dabei, wenn das
Modell eine Sprache gemeldet hat.

### Fehler

| HTTP | `error.code` | Ursache |
|------|--------------|---------|
| 400 | `INVALID_FORMAT`, `MISSING_FILE`, `PARSE_ERROR` | Eingabe |
| 400 | `CHUNK_TOO_LARGE`, `CHUNK_TOO_LONG`, `CHUNK_TIMEOUT`, `EMPTY_TRANSCRIPTION`, `TRANSCRIPTION_ERROR` | Anbieter-Grenze oder -Fehler; kein Fehlertext als Ergebnis |
| 503 | `NO_MODEL_CONFIGURED` | In der Maske ist `diarized_transcription` kein Modell zugeordnet |
| 503 | `PROVIDER_UNSUPPORTED` | Zugeordneter Provider kann keine Sprecher-Erkennung (nur `openai`) |
