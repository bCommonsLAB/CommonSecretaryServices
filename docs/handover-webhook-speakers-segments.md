# Hand-off: Audio-Webhook um `speakers`, `segments`, `dropped_context` ergänzen

Stand 07.10.2026. Vorgeschichte: P1 (`POST /audio/process-diarized`) und P2
(`POST /transcript/korrekturvorschlag`) sind mit PR #28 auf `main`. Der Branch
`claude/webhook-speakers-segments` ist angelegt und steht noch auf `main`.
Auftraggeber: KnowledgeScout, Plan „Von Menschen geprüfte Veranstaltung"
(`docs/plans/von-menschen-gepruefte-veranstaltung.plan.md` im KS-Repo), dort
„Lücke 2" aus dem Prüffall vom 06.10.2026.

## Befund

Im Job-Modus (mit `callback_url`) bekommt der Client nur den Text. Der
Sprecher-Weg liefert aber Labels je Stück, die KnowledgeScout flach als
`speakers` ins Frontmatter des Transkripts schreibt (Welle C2, P3a). Ohne die
Liste kann der Korrektur-Schritt P3b die Labels nicht auf Namen abbilden.

Was heute passiert:

- `src/core/processing/handlers/audio_handler.py`, nach „Finaler Webhook (analog
  PDF)": `payload_final["data"]` ist nur `{"transcription": {"text": transcript_text}}`.
  Das ist der Webhook, den KnowledgeScout wirklich empfängt.
- `src/api/sse.py`, `_build_completed_data_audio`: baut für SSE und Status-Abfrage
  ebenfalls nur `{"transcription": {"text": markdown_content}}`.
- Das vollständige Ergebnis liegt bereits am Job: der Handler speichert
  `JobResults(structured_data=result_dict)`, und `result_dict["data"]` ist die
  Antwort von `DiarizedAudioProcessor._to_data` (`src/processors/diarized_audio_processor.py`):
  `output_text`, `original_text`, `speakers`, `segments`, `detected_language`,
  `duration`, `llm_model`, `chunk_count`, `dropped_context`, `transcription`,
  `process_id`, `from_cache`. Beim normalen Weg (`audio/process`) fehlen
  `speakers`, `segments`, `dropped_context` schlicht, der Rest ist gleich.

Nebenbefund aus dem Prüffall: Zwischen „Stück exportiert" und dem Ende loggt
der Sprecher-Processor nichts; bei 48 Minuten Audio sind das bis zu 15 Minuten
Stille im Log. Ein Fortschritts-Eintrag je abgeschlossenem Stück (Webhook
`phase=progress` plus `repo.add_log_entry`) reicht.

## Auftrag

1. **Eine gemeinsame Builder-Funktion** für den Audio-`data`-Block, genutzt von
   beiden Stellen (`audio_handler.py` Webhook und `sse.py` SSE/Status). Vorschlag:
   `build_audio_completed_data(job_or_result_dict)` in `src/api/sse.py` oder
   einem kleinen Modul daneben; der Handler hat `result_dict` direkt, SSE hat
   `job.results.structured_data`.
2. **Inhalt des `data`-Blocks** (flach, wie die Sync-Antwort von `process-diarized`):
   - immer: `transcription: {"text": …}` (bleibt, Rückwärtskompatibilität) und
     `output_text`
   - wenn vorhanden: `speakers` (Liste der Labels in Reihenfolge des ersten
     Auftretens), `segments` (`speaker`, `start`, `end`, `text`), `dropped_context`
     (Liste von Strings), `detected_language`, `duration`, `llm_model`,
     `chunk_count`, `from_cache`
   - KnowledgeScout liest `data.segments` oder `data.transcription.segments`,
     `data.speakers`, `data.output_text`; siehe KS-Repo
     `src/lib/secretary/extract-audio-text.ts` und
     `src/lib/external-jobs/audio-speakers.ts`. Die flachen Schlüssel sind der
     Vertrag, nicht die Verschachtelung.
3. **Kein stiller Default:** Fehlt `structured_data` oder `data` darin, Text wie
   bisher senden und einen Log-Eintrag am Job schreiben („Webhook ohne
   Sprecherdaten: structured_data fehlt"), nicht leere Listen erfinden.
4. **Fortschritt je Stück** im Sprecher-Processor (Nebenbefund), ein Eintrag je
   abgeschlossenem Stück mit Index, Dauer und Sprecherzahl.
5. **Doku nachziehen:** `docs/_secretary-service-docu/audio.md` im KS-Repo
   (Abschnitt „Webhook Payload (Async Completion)" und der Satz unter
   `process-diarized` „der Webhook trägt den Text unter `data.transcription.text`")
   sowie das Pendant in diesem Repo unter `docs/`.

## Tests

- `src/tests/test_sse.py` erweitern: Job mit `structured_data` aus einem
  diarisierten Ergebnis → `data.speakers`, `data.segments`, `data.dropped_context`
  im Builder-Ergebnis; Job ohne `structured_data` → nur `transcription.text`.
- Handler-Test: der an `requests.post` übergebene `payload_final["data"]`
  enthält dieselben Felder (Mock auf `requests.post`, Muster in
  `tests/test_diarization.py` und `src/tests/test_sse.py`).
- `pytest` (Konfiguration `pytest.ini`, `testpaths = .tests`) muss grün bleiben;
  `mypy`/`pyright` laut `mypy.ini`/`pyrightconfig.json` ohne neue Befunde.

## Prüffall

KnowledgeScout lokal (PR #356 im KS-Repo enthält die P3a-Felder im
Pipeline-Sheet), Secretary auf `127.0.0.1:5001`, Use-Case
`diarized_transcription` zugeordnet (Seed-Skript, siehe KS-Memory „Lokaler
Secretary: Use-Case zuordnen"). Library „Dachverband für Soziales",
Ordner `events/Journalisten Schulung`, Datei „Journalistenschulung Armut-Teil 4 -
Diskussion.m4a" (48 min, ~0,30 USD im Sprecher-Modus). Soll: Nach dem Lauf
steht im Transkript-Frontmatter `speakers` mit den Labels je Stück, und im
KS-Job-Trace liegt `dropped_context` sichtbar. Kleinere Kosten: Teil 1
(Einführung, 19 MB) nehmen.

## Abgrenzung

- Nicht in diesem Paket: Namensraum-Umzug `realtime` → `audio`, Stimmproben,
  Zuordnung Label → Name (das macht P3b in KnowledgeScout mit dem Menschen).
- Secretary erzwingt `schema_json` nicht; davon ist hier nichts betroffen.

## Empfehlung

Modell: Sonnet mit mittlerem Thinking, der Eingriff ist klar umrissen (zwei
Builder-Stellen, ein Test, Doku). Neuer Agent. Kosten unter 1 USD.

## Start-Prompt (kopierbar)

```
Lies docs/handover-webhook-speakers-segments.md und arbeite den Auftrag auf dem
Branch claude/webhook-speakers-segments ab. Beide Stellen (audio_handler.py
Webhook und sse.py SSE-Builder) nutzen danach eine gemeinsame Funktion, die
speakers, segments und dropped_context aus structured_data flach in data legt;
fehlt structured_data, Text wie bisher plus Log-Eintrag, kein stilles Erfinden.
Tests in src/tests/test_sse.py und für den Handler-Webhook, pytest grün. Doku in
docs/ nachziehen. Commit-Messages auf Deutsch, PR gegen main, am Ende
Hand-off-Block mit Prüffall-Anleitung für den Lauf gegen KnowledgeScout.
```
