# Umsetzungsplan Sicherheit – Common Secretary Services

Grundlage: `docs/sicherheitsanalyse-2026-10.md` (Befunde K1–K6, H1–H7, M1–M10, N1–N4) und die Figma-Übersicht
<https://www.figma.com/design/DEDSmfeQsUX5kfihTW8PJG>.

Dieses Dokument ist der Arbeitsvorrat für Claude-Code-Sitzungen. Jedes Arbeitspaket (AP) ist so geschnitten, dass es in einer Sitzung als eigener Branch und Pull Request abgeschlossen werden kann. Status wird direkt hier gepflegt (Checkboxen), damit eine neue Sitzung ohne Vorwissen weiß, wo sie steht.

## So wird mit diesem Plan gearbeitet

1. Neue Sitzung starten mit: „Setze Arbeitspaket AP-xx aus `docs/sicherheitsplan-umsetzung.md` um.“ Die Sitzung liest zuerst dieses Dokument und den zugehörigen Abschnitt der Analyse.
2. Ein AP = ein Branch `claude/sec-ap-xx-kurzname` = ein PR gegen `main`. Keine Vermischung mehrerer APs in einem PR.
3. Vor dem Push: `pytest .tests src/tests -q` muss grün sein; neue Schutzmaßnahmen bekommen einen Test in `.tests/`.
4. Nach dem Merge: Checkbox hier abhaken, Datum und PR-Nummer eintragen, offene Reste als Notiz ans AP hängen.
5. Reihenfolge: **AP-01 und AP-02 zuerst**, weil die Produktionsinstanz laut AP-00-Prüfung offen ist. AP-00 und AP-00b (Betreiberaufgaben) laufen parallel. Danach der Rest von Phase 1, Phase 2 kann parallel laufen, Phase 3 danach.
6. Nichts aus diesem Plan ändert den fachlichen Funktionsumfang. Wo eine Maßnahme ein Verhalten ändert (z. B. fail-closed), wird das in README und `docs/reference/environment-variables.md` nachgezogen.

Legende Aufwand: S = unter einem halben Tag, M = ein Tag, L = mehrere Tage.

---

## Leitprinzip: sicher ohne Umgebungskonfiguration

Der Dienst wird auf vielen Rechnern installiert. Jede Schutzmaßnahme gehört deshalb in die Anwendung selbst oder in die mitgelieferten Dateien (`Dockerfile`, `docker-compose.yml`, `.env.example`). Ein vorgeschalteter Proxy wie Traefik oder Dokploy ist eine optionale Zusatzschicht, nie Voraussetzung.

- **Geschlossen per Default.** Eine frische Installation ohne Sicherheitskonfiguration ist zu: die API startet nicht ohne Token, das Dashboard zeigt ohne konfigurierte Anmeldung nur eine Hinweisseite.
- **Nur Umgebungsvariablen pro Installation.** Was eine Installation braucht, steht in ihrer `.env`. Es wird nichts am Proxy, an Traefik oder an Dokploy verlangt.
- **Mitgelieferte Compose ist sicher.** Sie veröffentlicht nur den Anwendungsport, Mongo ist nur intern erreichbar und hat Zugangsdaten.
- **Proxy-Header sind standardmäßig nicht vertrauenswürdig.** `X-Forwarded-*` und `X-Auth-Request-*` werden nur ausgewertet, wenn eine Installation das ausdrücklich einschaltet. Adressen für Weiterleitungen kommen aus `PUBLIC_BASE_URL`, nie aus dem `Host`-Header.
- **Maßnahmen am Proxy sind Sofortschutz.** Sie überbrücken die Zeit bis zum Rollout der Anwendungsänderung auf einer einzelnen Instanz und ersetzen sie nicht.

## Offene Entscheidungen (vor Phase 1 klären)

### E1 – Authentifizierung für das Dashboard (kein US-Identity-Provider) – ENTSCHIEDEN

**Entscheidung (18.10.2026, überarbeitet): Die eigene Nextcloud ist Anmeldedienst nach OpenID Connect (OIDC), und die Anwendung spricht selbst mit ihr (Bibliothek Authlib in Flask).** Es gibt keinen oauth2-proxy und keine Traefik-Konfiguration. Jede Installation braucht nur Umgebungsvariablen. Installationen, die die Nextcloud nicht erreichen, nutzen den eingebauten Basic-Auth-Modus. Diese Fassung ersetzt die erste Variante mit oauth2-proxy, weil der Dienst auf vielen Rechnern ohne eigene Proxy-Konfiguration laufen soll.

Begründung:

- Keine neue Benutzerverwaltung: Konten, Gruppen und Zwei-Faktor-Anmeldung kommen aus der bestehenden Nextcloud.
- Kein US-Anbieter: Nextcloud ist self-hosted, die OIDC-App und Authlib sind Open Source.
- Unabhängig vom Betriebsort: Die Anmeldung funktioniert gleich, ob die Installation hinter Dokploy, direkt auf einem Rechner oder lokal läuft.

Ablauf einer Dashboard-Anmeldung:

```
Browser ──► Secretary /logs            (keine Sitzung)
   │◄────── Redirect zu Nextcloud /apps/oidc/authorize   (PKCE, state, nonce)
   │──────► Nextcloud: Login + Zwei-Faktor
   │◄────── Redirect zu <PUBLIC_BASE_URL>/auth/callback?code=…
Secretary ──► Nextcloud Token-Endpunkt (Server zu Server): Code gegen ID-Token
Secretary: Signatur, Issuer, Audience, Ablauf, nonce und Gruppe prüfen ──► Sitzungs-Cookie ──► /logs
```

Was jede Installation braucht:

