# Anmeldung für API und Dashboard

Diese Anleitung gilt für jede Installation von Common Secretary Services. Die Anwendung schützt sich selbst. Am Proxy, in Traefik oder in Dokploy ist dafür nichts einzurichten. Hintergrund: Arbeitspakete AP-01 und AP-02 in `docs/sicherheitsplan-umsetzung.md`.

## Was geschützt ist

| Bereich | Schutz | Ohne Konfiguration |
|---|---|---|
| Verarbeitungs-API (`/api/...`) | Service-Token `SECRETARY_SERVICE_API_KEY` | Server startet nicht |
| `/api/health/live` | frei (Liveness-Probe) | frei |
| `/api/health/...` (übrige) | Token, im Browser auch Dashboard-Anmeldung | 503 |
| Swagger (`/api/doc`, `/api/swagger.json`) | Token, Dashboard-Anmeldung oder `SWAGGER_IP_WHITELIST` | 503 |
| Dashboard (`/`, `/logs`, `/llm-config`, `/health`, `/test-procedures`, `/docs`) | Dashboard-Anmeldung | gesperrt (503 mit Hinweisseite) |

Eine Dashboard-Anmeldung öffnet nie die Verarbeitungs-API. Programme wie KnowledgeScout nutzen weiterhin nur den Service-Token.

## Schritt 1: Pflichtwerte je Installation

In die `.env` der Installation:

```bash
SECRETARY_SERVICE_API_KEY=<openssl rand -hex 32>
FLASK_SECRET_KEY=<openssl rand -hex 32>
```

Jede Installation bekommt eigene Werte. Ohne `SECRETARY_SERVICE_API_KEY` bricht `python -m src.main` mit einer Meldung ab.

## Schritt 2: Anmeldeart wählen

### Nextcloud (empfohlen)

Einmalig in der Nextcloud (Administrator):

1. App **„OIDC Identity Provider“** (App-ID `oidc`) aus dem App Store installieren. Nicht `user_oidc`, die macht Nextcloud zum Client eines anderen Anbieters.
2. Gruppe `secretary-admins` anlegen und die berechtigten Personen aufnehmen.
3. Unter Verwaltung → Sicherheit die Zwei-Faktor-Anmeldung für diese Gruppe erzwingen.
4. Unter Verwaltung → Sicherheit → OpenID Connect einen Client anlegen:
   - Name `secretary-dashboard`, Typ vertraulich (confidential), Signatur RS256
   - Weiterleitungsadresse `https://<installation>/auth/callback`, für jede Installation eine
5. Client-ID und Client-Secret im Passwortmanager ablegen.
6. Prüfen, ob die Discovery-Datei erreichbar ist und welche Adresse als `issuer` gemeldet wird:

```bash
curl -s https://<nextcloud>/.well-known/openid-configuration | python3 -m json.tool | grep -E '"issuer"|groups'
curl -s https://<nextcloud>/index.php/.well-known/openid-configuration | python3 -m json.tool | grep -E '"issuer"|groups'
```

In die `.env` der Installation:

```bash
DASHBOARD_AUTH_MODE=oidc
OIDC_ISSUER=https://<nextcloud>                 # Wert "issuer" aus der Discovery-Datei
# OIDC_DISCOVERY_URL=https://<nextcloud>/index.php/.well-known/openid-configuration   # nur falls nötig
OIDC_CLIENT_ID=secretary-dashboard
OIDC_CLIENT_SECRET=<aus Nextcloud>
PUBLIC_BASE_URL=https://<installation>           # ohne Schrägstrich am Ende
DASHBOARD_REQUIRED_GROUP=secretary-admins
```

Ablauf: Ein nicht angemeldeter Aufruf von `/logs` leitet auf `/auth/login` und weiter zur Nextcloud. Nach Anmeldung und zweitem Faktor kommt der Browser zu `<PUBLIC_BASE_URL>/auth/callback` zurück. Die Anwendung tauscht den Code beim Token-Endpunkt der Nextcloud ein. Dabei prüft sie Signatur, Aussteller, Empfänger, Ablauf, `nonce` und PKCE sowie die Gruppe. Danach setzt sie ein Sitzungs-Cookie (Standard 12 Stunden). „Abmelden“ oben rechts beendet die Sitzung.

Netz: Der Browser muss die Nextcloud erreichen, und der Server muss die Nextcloud ausgehend per HTTPS erreichen.

Liefert die Nextcloud keine Gruppen: Statt `DASHBOARD_REQUIRED_GROUP` eine Liste erlaubter Konten setzen, zum Beispiel `DASHBOARD_ALLOWED_USERS=peter,anna@example.org`. Beim Login protokolliert die Anwendung die Namen der empfangenen Claims, nicht ihre Werte. Daran sieht man, ob und unter welchem Namen Gruppen ankommen (`OIDC_GROUPS_CLAIM`, Standard `groups`).

### Basic Auth (Notzugang, lokal, ohne Nextcloud)

```bash
python -m src.dashboard.auth hash-password      # fragt das Passwort ab und gibt den Hash aus
```

