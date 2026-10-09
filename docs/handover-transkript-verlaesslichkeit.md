# Hand-off: Verlässlichkeit je Abschnitt aus der Transkription durchreichen

Stand 09.10.2026. Auftraggeber: KnowledgeScout (Branch
`claude/transcription-speaker-recognition-view-132872`, Commit `6dd933bb`).
Vorgänger in diesem Repo: `handover-webhook-speakers-segments.md` (07.10.,
Webhook mit `speakers`/`segments`) und `handover-heartbeat-je-stueck.md`.

## Warum

Ein Transkript ist nur etwas wert, wenn es ein Abbild der Wirklichkeit ist und
der Mensch sehen kann, wie wahrscheinlich das ist. Heute kommt beim Client
Text an, ohne jeden Hinweis, wo das Modell geraten hat.

Prüffall 09.10. (Diskussion, 46 Min., Deutsch/Italienisch, Sprecher-Weg):
derselbe Satz rund 20-mal hintereinander (Schleife), Wortmeldungen ins
Englische übersetzt und dabei erfunden, Zahlen verdreht (2015 → 2005), 16
Sprecher-Labels über drei Stücke, davon eines kaputt („Sprecher @"). Nichts
davon war am Ergebnis zu erkennen, bevor jemand den ganzen Text gelesen hat.

Das Whisper-Modell liefert pro Abschnitt drei Werte, die genau diese Fälle
anzeigen — der Dienst wirft sie weg.

## Die drei Werte

| Wert | Bedeutung | Erfahrungswert für „verdächtig" |
|---|---|---|
| `avg_logprob` | mittlere Log-Wahrscheinlichkeit der Tokens; je näher an 0, desto sicherer | unter −1.0 |
| `compression_ratio` | gzip-Verhältnis des Texts; hoch = Wiederholungen (Schleife) | über 2.4 |
| `no_speech_prob` | Wahrscheinlichkeit, dass gar nicht gesprochen wurde; hoch + schlechter logprob = erfundener Text bei Stille | über 0.6 |

Die Schwellen sind die Voreinstellungen aus dem Whisper-Decoder selbst
(`compression_ratio_threshold=2.4`, `logprob_threshold=-1.0`,
`no_speech_threshold=0.6`). Der Dienst gibt die Rohwerte weiter; wo der
Client die Grenze zieht, ist Sache des Clients.

## Befund im Code

- `src/core/llm/providers/openai_provider.py`, `transcribe()` (Z. 114–275):
  fordert `response_format="verbose_json"` an. Mit `whisper-1` kommen
  `segments[]` mit allen drei Werten zurück (Typ dafür existiert schon:
  `WhisperSegment` in `src/utils/openai_types.py` Z. 64–76). Der Code baut
  danach aber **ein einziges `TranscriptionSegment`** über den ganzen Text
  (Z. 247–253, `segment_id=0`, `start=0`, `end=duration`) — die Whisper-Segmente
  samt Werten sind weg.
- `src/core/models/audio.py` Z. 79–99: `TranscriptionSegment` hat
  `confidence: float = 1.0`. Nie gefüllt, steht immer auf 1.0.
- `src/utils/transcription_utils.py` Z. 1637–1656: der Stück-Weg (lange
  Dateien) ruft `provider.transcribe(..., response_format="verbose_json")`
  und verpackt das Ergebnis in ein Hilfsobjekt, das nur `text`, `language`
  und `usage` kennt — auch hier gehen die Segmente verloren. Der direkte
  Client-Aufruf im `else`-Zweig (Z. 1658–1672) hätte sie noch.
- `gpt-4o-transcribe` / `gpt-4o-mini-transcribe`: kein `verbose_json`
  (Retry Z. 201 fängt das ab und fällt auf `json` zurück). Wahrscheinlichkeiten
  gibt es dort nur mit `include=["logprobs"]` — **pro Token**, nicht pro
  Abschnitt, und ohne `compression_ratio`/`no_speech_prob`. Daraus lässt sich
  ein Abschnittswert mitteln, Schleifen muss man dann aus dem Text erkennen.
- Sprecher-Weg `transcribe_diarized()` (Z. 278–355, Modell
  `gpt-4o-transcribe-diarize`, `response_format="diarized_json"`): Antwort
  wird roh durchgereicht (`core.llm.diarization.read_diarized_segments`). Ob
  dieses Modell `logprobs` annimmt, ist **zu testen**; vermutlich nein. Dann
  bleibt für den Sprecher-Weg nur die Text-Prüfung im Client.
- Webhook/SSE: `src/api/audio_completed_data.py` reicht `segments` bereits
  durch, wenn der Processor sie in `structured_data["data"]` legt
  (`_OPTIONAL_KEYS`). Neue Felder je Segment brauchen dort keinen Umbau —
  nur die Doku.

Konsequenz: Für `whisper-1` sind die Werte da und werden nur verschluckt.
Für die GPT-4o-Modelle gibt es einen schwächeren Ersatz. Welches Modell im
Use-Case `transcription` konfiguriert ist (Maske / `scripts/seed_llm_models.py`),
entscheidet, was am Ende ankommt — der Dienst soll das **sagen**, nicht raten.

## Auftrag

1. **Segmente behalten** (`openai_provider.transcribe`): aus
   `response.segments` je ein `TranscriptionSegment` bauen (`start`, `end`,
   `text`), nicht mehr eines über alles. Der Gesamttext bleibt `result.text`.
2. **Werte am Segment**: `TranscriptionSegment` um `avg_logprob`,
   `compression_ratio`, `no_speech_prob` erweitern (`Optional[float]`, Default
   `None` — „nicht geliefert" ist etwas anderes als 0.0, kein stiller
   Default). `confidence` aus `avg_logprob` ableiten (`exp(avg_logprob)`,
   auf 0–1 begrenzt) oder entfernen, wenn es niemand liest — aber nicht
   weiter stumm auf 1.0 lassen.
3. **Stück-Weg** (`transcription_utils.py` um Z. 1637): das Hilfsobjekt
   `TranscriptionResponse` muss die Segmente mitnehmen; Zeitmarken je Stück
   um den Stück-Offset verschieben, damit `start`/`end` auf die ganze Datei
   zeigen.
4. **GPT-4o-Modelle**: `include=["logprobs"]` anfordern, wenn das Modell es
   kann; aus den Token-Logprobs je Segment einen Mittelwert bilden und als
   `avg_logprob` eintragen; `compression_ratio` im Dienst aus dem Segmenttext
   selbst berechnen (gzip-Länge / Textlänge, wie Whisper es tut);
   `no_speech_prob` bleibt `None`. Was fehlt, steht in `dropped_context`
   bzw. einem neuen Feld `quality_source` („whisper", „logprobs", „none") —
   der Client darf nicht raten, woher die Zahl kommt.
5. **Sprecher-Weg**: einmal testen, ob `gpt-4o-transcribe-diarize`
   `include=["logprobs"]` annimmt. Ja → wie 4. Nein → `quality_source: "none"`
   und ein Log-Eintrag; der Client prüft dann nur den Text.
6. **Antwort und Webhook**: die drei Werte plus `quality_source` flach je
   Segment in `data.segments[]` (Sync-Antwort, Webhook, SSE — alle drei über
   `build_audio_completed_data`). Zusätzlich `data.language` (vom Modell
   erkannte Sprache) — der Client braucht sie für die Sprachdrift-Prüfung.
7. **Doku**: `docs/` hier und `docs/_secretary-service-docu/audio.md` im
   KS-Repo (Abschnitte Sync-Antwort, Webhook-Payload, `process-diarized`).

Nicht hier: Schwellen anwenden, Absätze einfärben, Korrektur vorschlagen. Das
macht KnowledgeScout aus den Rohwerten (nächster Schritt dort).

## Tests

- `src/tests/`: Provider-Test mit gemockter `verbose_json`-Antwort (zwei
  Segmente, unterschiedliche Werte) → zwei `TranscriptionSegment` mit den
  Werten; Antwort ohne `segments` → ein Segment, Werte `None`,
  `quality_source: "none"`.
- Stück-Weg: zwei Stücke à 60 s → Segmente des zweiten Stücks beginnen bei
  ≥ 60 s.
- `audio_completed_data`: Segment-Werte überleben den Builder unverändert.
- `pytest` (`pytest.ini`, `testpaths = .tests`) grün; `mypy`/`pyright` ohne
  neue Befunde. Dataclasses, keine Pydantic (`.cursorrules`).

## Prüffall

Secretary lokal auf `127.0.0.1:5001`, Use-Case `transcription` einmal mit
`whisper-1`, einmal mit `gpt-4o-transcribe` (Seed:
`scripts/seed_llm_models.py`, Zuordnung über `PUT current-model`, siehe
KS-Memory „Lokaler Secretary: Use-Case zuordnen").

Datei: „Journalistenschulung Armut – Teil 4 – Diskussion.m4a" (Library
Dachverband, Ordner `events/Journalisten Schulung`). Erwartung mit
`whisper-1`: die Schleifen-Stelle („… welfare state" ×20 im Sprecher-Transkript)
zeigt im normalen Weg entweder keine Schleife oder `compression_ratio > 2.4`;
die Englisch-Stelle (Wortmeldung Softwarearchitekt) hat `avg_logprob < −1`
oder ist korrekt deutsch. Beides als Zahlen im Webhook sichtbar — das ist
das Abnahmekriterium, nicht „der Text ist besser".

## Danach in KnowledgeScout

Aus den Rohwerten je Absatz: Vermerk `verlaesslichkeit` im Frontmatter,
Stopp-Zeichen in Werkbank und Reiter „Transkript" (ADR 0006, Maschine setzt
es selbst), Markierung der Absätze in der neuen Korrektur-Ansicht (links Text,
rechts Arbeit), dazu Text-Prüfungen, die ohne Werte auskommen (Schleifen,
Sprachdrift gegen `data.language`, Länge gegen Dauer, kaputte Labels).

## Ergebnis 09.10.2026 (Branch `claude/transkript-verlaesslichkeit-6e7aa8`)

### Befund vor dem Bau

- **Schritt 5, Sprecher-Modell:** `gpt-4o-transcribe-diarize` nimmt
  `include=["logprobs"]` nicht an. Mit `diarized_json`: „include=logprobs is only
  supported for response_format 'json'"; mit `json`: „Logprobs are not supported for
  diarization models". Folge: Sprecher-Weg `quality_source: "none"` plus Log-Eintrag.
- **Use-Case `transcription`:** in der Dev-Datenbank ist `openai/gpt-transcribe`
  zugeordnet (seit 06.09.2026), nicht `whisper-1`. `gpt-transcribe` nimmt
  `include=["logprobs"]` mit `response_format=json` an und meldet die Sprache als
  `languages: [{code: "de"}]`. `gpt-4o-transcribe` und `gpt-4o-mini-transcribe`
  liefern Logprobs, aber keine Sprache. `whisper-1` liefert mit `verbose_json`
  Segmente mit allen drei Werten.
- Nebenbefund: Whisper berechnet die drei Werte je 30-s-Decoder-Fenster; alle
  Segmente eines Fensters teilen sich dieselben Zahlen. Bei einer 46-Minuten-Datei
  sind das trotzdem rund 90 unabhängige Messpunkte.

### Gebaut

| Schritt | Wo |
|---|---|
| 1 Segmente behalten | `openai_provider.transcribe()` baut je Whisper-Segment ein `TranscriptionSegment`; Lesen in `core/llm/transcription_quality.py` |
| 2 Werte am Segment | `TranscriptionSegment`: `avg_logprob`, `compression_ratio`, `no_speech_prob` (Optional, Default None), `quality_source`; `confidence` ist jetzt Optional und wird aus `avg_logprob` abgeleitet (`exp`, 0–1), sonst None |
| 3 Stück-Weg | `transcribe_segment` bekommt `segment_offset`/`segment_duration`, verschiebt die Zeitmarken; `transcribe_segments` sammelt die Segmente aller Stücke und vergibt IDs neu |
| 4 GPT-Modelle | Format vorab je Modell (`plan_transcription_request`): Whisper `verbose_json`, GPT `json` + `include=["logprobs"]`; Mittelwert der Token-Logprobs, `compression_ratio` aus dem Text, `no_speech_prob` None, `quality_source: "logprobs"`. Wird `include` abgewiesen, einmal ohne wiederholen |
| 5 Sprecher-Weg | `quality_source: "none"`, Log „Sprecher-Transkription ohne Verlässlichkeitswerte" |
| 6 Antwort/Webhook | `AudioProcessingResult.to_dict()` legt `segments` flach und `language` (vom Modell gemeldet, sonst None) in `data`; `build_audio_completed_data` reicht `language` durch; Sprecher-Weg `_to_data` nutzt dieselbe Segmentform |
| 7 Doku | `docs/reference/api/endpoints/audio.md` (Sync-Antwort, Abschnitt „Verlässlichkeit je Abschnitt", Webhook, `process-diarized`), `jobs.md` |

Nebeneffekt: der Provider lädt die Datei bei GPT-Modellen nicht mehr zweimal hoch
(früher erst `verbose_json`, nach dem Fehler `json`).

### Geprüft

- `pytest`: 153 bestanden, 1 Fehler vorbestehend (`test_simple_audio_cache`, braucht
  Schreibzugriff auf MongoDB; scheitert auf `main` genauso).
- `mypy` auf den berührten Dateien: keine neuen Befunde, vier alte in
  `diarized_audio_processor.py` verschwinden. `pyright` ist lokal nicht installiert.
- Realer Lauf gegen die API mit einer 16-s-TTS-Probe durch `OpenAIProvider.transcribe`:
  `whisper-1` → 4 Segmente, `quality_source: whisper`, Sprache `de`;
  `gpt-transcribe` → 1 Segment, `logprobs`, Sprache `de`; `gpt-4o-transcribe` → 1
  Segment, `logprobs`, Sprache None; `gpt-4o-transcribe-diarize` → 1 Segment, `none`.

### Offen

- Prüffall mit der 46-Minuten-Diskussion aus der KS-Library (Schleife
  `compression_ratio > 2.4`, Englisch-Stelle `avg_logprob < −1`) — braucht den
  Webhook-Weg über KnowledgeScout. Mit dem aktuell zugeordneten `gpt-transcribe`
  kommt je Stück ein Wert; die Schleifen-Stelle zeigt sich dann nur, wenn sie das
  ganze Stück prägt. Für Werte je Abschnitt `whisper-1` zuordnen.
- `docs/_secretary-service-docu/audio.md` im KS-Repo: nicht angefasst, weil die
  Datei dort auf Branch `claude/clever-hypatia-8ar4yd` bereits uncommittete
  Änderungen hat. Der Vertragstext steht in `audio.md` hier (Abschnitt
  „Verlässlichkeit je Abschnitt") und lässt sich übernehmen.
