# Analyse: CI-Version-Branch scheitert mit non-fast-forward

## Beobachtung

Der Workflow `ci-main` erstellt fuer jeden Patch-Bump einen Branch nach dem Muster `chore/bump-version-<version>`. Bei einem erneuten Lauf fuer dieselbe Version kann dieser Branch bereits auf dem Remote existieren. Der einfache Push mit `git push origin "$BRANCH_NAME" --set-upstream` scheitert dann mit `non-fast-forward`.

## Varianten

1. Einfacher Force-Push mit `--force`.
   Das ist kurz, kann aber Remote-Aenderungen ohne Lease-Pruefung ueberschreiben.

2. Remote-Branch vorher loeschen und neu pushen.
   Das ist ebenfalls idempotent, erzeugt aber ein unnoetiges Delete/Recreate-Fenster.

3. Remote-Branch fetchen und mit `--force-with-lease` pushen.
   Das aktualisiert den kurzlebigen Bot-Branch, bricht aber ab, wenn sich der Remote-Branch seit dem Fetch unerwartet veraendert hat.

## Entscheidung

Variante 3 ist die engste Aenderung. Sie macht den CI-Retry fuer denselben Versions-Branch idempotent und vermeidet einen blinden Force-Push. Der Branch ist durch das `chore/bump-version-<version>`-Muster als Bot-Branch eingegrenzt.
