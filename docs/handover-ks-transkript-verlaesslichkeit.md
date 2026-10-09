# Hand-off an KnowledgeScout: Verlässlichkeit je Abschnitt im Audio-Ergebnis

Stand 09.10.2026. Secretary-Branch `claude/transkript-verlaesslichkeit-6e7aa8`
(Commit `0e4951b`, von `main`). Vorgänger: `handover-transkript-verlaesslichkeit.md`
(Auftrag und Befund) und `handover-webhook-speakers-segments.md` (Webhook mit
`speakers`/`segments`, 07.10.). Dieses Dokument richtet sich an die KS-Session: was
der Secretary jetzt anders liefert, was KS daraus bauen soll, und wie man es prüft.

## Worum es geht

Ein Transkript ist nur etwas wert, wenn der Mensch sehen kann, wie wahrscheinlich es
ein Abbild der Wirklichkeit ist. Bisher kam beim Client Text an, ohne Hinweis, wo das
Modell geraten hat. Prüffall 09.10. (Diskussion, 46 Min., Deutsch/Italienisch):
derselbe Satz rund 20-mal hintereinander, Wortmeldungen ins Englische übersetzt und
dabei erfunden, Zahlen verdreht. Nichts davon war am Ergebnis zu erkennen.

Der Secretary reicht jetzt die Rohwerte des Modells je Abschnitt durch. Er wendet
**keine Schwellen** an, färbt nichts ein, schlägt keine Korrektur vor. Das ist der
nächste Schritt in KnowledgeScout.

## Was im Secretary anders ist

### 1. `data.segments[]` sind jetzt die Abschnitte des Modells

Vorher: ein einziges Segment über den ganzen Text (`start: 0`, `end: Antwortzeit`),
Werte weggeworfen. Jetzt: je Abschnitt des Modells ein Segment, Zeitmarken in
Sekunden **bezogen auf die ganze Datei** (bei langen Dateien schneidet der Secretary
in Stücke von 300 s und verschiebt die Zeitmarken um den Stück-Offset).

Jedes Segment hat dieselbe Form, im normalen Weg wie im Sprecher-Weg:

```json
{
  "segment_id": 12,
  "start": 1843.2,
  "end": 1849.0,
  "text": "… welfare state welfare state welfare state …",
  "speaker": null,
  "title": null,
  "avg_logprob": -1.62,
  "compression_ratio": 2.71,
  "no_speech_prob": 0.65,
  "confidence": 0.198,
  "quality_source": "whisper"
}
```

