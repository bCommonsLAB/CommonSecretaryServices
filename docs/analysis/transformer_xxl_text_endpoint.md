# Analyse: Endpoint `POST /api/transformer/xxl-text` (Zusammenfassung großer Textdateien)

## Ausgangslage / Problem
Der bestehende Datei-Endpoint `POST /api/transformer/text/file` liest den Dateiinhalt vollständig ein und ruft anschließend `TransformerProcessor.transform(...)` auf. Diese Methode validiert jedoch aktuell harte Grenzen (u. a. **max. 100.000 Zeichen**), wodurch große Dateien (z. B. ~6 Mio. Zeichen / ~7 MB) bereits **vor** dem LLM-Aufruf scheitern. Selbst wenn die Validierung gelockert würde, bleibt das Token-Limit des LLMs der dominante Engpass.

Für eine reine Zusammenfassung (Map-Reduce / "summary-of-summaries") ist daher ein **Chunking-Ansatz** nötig: Text wird in überlappende Teile zerlegt, jeder Teil wird separat zusammengefasst, und am Ende werden die Teil-Zusammenfassungen zu einer finalen Zusammenfassung verdichtet.

## Anforderungen (aus Nutzerwunsch abgeleitet)
- **Input als Datei-Upload** (ähnlich `POST /transformer/text/file`, Form-Data).
- **Chunking nach Zeichenlänge**: Standard \(chunk\_size\_chars = 200_000\), Überlappung \(overlap\_chars = 2_000\) oder \(5_000\).
- **Pro Chunk**: Summary erzeugen.
- **Final**: Summary aus allen Chunk-Summaries erzeugen.
- **Response-Standard**: `status`, `request`, `process` (inkl. `process.llm_info`), `data`, `error`.
- **Typisierung/Dataclasses**: strikte Typ-Annotationen, Validierung in `__post_init__`, `slots=True` wo sinnvoll.

## 3 Lösungsvarianten
### Variante A: Synchroner Endpoint (direkt in Request)
**Idee:** `POST /api/transformer/xxl-text` verarbeitet Datei komplett synchron: chunking → chunk summaries → final summary → Response.

- **Pro:** Sehr einfache API, schnelle Implementierung, kein Job-Management.
- **Contra:** Langes Request-Lifecycle-Risiko (Timeouts, Reverse-Proxy Limits), hohe Laufzeit/Token-Kosten in einem Request.
- **Eignung:** Gut als erster Wurf, solange Dateigrößen/Chunk-Anzahl begrenzt werden.

### Variante B: Asynchroner Job (bestehende Jobs-Infrastruktur)
**Idee:** Datei wird hochgeladen, serverseitig persistiert (oder in Mongo/GridFS), dann Job erstellt; Worker macht chunk summaries und final summary; Progress/Callback möglich.

- **Pro:** Robust gegen Timeouts, progress reporting, wiederaufsetzbar, besser skalierbar.
- **Contra:** Mehr Implementationsaufwand (Speicher, Job-API, Cleanup, Security, Retry-Strategien).
- **Eignung:** Für sehr große Dokumente und produktive Nutzung mit langen Laufzeiten.

### Variante C: Streaming / iteratives Verdichten
**Idee:** Text wird inkrementell "rolling" verdichtet: Summary wird fortlaufend aktualisiert (z. B. sliding window), optional mit Abschnitts-Metadaten.

- **Pro:** Kann Speicher und Anzahl LLM-Calls reduzieren.
- **Contra:** Gefahr von Drift/Verlust wichtiger Details; schwerer zu testen; komplizierter prompt/quality control.
- **Eignung:** Für spezielle Qualitäts-/Kostenprofile, nicht als minimaler Start.

## Entscheidung für die Implementierung (jetzt)
Für einen minimal-invasiven Start implementieren wir **Variante A (synchron)** als neuen Endpoint `POST /api/transformer/xxl-text`, aber mit klaren Sicherheitsgeländern:
- Dynamische Chunk-Größe & Overlap auf Basis des Modell-Kontextfensters (Tokens).
  - Kontextfenster wird in MongoDB unter `llm_models.metadata.context_length` gepflegt.
  - Overlap ist standardmäßig 4% der Chunk-Größe (konfigurierbar via `overlap_ratio`).
- Chunk-Verarbeitung sequenziell oder begrenzt parallel (max. 3 gleichzeitig).
- Chunking als deterministische Utility mit Unit-Tests.
- LLM-Tracking: alle Chunk-Calls + finaler Call werden im `process.llm_info` gesammelt.
- Caching optional (im ersten Wurf: finaler Output).

## Betroffene Dateien (vorläufig)
- `src/api/routes/transformer_routes.py` (neuer Endpoint + Parser)
- `src/processors/transformer_processor.py` (Wrapper-Methode für XXL-Summarization, minimaler Eingriff)
- `src/utils/text_chunking.py` (neu: Chunking-Utility + Dataclasses)
- `src/utils/xxl_text_summarization.py` (neu: reine Orchestrierung, testbar ohne echten Provider)
- `.tests/test_text_chunking.py` / `.tests/test_xxl_text_summarization.py` (neu)


