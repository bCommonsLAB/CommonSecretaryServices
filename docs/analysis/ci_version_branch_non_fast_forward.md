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

## Folgefehler

Nach dieser Aenderung lief `Push version and tag` erfolgreich durch. Der naechste Fehler entstand im Schritt `peter-evans/create-pull-request@v5`. Die Annotation meldete nur `git failed with exit code 128` waehrend `Checking the base repository state`.

Der Workflow hatte zu diesem Zeitpunkt den Versions-Branch bereits selbst erstellt, committed und gepusht. Die `create-pull-request` Action fuehrt danach erneut eigene Git-Branch-Logik aus. Das ist unnoetig und fehleranfaellig.

Die PR-Erstellung wird deshalb direkt ueber `gh pr list` und `gh pr create` erledigt. Der Schritt ist idempotent: Wenn ein offener PR fuer denselben Head-Branch existiert, wird dessen Nummer wiederverwendet.