| Feld | Bedeutung | Erfahrungswert „verdächtig" (Whisper-Voreinstellung) |
|---|---|---|
| `avg_logprob` | mittlere Log-Wahrscheinlichkeit der Tokens; je näher an 0, desto sicherer | unter −1.0 |
| `compression_ratio` | gzip-Verhältnis des Texts; hoch = Wiederholungen, also Schleife | über 2.4 |
| `no_speech_prob` | Wahrscheinlichkeit, dass gar nicht gesprochen wurde; hoch **zusammen mit** schlechtem `avg_logprob` = erfundener Text bei Stille | über 0.6 |
| `confidence` | `exp(avg_logprob)`, auf 0–1 begrenzt. Bequemer Ersatz für `avg_logprob`, nichts Eigenes | – |
| `quality_source` | woher die Zahlen stammen: `"whisper"`, `"logprobs"`, `"none"` | – |
| `speaker` | nur im Sprecher-Weg gefüllt („Stück 1 Sprecher A"), sonst `null` | – |
| `title` | Kapiteltitel am ersten Segment eines Kapitels, sonst `null` | – |

**`null` heißt „nicht geliefert".** Nie 0.0 als stiller Ersatz. KS darf `null` nicht
als „sicher" oder „unsicher" lesen, sondern nur als „keine Aussage" — und
`quality_source` sagt, warum.

### 2. `quality_source` hängt am Modell im Use-Case `transcription`

Was ankommt, entscheidet die Zuordnung in der LLM-Maske des Secretary
(`/llm-config`, Use-Case „Transcription (Audio/Video)"). Stand 09.10. in der
Dev-Datenbank: **`openai/gpt-transcribe`**.

| Modell | `quality_source` | Segmente | Werte |
|---|---|---|---|
| `whisper-1` | `whisper` | die Abschnitte des Modells, typisch 5–15 s | alle drei. Whisper berechnet sie je 30-s-Decoder-Fenster; Segmente **innerhalb eines Fensters teilen sich dieselben Zahlen**. Bei 46 Minuten sind das rund 90 unabhängige Messpunkte |
| `gpt-transcribe`, `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` | `logprobs` | **ein Segment je Stück** (300 s), weil diese Modelle keine Abschnitte liefern | `avg_logprob` = Mittel der Token-Logprobs des ganzen Stücks; `compression_ratio` vom Secretary aus dem Stücktext berechnet; `no_speech_prob` `null` |
| `gpt-4o-transcribe-diarize` (Sprecher-Weg `process-diarized`) | `none` | je Sprecherwechsel, wie bisher | keine. Das Modell weist `include=["logprobs"]` ab (Probe 09.10.: „Logprobs are not supported for diarization models") |

Konsequenz für KS: Mit `gpt-transcribe` zeigt sich eine Schleife nur, wenn sie das
ganze 5-Minuten-Stück prägt. Für Werte je Abschnitt muss `whisper-1` zugeordnet
sein. Für den Sprecher-Weg gibt es **keine** Werte; dort bleibt nur die Textprüfung.

### 3. `data.language`: die vom Modell erkannte Sprache

Neu, flach im `data`-Block, ISO 639-1 (`"de"`, `"it"`, `"en"`) oder `null`, wenn
das Modell keine Sprache gemeldet hat. Gemeldet wird sie von `whisper-1` und
`gpt-transcribe`; `gpt-4o-transcribe`, `gpt-4o-mini-transcribe` und das
Sprecher-Modell melden keine. Bei Stückelung gewinnt die am häufigsten gemeldete
Sprache. Das ist der Bezugswert für die Sprachdrift-Prüfung.

Nicht verwechseln mit `detected_language` (nur Sprecher-Weg, bisher schon da): das
ist die Arbeitssprache (Vorgabe des Aufrufers oder, bei `auto`, die erkannte), nicht
zwingend das, was das Modell gesagt hat.

### 4. Wo die Felder ankommen

Alle drei Wege liefern denselben `data`-Block:

- **Sync-Antwort** `POST /api/audio/process` und `POST /api/audio/process-diarized`:
  `data.segments[]`, `data.language`, dazu wie bisher `data.transcription.text`
  (und verschachtelt `data.transcription.segments`, identisch zu `data.segments`).
- **Webhook** `phase: completed`: `data.transcription.text`, `data.output_text`,
  `data.segments[]`, `data.language`; im Sprecher-Weg dazu `speakers`,
  `dropped_context`, `detected_language`, `duration`, `llm_model`, `chunk_count`.
- **SSE** `GET /api/jobs/{id}/stream` und Job-Status `GET /api/jobs/{id}`: derselbe Block.

Die flachen Schlüssel sind der Vertrag, nicht die Verschachtelung. Felder, die der
Lauf nicht geliefert hat, fehlen (keine leeren Listen); die Werte innerhalb eines
Segments sind dagegen immer alle da, ggf. als `null`.

### 5. Nebenbedingungen

- Die Segmenttexte sind die **des Modells in der Originalsprache**, auch wenn
  `transcription.text` übersetzt (`target_language`) oder per Template umgeformt
  wurde. Absätze aus `output_text` lassen sich also nicht 1:1 auf Segmente mappen,
  wenn übersetzt wurde — über die Zeitmarken schon.
- `confidence` war bisher immer `1.0` (nie gefüllt). Wer das gelesen hat, sieht
  jetzt `null` oder einen echten Wert. Bitte prüfen, ob KS `confidence` irgendwo
  als Pflichtfeld oder als `1.0 == gut` behandelt.
- Cache: Ergebnisse aus dem Secretary-Cache tragen die neuen Felder nur, wenn sie
  nach dieser Änderung erzeugt wurden. Alte Cache-Treffer haben `segments` mit
  einem Eintrag und `quality_source: "none"`. Für den Prüffall `useCache=false`
  setzen oder die Datei neu laufen lassen.
- Nebeneffekt der Umstellung: der Secretary lädt die Datei bei GPT-Modellen nicht
  mehr zweimal zum Anbieter hoch (vorher erst `verbose_json`, nach dem Fehler
  `json`). Kürzere Laufzeit, gleiche Kosten.

## Was KS daraus bauen soll (aus dem ursprünglichen Auftrag)

Aus den Rohwerten je Absatz:

1. Vermerk `verlaesslichkeit` im Frontmatter des Transkripts (Zusammenfassung:
   Anteil verdächtiger Abschnitte, schlechtester `avg_logprob`, höchste
   `compression_ratio`, `quality_source`, `language`).
2. Stopp-Zeichen in Werkbank und Reiter „Transkript" (ADR 0006: die Maschine setzt
   es selbst), wenn Abschnitte über den Schwellen liegen.
3. Markierung der Absätze in der Korrektur-Ansicht (links Text, rechts Arbeit) über
   die Zeitmarken der Segmente.
4. Text-Prüfungen, die **ohne Werte auskommen** — nötig für den Sprecher-Weg
   (`quality_source: "none"`) und als zweite Meinung sonst: Schleifen (gleicher
   Satz n-mal hintereinander), Sprachdrift gegen `data.language`, Textlänge gegen
   Dauer, kaputte Labels („Sprecher @").
5. Doku `docs/_secretary-service-docu/audio.md` im KS-Repo nachziehen (Sync-Antwort,
   Webhook-Payload, `process-diarized`). Der Vertragstext steht im Secretary-Repo in
   `docs/reference/api/endpoints/audio.md`, Abschnitt „Verlässlichkeit je Abschnitt",
   und lässt sich übernehmen. Diese Datei hat im KS-Repo auf Branch
   `claude/clever-hypatia-8ar4yd` bereits uncommittete Änderungen — bitte dort
   zusammenführen, nicht überschreiben.

Schwellen: die Whisper-Voreinstellungen (−1.0 / 2.4 / 0.6) sind ein Startpunkt, kein
Gesetz. Sie gehören in KS an eine Stelle, die sich ohne Code ändern lässt.

## So testet man es

### Voraussetzung: Secretary lokal aus dem Branch

Im Secretary-Repo den Worktree des Branches nehmen (oder den Branch auschecken),
`.env` aus dem Haupt-Checkout hineinkopieren, dann:

```bash
PYTHONPATH=. C:/Users/peter.aichner/projects/CommonSecretaryServices/venv/Scripts/python.exe src/main.py
```

Läuft auf `http://127.0.0.1:5001`. `GET /api/health` antwortet mit 308, das reicht als
Lebenszeichen. Swagger: `http://127.0.0.1:5001/api/doc`. Alle `/api/…`-Aufrufe
brauchen den Header `X-Secretary-Api-Key` mit `SECRETARY_SERVICE_API_KEY` aus der
`.env`.

### Schritt 1: Schnelltest mit der kurzen Probe (16 s, Deutsch)

Datei: `cache/probe/probe.mp3` im Secretary-Worktree (TTS-Probe, nicht im Git).

```bash
curl -s -X POST "http://127.0.0.1:5001/api/audio/process" -H "X-Secretary-Api-Key: DEIN_KEY" -F "file=@cache/probe/probe.mp3" -F "source_language=auto" -F "target_language=de" -F "useCache=false" | python -c "import json,sys; d=json.load(sys.stdin)['data']; print('language:', d['language']); [print({k:s[k] for k in ('start','end','avg_logprob','compression_ratio','no_speech_prob','quality_source')}, s['text'][:40]) for s in d['segments']]"
```

Erwartung mit `gpt-transcribe` (aktuelle Zuordnung): `language: de`, **ein** Segment
0–16 s, `quality_source: logprobs`, `avg_logprob` nahe 0, `no_speech_prob: None`.

### Schritt 2: Auf `whisper-1` umschalten und wiederholen

```bash
curl -s -X PUT "http://127.0.0.1:5001/llm-config/api/use-cases/transcription/current-model" -H "Content-Type: application/json" -d "{\"model_id\": \"openai/whisper-1\"}"
```

(oder in der Maske `http://127.0.0.1:5001/llm-config`). Dann Schritt 1 wiederholen.
Erwartung: **mehrere** Segmente (bei der Probe vier), `quality_source: whisper`, alle
drei Werte gefüllt. Zurück mit `openai/gpt-transcribe`.

**Achtung:** Die Zuordnung liegt in der geteilten Dev-Datenbank
(`common-secretary-service-dev`, Collection `llm_use_case_config`) und gilt sofort
für jeden Secretary, der gegen diese Datenbank läuft. Nach dem Test zurückstellen.

### Schritt 3: Der Prüffall über KnowledgeScout (Webhook-Weg)

KS auf `http://127.0.0.1:5001` zeigen (KS-Memory „Lokaler Secretary: Use-Case
zuordnen"). Datei: „Journalistenschulung Armut – Teil 4 – Diskussion.m4a", Library
Dachverband, Ordner `events/Journalisten Schulung`. Einmal mit `whisper-1`, einmal
mit `gpt-transcribe`, jeweils Cache aus.

Im Webhook `phase: completed` prüfen:

- `data.segments` ist eine Liste mit vielen Einträgen (whisper) bzw. ~10 Einträgen
  (gpt-transcribe, einer je 300-s-Stück); `start` steigt monoton bis zur Dauer der
  Datei (~2760 s); kein Segment hat `start: 0, end: <Antwortzeit>` als Einziges.
- `data.language` ist `"de"` oder `"it"` (nicht `null`).
- Die **Schleifen-Stelle** („… welfare state" ×20 im früheren Sprecher-Transkript):
  mit `whisper-1` entweder keine Schleife im Text oder ein Segment mit
  `compression_ratio > 2.4`. Das ist das Abnahmekriterium — die Zahl ist im Webhook
  sichtbar, nicht „der Text ist besser".
- Die **Englisch-Stelle** (Wortmeldung Softwarearchitekt): korrekt deutsch, oder
  ein Segment mit `avg_logprob < -1`.
- Sprecher-Weg (`process-diarized`) zur Kontrolle: alle Segmente `quality_source:
  "none"`, Werte `null`, im Secretary-Log eine Zeile „Sprecher-Transkription ohne
  Verlässlichkeitswerte". Das ist so erwartet.

Zum Mitlesen ohne Webhook-Empfänger: Job-ID aus der 202-Antwort nehmen und
`GET /api/jobs/{id}/stream` (SSE) oder den Job-Status `GET /api/jobs/{id}` abrufen; der `data`-Block ist
derselbe.

### Schritt 4: Negativprobe

Ein Segment aus Schritt 3 mit hoher `compression_ratio` nehmen und den Text ansehen:
er muss sich tatsächlich wiederholen. Ein Segment mit `avg_logprob` nahe 0 muss
sauber lesbar sein. Wenn das nicht stimmt, ist die Zuordnung Segment ↔ Text falsch,
nicht die Schwelle.

## Was im Secretary geprüft wurde

- 19 neue Tests in `src/tests/test_transcription_quality.py`; Gesamtlauf 153
  bestanden. Ein Fehler vorbestehend (`test_simple_audio_cache`, braucht
  MongoDB-Schreibzugriff, scheitert auf `main` genauso).
- `mypy` ohne neue Befunde.
- Realer API-Lauf mit der 16-s-Probe durch den geänderten Provider für `whisper-1`
  (4 Segmente, `whisper`, `de`), `gpt-transcribe` (1 Segment, `logprobs`, `de`),
  `gpt-4o-transcribe` (1 Segment, `logprobs`, Sprache `null`),
  `gpt-4o-transcribe-diarize` (1 Segment, `none`).
- Sync-Endpunkt über den laufenden Dienst mit `gpt-transcribe`: `data.segments`
  flach mit Werten, `data.language: "de"`.

Nicht geprüft: die 46-Minuten-Datei über den Webhook (braucht KS, Schritt 3).

## Dateien im Secretary (zum Nachlesen)

| Datei | Inhalt |
|---|---|
| `src/core/llm/transcription_quality.py` | Format und `include` je Modell, Segmente aus der Antwort, Mittelwert der Logprobs, `compression_ratio` wie Whisper |
| `src/core/models/audio.py` | `TranscriptionSegment` mit den neuen Feldern, `TranscriptionResult.detected_language`, flache `segments`/`language` in `AudioProcessingResult.to_dict()` |
| `src/core/llm/providers/openai_provider.py` | `transcribe()`: Segmente behalten, Retry ohne `include` |
| `src/utils/transcription_utils.py` | Stück-Weg: Offsets, Sammeln, IDs |
| `src/processors/diarized_audio_processor.py` | Sprecher-Weg: `quality_source: "none"`, Log |
| `src/api/audio_completed_data.py` | `language` im Webhook/SSE-Block |
| `docs/reference/api/endpoints/audio.md` | Vertragstext, Abschnitt „Verlässlichkeit je Abschnitt" |
