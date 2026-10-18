# MongoDB mit Anmeldung (mitgelieferte docker-compose.yml)

Seit Arbeitspaket AP-07 (`docs/sicherheitsplan-umsetzung.md`) startet die mitgelieferte `docker-compose.yml` die MongoDB so:

- ohne Port auf dem Host: nur der Secretary-Dienst im selben Compose-Netz erreicht sie,
- mit Anmeldung (`mongod --auth`),
- nur, wenn `MONGO_ROOT_USER` und `MONGO_ROOT_PASSWORD` in der `.env` stehen. Sonst bricht `docker compose` mit einer Meldung ab.

Der Secretary-Dienst bekommt die Verbindungsadresse automatisch: `mongodb://<MONGO_ROOT_USER>:<MONGO_ROOT_PASSWORD>@mongodb:27017/<MONGO_DB_NAME>?authSource=admin`. `MONGO_DB_NAME` ist standardmäßig `commonsec`.

Diese Anleitung betrifft nur Installationen, die die MongoDB aus der mitgelieferten Compose-Datei nutzen. Wer eine externe MongoDB nutzt, zum Beispiel einen eigenen Datenbankdienst oder Atlas, setzt `MONGODB_URI` wie bisher und braucht den `mongodb`-Dienst nicht.

## Werte in die .env

```bash
MONGO_ROOT_USER=secretary
MONGO_ROOT_PASSWORD=<openssl rand -hex 24>
# MONGO_DB_NAME=commonsec
```

Das Passwort darf nur Buchstaben und Ziffern enthalten, weil es in der Verbindungsadresse steht. `openssl rand -hex 24` erfüllt das.

## Neue Installation

```bash
docker compose up -d
docker compose ps        # beide Dienste "healthy"
```

Beim ersten Start legt MongoDB den Admin-Benutzer aus der `.env` an.

## Bestehende Installation mit Daten

Die Variablen `MONGO_INITDB_*` wirken nur auf ein leeres Datenverzeichnis. Bei einem vorhandenen Volume `mongo_data` muss der Admin-Benutzer einmal von Hand angelegt werden.

1. **Sicherung**, solange noch die alte Compose-Datei läuft:
   ```bash
   docker compose exec -T mongodb mongodump --archive > mongo-backup-$(date +%F).archive
   ```
2. **Werte eintragen:** `MONGO_ROOT_USER` und `MONGO_ROOT_PASSWORD` in die `.env` schreiben (siehe oben).
3. **Neue Compose-Datei holen** (`git pull`) und nur die Datenbank starten:
   ```bash
   docker compose up -d mongodb
   ```
   MongoDB läuft jetzt mit `--auth`. Weil noch kein Benutzer existiert, erlaubt sie das Anlegen des ersten Benutzers von innerhalb des Containers.
4. **Admin-Benutzer anlegen.** Die Werte kommen aus der Umgebung des Containers, nichts muss abgetippt werden:
   ```bash
   docker compose exec mongodb mongosh admin --quiet --eval \
     'db.createUser({user: process.env.MONGO_INITDB_ROOT_USERNAME, pwd: process.env.MONGO_INITDB_ROOT_PASSWORD, roles: ["root"]})'
   ```
   Meldet der Befehl, dass eine Anmeldung nötig ist, gibt es schon einen Benutzer. Dann dessen Zugangsdaten in die `.env` eintragen.
5. **Datenbanknamen prüfen.** Die alte Compose-Datei setzte eine Verbindungsadresse ohne Datenbanknamen. Wo bestehende Daten liegen, zeigt:
   ```bash
   docker compose exec mongodb sh -c 'mongosh admin --quiet -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --eval "db.adminCommand({listDatabases: 1}).databases.map(d => d.name)"'
   ```
   Liegen die Daten nicht in `commonsec`, `MONGO_DB_NAME` in der `.env` entsprechend setzen.
6. **Alles starten und prüfen:**
   ```bash
   docker compose up -d
   docker compose logs secretary-services | grep -i "MongoDB-Verbindung"   # "erfolgreich hergestellt"
   ss -ltn | grep 27017 || echo "Port 27017 ist auf dem Host nicht offen"
   ```

## Wiederherstellen aus der Sicherung

```bash
docker compose exec -T mongodb sh -c 'mongorestore --archive -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin' < mongo-backup-<datum>.archive
```

## Fehlerbilder

| Symptom | Ursache |
|---|---|
| `required variable MONGO_ROOT_USER is missing a value` | Die Werte fehlen in der `.env` |
| Secretary-Log: „Authentication failed“ | Benutzer existiert nicht (Schritt 4) oder Passwort weicht ab |
| Secretary-Log: „enthält keinen Datenbanknamen“ | Eigene `MONGODB_URI` ohne Datenbanknamen gesetzt |
| `mongodb` bleibt „unhealthy“ | Container-Log prüfen (`docker compose logs mongodb`), meist Rechte am Volume |