In die `.env`, den Hash in **einfachen Anführungszeichen**, weil er `$`-Zeichen enthält:

```bash
DASHBOARD_AUTH_MODE=basic
DASHBOARD_USER=admin
DASHBOARD_PASSWORD_HASH='scrypt:32768:8:1$...$...'
```

Bei Störungen der Nextcloud lässt sich eine Installation so auf den Notzugang umschalten: `DASHBOARD_AUTH_MODE=basic` setzen und neu starten.

### Hinter einem eigenen Proxy (optional)

Läuft die Installation hinter Traefik oder Dokploy, `TRUSTED_PROXY_COUNT=1` setzen. Dann stehen die echten Client-Adressen im Log und die Swagger-Whitelist wirkt. Ohne diesen Wert ignoriert die Anwendung alle `X-Forwarded-*`-Header. Für die Anmeldung selbst ist das nicht nötig. Die Variante, die Anmeldung ganz an einen Proxy abzugeben (`DASHBOARD_AUTH_MODE=forward`), beschreibt AP-20 im Sicherheitsplan.

### Lokale Entwicklung ohne Anmeldung

```bash
ALLOW_INSECURE_NO_AUTH=true
DASHBOARD_AUTH_MODE=off
```

Nie auf einem erreichbaren Rechner verwenden.

## Prüfen nach dem Rollout

```bash
H=https://<installation>
for p in / /logs /llm-config /test /api/health/ /api/booklet/themes; do
  printf "%-22s %s\n" "$p" "$(curl -s -o /dev/null -w '%{http_code}' $H$p)"; done
curl -s -o /dev/null -w "Token:        %{http_code}\n" -H "X-Secretary-Api-Key: $SECRETARY_SERVICE_API_KEY" $H/api/booklet/themes
curl -s -o /dev/null -w "Header-Trick: %{http_code}\n" -H "X-Auth-Request-User: admin" -H "X-Forwarded-For: 127.0.0.1" $H/logs
curl -s -o /dev/null -w "Live:         %{http_code}\n" $H/api/health/live
```

Erwartung: Dashboard-Pfade liefern 302 zur Anmeldung (OIDC) oder 401 (Basic), nie 200. Die API liefert ohne Token 401 und mit Token 200. Der Header-Trick ändert nichts, `/api/health/live` liefert 200.

## Änderungen gegenüber früheren Versionen

- Der Server startet nicht mehr ohne `SECRETARY_SERVICE_API_KEY`. Früher lief die API dann ohne jede Prüfung.
- Das Dashboard ist ohne Anmeldung gesperrt. Früher war es für jeden erreichbar.
- `/api/health/` und `/api/health/use-case/...`, `/api/health/endpoint/...` brauchen den Token. Clients, die diese Vorab-Prüfung ohne Token aufrufen, müssen den Token mitsenden. Frei bleibt nur `/api/health/live`.
- Swagger braucht Token, Dashboard-Anmeldung oder Whitelist. Früher war es frei.
- `ALLOW_SWAGGER_WHITELIST` heißt jetzt `SWAGGER_IP_WHITELIST`, versteht CIDR und öffnet nur noch Swagger. Früher öffnete sie die ganze API und war über gefälschte Header umgehbar. Der alte Name funktioniert noch, mit Warnung im Log.
- `ALLOW_LOCALHOST_NO_AUTH` wertet nur noch die echte Gegenstelle aus, keine `Host`-, `X-Forwarded-For`- oder `X-Real-IP`-Header.
- Schreibende Aufrufe im Dashboard brauchen einen CSRF-Token. Die Dashboard-Seiten senden ihn automatisch mit.
- Die mitgelieferte `docker-compose.yml` reicht die neuen Variablen aus der `.env` an den Container durch.

## Fehlerbilder

| Symptom | Ursache |
|---|---|
| Start bricht mit „Sicherheitskonfiguration unvollständig“ ab | Die aufgezählten Variablen fehlen oder sind zu kurz |
| Dashboard zeigt „Dashboard gesperrt“ | Keine Anmeldeart eingerichtet oder Konfiguration unvollständig, Details im Server-Log |
| „Anmeldedienst nicht erreichbar“ | Discovery-Adresse falsch (`OIDC_ISSUER` bzw. `OIDC_DISCOVERY_URL`) oder Nextcloud vom Server aus nicht erreichbar |
| Nextcloud meldet ungültige Weiterleitungsadresse | `<PUBLIC_BASE_URL>/auth/callback` ist beim Client nicht eingetragen |
| „Anmeldung fehlgeschlagen“ nach Rückkehr | `issuer` stimmt nicht mit `OIDC_ISSUER` überein, Uhrzeit des Servers falsch oder Cookie blockiert |
| „Kein Zugriff“ nach erfolgreicher Anmeldung | Konto nicht in `DASHBOARD_REQUIRED_GROUP` oder Gruppen fehlen im Token, siehe Claim-Namen im Log |
| Basic-Passwort wird nie akzeptiert | Hash in der `.env` ohne einfache Anführungszeichen, `$`-Teile wurden ersetzt |
| 400 bei Speichern im Dashboard | CSRF-Token fehlt, Seite neu laden |
