# Analyse: 413 Request Entity Too Large bei /api/transformer/chat

## Symptom (Produktion)

```
POST /api/transformer/chat HTTP/1.1" 400
Fehler bei Chat-Completion-Endpoint
werkzeug.exceptions.RequestEntityTooLarge: 413 Request Entity Too Large:
The data value transmitted exceeds the capacity limit.
```

Kleine Chats funktionieren (HTTP 200), große scheitern reproduzierbar mit 400.

## Ursache (belegt durch Traceback)

Der Traceback endet in:

```
src/api/routes/transformer_routes.py", line 903, in post
    args = chat_parser.parse_args()
...
werkzeug/formparser.py", line 282, in _parse_urlencoded
    raise RequestEntityTooLarge()
```

Der Fehler entsteht also **nicht** beim Upstream-LLM, sondern schon beim Einlesen
der Anfrage im **Werkzeug-Formular-Parser** innerhalb unserer eigenen App.

Hintergrund:

- Der Chat-Endpunkt liest alle Felder als Formulardaten (`location='form'`),
  inklusive des potenziell sehr großen Feldes `messages`.
- Werkzeug begrenzt die im Speicher gehaltene Formulardatenmenge pro Feld über
  `max_form_memory_size`. Seit **Werkzeug 3.1** ist der Default **500 kB**
  (vorher unbegrenzt).
- Die Flask-Config `MAX_FORM_MEMORY_SIZE` (in `src/dashboard/app.py` gesetzt)
  wirkt **erst ab Flask 3.1**. Das Projekt nutzt laut `requirements.txt`
  **Flask 3.0.2** -> die Config wird ignoriert -> es gilt der 500-kB-Default.

Damit ist die bestehende Konfigurationszeile wirkungslos, und jedes
form-kodierte `messages`-Feld über 500 kB führt zu HTTP 413, das unser
Handler als 400 zurückgibt.

Wichtig zur Abgrenzung: Das ist **nicht** das `MAX_CONTENT_LENGTH`-Limit
(100 MB). Dessen 413-Handler erzeugt eine andere, deutsche Meldung
("Request zu groß (HTTP 413). Content-Length: ...").

## Lösungsvarianten

1. **JSON-Body statt Formular (gewählt).** Parser-Felder von `location='form'`
   auf `location='json'` umstellen. Dann wird der Formular-Parser nie aufgerufen;
   es greift nur noch `MAX_CONTENT_LENGTH`. Sauberster Fix an der Wurzel.
   Nachteil: API-Vertragsänderung — Aufrufer muss `application/json` senden.
2. **Formular beibehalten, Limit wirksam machen.** `max_form_memory_size` direkt
   am Request setzen (Flask 3.0.2 ignoriert die Config). Kein Client-Eingriff,
   behält aber den Formular-Parser.
3. **Flask auf >= 3.1 anheben**, damit die vorhandene Config greift.
   Dependency-Änderung mit größerem Testaufwand.

## Entscheidung

Variante 1 (JSON-Body). Der aufrufende "Secretary Service" kann auf JSON
umgestellt werden. `messages` wird sowohl als native JSON-Liste als auch als
JSON-String akzeptiert (Abwärtskompatibilität auf Feldebene).

## Betroffene Dateien

- `src/api/routes/transformer_routes.py`
  - `chat_parser`: alle Felder `location='json'`, `messages` mit Passthrough-Typ.
  - `post()`: `messages` als Liste **oder** JSON-String verarbeiten.
- `docs/reference/api/endpoints/transformer.md`: Beispiele auf JSON umstellen.

## Neuer Aufruf (Client)

```bash
curl -X POST "http://localhost:5001/api/transformer/chat" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hallo"}],"model":"openai/gpt-4","provider":"openrouter"}'
```

## Status

Hypothese durch Traceback und Versionslage belegt. Noch **nicht** in Produktion
verifiziert. Test: identischen großen Chat einmal als Formular (erwartet 413/400)
und einmal als JSON (erwartet 200) senden.
