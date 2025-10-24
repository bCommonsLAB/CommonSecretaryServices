---
status: draft
last_verified: 2025-10-18
---

## PDF-Workflow: Soll, Testmatrix, Prüfregeln

Ziel: Den dreistufigen Workflow Extract → Transform/Frontmatter → Ingest eindeutig, idempotent und für Anwender nachvollziehbar machen. Logs dienen der Verifikation; nach erfolgreicher Absicherung werden sie auf das Wesentliche reduziert.

### Sollbild
- extract_pdf: PDF → Markdown (Shadow‑Twin). Skip, wenn Twin vollständig existiert.
- transform_template: Metadaten/Frontmatter generieren. Skip, wenn Frontmatter vollständig.
- ingest_rag: Kapitel normalisieren, chunken, Pinecone upsert; Doc‑Meta 1× pro Twin.
- Einheitliches Event-Muster je Schritt: `step_running` → `gate_[plan|skip]` → `step_completed`.
- Keine Duplikat‑Events im finalen Modus.

### Abweichungen im Praxis-Log (Stichpunkte)
- Transform meldet `transform_gate_skip: frontmatter_complete`, parallel aber `template step_completed` und internen Callback `template_completed` mit Payload.
- Store meldet `shadow_twin_exists`, führt aber `store_shadow_twin` inkl. `stored_local` aus (später `savedItemsCount=0`). Semantik wirkt uneinheitlich (schein‑write vs. noop‑write).
- Ingest sendet redundante Status (`ingest_start` dup, uneinheitliche Decision‑Flags und Zählwerte `total=6` vs. `7` Vektoren).
- Spans zeigen 0s, während Events Sekunden anzeigen → Messstart/-ende uneinheitlich.
- `dup 1/2`‑Events vermindern Lesbarkeit.

### Akzeptanzkriterien (Messkonzept)
- Gate‑Eindeutigkeit: Pro Schritt genau ein Gate‑Event mit Entscheidung (plan|skip) und Begründung.
- Idempotenz: Bei „exists/complete“ keinerlei Nebenwirkung (kein Store, kein Template‑Callback‑Body), nur `gate_skip` + `step_completed` ohne Payload.
- Zählkonsistenz: Pinecone‑Metriken konsistent (doc_meta=1, `chunks=N`, `vectors=N+X`) und unverändert zwischen Zwischen‑ und Abschluss‑Events.
- Zeitmessung: Schritt‑Spans weichen höchstens ±100ms von erster/letzter Event‑Zeit des Schritts ab.
- Keine `dup`‑Events im Default‑Modus.

### Testszenarien (Matrix)
1. Neuaufbau (kein Twin): Erwartet extract do, transform do, ingest do.
2. Update „Twin+Frontmatter vollständig“: extract skip, transform skip, ingest do (Doc‑Meta nur upsert/update, keine Duplikate).
3. Update „Twin vorhanden, Frontmatter unvollständig“: extract skip, transform do, ingest do.
4. Partial bis Schritt 1: nur extract do, kein transform/ingest.
5. Partial bis Schritt 2: extract do/skip, transform do, kein ingest.
6. Force‑Refresh: alle Schritte do; Idempotenz‑Bypass dokumentiert.

### Durchführung (Rahmen)
- Testdaten: `_Niedrist_2020_...pdf` sowie eine kleine 1–2‑seitige PDF.
- Vorbedingungen: Shadow‑Twin/Frontmatter gezielt anlegen/manipulieren (vollständig/unvollständig). Pinecone‑Index für Neuaufbau‑Runs bereinigen.
- Auslösung: Secretary‑Service HTTP‑Calls (Port 3000) mit `useCache` und optionalen Policies (extract/metadata/ingest = do/skip) oder über Job‑Parameter.
- Artefakte: Roh‑Logs (JSON/JSONL) pro Run, Pinecone‑Upsert‑Metriken, Shadow‑Twin‑Dateien (Vorher/Nachher‑Diff).

### Auswertung
- Parser/Checker (Testscripts):
  - Extrahiert Schrittblöcke, prüft Gate‑Kohärenz, Idempotenz, Duplikate, Metrik‑Konsistenz, Spans vs. Eventzeiten.
  - Liefert pro Run eine kompakte Checkliste (PASS/FAIL) und Diff der Abweichungen.
  - Bei FAIL: gezielte Log‑Zeilen verlinken; Twin/Pinecone gegenprüfen.

### Maßnahmen bei Abweichungen
- Transform‑Skip: kein `template_completed`‑Callback mit Body; nur `transform_gate_skip` + `step_completed` ohne Payload.
- Store bei `exists`: nur `stored_path` referenzieren; kein `stored_local`/`savedItemId`.
- Ingest‑Events vereinheitlichen: genau eine `ingest_start`, eindeutige Decision‑Flag, konsistente Zählwerte bis Abschluss.
- Spans: explizite Start/Stop‑Marken je Schritt.
- Duplikate: dedupe über Correlation‑Key (step+phase+timestamp) oder am Emittenten entfernen.

### Log‑Reduktion (nach Freigabe)
- Debug‑Pfad: detaillierte Events.
- Default‑Pfad: nur Gate‑ und Abschluss‑Events plus Kernmetriken.
- Schalter `verbose` pro Job.


