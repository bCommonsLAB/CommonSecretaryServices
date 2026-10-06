# Transcript API Endpoints

Textschritte **am** Transkript. Hier wird nichts geschrieben — es entstehen nur
Vorschläge, die ein Mensch im Client (KnowledgeScout, `transkript_korrigieren`)
bestätigt oder verwirft.

## POST /api/transcript/korrekturvorschlag

Hält ein Audio-Transkript gegen Begleittexte derselben Veranstaltung (Einladung mit
Sprecherliste, Folien-Transkripte) und schlägt vor:

- **`ersetzungen`** für Hörfehler bei Namen, Zahlen, Orten und Fachbegriffen
- **`sprecher`**: Zuordnung Sprecher-Label → Person

Hintergrund: Das Sprecher-Modell (`/audio/process-diarized`) nimmt keinen Kontext an.
Der volle Kontext (Einladung, Folien) wirkt erst hier, im Textschritt. Modell: Use-Case
`chat_completion`, Temperatur 0. Das Antwortschema steht **ausdrücklich im Prompt**;
der Dienst erzwingt kein `schema_json`, prüft die Antwort aber streng (siehe Regeln).

### Request

**Content-Type**: `application/json`

```json
{
  "transkript": "**Stück 1 Sprecher A:** Guten Morgen, ich bin Frau Mahler …\n**Stück 1 Sprecher B:** …",
  "begleittexte": [
    { "name": "Einladung", "text": "Journalistenschulung … Referentinnen: Dr. Anna Mahlknecht …" },
    { "name": "Folien Vortrag 1", "text": "Folie 1: …\nFolie 3: Anteil 2023: 14 Prozent" }
  ],
  "zielsprache": "de"
}
```

| Feld | Typ | Pflicht | Beschreibung |
|------|-----|---------|--------------|
| `transkript` | String | ja | Audio-Transkript (Markdown), optional mit Sprecher-Präfixen |
| `begleittexte` | Liste `{name, text}` | nein | Einladung, Flyer, Folien-Transkripte. Ohne Begleittexte werden keine Namen zugeordnet |
| `zielsprache` | String | nein (`de`) | Sprache der Begründungen |

### Response (Success)

```json
{
  "status": "success",
  "data": {
    "ersetzungen": [
      { "alt": "Frau Mahler", "neu": "Frau Mahlknecht", "zeile": 1,
        "kontext": "**Stück 1 Sprecher A:** Guten Morgen, ich bin Frau Mahler …",
        "begruendung": "Name laut Einladung", "beleg": "einladung" },
      { "alt": "vierzig Prozent", "neu": "vierzehn Prozent", "zeile": 2,
        "kontext": "…", "begruendung": "Folie 3 nennt 14 Prozent", "beleg": "folie 3" }
    ],
    "sprecher": [
      { "label": "Stück 1 Sprecher A", "name": "Dr. Anna Mahlknecht", "begruendung": "stellt sich vor", "beleg": "selbstvorstellung" },
      { "label": "Stück 1 Sprecher B", "name": "Lea Berger", "begruendung": "Thema passt zum Vortrag", "beleg": "unsicher" }
    ],
    "verworfen": [
      "ersetzung 'Sprecher A': kommt 3x im Transkript vor, erwartet genau 1x"
    ],
    "modell": "gpt-4.1-mini",
    "tokens": 4821,
    "dauer_ms": 3120.4
  }
}
```

### Regeln, die der Dienst durchsetzt

| Regel | Warum |
|-------|-------|
| `alt` kommt im Transkript **genau einmal** vor | Der Client reicht die Liste unverändert an `transkript_korrigieren` weiter; ein mehrdeutiges `alt` wäre dort nicht anwendbar |
| `zeile` wird aus dem Transkript **berechnet** | Dem Modell wird die Zeilennummer nicht geglaubt |
| `name` steht in einem **Begleittext** | Namen nur, wenn belegt; alles andere bleibt Rolle („Frage aus dem Publikum") |
| `label` kommt im Transkript vor | Sonst ist die Zuordnung sinnlos |
| `beleg` ∈ `einladung`, `folie <N>`, `selbstvorstellung`, `unsicher` | Feste Menge; Groß-/Kleinschreibung wird normalisiert, anderes wird verworfen |
| Ein `alt` bzw. ein `label` nur einmal | Zwei Vorschläge für dieselbe Stelle würden sich widersprechen |

Was eine Regel nicht besteht, steht mit Begründung unter `verworfen` — nicht still weg.

### Fehler

| HTTP | `error.code` | Ursache |
|------|--------------|---------|
| 400 | `MISSING_TRANSKRIPT`, `INVALID_BEGLEITTEXTE` | Eingabe |
| 413 | `INPUT_TOO_LARGE` | Transkript + Begleittexte über 600.000 Zeichen |
| 502 | `INVALID_LLM_RESPONSE` | Antwort des Modells ist kein lesbares JSON-Objekt |
| 503 | `NO_MODEL_CONFIGURED` | In der Maske ist `chat_completion` kein Modell zugeordnet |
