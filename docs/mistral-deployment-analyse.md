# Analyse: Mistral-OCR "Paket nicht installiert" nur online (nicht lokal)

Datum: 2026-06-30
Betroffene Dateien:

- `requirements.txt` (Zeile 52)
- `src/core/llm/providers/mistral_provider.py` (Import-Block, `__init__`)

## Symptom

- **Lokal:** Health-Check meldet `ocr_pdf` als "verfügbar" (mistralai 1.9.11 installiert).
- **Online (Deploy):** Health-Check meldet `ocr_pdf` als "nicht verfügbar" mit:
  > Fehler beim Erstellen des Providers 'mistral': mistralai Paket nicht
  > installiert. Installieren Sie es mit: pip install mistralai

## Befund (mit Evidenz)

1. `mistralai` steht seit dem 13.11.2025 in `requirements.txt` und wird im
   Dockerfile via `pip install -r requirements.txt` installiert. Das Paket
   "fehlt" online also nicht wirklich – die Meldung ist **irreführend**.

2. Ursache ist eine **ungepinnte Version**: `mistralai>=1.9.0`.
   - Lokal: verifiziert **mistralai 1.9.11** -> Importe funktionieren.
   - Frischer CI-Build: `pip install mistralai>=1.9.0` zieht die **neueste**
     Version (aktuell **2.5.0**). In mistralai 2.x wurden `TextChunk` und
     `ImageURLChunk` aus `mistralai.models` entfernt (jetzt in
     `mistral_common.protocol.instruct.chunk`).

3. Der Provider importierte **alle Symbole in einem einzigen `try`-Block** und
   fing jeden `ImportError` pauschal ab. Schlägt nur ein Symbol fehl, wird
   `Mistral = None` gesetzt und der Provider meldet fälschlich "Paket nicht
   installiert" – obwohl der Client selbst importierbar wäre und z. B. OCR
   (reiner HTTP-Call, siehe `pdf_processor._process_mistral_ocr`) gar keine
   Chunk-Typen benötigt.

4. **Separat / kein Deployment-Problem:** Die 429-Fehler im Log
   ("Service tier capacity exceeded", code 3700) sind ein Rate-/Kapazitätslimit
   von Mistral selbst und treten auch dort auf, wo das SDK funktioniert.

5. **Zusätzlicher Operations-Hinweis:** Laut Kommentar in
   `.github/workflows/ci-main.yml` zieht Dokploy das neue Image nicht
   automatisch. Sekundäre Fehlerquelle für "altes Image online".

## Lösungsvarianten

- **A – Version pinnen (umgesetzt):** `requirements.txt` auf
  `mistralai==1.9.11`. Deterministisch, schließt zugleich das Supply-Chain-
  Risiko aus (das bösartige `mistralai==2.4.6` vom Mai 2026 würde von `>=`
  potenziell gezogen).
- **B – Import robust machen (umgesetzt):** Client-Import vom optionalen
  Chunk-/Message-Import trennen. Jeder Import in eigenem `try/except`. `__init__`
  fordert nur noch den `Mistral`-Client und liefert im Fehlerfall den echten
  Import-Fehler statt der irreführenden Pauschalmeldung.
- C – Migration auf mistralai 2.x (nicht umgesetzt): größter Aufwand/Risiko.

## Entscheidung

A + B kombiniert.

## Verifikation (durch Anwender auszuführen)

Im laufenden Online-Container nach Redeploy:

```bash
pip show mistralai            # erwartet: 1.9.11
python -c "from mistralai import Mistral; print('client ok')"
```

Anschließend ein echter OCR-Lauf über `/api/pdf` bzw. `/api/transformer`.
Erst wenn dieser fehlerfrei durchläuft, gilt das Problem als bestätigt behoben.
