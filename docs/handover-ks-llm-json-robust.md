# Hand-off an KnowledgeScout: LLM-JSON wird repariert oder ist ein Fehler

Stand 08.11.2026. Secretary-Branch `claude/llm-json-robust-0f7668`.
Vertrag: `docs/reference/api/endpoints/transformer.md`, Abschnitt „LLM-JSON: Antwortmodus,
Reparatur, Fehlerstatus“.

## Was war

Library `ID_OnedriveTest`, Vorlage `chatverlauf-de`, Modell `google/gemini-2.5-flash` über
OpenRouter. Bei langen Markdown-Feldern (`entscheidungen_md`, `getan_md`, `befunde_md`,
`verweise_md`) lieferte Gemini vom 05.11. bis 08.11.2026 in etwa der Hälfte der Fälle
ungültiges JSON: gerade Anführungszeichen unmaskiert im Wert („Expecting ',' delimiter:
line 39/40 column 600–1900“), einmal „Invalid \escape“. Der Parser kannte nur Codezäune
entfernen, direkt parsen, Substring plus Bereinigung, noch einmal parsen. Scheiterte das,
schrieb der Secretary die Fehlermeldung als Wert in jedes Feld von `structured_data` und
antwortete mit HTTP 200. KnowledgeScout erkannte das nur an Textmarkern
(`template-run.ts`, `extractionErrorMarkers`). Notbehelf seit 05.11.: Die Vorlage verlangt
typografische Anführungszeichen; das halbierte die Fehler nur. Drei Belege (Arbeitsliste
A2, A33, A70) scheiterten reproduzierbar, zwölf weitere am 05.11. im ersten Versuch.

## Was der Secretary jetzt tut

1. **JSON-Antwortmodus.** `transform_by_template` fragt das Modell mit
   `response_format: {type: json_object}` an, wo der Provider das durchreicht
   (`openrouter`, `openai`, `ollama`; OpenRouter setzt es für Gemini in
   `response_mime_type` um). Vorgabe an. Je Modell in `config.yaml` unter
   `llm_config.json_response_mode.models` abschaltbar, für die Installation mit
   `LLM_JSON_RESPONSE_MODE=off`. Lehnt Provider oder Modell den Modus ab, wiederholt der
   Dienst genau einmal ohne und loggt das; `repair_info.json_mode` sagt, was galt.
2. **Reparaturstufen** in `src/utils/json_validation.py` (`parse_llm_json`):
   direkt → Bereinigung (trailing Kommas, Escapes) → strukturgeführtes Maskieren von
   geraden Anführungszeichen, rohen Zeilenumbrüchen und kaputten Escapes in Werten
   (entscheidet anhand von `:`, `,` + nächstem Schlüssel, `}`/`]`, ob ein
   Anführungszeichen den Wert schließt; eine allgemeine Bibliothek macht aus
   `"Fehler: LLM-JSON (2×)"` sonst ein Phantomfeld) → Bibliothek `json_repair`
   (einfache Anführungszeichen, fehlende Klammern). Jede Stufe, die den Inhalt verändert,
   steht in der Antwort: `data.repaired: true`, `data.repair_info` mit `stage`, `hints`,
   `json_mode`. Ohne Reparatur `data.repaired: false`.
3. **Fehler bleibt Fehler.** Ergibt auch die letzte Stufe kein nicht-leeres Objekt, oder
   endet die Antwort nicht mit `}` (abgeschnitten), kommt HTTP 400, außen
   `status: "error"`, `error.code: "TEMPLATE_ERROR"`,
   `error.details.error_type: "LLMJSONParseError"`, dazu `model`, `json_mode`, `line`,
   `column`, `raw_response_file`. Keine Fehlermeldung mehr als Feldwert. Der Job-Weg
   (`callback_url`) meldet denselben Fehler als `phase=error`.
4. **Rohantworten sammeln.** Mit `LLM_JSON_DEBUG_DIR=<Ordner>` landet jede nicht
   parsebare Antwort vollständig als `<Zeit>_<Vorlage>_<id>.raw.txt` plus `.meta.json`
   (Modell, Fehler, Zeile, Spalte) dort; der Pfad steht in der Fehlermeldung. Vorgabe aus.
   Nur die Modellantwort, kein Prompt, kein Eingabetext, keine Schlüssel.

## Was KnowledgeScout nachziehen kann (nichts muss)

- Der Fehlerfall läuft über den Zweig „HTTP-Status nicht OK“ in
  `src/lib/external-jobs/template-run.ts`, den KS seit dem Hand-off vom 11.10.2026
  (`handover-ks-transformer-fehlerstatus.md`) kennt. Die Marker-Erkennung
  (`extractionErrorMarkers`) greift nicht mehr, kann bleiben oder entfallen.
- Neu lesbar: `data.repaired` und `data.repair_info`. Vorschlag: im Job-Trace als
  Attribut festhalten (`template_response_structured_data`), damit sich sehen lässt, wie
  oft die Reparatur greift. Fürs Artefakt ist das Ergebnis vollwertig.
- `error.details.raw_response_file` zeigt auf den Prod-Container; nützlich nur, wer dort
  liest.

## Abnahme (Peter)

1. Deploy über Dokploy (Image zieht `json-repair==0.64.6` aus `requirements.txt`).
   Optional vorher im Container `LLM_JSON_DEBUG_DIR=/app/logs/llm-json` setzen, um
   verbleibende Fälle einzusammeln.
2. Über die Brücke (`transformation_starten`, Library `ID_OnedriveTest`) die 15 seit dem
   05.11. an LLM-JSON gescheiterten Belege neu transformieren (Arbeitsliste
   `Organisation/Arbeitsliste Sitzungen nachtragen.md`, Vermerk „LLM-JSON“; zuerst die
   drei reproduzierbaren A2, A33, A70, dann A1, A3, A28, A30, A63, A87, A95, A99, A108 und
   die übrigen laut Liste). Ziel: null Fehler; `job_status` zeigt `data.repaired`, wenn
   repariert wurde.
3. Erst danach die Anführungszeichen-Regel aus der Vorlage `chatverlauf-de` wieder
   herausnehmen und eine Stichprobe (fünf Belege) erneut laufen lassen.
4. Falls weiter etwas scheitert: Rohantwort aus `LLM_JSON_DEBUG_DIR` als Fixture nach
   `.tests/fixtures/llm_json/` und einen pytest-Fall in `.tests/test_llm_json_parsing.py`.

## Tests

`.tests/test_llm_json_parsing.py` (35 Fälle): jede Fixture in `.tests/fixtures/llm_json/`
(20-Felder-Antwort mit geraden Anführungszeichen, rohen Zeilenumbrüchen und ungültigem
Escape; „Invalid \escape“; trailing Komma; Prosa um ein Objekt; gültig; nur Prosa;
abgeschnitten), Debug-Ablage, Antwortmodus je Modell/Provider/Umgebung, Fake-Provider
durch `transform_by_template` (response_format geht mit, Wiederholung ohne bei
Ablehnung, `repaired` in der Antwort, Parse-Fehler wird HTTP 400 mit
`error_type: LLMJSONParseError`).
