# Webhook: Sprecherfelder flach in `data`

Stand 07.10.2026. Auftrag: `docs/handover-webhook-speakers-segments.md`.

## Befund

Der Sprecher-Processor legt `speakers`, `segments` und `dropped_context` bereits in
`result_dict["data"]` (`DiarizedAudioProcessor._to_data`). Der Handler speichert
dieses Dict als `JobResults.structured_data`. Der Abschluss-Webhook und der
SSE-Builder lesen es nicht: beide senden nur `data.transcription.text`.

Der normale Weg (`/audio/process`) hat diese drei Schlüssel nicht. Sie dürfen
nicht als leere Listen ergänzt werden, sonst sieht KnowledgeScout „keine Sprecher“
statt „dieses Ergebnis hat keine Sprecherdaten“.

Zwischen „Stück exportiert“ und dem Ende des Sprecher-Processors gibt es keinen
Log. Bei langer Aufnahme bleibt das bis zum letzten Stück still.

## Varianten

1. **Builder in `sse.py`, Handler importiert ihn.** Eine Funktion, aber `sse.py`
   ist schon lang, und der Handler hinge an der SSE-Schicht.
2. **Kleines Modul `src/api/audio_completed_data.py`, beide rufen es auf.**
   Reine Funktion, einzeln testbar, Webhook und SSE bleiben dünn. Gewählt.
3. **SSE gibt `structured_data` roh zurück.** Der Client müsste zwei Formen
   lesen. Der Vertrag ist die flache Form der Sync-Antwort.

Fortschritt je Stück: der Processor kennt weder Webhook noch Repository.

1. **Callback `on_chunk_done` vom Handler in `process_diarized`.** Der Processor
   loggt selbst; der Handler schreibt Job-Log, Job-Fortschritt und
   `phase=progress`. Gewählt.
2. Nur `logger.info` im Processor. Das Terminal ist nicht mehr still, KnowledgeScout
   sieht den Fortschritt nicht.
3. Processor bekommt das Repository. Vermischt Transkription und Job-Persistenz.

## Vertrag des Builders

`build_audio_completed_data(job_oder_result_dict)`:

- Quelle ist ein `Job` (`results.structured_data`) oder das `to_dict()` der Response.
- Immer `transcription.text`. Liegt ein `data`-Block vor, immer auch `output_text`
  (aus dem Block, sonst derselbe Text).
- Nur wenn der Schlüssel im Block steht: `speakers`, `segments`, `dropped_context`,
  `detected_language`, `duration`, `llm_model`, `chunk_count`, `from_cache`.
- Verschachtelte `transcription.segments` des normalen Wegs werden nicht nach
  oben gezogen. Deren Form ist eine andere (kein Sprecher-Vertrag).
- Fehlt `structured_data` oder `data`: nur `transcription.text`, dazu der
  Log-Satz „Webhook ohne Sprecherdaten: structured_data fehlt“. Der Handler
  schreibt ihn an den Job. SSE schreibt eine Warnung ins Anwendungslog, weil
  ein Status-Lesen den Job-Log sonst bei jedem Poll wiederholen würde.

Fortschritt: nach jedem fertigen Stück Index, Dauer in Sekunden und Zahl der
verschiedenen Labels. Der Prozentwert zählt fertige Stücke (20 bis 90), nicht
die Stücknummer, weil die Stücke parallel fertig werden.
