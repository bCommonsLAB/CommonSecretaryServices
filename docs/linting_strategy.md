# Linting-Strategie für Common Secretary Services

## Allgemeine Richtlinien

Im Common Secretary Services Projekt legen wir großen Wert auf Codequalität und Typensicherheit. Wir verwenden mypy als statisches Typprüfwerkzeug für unseren Python-Code.

## Bekannte Linting-Probleme

### flask_restx Typannotationen

Die Bibliothek flask_restx, die wir für unsere API-Endpoints verwenden, bietet keine vollständigen Typannotationen. Dies führt zu folgenden mypy-Fehlern:

- `Type of "add_argument" is partially unknown` bei RequestParser.add_argument
- `Type of "boolean" is partially unknown` bei inputs.boolean
- `Type of "model" is partially unknown` bei API.model
- `Type of "route/expect/response/doc" is partially unknown` bei Dekoratoren

### Dictionary get()-Methode und Typkonvertierungen

In Prozessor-Modulen führt die Verwendung von dict.get() mit nachfolgenden Typkonvertierungen zu mypy-Fehlern:

- `Type of "get" is partially unknown` bei dict.get()-Aufrufen
- `Argument type is unknown` bei Typkonvertierungen wie str(), int()

### Lösungsansatz

Wir haben folgende Maßnahmen ergriffen, um mit diesen Problemen umzugehen:

1. **pyproject.toml Konfiguration**: In der `pyproject.toml` haben wir spezifische Überschreibungen für die Router- und Prozessor-Module definiert, die es erlauben, bestimmte Fehler zu ignorieren.

2. **Kommentare in den Dateien**: Betroffene Dateien enthalten einen Kommentar am Anfang (`# mypy: disable-error-code="attr-defined,valid-type,misc"`), der auf die bekannten Probleme hinweist und bestimmte Fehlertypen deaktiviert.

3. **README.md im routes-Verzeichnis**: Eine Dokumentation der bekannten Probleme und der gewählten Lösungsansätze.

4. **Angepasstes Linting-Skript**: Das Skript `scripts/run_lint.py` filtert bekannte Probleme aus der mypy-Ausgabe heraus, um sich auf relevante Fehler zu konzentrieren.

## Empfohlene Vorgehensweise bei der Entwicklung

Bei der Arbeit mit API-Routen und Prozessoren:

1. Verwenden Sie das `# type: ignore`-Kommentar für problematische Importe.
2. Bei Dictionary-Zugriffen mit get() können Sie explizite Type-Casts verwenden:
   ```python
   # Beispiel:
   value = cast(Optional[str], dict_obj.get('key'))
   ```
3. Fügen Sie explizite Typannotationen hinzu, wo immer möglich.
4. Verwenden Sie das Linting-Skript (`python scripts/run_lint.py`), um nur relevante Fehler zu sehen.
5. Ignorieren Sie bekannte Probleme, aber beheben Sie alle anderen Linter-Fehler.

## Zukünftige Verbesserungen

Langfristig könnten wir folgende Maßnahmen in Betracht ziehen:

1. Beitragen von Typstubs für problematische Bibliotheken.
2. Erstellen eigener vollständiger Typstubs.
3. Umstellung auf Bibliotheken mit besserer Typunterstützung.
4. Einheitlichere Muster für Dictionary-Zugriffe und -Konvertierungen.

Diese Entscheidungen sollten jedoch im Rahmen einer größeren Refaktorierung getroffen werden und nicht während der laufenden Entwicklung. 