| Variable | Zweck |
|---|---|
| `DASHBOARD_AUTH_MODE=oidc` | Anmeldung über Nextcloud |
| `OIDC_ISSUER` (optional `OIDC_DISCOVERY_URL`) | Adresse der Nextcloud bzw. ihrer Discovery-Datei (AP-00b) |
| `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Client aus Nextcloud |
| `PUBLIC_BASE_URL` | Öffentliche Adresse dieser Installation, daraus entsteht die Rücksprungadresse |
| `DASHBOARD_REQUIRED_GROUP` | z. B. `secretary-admins` |
| `FLASK_SECRET_KEY` | Signiert Sitzung und CSRF-Token, je Installation eigener Zufallswert |
| `DASHBOARD_USER`, `DASHBOARD_PASSWORD_HASH` | Notzugang, falls Nextcloud nicht erreichbar ist |

Voraussetzungen im Netz: Der Browser muss die Nextcloud erreichen, und der Server muss den Token-Endpunkt der Nextcloud ausgehend per HTTPS erreichen. Für jede Installation muss ihre Rücksprungadresse `<PUBLIC_BASE_URL>/auth/callback` beim Nextcloud-Client eingetragen sein (AP-00b klärt, ob ein Client mehrere Adressen haben kann).

Risiken und Gegenmaßnahmen:

| Risiko | Gegenmaßnahme |
|---|---|
| Nextcloud wird sicherheitskritisch | Zwei-Faktor-Pflicht für `secretary-admins`, Nextcloud aktuell halten, Brute-Force-Schutz aktiv |
| Nextcloud gestört oder von einer Installation aus nicht erreichbar | Basic-Auth-Notzugang per `DASHBOARD_AUTH_MODE=basic` |
| OIDC-App ist eine Community-App | Wartungsstand vor Einrichtung prüfen (AP-00b), bei Nextcloud-Updates mittesten |
| Manipulierte Rücksprungadresse über den `Host`-Header | Rücksprungadresse nur aus `PUBLIC_BASE_URL` |
| Gestohlenes Sitzungs-Cookie | `Secure`, `HttpOnly`, `SameSite=Lax`, begrenzte Laufzeit, Abmelden löscht die Sitzung |
| Gruppen fehlen im Token | In AP-00b prüfen; Ersatz: `DASHBOARD_ALLOWED_USERS` als Liste erlaubter Benutzernamen oder E-Mail-Adressen |

Geprüfte und verworfene Alternativen (zur Dokumentation): oauth2-proxy vor Traefik (verlangt Proxy-Konfiguration je Installation, bleibt als Option in AP-20), Authelia (kann keinen fremden OIDC-Anbieter als Quelle nutzen), Zitadel (Schweiz, eigener Dienst nötig), Ory (München, API-first), LemonLDAP::NG (Frankreich, schwergewichtig), Keycloak und Authentik (Hersteller US-Gesellschaften). Zitadel bleibt die Ausweichoption, falls später eine zentrale, mandantenfähige Anmeldung für mehrere Dienste nötig wird; die Flask-Seite bleibt dann gleich, nur der Issuer ändert sich.

Entscheidung: `[x]` Nextcloud (OIDC) direkt in der Anwendung + Basic-Notzugang, 18.10.2026 (ersetzt die Variante mit oauth2-proxy)

### E2 – Reverse-Proxy-Vertrauen

`TRUSTED_PROXY_COUNT` (Default 0) steuert, ob die Anwendung `X-Forwarded-For` auswertet. Die Sicherheit hängt nach dem Leitprinzip nicht davon ab: Anmeldung und Rücksprungadressen funktionieren ohne. Der Wert betrifft nur die Client-IP für Logs, Rate-Limit (AP-16) und die Swagger-Whitelist. Installationen hinter Dokploy oder Traefik setzen ihn auf 1, alle anderen lassen ihn auf 0.

Entscheidung: `[ ]` geklärt, Wert für die Produktionsinstanz: ___

### E3 – Darf der Generic-Extractor von yt-dlp bleiben?

Die Media-Endpunkte für KnowledgeScout nutzen beliebige Webseiten (Rai, Presseseiten). Eine reine Extractor-Allowlist würde das brechen. Vorschlag in AP-12: Generic bleibt erlaubt, aber nur für öffentliche IP-Ziele (DNS-Prüfung), plus Host-Denylist. Alternativ eine Allowlist aus `MEDIA_ALLOWED_HOSTS`.

Entscheidung: `[ ]` Public-IP-Prüfung (empfohlen) `[ ]` Host-Allowlist

---

## Phase 0 – Sofortmaßnahmen im Betrieb (kein Code, Stunden)

### AP-00 Betrieb absichern
Befunde: K1, K2, K3, K4, K5, K6. Aufwand: S. Zuständig: Betreiber (nicht Claude-Sitzung, aber die Sitzung kann die Checkliste begleiten).

- [x] Von außen prüfen: sind `https://<host>/`, `/logs`, `/llm-config` und Port 27017 erreichbar? Geprüft am 18.10.2026 aus einer Claude-Code-Cloud-Sitzung, nur GET-Anfragen, nur Statuscodes ausgewertet:

  | Pfad auf `secretaryservices.bcommonslab.org` | Status | Bewertung |
  |---|---|---|
  | `/` (Dashboard) | 200 | **offen (K1 bestätigt)** |
  | `/logs` | 200, aktuelle Einträge vom selben Tag | **offen, Logs öffentlich lesbar (K1, M5)** |
  | `/llm-config`, `/llm-config/api/models` | 200 | **offen, Konfiguration einsehbar und vermutlich änderbar** |
  | `/test` | 200 | offen |
  | `/api/doc`, `/api/swagger.json` | 200 | offen (bewusste Ausnahme, M3) |
  | `/api/health/` | 200, enthält Provider, Modelle und `remaining_usd` | **Guthaben öffentlich (M3)** |
  | `/api/jobs/<id>` ohne Token | 401 | Token-Pflicht greift |
  | `/api/jobs/<id>` mit `X-Forwarded-For: 127.0.0.1` oder `X-Real-IP: 127.0.0.1` | 401 | Header-Umgehung greift derzeit nicht, Whitelist ist offenbar leer (K2 aktuell nicht ausnutzbar, Code-Fix in AP-01 bleibt nötig) |
  | Antwort-Header | `Server: Werkzeug/3.1.9 Python/3.12.1`, keine Security-Header | Entwicklungsserver in Produktion bestätigt (H4, M4) |

  Nicht geprüft: Port 27017 (über den Proxy der Cloud-Umgebung nicht testbar, lokal mit `nc -vz -w 5 secretaryservices.bcommonslab.org 27017` prüfen: ______). `commonsecretaryservices.bcommonslab.org` aus README und API-Doku war nicht erreichbar (Proxy meldet 502); vermutlich alter Hostname, README und Doku in AP-18 auf `secretaryservices.bcommonslab.org` vereinheitlichen. Ergebnis lokal bestätigen: ______
- [ ] Optionaler Sofortschutz nur für die bereits offene Produktionsinstanz, bis AP-02 dort ausgerollt ist: in Dokploy/Traefik `/`, `/logs`, `/llm-config`, `/docs`, `/test*` und `/api/health/` auf eigene IPs oder VPN beschränken. Die dauerhafte Lösung ist anwendungsseitig (AP-01, AP-02) und braucht keine Proxy-Konfiguration.
- [ ] Produktions-Env: `ALLOW_SWAGGER_WHITELIST` leeren, `ALLOW_LOCALHOST_NO_AUTH=false`, `PYTHONHTTPSVERIFY` nicht gesetzt.
- [ ] `SECRETARY_SERVICE_API_KEY` gesetzt und mindestens 32 Zufallsbytes (`openssl rand -hex 32`). Clients (KnowledgeScout) aktualisieren.
- [ ] Dokploy-Deploy-Token rotieren (K6); neuen Wert als GitHub-Secret `DOKPLOY_DEPLOY_URL` ablegen (wird in AP-15 im Workflow verwendet).
- [ ] LocalBrain/OpenWebUI-Key aus `src/scripts/test_localbrain.py` beim Zielsystem rotieren (K5).
- [ ] Falls `PYTHONHTTPSVERIFY=0` je auf einem Server lief: OpenAI-, Mistral-, OpenRouter-, Voyage-Keys rotieren.
- [ ] MongoDB der Produktionsinstanz: Port prüfen (siehe oben) und, falls offen, bis zum Rollout von AP-07 manuell schließen. Dauerhaft löst das die mitgelieferte Compose in AP-07 für alle Installationen.
- [ ] GitHub: Secret Scanning + Push Protection aktivieren, Branch-Protection für `main` (PR-Pflicht, Checks erforderlich).

