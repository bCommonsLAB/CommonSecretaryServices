# Hand-off: Verlässlichkeit, Teil 2 — Sprache je Stück, Wort-Zeitmarken, Schleifen-Wächter; Zielbild lokales Whisper und getrennte Sprecher

Stand 09.10.2026. Baut auf Branch `claude/transkript-verlaesslichkeit-6e7aa8`
(Commits `0e4951b`, `a23309b`, `96752db`) auf. Vorgänger:
`handover-transkript-verlaesslichkeit.md` (Auftrag Teil 1) und
`handover-ks-transkript-verlaesslichkeit.md` (was Teil 1 liefert).
Auftraggeber: KnowledgeScout, Branch `claude/transcription-speaker-recognition-view-132872`.

## Ziel (unverändert)

Ein Transkript ist nur etwas wert, wenn es ein Abbild der Wirklichkeit ist und der
Mensch sehen kann, wie wahrscheinlich das ist. Teil 1 reicht die Whisper-Werte je
Abschnitt durch. Der Prüffall zeigt: das reicht nicht.

## Prüffall 09.10. (Teil 1 über den KS-Webhook-Weg, `whisper-1`)

Datei „Teil 4 – Diskussion" (49 Min., Deutsch/Italienisch gemischt, Publikums-
diskussion), Kopie im KS-Ordner `events/Journalisten Schulung/test`, Secretary-Job
`job-ebe60163-ead3-4799-a2fa-55b644912c91` (Ergebnis in der Dev-Mongo abrufbar).

Was gut war:
- 582 Segmente, `quality_source: whisper`, Zeitmarken 0 → 2950 s lückenlos.
- Nach Whispers eigener Regel (`avg_logprob < −1` oder `compression_ratio > 2.4`)
  **0 verdächtige Abschnitte**; schlechtester logprob −0.96, höchste Wiederholung 2.09.
  Keine Schleife, kein erfundener Block — anders als beim Sprecher-Weg derselben Datei.
