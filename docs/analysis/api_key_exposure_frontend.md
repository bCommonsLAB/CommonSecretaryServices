# Sicherheitsanalyse: API-Keys im Frontend sichtbar

## Kurzfassung

API-Keys, die über Docker Compose als Umgebungsvariablen gesetzt werden
(`OPENAI_API_KEY`, `VOYAGE_API_KEY`, ...), tauchen im Dashboard-Frontend auf.
Das ist eine **Exposition sensibler Daten**. Keys sollen ausschließlich über
Umgebungsvariablen verwaltet werden und niemals im Frontend erscheinen.

## Beobachtung (vom Anwender gemeldet)

Auf der Seite `/config` erscheinen:
1. Eine Sektion "OpenAI API Key" mit (maskiertem) Key `sk-proj...m7O8A`.
2. Ein YAML-Editor, der die gesamte Konfiguration anzeigt.

## Fundierte Ursachenanalyse

Es existieren **zwei getrennte Lecks**:

### Leck 1 — YAML-Editor zeigt aufgelöste Klartext-Keys (KRITISCH)

`config/config.yaml` enthält nur Platzhalter, z. B.:

```yaml
llm_providers:
  openai:
    api_key: ${OPENAI_API_KEY}
  voyageai:
    api_key: ${VOYAGE_API_KEY}
```

Das ist korrekt. Das Problem entsteht beim **Anzeigen**:

- `src/core/config.py` → `Config.get_all()` → `_read_config()` ruft
  `replace_env_vars(...)` auf.
- `src/core/config_utils.py` → `replace_env_vars()` ersetzt `${OPENAI_API_KEY}`
  durch den **echten** Wert aus `os.environ`.
- `src/dashboard/routes/main_routes.py` → `config_page()` (Route `GET /config`)
  rendert exakt dieses aufgelöste Ergebnis als YAML in den Editor:

```python
config = Config()
config_data = config.get_all()           # <- löst ${...} zu echten Keys auf
config_yaml = yaml.safe_dump(config_data) # <- echte Keys im Klartext
return render_template('config.html', config=config_yaml)
```

Ergebnis: Die in Docker Compose gesetzten Klartext-Keys stehen sichtbar im
Editor. Zusätzlich kann das Speichern (`POST /api/config`, `POST /config/yaml`)
diese aufgelösten Keys in `config.yaml` zurückschreiben.

> Hinweis: Es sind zwei Routen für `GET /config` registriert
> (`main.config_page` und `config.config_page`). Beide rendern `config.html`.
> `main` ist zuerst registriert und gewinnt das Routing. Beide Varianten sind
> jedoch betroffen und müssen bereinigt werden.

### Leck 2 — Frontend-Verwaltung des OpenAI-Keys (maskiert, irreführend)

- `src/dashboard/templates/config.html` enthält die Sektion "OpenAI API Key"
  inkl. JavaScript, das per `GET /config/api-key` den maskierten Key lädt und
  per `POST /config/api-key` setzt.
- `src/dashboard/routes/config_routes.py` → `handle_api_key()` liefert den
  maskierten Key (`sk-proj...m7O8A`, erste 7 + letzte 5 Zeichen) und erlaubt
  das Setzen.
- `src/core/config_keys.py` → `set_openai_api_key()` setzt nur `os.environ`
  zur Laufzeit (nicht persistent). Der UI-Text "wird sicher in der .env Datei
  gespeichert" ist somit **irreführend**.
- `src/dashboard/routes/main_routes.py` → `save_config()` enthält zusätzlich
  Logik, die einen `api_keys.openai_api_key` aus dem YAML übernimmt.

### Querschnitt

- Alle betroffenen Dashboard-Routen sind **nicht authentifiziert**.
- Maskierung (erste 7 + letzte 5 Zeichen) ist kein ausreichender Schutz.

## Betroffene Dateien

- `src/dashboard/routes/main_routes.py` (`config_page`, `save_config`)
- `src/dashboard/routes/config_routes.py` (`config_page`, `handle_api_key`,
  `update_yaml_config`, `test_openai_api_key`)
- `src/dashboard/templates/config.html` (API-Key-Sektion + JS)
- `src/core/config.py` (`get_all` / `_read_config` löst Secrets auf)
- `src/core/config_utils.py` (`replace_env_vars`)
- `src/core/config_keys.py` (`set_*_api_key`)

## Lösungsvarianten

### Variante A — Minimal-invasiv (Anzeige bereinigen)
- YAML-Editor zeigt die **rohe** `config.yaml` (Platzhalter `${...}`) statt der
  aufgelösten Konfiguration.
- API-Key-Sektion und `/config/api-key`-Routen entfernen.
- Aufwand: gering. Risiko: Secret-Felder müssen beim Speichern weiter
  geschützt werden.

### Variante B — Konsequente Trennung (empfohlen)
- Wie A, plus:
- Zentrale Redaktions-/Whitelist-Logik: Secret-Felder werden serverseitig
  **niemals** an das Frontend gegeben und beim Speichern **niemals** in
  `config.yaml` geschrieben (immer Platzhalter erzwingen).
