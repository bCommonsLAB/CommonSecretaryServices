# Prozessoren

Dieses Verzeichnis enthält alle Prozessor-Klassen für den Service, aufgeteilt nach Medientyp.

## Bekannte Linter-Probleme

Die Prozessor-Dateien enthalten bekannte Linter-Fehler bei der Verwendung von Dictionary-Zugriffen mit `.get()` und nachfolgenden Typkonvertierungen. Diese Fehler beziehen sich auf fehlende Typinformationen und können ignoriert werden, da sie die Funktionalität nicht beeinträchtigen.

Folgende Fehlertypen sind bekannt und akzeptiert:

1. `Type of "get" is partially unknown` - Die `.get()`-Methode hat unvollständige Typinformationen
2. `Argument type is unknown` - Bei Typkonversionen wie `str()` oder `int()` kann der Typ nicht korrekt ermittelt werden

Um diese Probleme zu beheben, müsste entweder:
1. Explizite Type-Casts mit `cast()` für jeden `.get()`-Aufruf verwendet werden
2. Die Linter-Konfiguration angepasst werden, um diese spezifischen Fehler zu ignorieren
3. Eine andere Methode für den Dictionary-Zugriff implementiert werden

Aktuell verwenden wir eine Kombination aus Option 1 und 2:
- Wichtige Typkonversionen werden mit `cast()` explizit gekennzeichnet
- Für bekannte Linter-Fehler wird die Mypy-Konfiguration angepasst
- Am Dateianfang wird `# mypy: disable-error-code="attr-defined,valid-type,misc"` verwendet

Weitere Informationen finden Sie in der [Linting-Strategie](../../docs/linting_strategy.md). 