- Die bekannten Fehlstellen des Sprecher-Transkripts sind richtig („auf wessen
  Rücken wird hier der Wohlstand gemacht", „ich bin Softwarearchitekt",
  „Schublade des Bürgermeisters").

Was die Zahlen **nicht** treffen — und das ist der Auftrag:

| Stelle | Gesprochen | Transkript | `avg_logprob` | `no_speech_prob` |
|---|---|---|---|---|
| 223–251 s | Deutsch („jährlich werden Schafe und Ziegen erhoben") | **Italienisch**, falsch übersetzt („ogni anno le uova e le zuccherie vengono intervistate") | −0.71 | 0.79 |
| 354–382 s | Italienische Zusammenfassung (angekündigt: „ich fasse jetzt kurz auf Italienisch zusammen") | **Deutsch**, holpriges Übersetzungsdeutsch | −0.71 | 0.97 |
| 118–168 s | dasselbe Muster | Italienisch | −0.54 … −0.88 | 0.82–0.85 |

Whisper rät bei Sprachwechseln innerhalb eines 30-s-Fensters die Sprache falsch und
**übersetzt** statt zu transkribieren. `avg_logprob` bleibt dabei unauffällig. Der
einzige Wert, der diese Fenster trifft, ist `no_speech_prob` (hoch bei klar
gesprochener Rede). 162 von 582 Segmenten liegen über 0.6, 55 über 0.9; drei
Fenster stichprobenartig geprüft, alle drei übersetzt. Hypothese, keine Gewissheit.

Zweiter Befund: `data.language` ist `"de"` für die ganze Datei, obwohl lange
Passagen Italienisch sind. Je Stück (300 s) meldet Whisper die Sprache — der
Dienst verwirft sie beim Zusammenbauen (`transcription_utils.py`, Stück-Weg;
`reported_language` in `transcription_quality.py` wird nur noch für die Mehrheit
genutzt).

## Auftrag A (zuerst, klein): Sprache je Stück und je Segment

1. `language` **je Stück** behalten: beim Zusammenbauen im Stück-Weg die von Whisper
   gemeldete Sprache an jedes Segment des Stücks schreiben (`segment.language`,
   ISO 639-1 oder `null`, `quality_source` sagt wie bisher, ob das Modell sie
   geliefert hat). `data.language` (Mehrheit) bleibt für Rückwärtskompatibilität.
2. **Text-Spracherkennung je Segment** als zweite Meinung: `segment.text_language`
   aus dem Segmenttext (`langdetect` oder `lingua`, reine Textstatistik, kein
   LLM-Aufruf, keine Kosten). Kurze Segmente (< 20 Zeichen) → `null`, nicht raten.
   Dazu `segment.text_language_prob` (0–1), falls die Bibliothek sie liefert.
3. Kein Schwellenwert, keine Bewertung im Dienst — KS vergleicht `language`
   (Stück) gegen `text_language` (Segment) gegen die Nachbarn und gegen
   `no_speech_prob` und entscheidet selbst, was „vermutlich übersetzt" heißt.

Abnahme am Prüffall: Segmente 223–251 s tragen `language: "de"` oder `"it"` je
Stück und `text_language: "it"`; Segmente 354–382 s `text_language: "de"` bei
angekündigtem Italienisch. Beides muss im Webhook als Zahl/Code sichtbar sein.

## Auftrag B (klein): Wort-Zeitmarken

`whisper-1` nimmt `timestamp_granularities=["word"]` (nur mit `verbose_json`).
Ergebnis: `words[]` mit `word`, `start`, `end` je Segment, Zeitmarken um den
Stück-Offset verschoben wie die Segmente. Flach unter `segment.words`.

Zweck in KS: In der Korrektur-Ansicht auf einen Absatz klicken und genau diese
Stelle im Audio hören. Ohne Wort-Zeitmarken muss der Mensch die Sekunde suchen —
dann hört niemand nach.

Für GPT-Modelle (`logprobs`-Weg) gibt es keine Wort-Zeitmarken; `words` fehlt
dann (kein leeres Array erfinden). Zu prüfen: Kosten/Antwortgröße bei 49 Minuten
(~8.000 Wörter) — der Webhook-Body wächst; wenn er zu groß wird, `words` nur in
Job-Status/SSE, nicht im Webhook, und das im Vertrag sagen.

## Auftrag C (mittel): Schleifen-Wächter

Whisper macht intern einen „temperature fallback" (bei `compression_ratio > 2.4`
oder `avg_logprob < −1` neu decodieren mit höherer Temperatur); die API tut das
nicht. Der Dienst holt das für den Stück-Weg nach:

1. Nach jedem Stück die Segmente prüfen. Liegt eines über den Whisper-Schwellen,
   **dieses Stück einmal neu** laufen lassen — ohne den Prompt-Kontext des
   Vorstücks (häufigste Schleifen-Ursache, siehe `transcription_utils.py`, wo das
   Ende des Vorstücks als `prompt` mitgegeben wird) und mit `temperature=0.2`.
2. Bleibt es schlecht: das bessere der beiden Ergebnisse nehmen (weniger
   Segmente über den Schwellen), das Stück im Ergebnis als `retried: true` mit
   beiden Wertepaaren markieren. Kein drittes Mal; kein stilles Verwerfen.
3. Log-Eintrag je Wiederholung mit Stück-Index, Grund und Werten vorher/nachher.
   Kosten: nur betroffene Stücke laufen doppelt.

Abnahme: Testdatei mit absichtlicher Schleife (ein Stück Stille/Rauschen zwischen
Sprache erzeugt sie bei Whisper verlässlich) → Wiederholung im Log, `retried` im
Ergebnis; sauberer Prüffall Teil 4 → keine Wiederholung.

## Zielbild D (groß): lokales Whisper als zweiter Weg

`faster-whisper` mit `large-v3` als eigenes Modell im Use-Case `transcription`
(Provider `local`, auswählbar in der Maske; die OpenAI-Wege bleiben). Es liefert,
was die API nicht hergibt:

- `language_probability` je Segment und Sprach-Entscheidung je Fenster — für
  Deutsch/Italienisch gemischt die Lösung des Übersetzungsproblems: je Fenster
  die Sprache mit dem besseren logprob nehmen, statt übersetzen zu lassen
  (`language=None`, `multilingual=True` je nach Version).
- Wahrscheinlichkeit **je Wort** (`word.probability`) — feinere Markierung in KS
  als je Segment.
- `condition_on_previous_text=False` — verhindert Schleifen an der Quelle; dann
  entfällt Auftrag C für diesen Weg.
- Keine Kosten je Minute, aber Laufzeit: 49 Minuten Audio in Minuten mit GPU,
  rund eine Stunde ohne. Der Dienst läuft heute im Docker ohne GPU — das ist die
  offene Infrastrukturfrage, bevor man baut.

Wann: wenn die Statistik aus Auftrag A nach einigen Aufnahmen zeigt, dass gemischte
Sprache innerhalb eines Fensters häufig ist. Vor dem Bau: Laufzeit auf der
Zielmaschine messen.

## Zielbild E (groß): Sprecher getrennt vom Text

Der heutige Sprecher-Weg (`gpt-4o-transcribe-diarize`) ist für Diskussionen
unbrauchbar: kein Kontext, keine Zielsprache, keine Werte, Labels je Stück neu
gezählt (16 Labels auf drei Stücke), übersetzt und erfindet. Das lässt sich im
Dienst nicht heilen — nur ersetzen:

1. **Text** aus dem normalen Weg (whisper-1 oder lokal, mit Thema und Namen, mit
   Werten).
2. **Wer spricht wann** aus `pyannote.audio` (Speaker Diarization, lokal, Modell
   `pyannote/speaker-diarization-3.1`, HuggingFace-Token nötig): Zeitbereiche mit
   Sprecher-Label, über die **ganze Datei** einheitlich — ein Label je Person,
   nicht je Stück.
3. Der Dienst legt beides über die Zeitmarken zusammen: je Segment der Sprecher
   mit der größten Überdeckung; bei Überdeckung < 50 % `speaker: null` und ein
   Vermerk, nicht raten. Ergebnisform wie heute (`segments[].speaker`,
   `speakers[]`), damit KS nichts umbauen muss.
4. `process-diarized` behält seine Schnittstelle, wählt aber den neuen Weg, wenn
   der Use-Case `diarized_transcription` auf `local/pyannote` steht.

Dann gibt es Sprecher-Labels **und** Verlässlichkeitswerte **und** Kontext in einem
Ergebnis — das Diarize-Modell kann keins davon zusammen. Laufzeit pyannote ohne
GPU: etwa Echtzeit (49 Minuten Audio ≈ 40–60 Minuten), mit GPU Minuten. Gleiche
Infrastrukturfrage wie D; zusammen entscheiden.

## Reihenfolge und Modellwahl

A + B zuerst (ein Nachmittag, kein Risiko, kein neuer Dienst), dann C. D und E sind
ein eigenes Vorhaben mit vorgeschalteter GPU-Entscheidung; E vor D, weil die
Sprecherfrage der Anlass war und E sie ohne Qualitätsverlust löst.

Sonnet reicht für A–C (der Weg ist vorgezeichnet); für D/E Opus, dort sind
Infrastruktur und Alignment zu entscheiden.

## Tests und Regeln

- Dataclasses, keine Pydantic (`.cursorrules`); `mypy`/`pyright` ohne neue Befunde;
  `pytest` (`pytest.ini`, `testpaths = .tests`) grün — Stand nach Teil 1: 153
  bestanden, 1 vorbestehender Fehler (`test_simple_audio_cache`, braucht Mongo).
- Tests in `src/tests/test_transcription_quality.py` erweitern: Sprache je Stück
  überlebt den Stück-Weg; `text_language` bei kurzem Text `null`; `words` mit
  Offset; Wächter wiederholt genau einmal und nimmt das bessere Ergebnis.
- Vertrag nachziehen: `docs/reference/api/endpoints/audio.md` hier, danach
  `docs/_secretary-service-docu/audio.md` im KS-Repo (dort liegen auf Branch
  `claude/clever-hypatia-8ar4yd` uncommittete Änderungen — zusammenführen).
- Cache: Ergebnisse vor dieser Änderung haben die neuen Felder nicht; Prüffälle
  mit `useCache=false` (camelCase — KS schickt das für Audio bereits so).

## Start-Prompt für die Secretary-Session

```
Lies docs/handover-secretary-verlaesslichkeit-2.md. Arbeite Auftrag A und B ab
(Sprache je Stück und je Segment, Wort-Zeitmarken), mit Tests, auf dem Branch
claude/transkript-verlaesslichkeit-6e7aa8 oder einem neuen von dort. Prüfe das
Ergebnis am Prüffall (Job job-ebe60163-… neu laufen lassen oder die Datei aus dem
KS-Ordner test) und melde die Werte der drei genannten Fenster. Auftrag C erst
danach, D/E nicht bauen — nur die GPU-Frage mit einer Laufzeitmessung von
faster-whisper und pyannote auf dieser Maschine beantworten.
```

---

## Ergebnis Secretary 09.10.2026 (Branch `claude/transkript-verlaesslichkeit-6e7aa8`)

### Auftrag A: gebaut

Jedes Segment trägt jetzt `language` (vom Modell für das Stück gemeldet),
`text_language` und `text_language_prob` (aus dem Segmenttext, lingua, kein
Modellaufruf; unter 20 Zeichen `null`). Gilt auch für den Sprecher-Weg.
`data.language` (Mehrheit) bleibt.

Bibliothek: `lingua-language-detector`, nicht `langdetect`. Am Prüf-Transkript
(539 Segmente ≥ 20 Zeichen) lag langdetect 16-mal daneben, oft mit Wahrscheinlichkeit
1.00 (Afrikaans, Schwedisch, Polnisch für deutsche Sätze); lingua, beschränkt auf
35 Sprachen, zweimal, beide mit Wahrscheinlichkeit unter 0.4. Kosten: rund 290 MB
im Docker-Image.

Prüffall neu gelaufen (`whisper-1`, ohne Cache, 67 s):

| Fenster | `language` (Stück) | `text_language` | `no_speech_prob` | Text |
|---|---|---|---|---|
| 118–168 s | `de` | `it` (0.67–1.0) | 0.81–0.88 | italienisch, übersetzt |
| 223–251 s | `de` | `it` (0.26–0.99) | 0.99 | italienisch, übersetzt („le macchine e i veicoli") |
| 354–382 s | `de` | `de` (0.81–1.0) | 0.97 | deutsch, aus dem Italienischen übersetzt |

Abnahme 223–251 s erfüllt. Für 354–382 s gilt `text_language: "de"` wie erwartet,
**aber** das ist auch die Stücksprache: Wenn Whisper in die Sprache des Stücks
übersetzt, zeigt der Sprachvergleich nichts. Dort bleiben nur `no_speech_prob` und
der angekündigte Sprachwechsel im Text davor. Über die ganze Datei: 65 von 465
Segmenten weichen ab (`de`→`it` 40, `it`→`de` 22, Rest Einzelfälle), 35 davon mit
`no_speech_prob` > 0.6.

### Auftrag B: gebaut, aber standardmäßig **aus**

Messung: `whisper-1` mit `timestamp_granularities=["word"]` liefert weniger Text.
Vier 5-Minuten-Stücke der Prüfdatei, je zwei Läufe mit und ohne Wort-Zeitmarken:

| Stück | Zeichen ohne words | Zeichen mit words |
|---|---|---|
| 0–300 s | 1707 / 1707 | 1429 / 1628 |
| 300–600 s | 3630 / 1590 | 2879 / 2879 |
| 600–900 s | 3473 / 3473 | 2670 / 2670 |
| 900–1200 s | 3048 / 3048 | 2617 / 2495 |

Im Stück 600–900 s fehlten mit Wort-Zeitmarken 16 von 36 Sätzen, darunter
793–860 s am Stück. Ein Transkript mit Lücken widerspricht dem Ziel; deshalb fordert
der Dienst keine Wörter an. Der Code ist da (Provider-Parameter `word_timestamps`,
Zuordnung Wort → Segment, Verschiebung um den Stück-Offset, getestet), aber nicht
über die API schaltbar. Webhook-Größe zum Vergleich: 250 KB ohne, 509 KB mit Wörtern.
Zum Anspringen einer Stelle reichen die Segment-Zeitmarken (2–15 s).

### Nebenbefunde

- **Lücken:** Im Prüffall gibt es 12–17 Stellen über 10 s ohne Segment, bis 49 s
  (z. B. 545–594 s). In einer Diskussion heißt das oft ausgelassene Rede. KS kann
  das aus `start`/`end` selbst ablesen; ob die Stellen still sind, ist ungeprüft.
- **Läufe schwanken:** derselbe Stück-Aufruf liefert mal 65, mal 26 Segmente
  (300–600 s). Ein einzelner Lauf ist keine Messung.
- **Prämisse von Auftrag C stimmt nicht:** Der Stück-Weg gibt das Ende des
  Vorstücks **nicht** als `prompt` mit. Die Stücke laufen parallel; alle bekommen
  denselben Kontext des Aufrufers (Thema, Begriffe). Im Prüffall liegt außerdem kein
  Segment über den Whisper-Schwellen — C würde dort nie auslösen.

### Vorschlag statt C (noch nicht gebaut)

Die Fehlerart im Prüffall ist Übersetzung, nicht Schleife. Wirksamer als ein
Temperatur-Neuversuch wäre eine **Sprach-Gegenprobe**: Wo `no_speech_prob` > 0.6
oder `language ≠ text_language`, das betroffene Zeitfenster einmal mit erzwungener
anderer Sprache (`language="it"` bzw. `"de"`) neu transkribieren und das Ergebnis mit
dem besseren `avg_logprob` nehmen, beide Wertepaare im Segment vermerken. Kosten: nur
die betroffenen Fenster laufen doppelt (im Prüffall rund ein Viertel der Datei).
Entscheidung offen: C wie beschrieben, Gegenprobe, oder beides.

### GPU-Frage (D/E)

Diese Maschine: NVIDIA RTX 2000 Ada Laptop GPU mit 8 GB, i9-13950HX, 64 GB RAM.
`faster-whisper large-v3` passt in 8 GB. Die Laufzeitmessung steht noch aus: sie
braucht rund 3 GB Modell plus CUDA-Bibliotheken, und `pyannote` braucht einen
Hugging-Face-Token mit akzeptierten Modellbedingungen; in der `.env` ist keiner.
Der Dienst im Docker hat weiterhin keine GPU.
