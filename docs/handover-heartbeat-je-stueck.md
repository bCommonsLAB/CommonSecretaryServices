# Hand-off: Heartbeat je Stück während der Sprecher-Transkription

Stand 07.10.2026, spät. Owner-Entscheidung: Heartbeat im Secretary, nicht
kleinere Stücke und nicht ein längerer Watchdog im KnowledgeScout.
Vorgeschichte: PR #28 (P1/P2), PR #29 (Webhook mit `speakers`, `segments`,
`dropped_context`, Fortschritt je fertigem Stück). Prüffall vom 07.10. abends
ist grün, siehe KS-Plan `docs/plans/von-menschen-gepruefte-veranstaltung.plan.md`,
Abschnitt „Stand", Absatz „Prüffall 07.10.2026 abends".

## Befund

Der KnowledgeScout-Watchdog setzt einen Job auf `failed`, wenn 10 Minuten
lang kein Callback kommt (`src/app/api/external/jobs/[jobId]/start/route.ts`,
fest `600_000` ms; jeder Callback an `[jobId]/route.ts` ruft `bumpWatchdog`).
Der Secretary meldet beim Sprecher-Weg (`DiarizedAudioProcessor`,
`src/processors/diarized_audio_processor.py`) zwischen „Sprecher-Transkription
gestartet" und „Stück n/m transkribiert" nichts. Ein 20-Minuten-Stück
(`MAX_CHUNK_MS` in `src/utils/pause_chunking.py`) darf bei OpenAI bis
`CHUNK_TIMEOUT_SECONDS = 900` (15 Minuten) dauern. Die Lücke zwischen 10 und
15 Minuten gibt es also planmäßig, und sie ist zweimal zugeschlagen:

- 07.10. abends, erster Lauf (KS-Job eb139571, Teil 1 Einführung, 20:23 min):
  Stück 2/2 (23 s) nach 12 s fertig, Stück 1/2 (20 min) nach 10 Minuten noch
  nicht zurück → KS `failed`, Secretary-Thread lief weiter und kam nie zurück
  (Rechner im Standby).
- Zweiter Lauf (KS-Job a1589a7e): Stück 1/2 nach 8,5 Minuten fertig, knapp
  unter der Grenze. Mit drei parallelen Stücken (`PARALLEL_CHUNKS = 3`) bei
  48 Minuten Audio lag der Lauf vom 06.10. bei 7:45; die Dauer schwankt also
  stark mit der Tageslast bei OpenAI.

## Auftrag

1. **Heartbeat je laufendem Stück** in `_transcribe_chunks`: Solange ein Stück
   bei `provider.transcribe_diarized` liegt, alle **120 Sekunden** ein
   Fortschritts-Callback. Vorschlag: neben `on_chunk_done` ein zweiter
   optionaler Callback `on_chunk_alive(index, total, elapsed_s)`; in `one()`
   eine `asyncio`-Task, die bis zum Ende des `to_thread`-Aufrufs alle 120 s
   den Callback ruft und danach sauber abgebrochen wird (`try/finally`,
   `task.cancel()`). Kein Thread-Timer, kein globaler Zustand.
2. **Durchreichen im Handler** (`src/core/processing/handlers/audio_handler.py`,
   um Zeile 180): derselbe Weg wie beim fertigen Stück, also
   `repo.update_job_status(... step="transcribing" ...)` plus
   `_post_progress("transcribing", percent, message)`. Prozent bleibt der
   zuletzt gemeldete Wert (kein erfundener Fortschritt); Meldung
   `Stück n/m läuft seit X min` (X ganzzahlig). Log-Zeile auf `info`.
3. **Kein stiller Fallback:** Fehler im Heartbeat-Callback werden wie beim
   fertigen Stück als `warning` geloggt und brechen die Transkription nicht
   ab. Fehlt `callback_url` (Sync-Weg), gibt es keinen Heartbeat und keinen
   Log-Lärm darüber.