### AP-00b Nextcloud als Anmeldedienst vorbereiten
Befund: K1 (Voraussetzung für den Modus `oidc` aus AP-02; AP-02 selbst kann ohne sie umgesetzt und mit `basic` ausgerollt werden). Aufwand: S. Zuständig: Betreiber der Nextcloud.

- [ ] Nextcloud-Version und Erreichbarkeit notieren: ______ (URL der Instanz: ______)
- [ ] App **„OIDC Identity Provider“** (App-ID `oidc`) aus dem App Store installieren. Nicht verwechseln mit `user_oidc`, die Nextcloud zum Client eines anderen Anbieters macht. Wartungsstand prüfen: letzte Veröffentlichung, Kompatibilität mit der eingesetzten Nextcloud-Version.
- [ ] Discovery-Adresse ermitteln, die von außen antwortet: `https://<nextcloud>/.well-known/openid-configuration` oder `https://<nextcloud>/index.php/.well-known/openid-configuration`. Den Wert `issuer` aus der Antwort notieren: ______ (wird `OAUTH2_PROXY_OIDC_ISSUER_URL`).
- [ ] Gruppe `secretary-admins` anlegen und berechtigte Personen aufnehmen.
- [ ] Zwei-Faktor-Anmeldung für `secretary-admins` erzwingen (Verwaltung → Sicherheit → Zwei-Faktor-Authentifizierung erzwingen, auf Gruppe beschränken).
- [ ] Unter Verwaltung → Sicherheit → OpenID Connect einen Client anlegen: Name `secretary-dashboard`, Typ vertraulich (confidential), Signatur RS256, Weiterleitungsadresse `https://secretaryservices.bcommonslab.org/auth/callback`. Client-ID und Client-Secret im Passwortmanager ablegen.
- [ ] Prüfen, ob ein Client mehrere Weiterleitungsadressen aufnehmen kann. Ja: weitere Installationen bekommen ihre Adresse `<PUBLIC_BASE_URL>/auth/callback` im selben Client. Nein: je Installation einen eigenen Client anlegen. Ergebnis: ______
- [ ] Prüfen, ob für lokale Installationen `http://localhost:5001/auth/callback` als Weiterleitungsadresse akzeptiert wird. Ergebnis: ______
- [ ] Prüfen, ob das ID-Token oder der Userinfo-Endpunkt die Gruppen liefert und unter welchem Claim (meist `groups`). Erster Hinweis: die Listen `scopes_supported` und `claims_supported` in der Discovery-Datei. Endgültig nach AP-02: die Anwendung protokolliert beim ersten Login die Namen der empfangenen Claims, nicht ihre Werte. Ergebnis: Claim-Name ______, enthält `secretary-admins`: ja / nein.
- [ ] Falls keine Gruppen kommen: Liste erlaubter Benutzernamen oder E-Mail-Adressen für `DASHBOARD_ALLOWED_USERS` festlegen.
- [ ] Werte je Installation in deren `.env` vorbereiten (nicht im Repo): `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `PUBLIC_BASE_URL`, `FLASK_SECRET_KEY` (je Installation eigener Wert, `openssl rand -hex 32`), `DASHBOARD_USER` und `DASHBOARD_PASSWORD_HASH` für den Notzugang.

---

## Phase 1 – Kleine Code-Änderungen mit großer Wirkung (diese Woche)

### AP-01 Auth-Middleware fail-closed und spoof-sicher
Befunde: K2, K3, M1. Aufwand: M. Dateien: `src/api/routes/__init__.py`, `src/dashboard/app.py`, `README.md`, `docs/reference/environment-variables.md`, neuer Test `.tests/test_api_auth.py`.

Schritte:
1. Start abbrechen (Exception mit klarer Meldung), wenn `SECRETARY_SERVICE_API_KEY` fehlt, außer `ALLOW_INSECURE_NO_AUTH=true` ist explizit gesetzt (nur für lokale Entwicklung, mit Warnung im Log).
2. Client-IP nur aus `request.remote_addr`. Neue Variable `TRUSTED_PROXY_COUNT` (Default 0); wenn > 0, `werkzeug.middleware.proxy_fix.ProxyFix(app, x_for=N, x_proto=N, x_host=N)` in `app.py` registrieren. `Host`, `X-Real-IP` und manuell gelesenes `X-Forwarded-For` aus der Middleware entfernen.
3. Whitelist nur noch für `/api/doc*` und `/api/swagger.json`; Name in `SWAGGER_IP_WHITELIST` ändern (alter Name wird mit Deprecation-Warnung weiter gelesen). Einträge mit `ipaddress.ip_network` parsen, damit CIDR wie dokumentiert funktioniert.
4. Localhost-Ausnahme nur über `remote_addr in {127.0.0.1, ::1}`, kein Host-Header.
5. Tokenvergleich mit `hmac.compare_digest`.
6. Health: nur `/api/health/live` bleibt ausgenommen; alle anderen Health-Routen verlangen den Token.
7. Doku und README-Beispiele anpassen (keine `127.0.0.1`-Whitelist-Empfehlung mehr).

Akzeptanz: Tests mit Flask-Testclient: (a) ohne Token 401, (b) mit Token 200, (c) `X-Forwarded-For: 127.0.0.1` ohne Token 401, (d) `Host: localhost` ohne Token 401, (e) mit `TRUSTED_PROXY_COUNT=1` und Whitelist greift die Forwarded-IP nur für `/api/doc`, (f) Start ohne Key wirft.

- [ ] erledigt am ______, PR #____

### AP-02 Dashboard authentifizieren (in der Anwendung, Nextcloud per OIDC)
Befunde: K1, M4 (CSRF). Aufwand: M–L. Voraussetzung: AP-01. Für den Modus `oidc` im Betrieb: AP-00b. Dateien: `src/dashboard/app.py`, neue Dateien `src/dashboard/auth.py` und `src/dashboard/templates/auth_*.html`, `requirements.txt` (`authlib`, `flask-wtf`), `.env.example`, neue Datei `docs/deployment/dashboard-anmeldung.md`, `docs/reference/environment-variables.md`, `src/dashboard/templates/base.html`, Tests `.tests/test_dashboard_auth.py`.

Ziel: Keine Installation hat ein offenes Dashboard, egal wie sie betrieben wird, und keine braucht dafür Proxy-Konfiguration.

Schritte:
1. **Modus bestimmen** in `src/dashboard/auth.py` über `DASHBOARD_AUTH_MODE`:
   - `oidc`: Anmeldung über Nextcloud (siehe Schritt 3).
   - `basic`: `DASHBOARD_USER` und `DASHBOARD_PASSWORD_HASH` (Werkzeug `generate_password_hash`), zeitkonstanter Vergleich, 401 mit `WWW-Authenticate`.
   - `forward`: Benutzer aus einem Proxy-Header, nur zusammen mit `TRUSTED_PROXY_COUNT>0`, sonst verweigert der Start. Nur für Installationen mit eigenem Proxy, siehe AP-20.
   - `off`: nur zusammen mit `ALLOW_INSECURE_NO_AUTH=true`, mit Warnung im Log.
   - **Nicht gesetzt:** sind `OIDC_*` vorhanden, gilt `oidc`; sonst ist `DASHBOARD_USER` gesetzt, gilt `basic`; sonst ist das Dashboard **gesperrt**. Alle Dashboard-Pfade antworten dann mit 503 und einer Hinweisseite, welche Variablen zu setzen sind. Die API läuft unabhängig davon weiter.
2. **Geschützte Pfade:** Ein `app.before_request` in `src/dashboard/app.py` schützt alles außer `/api/*` (eigene Middleware aus AP-01), `/api/health/live`, `/auth/*` und statischen Dateien. `/api/doc` und `/api/swagger.json` sind erreichbar mit Dashboard-Sitzung oder gültigem API-Key. Der Benutzername kommt in `flask.g.dashboard_user` und in den Log-Kontext.
3. **OIDC mit Authlib:**
   - Client über `server_metadata_url` registrieren: `OIDC_DISCOVERY_URL`, sonst `OIDC_ISSUER` plus `/.well-known/openid-configuration`, weil der Pfad bei Nextcloud variiert.
   - Authorization Code Flow mit PKCE (S256), `state` und `nonce`; Scopes `openid profile email` plus `groups`, wenn die Discovery-Datei ihn anbietet.
   - Rücksprungadresse ausschließlich `PUBLIC_BASE_URL` + `/auth/callback`; ohne `PUBLIC_BASE_URL` verweigert der Modus `oidc` den Start.
   - ID-Token prüfen: Signatur über JWKS, `iss`, `aud`, `exp`, `nonce`.
   - Zugang: `DASHBOARD_REQUIRED_GROUP` gegen den Claim `OIDC_GROUPS_CLAIM` (Default `groups`); ersatzweise `DASHBOARD_ALLOWED_USERS` (Benutzername oder E-Mail). Ohne Gruppe und ohne Liste verweigert der Modus den Start, damit nicht jedes Nextcloud-Konto hineinkommt. Abweisung mit 403 und Hinweisseite.
   - Beim ersten Login die Namen der empfangenen Claims protokollieren, nicht die Werte (hilft bei AP-00b).
   - Sitzung speichert nur Benutzername, E-Mail, Gruppen, Login-Zeit. Laufzeit `DASHBOARD_SESSION_HOURS` (Default 12).
   - `/auth/logout` löscht die Sitzung und leitet zum `end_session_endpoint` weiter, falls die Discovery-Datei einen nennt.
4. **Sitzung und Schlüssel:** `FLASK_SECRET_KEY` ist Pflicht, sobald das Dashboard nicht gesperrt ist. Ohne verweigert der Start mit klarer Meldung. Cookie `secretary_session` mit `HttpOnly`, `SameSite=Lax` und `Secure`, wenn `PUBLIC_BASE_URL` mit `https` beginnt.
5. **CSRF:** `flask-wtf` CSRFProtect für alle Dashboard-POSTs. Die `fetch`-Aufrufe in `llm_config.html`, `dashboard.html` und den Testseiten senden den Token als Header `X-CSRFToken`. `/api/*` bleibt ausgenommen, dort gilt der API-Key.
6. **Testrouten:** `/run_*_test` senden den Service-Token an die interne API mit.
7. **Oberfläche:** `base.html` zeigt den angemeldeten Benutzer und einen Link „Abmelden“.
8. **Dokumentation:** `docs/deployment/dashboard-anmeldung.md` beschreibt die Einrichtung des Nextcloud-Clients (aus AP-00b), die Variablen je Installation, eine lokale Installation mit `basic`, das Umschalten auf den Notzugang und typische Fehler (falsche Issuer-Adresse, fehlender Gruppen-Claim, Rücksprungadresse nicht eingetragen). `.env.example` und `docs/reference/environment-variables.md` bekommen alle neuen Variablen.

Akzeptanz:
- Tests mit Flask-Testclient und einem nachgebildeten OIDC-Anbieter (Discovery, JWKS und Token-Endpunkt gemockt):
  - Ohne jede Konfiguration: `/`, `/logs`, `/llm-config` antworten 503 mit Hinweisseite; `/api/jobs/x` mit gültigem Token funktioniert.
  - `oidc`: `/logs` ohne Sitzung leitet zur Authorize-Adresse weiter, mit `code_challenge` und `state`; die `redirect_uri` stammt aus `PUBLIC_BASE_URL`, auch wenn der Request einen anderen `Host`-Header trägt.
  - Callback mit falschem `state` liefert 400; gültiges Token ohne die Gruppe liefert 403; gültiges Token mit Gruppe setzt die Sitzung, danach `/logs` 200.
  - `oidc` ohne `PUBLIC_BASE_URL`, ohne `FLASK_SECRET_KEY` oder ohne Gruppe und Benutzerliste verweigert den Start.
  - `basic`: ohne Zugangsdaten 401, mit Zugangsdaten 200.
  - `forward` ohne `TRUSTED_PROXY_COUNT` verweigert den Start.
  - POST `/clear-logs` ohne CSRF-Token liefert 400.
- Abnahme auf der Produktionsinstanz: Die Außenprüfung aus AP-00 wiederholen. `/`, `/logs`, `/llm-config`, `/test` liefern keine 200 mehr ohne Anmeldung, sondern eine Weiterleitung zur Nextcloud. Ein Konto außerhalb von `secretary-admins` wird abgewiesen. `/api/*` mit API-Key funktioniert unverändert.

- [ ] erledigt am ______, PR #____

### AP-03 Dateinamen und Temp-Dateien
Befunde: H3, M6. Aufwand: S. Dateien: `src/api/routes/office_routes.py`, `src/processors/video_processor.py`, `src/api/routes/imageocr_routes.py`, `src/utils/template_utils.py`, `src/api/routes/audio_routes.py` (prüfen).

Schritte:
1. Neue Hilfsfunktion `src/utils/safe_paths.py`: `safe_upload_name(filename) -> str` (nur Suffix aus `secure_filename`, Basis = UUID) und `ensure_within(base, target)`.
2. `office_routes._save_upload_to_temp` und `video_processor` (Zeilen 759 und 1019) auf `safe_upload_name` umstellen; Original-Dateiname nur noch als Metadatum.
3. `imageocr_routes`: Temp-Datei in `tempfile.mkdtemp(prefix="imageocr-")` statt im Quellcode-Ordner; Aufräumen im `finally`.
4. `template_utils.get_template_content`: `template_name` gegen `^[A-Za-z0-9_\-]+$` prüfen und `ensure_within(templates_dir, path)`.

Akzeptanz: Tests mit Dateiname `../../x.docx` landet unter `temp_dir`; `template=../x` wirft `ValueError`.

- [ ] erledigt am ______, PR #____

### AP-04 Timeouts, Größenlimits und TLS-Verifikation
Befunde: H2, H6 (Timeouts). Aufwand: M. Dateien: `src/processors/pdf_processor.py`, `src/processors/audio_processor.py`, `src/processors/video_processor.py`, `src/api/routes/media_routes.py`, `src/main.py`, `config/config.yaml`.

Schritte:
1. Neue Hilfsfunktion `src/utils/http_fetch.py`: `download_to_file(url, dest, max_bytes, timeout=(5, 60))`, streamt in Blöcken, zählt Bytes, bricht bei Überschreitung ab, setzt User-Agent. Kein SSRF-Schutz in diesem AP (kommt in AP-12), aber die Schnittstelle ist dafür vorbereitet (`allow_private=False` Parameter, vorerst ohne Wirkung mit TODO-Verweis auf AP-12).
2. Alle `requests.get/head` ohne Timeout (pdf 453/1498/1544, audio 397) auf die Hilfsfunktion umstellen.
3. `nocheckcertificate`, `legacy_server_connect`, `verify=False` entfernen. `PYTHONHTTPSVERIFY=0` nur noch wirksam, wenn zusätzlich `FLASK_ENV=development`; sonst Warnung und ignorieren. `config.yaml` `youtube.ydl_opts.nocheckcertificate` entfernen.
4. Windows-Hinweis in README: `SSL_CERT_FILE` auf `certifi.where()` setzen statt Verifikation abzuschalten.

Akzeptanz: Grep nach `nocheckcertificate|verify=False|_create_unverified_context` liefert nur noch die Dev-Guard-Stelle; Test für `download_to_file` mit Mock-Server, der mehr als `max_bytes` liefert, wirft.

- [ ] erledigt am ______, PR #____

### AP-05 Fehlerausgaben und Informationsabfluss
Befunde: M3, M10 (tote Schalter). Aufwand: S. Dateien: `src/api/routes/pdf_routes.py`, `session_routes.py`, `common_routes.py`, `imageocr_routes.py`, `src/main.py`, `src/dashboard/app.py`, `config/config.yaml`.

Schritte:
1. Alle `'traceback': traceback.format_exc()` und `str(e)` in API-Antworten durch Fehlercode + generische Meldung ersetzen; Traceback nur ins Log mit `process_id`, damit er auffindbar bleibt.
2. `main.py`: die `print`-Zeilen mit Cookie-Pfaden entfernen; `app.py`: Whitelist nicht roh loggen.
3. `config.yaml`: `server.debug` und `rate_limiting` entfernen oder in AP-16 anbinden (Entscheidung dort), `server.host/port` mit Kommentar „nicht genutzt“ markieren oder nutzen.

Akzeptanz: Grep `format_exc()` in `src/api/routes` nur noch in Logger-Aufrufen.

- [ ] erledigt am ______, PR #____

### AP-06 Abhängigkeiten und Docker-Basis
Befunde: H5, H4 (Image, Pin). Aufwand: M (inklusive Testlauf). Dateien: `requirements.txt`, `Dockerfile`, neu `requirements.lock` oder `uv.lock`.

Schritte:
1. `pillow>=12.3.0`, `pymongo>=4.18.2`, `flask>=3.1.3`, `pytest>=9.0.3` setzen; `pip-audit` lokal laufen lassen bis 0 Befunde.
2. Lockfile einführen (`pip-compile --generate-hashes` oder `uv pip compile`), Dockerfile installiert aus dem Lockfile.
3. `pip install --upgrade yt-dlp` aus dem Dockerfile entfernen; yt-dlp bewusst im Lockfile nachziehen.
4. Basisimage auf aktuelles `python:3.12-slim` (Digest pinnen), `apt-get upgrade` im Build.
5. Vollständiger Testlauf `pytest`, Smoke-Test der Office- und PDF-Pipeline (Pillow-Major-Update!).

Akzeptanz: `pip-audit -r requirements.lock` ohne Befunde; Image baut; Tests grün.

- [ ] erledigt am ______, PR #____

### AP-07 Mitgelieferte Compose sicher per Default
Befund: K4. Aufwand: S–M. Dateien: `docker-compose.yml`, `.env.example`, README Abschnitt Docker, neue Datei `docs/deployment/mongo-migration.md`. Vorgezogen aus AP-14, weil die Compose-Datei auf jeder Installation landet.

Schritte:
1. Beim Mongo-Dienst das Port-Mapping `27017:27017` entfernen; Mongo ist nur im Compose-Netz erreichbar.
2. `MONGO_INITDB_ROOT_USERNAME` und `MONGO_INITDB_ROOT_PASSWORD` aus `.env`; `MONGODB_URI` für den Secretary-Dienst daraus zusammensetzen (`mongodb://${MONGO_ROOT_USER}:${MONGO_ROOT_PASSWORD}@mongodb:27017/?authSource=admin`). Fehlen die Werte, bricht `docker compose up` mit Meldung ab (`${VAR:?Meldung}`-Syntax).
3. `healthcheck` für beide Dienste; Secretary mit `depends_on: condition: service_healthy`.
4. **Migration bestehender Installationen dokumentieren:** Die `MONGO_INITDB_*`-Variablen wirken nur auf ein leeres Datenverzeichnis. Für vorhandene Volumes beschreibt `docs/deployment/mongo-migration.md`, wie man mit `mongosh` im Container einmalig einen Admin-Benutzer anlegt und danach mit Auth neu startet.
5. `.env.example` um die neuen Variablen ergänzen.

Akzeptanz: Frische Installation mit `.env` aus `.env.example` startet; `docker compose up` ohne Mongo-Zugangsdaten bricht mit verständlicher Meldung ab; Port 27017 ist auf dem Host nicht offen (`ss -ltn`); Migration an einer Kopie eines bestehenden Volumes einmal durchgespielt.

- [ ] erledigt am ______, PR #____

---

## Phase 2 – Strukturelle Härtung (diesen Monat)

### AP-12 SSRF-Schutz zentral
Befunde: H1, Teile von M7. Aufwand: L. Dateien: `src/utils/http_fetch.py` (aus AP-04), `src/utils/ssrf.py` (neu), alle Fetch-Stellen aus H1, `src/api/routes/media_routes.py`, `src/processors/video_processor.py`, alle Handler mit `callback_url`, `src/core/mongodb/secretary_worker_manager.py`.

Schritte:
1. `ssrf.py`: `resolve_and_check(url)` erlaubt nur `http/https`, löst den Host auf, lehnt Loopback, private (RFC 1918), Link-Local (169.254.0.0/16, fe80::/10), Multicast, `::1`, `0.0.0.0/8` und Cloud-Metadaten ab; liefert die geprüfte IP, die dann per `requests`-Adapter oder Host-Header-Pinning verwendet wird (verhindert DNS-Rebinding). Redirects manuell folgen und jedes Ziel erneut prüfen (max. 5).
2. `download_to_file` nutzt `resolve_and_check` standardmäßig; `allow_private=True` nur für Tests.
3. Webhooks: `WEBHOOK_ALLOWED_HOSTS` (kommagetrennt, Glob erlaubt). Leer = nur öffentliche IPs erlaubt. Prüfung beim Anlegen des Jobs (400 statt später stiller Fehler) und erneut beim Senden.
4. yt-dlp: eigener `YoutubeDL`-Hook, der vor dem Download die aufgelösten Format-URLs gegen `resolve_and_check` prüft; je nach E3 zusätzlich `allowed_extractors` oder `MEDIA_ALLOWED_HOSTS`.
5. Fehlercode `SSRF_BLOCKED` in der API-Doku dokumentieren.

Akzeptanz: Tests für `resolve_and_check` (private IPs, Metadaten-IP, Redirect auf privat); Integrationstest `callback_url=http://127.0.0.1:1/` wird mit 400 abgelehnt.

- [ ] erledigt am ______, PR #____

### AP-13 Booklet-Renderer härten
Befund: H7. Aufwand: S. Dateien: `src/processors/booklet/render.py`, `requirements.txt` (nh3).

Schritte:
1. `_markdown`: Ausgabe von python-markdown durch `nh3.clean` mit Tag-Allowlist (`p, br, strong, em, ul, ol, li, h1–h4, blockquote, a[href nur http/https/mailto]`) filtern.
2. WeasyPrint `url_fetcher`: nur `file://` unterhalb von `work_dir/images` und dem Template-Ordner; alles andere `ProcessingError`. `HTML(string=..., base_url=..., url_fetcher=...)`.
3. Test: Markdown mit `<img src="file:///etc/hostname">` erzeugt ein PDF ohne Bild und ohne Fehler; externer `<link>` wird geblockt.

- [ ] erledigt am ______, PR #____

### AP-14 Container und Compose härten
Befunde: H4 (root, Dev-Server), H6 (Ressourcen); K4 ist in AP-07 vorgezogen. Aufwand: M. Dateien: `Dockerfile`, `docker-compose.yml`, `docker-build-run.bat`, README Deployment-Abschnitt.

Schritte:
1. `gunicorn` in requirements; `CMD ["gunicorn","-w","2","--threads","8","--timeout","900","-b","0.0.0.0:5001","src.dashboard.app:app"]`; `src/main.py` bleibt für lokale Entwicklung.
2. `RUN useradd -r -u 10001 app`, Verzeichnisse `logs temp-processing cache` an `app` übergeben, `USER app`.
3. Compose (Mongo-Teil ist bereits in AP-07 erledigt): Service mit `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `deploy.resources.limits` (RAM/CPU), `healthcheck` auf `/api/health/live`.
4. Prüfen, dass Worker-Threads mit gunicorn starten (Worker wird aktuell beim ersten Request gestartet; mit `-w 2` liefe er doppelt → `preload` oder Worker in eigenem Prozess/Container, siehe AP-21).

Akzeptanz: `docker compose up` startet, Prozess läuft als UID 10001 (`docker exec id`), Mongo von außen nicht erreichbar, Health grün.

- [ ] erledigt am ______, PR #____

### AP-15 CI/CD härten
Befunde: M8, K6 (Token), N3. Aufwand: M. Dateien: `.github/workflows/ci-main.yml`, `.github/workflows/checks.yml`, neu `.github/dependabot.yml`, `SECURITY.md`, `.github/CODEOWNERS`.

Schritte:
1. `ci-main.yml`: Deploy-URL aus `${{ secrets.DOKPLOY_DEPLOY_URL }}`; alle Actions per Commit-SHA pinnen (mit Versionskommentar); `permissions` je Job minimal (`contents: write` nur im Release-Schritt, `packages: write` nur beim Push des Images); `CI_PAT` durch fine-grained Token (nur dieses Repo, nur Contents) oder GitHub App ersetzen.
2. `checks.yml`: Jobs `test` (`pytest`), `lint` (`ruff` oder bestehendes `mypy`), `security` (`bandit -r src -ll`, `pip-audit -r requirements.lock`, `gitleaks detect`), `image` (Build + `trivy image --severity HIGH,CRITICAL --exit-code 1`).
3. `dependabot.yml` für `pip`, `docker`, `github-actions`, wöchentlich.
4. `SECURITY.md` mit Meldeweg und unterstützten Versionen; `CODEOWNERS` für `src/api/routes/__init__.py`, `Dockerfile`, Workflows.

Akzeptanz: PR-Check läuft in unter 15 Minuten; absichtlich eingeschleuster Fake-Key wird von gitleaks gemeldet.

- [ ] erledigt am ______, PR #____

### AP-16 Security-Header und Rate-Limiting
Befunde: M4 (Header), H6 (Rate-Limit). Aufwand: M. Dateien: `src/dashboard/app.py`, `src/api/routes/__init__.py`, `requirements.txt` (`flask-limiter`), `config/config.yaml`.

Schritte:
1. `after_request`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy` für das Dashboard (Skripte nur `self` plus verwendete CDNs, danach schrittweise verschärfen), `Strict-Transport-Security`, wenn `PUBLIC_BASE_URL` mit `https` beginnt.
2. `flask-limiter` mit Schlüssel = Service-Token-Hash (API) bzw. Dashboard-Nutzer; Standard 60/min, teure Endpunkte (`/api/media/*`, `/api/audio/*`, `/api/video/*`, Batch-Tests) 10/min; Werte aus `config.yaml rate_limiting`. Speicher: In-Memory reicht für eine Instanz, sonst Redis.
3. Alte `RateLimiter`-Klasse entfernen oder als Adapter nutzen.

Akzeptanz: 61. Request in einer Minute liefert 429 mit `Retry-After`; Header in jeder Antwort vorhanden (Test).

- [ ] erledigt am ______, PR #____

### AP-17 Logging und Datenschutz
Befund: M5. Aufwand: M. Dateien: `src/utils/logger.py`, `config/config.yaml`, `src/api/routes/office_routes.py` und andere Stellen mit Formular-Logging, `src/core/mongodb/secretary_repository.py`, `src/core/mongodb/secretary_worker_manager.py`.

Schritte:
1. Level `INFO` in `config.yaml` (DEBUG nur per Env `LOG_LEVEL`).
2. Redaktionsfilter im Logger: Felder `text`, `transcript`, `content`, `callback_token`, `Authorization`, `cookie` werden gekürzt oder maskiert; URLs ohne Query-String loggen.
3. Webhook-Token: Der Token muss beim Senden im Klartext vorliegen, ein Hash reicht also nicht. Deshalb verschlüsselt ablegen (Fernet mit `SECRET_ENCRYPTION_KEY`) und nach erfolgreicher Zustellung aus dem Job-Dokument löschen.
4. Aufbewahrung: `max_size`/`backup_count` auf 20 MB × 5; Hinweis in README, Logs nicht dauerhaft auf Host-Volumes mit weiten Rechten zu halten.

Akzeptanz: Testlog eines Office-Uploads enthält keinen Formulartext und keinen Token; Job-Dokument nach Zustellung ohne `webhook.token`.

- [ ] erledigt am ______, PR #____

### AP-18 Repository-Hygiene
Befunde: N1, N2. Aufwand: S.

Schritte:
1. `git rm -r --cached .obsidian .vscode site src/scripts/test1.pdf src/scripts/test2.pdf`; `.gitignore` ergänzen (`site/`, `.vscode/`, `*.pdf` unter `src/scripts/`).
2. Produktions-Hostnamen in README und `docs/reference/api/*` auf `secretaryservices.bcommonslab.org` vereinheitlichen (AP-00-Prüfung: der ältere Name antwortete nicht).
3. `.env.example`: Atlas-Hostname durch `cluster.example.mongodb.net` und Benutzerpfad durch `<pfad>` ersetzen; gleiches in `docs/handover-ks-transkript-verlaesslichkeit.md`.
3. Hardcodierten Key aus `src/scripts/test_localbrain.py` und `test_openwebui.py` entfernen (nur Env-Variable); History-Rewrite nicht nötig, der Key wird in AP-00 rotiert.
4. `mkdocs.yml` prüfen, ob `site/` im Deployment gebraucht wird (Docs-Route liest `site/`); wenn ja, im Dockerfile `mkdocs build` ausführen statt das Build-Ergebnis zu committen.

- [ ] erledigt am ______, PR #____

---

## Phase 3 – Strukturell (Quartal)

### AP-19 Mehrere API-Keys mit Rechten und Objekt-Autorisierung
Befunde: M1 (Einzel-Key), M2. Aufwand: L. Dateien: `src/core/mongodb/api_key_repository.py` (neu), `src/api/routes/__init__.py`, `src/api/routes/secretary_job_routes.py`, `booklet_routes.py`, CLI `scripts/manage_api_keys.py` (neu).

Schritte:
1. Collection `api_keys`: `{key_hash (sha256), name, scopes: [namespaces], rate_limit, created_at, last_used_at, revoked}`; `SECRETARY_SERVICE_API_KEY` bleibt als „Legacy-Admin-Key“ gültig, bis alle Clients migriert sind.
2. Middleware setzt `g.api_client` (Name, Scopes); Namespace-Prüfung gegen Scopes.
3. Jobs speichern `owner_key_id`; `/api/jobs/<id>`, `/stream`, `/download-archive`, Booklet-Assets liefern 404 für fremde Jobs (Admin-Scope sieht alles).
4. CLI zum Anlegen/Widerrufen; Doku.

Akzeptanz: Zwei Keys, Job von Key A ist für Key B 404; Key ohne Scope `media` bekommt 403 auf `/api/media/*`.

- [ ] erledigt am ______, PR #____

### AP-20 Optional: Forward-Auth über oauth2-proxy für Installationen mit eigenem Proxy
Befund: K1 (zusätzliche Schicht). Aufwand: S. Nur für Installationen, deren Betreiber ohnehin einen Proxy pflegt und die Anmeldung dort bündeln will. Nach dem Leitprinzip ist das nie Voraussetzung; die Anwendung schützt sich mit AP-02 selbst.

Schritte: Die Anwendung im Modus `forward` aus AP-02 betreiben (`TRUSTED_PROXY_COUNT=1`, `DASHBOARD_FORWARD_USER_HEADER`, optional `DASHBOARD_REQUIRED_GROUP` gegen `DASHBOARD_FORWARD_GROUPS_HEADER`). Die folgende Vorlage als `docs/deployment/oauth2-proxy-beispiel.md` ablegen, nicht als Teil der Standard-Compose.

Vorlage für `docker-compose.auth.yml` (Werte aus Dokploy-Secrets, Hostnamen anpassen):

```yaml
services:
  oauth2-proxy:
    image: quay.io/oauth2-proxy/oauth2-proxy:v7.7.1   # beim Umsetzen auf aktuelle Version prüfen und per Digest pinnen
    environment:
      OAUTH2_PROXY_PROVIDER: oidc
      OAUTH2_PROXY_PROVIDER_DISPLAY_NAME: Nextcloud
      OAUTH2_PROXY_OIDC_ISSUER_URL: ${NC_OIDC_ISSUER}            # Wert "issuer" aus AP-00b
      OAUTH2_PROXY_CLIENT_ID: ${NC_OIDC_CLIENT_ID}
      OAUTH2_PROXY_CLIENT_SECRET: ${NC_OIDC_CLIENT_SECRET}
      OAUTH2_PROXY_CODE_CHALLENGE_METHOD: S256
      OAUTH2_PROXY_SCOPE: "openid profile email groups"          # "groups" nur, wenn die App den Scope kennt
      OAUTH2_PROXY_OIDC_GROUPS_CLAIM: groups                    # Claim-Name aus AP-00b
      OAUTH2_PROXY_ALLOWED_GROUPS: secretary-admins
      OAUTH2_PROXY_EMAIL_DOMAINS: "*"
      OAUTH2_PROXY_UPSTREAMS: static://202
      OAUTH2_PROXY_REVERSE_PROXY: "true"
      OAUTH2_PROXY_SET_XAUTHREQUEST: "true"
      OAUTH2_PROXY_HTTP_ADDRESS: 0.0.0.0:4180
      OAUTH2_PROXY_REDIRECT_URL: https://${SECRETARY_HOST}/oauth2/callback
      OAUTH2_PROXY_COOKIE_SECRET: ${OAUTH2_COOKIE_SECRET}
      OAUTH2_PROXY_COOKIE_SECURE: "true"
      OAUTH2_PROXY_COOKIE_SAMESITE: lax
      OAUTH2_PROXY_COOKIE_EXPIRE: 12h
      OAUTH2_PROXY_SKIP_PROVIDER_BUTTON: "true"
    labels:
      - traefik.enable=true
      - traefik.http.routers.secretary-oauth2.rule=Host(`${SECRETARY_HOST}`) && PathPrefix(`/oauth2/`)
      - traefik.http.routers.secretary-oauth2.priority=100
      - traefik.http.services.secretary-oauth2.loadbalancer.server.port=4180
      - traefik.http.middlewares.nc-auth.forwardauth.address=http://oauth2-proxy:4180/oauth2/auth
      - traefik.http.middlewares.nc-auth.forwardauth.authResponseHeaders=X-Auth-Request-User,X-Auth-Request-Email,X-Auth-Request-Groups
      - traefik.http.middlewares.nc-signin.errors.status=401
      - traefik.http.middlewares.nc-signin.errors.service=secretary-oauth2
      - traefik.http.middlewares.nc-signin.errors.query=/oauth2/sign_in

  secretary-services:
    environment:
      DASHBOARD_AUTH_MODE: forward
      TRUSTED_PROXY_COUNT: "1"
      DASHBOARD_REQUIRED_GROUP: secretary-admins
    labels:
      - traefik.enable=true
      # 1) Maschinen-API: nur API-Key, kein oauth2-proxy
      - traefik.http.routers.secretary-api.rule=Host(`${SECRETARY_HOST}`) && PathPrefix(`/api/`) && !PathPrefix(`/api/doc`) && !PathPrefix(`/api/swagger.json`)
      - traefik.http.routers.secretary-api.priority=50
      - traefik.http.routers.secretary-api.middlewares=strip-auth-headers
      # 2) Alles andere (Dashboard, Swagger, Docs): Nextcloud-Login
      - traefik.http.routers.secretary-ui.rule=Host(`${SECRETARY_HOST}`)
      - traefik.http.routers.secretary-ui.priority=10
      - traefik.http.routers.secretary-ui.middlewares=strip-auth-headers,nc-signin,nc-auth
      - traefik.http.services.secretary.loadbalancer.server.port=5001
      # Eingehende X-Auth-Request-* Header vom Client entfernen (gegen Fälschung)
      - traefik.http.middlewares.strip-auth-headers.headers.customrequestheaders.X-Auth-Request-User=
      - traefik.http.middlewares.strip-auth-headers.headers.customrequestheaders.X-Auth-Request-Email=
      - traefik.http.middlewares.strip-auth-headers.headers.customrequestheaders.X-Auth-Request-Groups=
```

Hinweise für die umsetzende Sitzung: Die Vorlage vor dem Einsatz mit der aktuellen oauth2-proxy-Dokumentation (Abschnitt Integration mit Traefik) und der eingesetzten Traefik-Version abgleichen, insbesondere wie nach der Anmeldung auf die ursprüngliche Seite zurückgeleitet wird. `trustForwardHeader` bewusst nicht setzen, damit vom Client gelieferte `X-Forwarded-*`-Header nicht an oauth2-proxy gelangen. Router-Namen, Entrypoints und TLS-Resolver an die bestehende Dokploy-Konfiguration anpassen; Dokploy kann eigene Labels setzen, die Vorlage ist dann als Ergänzung zu verstehen. Ob die Matcher-Syntax `!PathPrefix` verfügbar ist, hängt von der Traefik-Version ab (v3: ja); sonst die API-Router mit höherer Priorität ausdrücklich für Swagger ergänzen.

- [ ] Bedarf geprüft am ______, Ergebnis: ______

### AP-21 Konverter in eigenen Worker-Container
Befunde: M9, Rest von H4. Aufwand: L. Dateien: `docker-compose.yml`, neues `Dockerfile.worker`, `src/core/mongodb/secretary_worker_manager.py` (Start als eigener Prozess `python -m src.worker`), `src/dashboard/app.py` (Worker nicht mehr im Web-Prozess starten).

Schritte: Worker-Container ohne veröffentlichte Ports, Netzwerk nur zu Mongo und den LLM-Providern (eigenes Compose-Netz plus Egress-Regeln auf Proxy-Ebene), `seccomp`-Profil, Limits; Web-Container ohne ffmpeg/LibreOffice/Tesseract. Dateityp-Prüfung mit `python-magic` vor jeder Verarbeitung; Zip-Entpacklimit für Office (Gesamtgröße und Verhältnis).

- [ ] erledigt am ______, PR #____

### AP-22 LLM-Pipeline: Prompt-Injection und Ausgabevalidierung
Befund: M7. Aufwand: M. Dateien: `src/processors/transformer_processor.py`, `src/core/llm/schema_registry.py`, Dashboard-Templates mit `innerHTML`.

Schritte: Für alle strukturierten Ausgaben `jsonschema`-Validierung erzwingen und bei Verstoß Fehler statt Teilübernahme; LLM-Ausgaben im Dashboard nur über `textContent` oder nach Escaping rendern; Bedrohungsmodell als Abschnitt in `docs/explanations/` (was fremde Inhalte beeinflussen können, was nicht); kein Ausführen von Aktionen auf Basis von Modellausgaben.

- [ ] erledigt am ______, PR #____

### AP-23 Regelbetrieb
Aufwand: S, wiederkehrend. Monatlich `pip-audit` und `trivy` (durch AP-15 automatisiert), vierteljährlich Rotation von Service-Token und Provider-Keys, nach jedem neuen Endpunkt Abgleich mit der Checkliste in `docs/sicherheitsanalyse-2026-10.md` Abschnitt 4.3. Verantwortlich: ______

- [ ] Rhythmus festgelegt am ______

---

## Zuordnung Befund → Arbeitspaket

| Befund | AP |
|---|---|
| K1 Dashboard ohne Auth | AP-02 (in der Anwendung), AP-00b (Nextcloud-Client), AP-00 (optionaler Sofortschutz), AP-20 (optional mit Proxy) |
| K2 Whitelist spoofbar | AP-00 (Env), AP-01 |
| K3 Fail-open | AP-00 (Env), AP-01 |
| K4 Mongo offen | AP-07 (mitgelieferte Compose), AP-00 (Produktionsinstanz) |
| K5 Key im Code | AP-00 (Rotation), AP-18 |
| K6 Deploy-Token | AP-00 (Rotation), AP-15 |
| H1 SSRF | AP-04 (Vorbereitung), AP-12 |
| H2 TLS aus | AP-04 |
| H3 Path Traversal | AP-03 |
| H4 root, Dev-Server, Image, Pin | AP-06, AP-14, AP-21 |
| H5 Abhängigkeiten | AP-06, AP-15 |
| H6 Limits, Timeouts | AP-04, AP-16, AP-14 |
| H7 Booklet HTML | AP-13 |
| M1 Token-Vergleich, Einzel-Key | AP-01, AP-19 |
| M2 Objekt-Autorisierung | AP-19 |
| M3 Stacktraces, Health | AP-05, AP-01 |
| M4 Header, CSRF, innerHTML | AP-16, AP-02, AP-22 |
| M5 Logging, Token-Speicherung | AP-17 |
| M6 Template-Traversal | AP-03 |
| M7 Prompt-Injection | AP-22, AP-12 |
| M8 CI/CD | AP-15 |
| M9 Konverter-Sandbox | AP-21 |
| M10 tote Konfiguration | AP-05, AP-16 |
| N1–N4 Hygiene | AP-18 |

## Fortschritt

| Phase | Pakete | erledigt |
|---|---|---|
| 0 | AP-00, AP-00b | 0/2 |
| 1 | AP-01 … AP-07 | 0/7 |
| 2 | AP-12 … AP-18 | 0/7 |
| 3 | AP-19 … AP-23 | 0/5 |