- Doppelte `/config`-Route auflösen (eine kanonische Route).
- `set_*_api_key`-Methoden und zugehörige Save-Logik entfernen.
- Aufwand: mittel. Sauberste fachliche Trennung Secrets vs. Config.

### Variante C — Maximal (Defense-in-Depth)
- Wie B, plus:
- Zentrale `redact_secrets(config)`-Funktion vor jeder Frontend-Ausgabe.
- Config-Anzeige read-only (Editor entfernen) oder Authentifizierung für alle
  Dashboard-Routen.
- Unit-Tests, die sicherstellen, dass keine echten Keys (`sk-...`) je im
  HTTP-Response erscheinen.
- Aufwand: höher. Höchste Sicherheit.

## Empfehlung

Variante B als Kern, ergänzt um den Test-Aspekt aus C (Regressionstest gegen
Key-Exposition). Endgültige Auswahl trifft der Anwender.

## Umgesetzte Lösung (entschieden vom Anwender)

Leitlinie: API-Keys werden **ausschließlich** über Umgebungsvariablen (Docker
Compose / .env) konfiguriert. Sie stehen nicht in `config.yaml` und werden im
Frontend weder angezeigt noch verwaltet.

Durchgeführte Änderungen:

1. `src/core/config_keys.py`: Zentrales Mapping `PROVIDER_ENV_VARS`
   (Provider → ENV-Variable) und Methode `get_api_key_for_provider()`.
   `voyage_api_key`-Property ergänzt. Alle `set_*`-Methoden entfernt
   (Keys können zur Laufzeit nicht mehr aus dem Frontend gesetzt werden).
2. `src/core/llm/config_manager.py`: Lädt Provider-Keys über `ConfigKeys`
   aus ENV, ein `api_key`-Feld in `config.yaml` wird ignoriert.
3. `config/config.yaml`: Alle `api_key`/`voyage_api_key`-Felder entfernt.
4. `src/processors/rag_processor.py`: Voyage-Key nur noch aus `VOYAGE_API_KEY`,
   kein `config.yaml`-Fallback.
5. `src/dashboard/templates/config.html`: "OpenAI API Key"-Sektion + JS
   entfernt; Sicherheitshinweis ergänzt.
6. `src/dashboard/routes/config_routes.py`: `handle_api_key` und
   `test_openai_api_key` entfernt; `config_page` zeigt die ROHE `config.yaml`
   (Platzhalter bleiben); `sanitize_secrets()` entfernt Secret-Felder beim
   Speichern.
7. `src/dashboard/routes/main_routes.py`: unsichere doppelte `/config`-Route
   (mit `Config.get_all()`-Auflösung) entfernt; `/api/config` bereinigt
   (Key-Logik raus, Secret-Filter rein). Nav in `base.html` zeigt auf
   `config.config_page`.
8. `src/dashboard/routes/llm_config_routes.py`: Export schreibt keine
   `api_key`-Zeile mehr.
9. `docker-compose.yml` und `.env.example`: alle Provider-Keys dokumentiert.

### Verifikation (durchgeführt)

- `config.yaml` enthält 0 `api_key`-Felder, YAML valide.
- `ConfigKeys.get_api_key_for_provider()`: openai/mistral/openrouter/voyageai
  aus ENV, `ollama` → Dummy, unbekannt → `None`.
- `LLMConfigManager.get_all_providers()`: alle Provider erhalten ihren Key
  aus der Umgebung.
- `sanitize_secrets()`: entfernt `api_key`/`password`, behält Unkritisches.

### Nachtrag: YAML-Konfigurations-Modul komplett entfernt

Da die `config.yaml` ausschließlich in der Entwicklungsumgebung gepflegt und per
Docker publiziert wird, wurde der Web-Editor für die Konfiguration vollständig
entfernt (er war überflüssig und ein zusätzliches Risiko):

- Gelöscht: `src/dashboard/routes/config_routes.py`,
  `src/dashboard/templates/config.html`.
- Blueprint-Registrierung entfernt in `src/dashboard/app.py` und
  `src/api/__init__.py`.
- Route `POST /api/config` (samt `sanitize_secrets`-Aufruf) in
  `src/dashboard/routes/main_routes.py` entfernt; ungenutzte Imports
  (`yaml`, `request`) bereinigt.
- Nav-Eintrag "Config" in `base.html` entfernt.
- Die separate "LLM Config"-Seite (MongoDB-basiert) bleibt unverändert.

Verifikation: App importiert fehlerfrei, alle Blueprints registrieren; die
Routen `/config`, `/config/*` und `/api/config` existieren nicht mehr
(99 Routen verbleiben).

### Offene Punkte / Empfehlung

- `mongodb.uri: ${MONGODB_URI}` bleibt als Platzhalter in `config.yaml`. Da der
  Editor jetzt die rohe Datei zeigt, wird er nicht aufgelöst – kein Leck.
- Dashboard-Routen sind weiterhin **nicht authentifiziert**. Eine
  Authentifizierung wäre als nächster Schritt sinnvoll (separat zu klären).
- Ein automatischer Regressionstest (kein `sk-...` im HTTP-Response) ist noch
  nicht implementiert.
