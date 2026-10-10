# Hand-off an KnowledgeScout: Transkription ohne Übersetzung (`translate=false`)

Stand 11.10.2026. Secretary-Branch `claude/transkript-ohne-uebersetzung`, PR
[bCommonsLAB/CommonSecretaryServices#33](https://github.com/bCommonsLAB/CommonSecretaryServices/pull/33).
Grundlage: Auftrag F im Nachtrag von `docs/handover-secretary-verlaesslichkeit-2.md`.
Vertrag: `docs/reference/api/endpoints/audio.md`, Abschnitt „Nachträgliche Übersetzung".

## Kurzfassung

Der Secretary übersetzt ein Stück nicht mehr, wenn KnowledgeScout `translate=false`
schickt. Das tut KS auf dem Branch `claude/transcription-speaker-recognition-view-132872`
schon (`src/lib/external-jobs/secretary-request-audio.ts`, normaler Weg). Am Request
muss KS also nichts ändern.

Neu für KS ist das Feld `data.translated_chunks`. Es sagt, welche Stücke des Gesamttexts
doch übersetzt wurden. Mit `translate=false` ist es leer.

## Warum

Der Secretary schneidet lange Aufnahmen in Stücke von 4–5 Minuten. Meldet das Modell
für ein Stück genau eine Sprache, die von `target_language` abweicht, ließ der Dienst
den Text dieses Stücks von einem Sprachmodell übersetzen. Am Prüf-Transkript
(„Teil 4 – Diskussion", 49 Min., Deutsch/Italienisch) war `transcription.text` dadurch
stellenweise eine Übersetzung. KS konnte das nicht sehen: Die Segmente hatten den
Originaltext, der Gesamttext nicht.

`languages=["de","it"]` schützte nur Stücke, für die das Modell beide Sprachen meldete.
Ein rein italienisches Stück wurde weiter übersetzt. `target_language` wegzulassen hilft
nicht, die Route setzt dann `de` ein.

## Was der Secretary jetzt tut

### Eingabe

| Feld | Typ | Default | Wirkung |
|---|---|---|---|
| `translate` | Boolean als Formularfeld (`"false"` / `"true"`) | `true` | `false`: kein Stück wird übersetzt |
| `languages` | JSON-Liste oder kommagetrennt | – | Stücke, deren gemeldete Sprache darin steht, werden nicht übersetzt |

Beides gilt im Sync-Weg und im Job-Weg (`callback_url`). `/audio/process-diarized`
übersetzt nie und kennt das Feld nicht; KS schickt es dort zu Recht nicht.

### Regel je Stück

| Fall | Übersetzt? |
|---|---|
| Modell meldet die Zielsprache, keine oder mehrere Sprachen | nein |
| `translate=false` | **nein, nie** |
| gemeldete Sprache steht in `languages` | nein |
| sonst (genau eine andere Sprache gemeldet) | ja |

### Ausgabe

Neu im `data`-Block von Sync-Antwort, Webhook (`phase: completed`), SSE und Job-Status:

```json
"translated_chunks": [
  { "index": 2, "start": 275.375, "end": 553.6, "source_language": "it", "target_language": "de" }
]
```

| Feld | Bedeutung |
|---|---|
| `index` | Stück ab 1 |
| `start`, `end` | Zeitbereich des Stücks in Sekunden, bezogen auf die ganze Datei |
| `source_language` | vom Modell gemeldete Sprache des Stücks |
| `target_language` | Sprache, in die übersetzt wurde |

- **Leere Liste:** nichts übersetzt. Mit `translate=false` immer leer.
- **Schlüssel fehlt:** Der Secretary ist älter als dieser PR (oder es ist der
  Sprecher-Weg). Dann weiß KS nicht, ob übersetzt wurde. In Prod gilt das, bis `main`
  dort ausgerollt ist.
- **`segments[].text` ist nie übersetzt**, in keinem Fall. Übersetzt wird nur
  `transcription.text` / `output_text`.

### Cache

`translate=false` steht im Cache-Schlüssel. Ein früher übersetztes Ergebnis kommt
dafür nicht aus dem Cache. KS schickt für Audio ohnehin `useCache=false`.

### Log im Secretary

- je nicht übersetztem Stück mit Grund: `Stück 2: nicht übersetzt (translate=false)`
- je übersetztem Stück: `Stück 2 übersetzt: it -> de`
- beim Aufteilen neu formuliert, weil die alte Zeile („Kapitel 1 zu lang, teile es
  auf") nach Fehler und Aufforderung klang:
  `Lange Aufnahme (49,5 Min.): der Dienst teilt sie automatisch in 11 Stücke (10 von 10 Schnitten an Sprechpausen), kein Eingriff nötig`

## Gemessen

Prüfdatei über die echte API, `gpt-transcribe`, ohne Cache, ohne `languages`:

| Anfrage | `translated_chunks` | Übersetzungsaufrufe | Italienisch im Gesamttext |
|---|---|---|---|
| ohne `translate` | Stück 2 (275–554 s), it → de | 1 | nein |
| `translate=false` | `[]` | 0 | ja |

Tests im Secretary: `src/tests/test_audio_translation_switch.py` (12 Tests), unter
anderem: der Job-Parameter `translate=false` erreicht den Processor.

## Was KS tun sollte

1. **Request:** nichts ändern. Prüfen, dass `translate: 'false'` aus
   `secretary-request-audio.ts` mit dem Feature-Branch nach `main` kommt.
2. **`data.translated_chunks` lesen** (im Webhook-Handler neben `segments` und
   `language`):
   - nicht leer: in der Korrektur-Ansicht einen Hinweis zeigen, dass die genannten
     Zeitbereiche im Gesamttext übersetzt sind, und die Absätze in diesen Bereichen
     markieren. Bei `translate=false` sollte das nie auftreten; wenn doch, ist es ein
     Fehler im Secretary und gehört gemeldet.
   - Schlüssel fehlt: „Übersetzung unbekannt" statt „nicht übersetzt" annehmen.
3. **Doku nachziehen:** `docs/_secretary-service-docu/audio.md` im KS-Repo
   (Parameter `translate`, Feld `translated_chunks`). Dort liegen auf Branch
   `claude/clever-hypatia-8ar4yd` uncommittete Änderungen — zusammenführen, nicht
   überschreiben.

## So testet man es

Secretary lokal auf `http://127.0.0.1:5001` mit dem Stand von PR #33 (läuft so auf dem
Rechner von Peter Aichner; sonst Branch auschecken, `.env` kopieren,
`python src/main.py`).

Schnelltest per curl, Datei „Teil 4 – Diskussion":

```bash
curl -s -X POST "http://127.0.0.1:5001/api/audio/process" -H "X-Secretary-Api-Key: DEIN_KEY" -F "file=@Teil4.m4a" -F "source_language=auto" -F "target_language=de" -F "translate=false" -F "useCache=false" | python -c "import json,sys; d=json.load(sys.stdin)['data']; print(d['translated_chunks']); print('ci sono state' in d['transcription']['text'].lower())"
```

Erwartung: `[]` und `True`. Gegenprobe ohne `-F "translate=false"`: meist mindestens
ein Eintrag in `translated_chunks` und `False` (vom Modell abhängig, nicht in jedem Lauf).

Über KS: denselben Ordner wie beim Prüffall mit dem Feature-Branch transkribieren.
Im Webhook `phase: completed` muss `data.translated_chunks` als leere Liste stehen und
der Gesamttext die italienischen Passagen auf Italienisch enthalten. Im Secretary-Log
stehen dann Zeilen „Stück N: nicht übersetzt (translate=false)".

## Offen

- PR #33 mergen und `main` in Prod ausrollen. Bis dahin fehlt `translated_chunks` in
  Prod, und Prod übersetzt rein fremdsprachige Stücke weiter.
- Die Template-Transformation des Secretary (`template`) arbeitet weiter mit
  `target_language`. KS schickt im Audio-Request kein Template, deshalb betrifft es KS
  nicht.