4. **Timeout-Verhältnis dokumentieren:** In `diarized_audio_processor.py` am
   `CHUNK_TIMEOUT_SECONDS` ein Kommentar, dass der Client-Watchdog (KS) 600 s
   hält und der Heartbeat deshalb deutlich darunter liegen muss (120 s).
   Intervall als Konstante `CHUNK_HEARTBEAT_SECONDS = 120.0`.
5. **Doku:** `docs/_secretary-service-docu/audio.md` im KS-Repo (Abschnitt
   „Webhook Payload (Progress)" beim Sprecher-Weg) und das Pendant unter
   `docs/` in diesem Repo: Heartbeat-Meldung mit Beispiel.

Nicht in diesem Paket: Stückgröße (`MAX_CHUNK_MS`), Parallelität, der
normale Weg `audio/process` (dort sind die Stücke 5 Minuten, kein Problem),
Namensraum-Umzug `realtime` → `audio`.

## Tests

- `tests/test_diarization.py` erweitern: Provider-Mock, dessen
  `transcribe_diarized` z. B. 0,5 s schläft; `CHUNK_HEARTBEAT_SECONDS` im Test
  per Monkeypatch auf 0,1 s → mindestens zwei Heartbeat-Aufrufe mit
  steigendem `elapsed_s`, danach genau ein `on_chunk_done`; nach dem Ende
  keine weiteren Aufrufe (Task abgebrochen). Ein werfender Heartbeat-Callback
  bricht die Transkription nicht ab.
- Handler-Test: der an `requests.post` übergebene Progress-Payload trägt
  `phase=progress`, `data.progress` unverändert, `message` mit „läuft seit".
- `pytest` grün (`pytest.ini`, `testpaths = .tests`); mypy/pyright ohne neue
  Befunde (vorhandene Altbefunde im Audio-Handler sind bekannt).

## Prüffall

KnowledgeScout lokal auf Port 3001 aus dem Worktree mit PR #356 (oder
`master` nach dem Merge), Secretary auf `127.0.0.1:5001`, Use-Case
`diarized_transcription` zugeordnet. Library „Dachverband für Soziales",
Ordner `events/Journalisten Schulung`, Datei „Journalistenschulung Armut-Teil
1 - Einführung.m4a" (20:23 min, ~0,13 USD). Soll: Im KS-Job-Trace erscheinen
während Stück 1 alle zwei Minuten `progress`-Events „Stück 1/2 läuft seit
2 min", „… 4 min", … ; der Job bleibt `running`, auch wenn das Stück länger
als 10 Minuten dauert, und endet mit `speakers` im Frontmatter.

**Vorsicht beim lokalen KS:** Die Worktree-`.env` zeigt auf die Prod-DB und
teilt den Worker-Pool (`JOBS_WORKER_POOL_ID`) mit der Hauptinstanz. Vor dem
Prüffall einen eigenen `JOBS_WORKER_POOL_ID` in der Worktree-`.env` setzen,
sonst zieht die Worktree-Instanz Jobs anderer Sessions (Befund 07.10.
abends: 32 Klimamaßnahmen-Jobs in den Watchdog-Timeout gelaufen).

## Empfehlung

Sonnet mit mittlerem Thinking, neuer Agent, unter 1 USD. Zwei Dateien plus
Tests plus Doku.

## Start-Prompt (kopierbar)

```
Lies docs/handover-heartbeat-je-stueck.md und arbeite den Auftrag auf einem
neuen Branch von main ab (claude/heartbeat-je-stueck). In
_transcribe_chunks alle 120 s ein on_chunk_alive-Callback je laufendem Stück
(asyncio-Task, sauber abgebrochen), im Audio-Handler als phase=progress mit
"Stück n/m läuft seit X min" und unverändertem Prozentwert gepostet; Fehler
im Callback nur als warning. Konstante CHUNK_HEARTBEAT_SECONDS = 120.0 mit
Kommentar zum 600-s-Watchdog des Clients. Tests in tests/test_diarization.py
(Monkeypatch auf 0,1 s) und für den Handler-Payload, pytest grün. Doku in
docs/ nachziehen. Commit-Messages auf Deutsch, PR gegen main, am Ende
Hand-off-Block mit Prüffall-Anleitung.
```
