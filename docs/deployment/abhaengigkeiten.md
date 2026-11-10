# Abhängigkeiten und Basisimage aktualisieren

Seit Arbeitspaket AP-06 des Sicherheitsplans gilt:

- `requirements.txt` nennt nur die **direkten** Abhängigkeiten, mit Untergrenzen oder festen Versionen.
- `requirements.lock` ist daraus erzeugt. Dort steht jedes Paket, auch jedes mittelbar benötigte, mit fester
  Version und Prüfsummen. **Installiert wird aus dem Lockfile**, im Image und lokal.
- Das `Dockerfile` pinnt das Basisimage `python:3.12-slim` per Digest und installiert mit `--require-hashes`.
  Ein Paket, dessen Datei nicht zur Prüfsumme passt, bricht den Build ab.
- Es gibt kein `pip install --upgrade` mehr im Build. Auch yt-dlp wird nur über die beiden Dateien angehoben.

Zwei Builds desselben Commits ergeben damit dieselben Python-Pakete. Vorher zog jeder Build die jeweils neuesten
Versionen aller nicht gepinnten Pakete.

## Lokal installieren

```bash
pip install --require-hashes -r requirements.lock
# Windows zusätzlich:
pip install python-magic-bin
```

## Ein Paket anheben oder hinzufügen

Werkzeug: [uv](https://docs.astral.sh/uv/). Befehle aus dem Projektverzeichnis.

1. Version in `requirements.txt` ändern oder Paket ergänzen.
2. Lockfile neu erzeugen:

   ```bash
   uv pip compile requirements.txt --universal --python-version 3.12 --generate-hashes --no-header -o requirements.lock
   ```

   Ohne Änderung an `requirements.txt` hebt derselbe Befehl mit `--upgrade` alle Pakete auf den neuesten
   erlaubten Stand, mit `--upgrade-package <name>` nur eines.
3. Auf bekannte Schwachstellen prüfen. Erwartet wird „No known vulnerabilities found“:

   ```bash
   pip-audit -r requirements.lock --require-hashes --disable-pip
   ```

4. Tests laufen lassen: `pytest .tests src/tests -q`.
5. `requirements.txt` und `requirements.lock` gemeinsam committen. `.tests/test_dependency_lock.py` schlägt fehl,
   wenn eine direkte Abhängigkeit im Lockfile fehlt oder nicht zur Angabe in `requirements.txt` passt.

## yt-dlp anheben

YouTube ändert seine Schnittstellen häufig, yt-dlp muss deshalb öfter nachgezogen werden als andere Pakete.
Die Version in `requirements.txt` (`yt-dlp[default]==…`) ändern und die Schritte 2 bis 5 ausführen. Die
Untergrenze prüft `.tests/test_ytdlp_version.py`.

## Basisimage anheben

Der Digest im `Dockerfile` friert das Basisimage ein. Sicherheitsupdates der Debian-Pakete holt
`apt-get upgrade` bei jedem Build trotzdem. Das Basisimage selbst (neue Python-Patchversion) so anheben:

```bash
docker buildx imagetools inspect python:3.12-slim
```

Den Wert hinter `Digest:` in der `FROM`-Zeile eintragen, das Datum im Kommentar darüber anpassen, Image bauen
und einmal starten.

## Rhythmus

Einmal im Monat `pip-audit` gegen das Lockfile laufen lassen und das Basisimage anheben, außerdem sofort bei
einer Sicherheitsmeldung zu einem verwendeten Paket. AP-15 des Sicherheitsplans verlegt die Prüfung in die CI.
