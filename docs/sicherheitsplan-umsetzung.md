# Umsetzungsplan Sicherheit – Common Secretary Services

Grundlage: `docs/sicherheitsanalyse-2026-10.md` (Befunde K1–K6, H1–H7, M1–M10, N1–N4) und die Figma-Übersicht
<https://www.figma.com/design/DEDSmfeQsUX5kfihTW8PJG>.

Dieses Dokument ist der Arbeitsvorrat für Claude-Code-Sitzungen. Jedes Arbeitspaket (AP) ist so geschnitten, dass es in einer Sitzung als eigener Branch und Pull Request abgeschlossen werden kann. Status wird direkt hier gepflegt (Checkboxen), damit eine neue Sitzung ohne Vorwissen weiß, wo sie steht.

## So wird mit diesem Plan gearbeitet

1. Neue Sitzung starten mit: „Setze Arbeitspaket AP-xx aus `docs/sicherheitsplan-umsetzung.md` um.“ Die Sitzung liest zuerst dieses Dokument und den zugehörigen Abschnitt der Analyse.
2. Ein AP = ein Branch `claude/sec-ap-xx-kurzname` = ein PR gegen `main`. Keine Vermischung mehrerer APs in einem PR.
3. Vor dem Push: `pytest .tests src/tests -q` muss grün sein; neue Schutzmaßnahmen bekommen einen Test in `.tests/`.
4. Nach dem Merge: Checkbox hier abhaken, Datum und PR-Nummer eintragen, offene Reste als Notiz ans AP hängen.
5. Reihenfolge: AP-00 und AP-00b zuerst (Betriebsmaßnahmen ohne Code), dann Phase 1 in der angegebenen Reihenfolge, Phase 2 kann parallel laufen, Phase 3 danach.
6. Nichts aus diesem Plan ändert den fachlichen Funktionsumfang. Wo eine Maßnahme ein Verhalten ändert (z. B. fail-closed), wird das in README und `docs/reference/environment-variables.md` nachgezogen.

Legende Aufwand: S = unter einem halben Tag, M = ein Tag, L = mehrere Tage.

---

## Offene Entscheidungen (vor Phase 1 klären)

### E1 – Authentifizierung für das Dashboard (kein US-Identity-Provider) – ENTSCHIEDEN

**Entscheidung (18.10.2026): Die eigene Nextcloud-Instanz wird Anmeldedienst nach OpenID Connect (OIDC).** Vor Traefik sitzt **oauth2-proxy** als Forward-Auth-Schicht und wickelt die Anmeldung mit Nextcloud ab. Flask liest nur den vom Proxy gesetzten Benutzernamen. Ein Basic-Auth-Zugang bleibt als Notzugang und für lokale Setups ohne Proxy.

Begründung:

- Keine neue Benutzerverwaltung: Konten, Gruppen und Zwei-Faktor-Anmeldung kommen aus der bestehenden Nextcloud.
- Kein US-Anbieter: Nextcloud ist self-hosted, die OIDC-App und oauth2-proxy sind Open Source, alle Daten bleiben auf eigener Infrastruktur.
- Wenig Python-Code: Das Dashboard braucht nur einen Modus, der einen Header vom vertrauenswürdigen Proxy auswertet. Den ganzen OIDC-Ablauf übernimmt oauth2-proxy.
- Authelia scheidet aus, weil es selbst Anmeldedienst ist und keinen fremden OIDC-Anbieter wie Nextcloud als Quelle nutzen kann.

Ablauf einer Dashboard-Anmeldung:

```
Browser ──► Traefik ──forwardAuth──► oauth2-proxy  (Cookie gültig?)
   │             │                        │ nein
   │             │                        ▼
   │◄────── Redirect zu Nextcloud /apps/oidc/authorize (Login + 2FA)
   │──────► oauth2-proxy /oauth2/callback  (Code → Token, Gruppe prüfen, Cookie setzen)
   │──────► Traefik ──► Flask mit Header X-Auth-Request-User / -Groups
```

Maschinenzugriff bleibt beim API-Key: KnowledgeScout und andere Clients nutzen weiter Service-Tokens auf `/api/*`. Diese Pfade laufen **nicht** über oauth2-proxy (AP-19 macht daraus mehrere Keys mit Rechten).

Risiken und Gegenmaßnahmen:

| Risiko | Gegenmaßnahme |
|---|---|
| Nextcloud wird sicherheitskritisch: wer Nextcloud übernimmt, kommt ins Dashboard | Zwei-Faktor-Pflicht für die Gruppe `secretary-admins`, Nextcloud aktuell halten, Brute-Force-Schutz aktiv |
| Nextcloud gestört, niemand kommt ins Dashboard | Basic-Auth-Notzugang (`DASHBOARD_AUTH_MODE=basic`) per Env umschaltbar, Passwort im Passwortmanager |
| OIDC-App ist eine Community-App, nicht von der Nextcloud GmbH | Wartungsstand vor Einrichtung prüfen (AP-00b), bei Updates von Nextcloud mittesten |
| Header `X-Auth-Request-User` von außen gefälscht | Flask akzeptiert ihn nur mit `TRUSTED_PROXY_COUNT>0`, Port 5001 ist nicht direkt erreichbar, Traefik entfernt eingehende `X-Auth-Request-*`-Header |
| Gruppen fehlen im Token, jedes Nextcloud-Konto kommt rein | In AP-00b prüfen; Ersatz: Liste erlaubter E-Mail-Adressen in oauth2-proxy |

Geprüfte und verworfene Alternativen (zur Dokumentation): Authelia (kein externer OIDC-Anbieter als Quelle), Zitadel (Schweiz, eigener Dienst nötig), Ory (München, API-first, eigene Login-UI), LemonLDAP::NG (Frankreich, schwergewichtig), Keycloak und Authentik (Hersteller US-Gesellschaften). Zitadel bleibt die Ausweichoption, falls später mehr als ein Dashboard eine zentrale, mandantenfähige Anmeldung braucht.

Entscheidung: `[x]` Nextcloud (OIDC) + oauth2-proxy + Basic-Notzugang, 18.10.2026

### E2 – Reverse-Proxy-Vertrauen

Für die Auth-Middleware (AP-01) muss feststehen, ob der Service immer hinter einem vertrauenswürdigen Proxy läuft, der `X-Forwarded-For` selbst setzt. Bei Dokploy/Traefik: ja. Lokal: nein. Das AP führt `TRUSTED_PROXY_COUNT` (Default 0) ein; in Dokploy auf 1 setzen.

Entscheidung: `[ ]` geklärt, Wert: ___

### E3 – Darf der Generic-Extractor von yt-dlp bleiben?

Die Media-Endpunkte für KnowledgeScout nutzen beliebige Webseiten (Rai, Presseseiten). Eine reine Extractor-Allowlist würde das brechen. Vorschlag in AP-12: Generic bleibt erlaubt, aber nur für öffentliche IP-Ziele (DNS-Prüfung), plus Host-Denylist. Alternativ eine Allowlist aus `MEDIA_ALLOWED_HOSTS`.

Entscheidung: `[ ]` Public-IP-Prüfung (empfohlen) `[ ]` Host-Allowlist

---

## Phase 0 – Sofortmaßnahmen im Betrieb (kein Code, Stunden)

### AP-00 Betrieb absichern
Befunde: K1, K2, K3, K4, K5, K6. Aufwand: S. Zuständig: Betreiber (nicht Claude-Sitzung, aber die Sitzung kann die Checkliste begleiten).

- [ ] Von außen prüfen: sind `https://<host>/`, `/logs`, `/llm-config` und Port 27017 erreichbar? Ergebnis hier notieren: ______
- [ ] In Dokploy/Traefik nur `/api/*` öffentlich routen; `/`, `/logs`, `/llm-config`, `/docs`, `/test*` auf interne IPs oder VPN beschränken (bis AP-02 mit Nextcloud-Anmeldung in Betrieb ist).
- [ ] Produktions-Env: `ALLOW_SWAGGER_WHITELIST` leeren, `ALLOW_LOCALHOST_NO_AUTH=false`, `PYTHONHTTPSVERIFY` nicht gesetzt.
- [ ] `SECRETARY_SERVICE_API_KEY` gesetzt und mindestens 32 Zufallsbytes (`openssl rand -hex 32`). Clients (KnowledgeScout) aktualisieren.
- [ ] Dokploy-Deploy-Token rotieren (K6); neuen Wert als GitHub-Secret `DOKPLOY_DEPLOY_URL` ablegen (wird in AP-15 im Workflow verwendet).
- [ ] LocalBrain/OpenWebUI-Key aus `src/scripts/test_localbrain.py` beim Zielsystem rotieren (K5).
- [ ] Falls `PYTHONHTTPSVERIFY=0` je auf einem Server lief: OpenAI-, Mistral-, OpenRouter-, Voyage-Keys rotieren.
- [ ] MongoDB: Port-Mapping entfernen, Root-User setzen, `MONGODB_URI` mit Credentials; Compose-Änderung kommt mit AP-14, bis dahin manuell.
- [ ] GitHub: Secret Scanning + Push Protection aktivieren, Branch-Protection für `main` (PR-Pflicht, Checks erforderlich).

### AP-00b Nextcloud als Anmeldedienst vorbereiten
Befund: K1 (Voraussetzung für AP-02). Aufwand: S. Zuständig: Betreiber der Nextcloud.

- [ ] Nextcloud-Version und Erreichbarkeit notieren: ______ (URL der Instanz: ______)
- [ ] App **„OIDC Identity Provider“** (App-ID `oidc`) aus dem App Store installieren. Nicht verwechseln mit `user_oidc`, die Nextcloud zum Client eines anderen Anbieters macht. Wartungsstand prüfen: letzte Veröffentlichung, Kompatibilität mit der eingesetzten Nextcloud-Version.
- [ ] Discovery-Adresse ermitteln, die von außen antwortet: `https://<nextcloud>/.well-known/openid-configuration` oder `https://<nextcloud>/index.php/.well-known/openid-configuration`. Den Wert `issuer` aus der Antwort notieren: ______ (wird `OAUTH2_PROXY_OIDC_ISSUER_URL`).
- [ ] Gruppe `secretary-admins` anlegen und berechtigte Personen aufnehmen.
- [ ] Zwei-Faktor-Anmeldung für `secretary-admins` erzwingen (Verwaltung → Sicherheit → Zwei-Faktor-Authentifizierung erzwingen, auf Gruppe beschränken).
- [ ] Unter Verwaltung → Sicherheit → OpenID Connect einen Client anlegen: Name `secretary-dashboard`, Typ vertraulich (confidential), Signatur RS256, Weiterleitungsadresse `https://<secretary-host>/oauth2/callback`. Client-ID und Client-Secret im Passwortmanager ablegen.
- [ ] Prüfen, ob das ID-Token oder der Userinfo-Endpunkt die Gruppen liefert und unter welchem Claim (meist `groups`). Test zum Beispiel über die Weiterleitung mit einem kurzen oauth2-proxy-Probelauf und `--show-debug-on-error`, oder mit einem OIDC-Testclient. Ergebnis: Claim-Name ______, enthält `secretary-admins`: ja / nein.
- [ ] Falls keine Gruppen kommen: Liste der erlaubten E-Mail-Adressen für oauth2-proxy festlegen (`OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE`).
- [ ] Werte für Dokploy vorbereiten (als Secrets, nicht im Repo): `NC_OIDC_CLIENT_ID`, `NC_OIDC_CLIENT_SECRET`, `OAUTH2_COOKIE_SECRET` (genau 32 Zeichen, z. B. `openssl rand -hex 16`), `DASHBOARD_USER`, `DASHBOARD_PASSWORD_HASH` für den Notzugang.

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

### AP-02 Dashboard authentifizieren (Nextcloud über oauth2-proxy)
Befunde: K1, M4 (CSRF). Aufwand: M. Voraussetzung: AP-01 (wegen `TRUSTED_PROXY_COUNT`), für den Produktivbetrieb AP-00b. Dateien: `src/dashboard/app.py`, neue Datei `src/dashboard/auth.py`, neue Datei `docker-compose.auth.yml`, neue Datei `docs/deployment/nextcloud-oidc.md`, `docs/reference/environment-variables.md`, `src/dashboard/templates/base.html` (Benutzername und Abmelden), Tests `.tests/test_dashboard_auth.py`.

Schritte:
1. `src/dashboard/auth.py` mit `DASHBOARD_AUTH_MODE`:
   - `forward` (Produktion): Benutzer kommt aus dem Header `DASHBOARD_FORWARD_USER_HEADER` (Default `X-Auth-Request-User`). Fehlt er, Antwort 401. Wird nur akzeptiert, wenn `TRUSTED_PROXY_COUNT>0`; sonst bricht der Start mit klarer Meldung ab. Optional zweite Prüfung: `DASHBOARD_REQUIRED_GROUP` (z. B. `secretary-admins`) gegen den Header `DASHBOARD_FORWARD_GROUPS_HEADER` (Default `X-Auth-Request-Groups`, kommagetrennt). Die Gruppenprüfung in oauth2-proxy bleibt die maßgebliche, diese ist Verteidigung in der Tiefe.
   - `basic` (Default, lokal und Notzugang): `DASHBOARD_USER` und `DASHBOARD_PASSWORD_HASH` (Werkzeug `generate_password_hash`, scrypt oder pbkdf2), Vergleich zeitkonstant, Antwort 401 mit `WWW-Authenticate`.
   - `off`: nur zusammen mit `ALLOW_INSECURE_NO_AUTH=true`, mit Warnung im Log.
2. Ein `app.before_request` in `src/dashboard/app.py` ruft die Prüfung für alle Pfade außer `/api/*` auf, ausgenommen `/api/doc*` und `/api/swagger.json`, die ebenfalls die Dashboard-Anmeldung verlangen. `/api/health/live` bleibt frei. Der Benutzername kommt in `flask.g.dashboard_user` und in den Log-Kontext.
3. CSRF: für alle Dashboard-POSTs `flask-wtf` CSRFProtect oder ein Double-Submit-Cookie. Die `fetch`-Aufrufe in `llm_config.html`, `dashboard.html` und den Testseiten senden den Token als Header `X-CSRFToken`. `/api/*` bleibt ausgenommen, weil dort der API-Key gilt.
4. Dashboard-Testrouten (`/run_*_test`) senden den Service-Token an die interne API mit, statt auf eine Auth-Ausnahme zu bauen.
5. `base.html`: angemeldeten Benutzer anzeigen; im Modus `forward` ein Link „Abmelden“ auf `/oauth2/sign_out?rd=<DASHBOARD_LOGOUT_REDIRECT>`.
6. `docker-compose.auth.yml` als Overlay mit dem Dienst `oauth2-proxy` und den Traefik-Labels (siehe Vorlage unten). In der Standard-Compose ändert sich nichts.
7. `docs/deployment/nextcloud-oidc.md`: Schritt-für-Schritt-Anleitung aus AP-00b plus diese Konfiguration, Prüfliste für die Abnahme, Umschalten auf den Notzugang, Fehlerbilder (falsche Issuer-URL, fehlender Gruppen-Claim, Cookie-Domain).
8. `docs/reference/environment-variables.md` um alle neuen Variablen ergänzen.

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

Akzeptanz:
- Tests (Flask-Testclient, ohne echten Proxy): `/logs` im Modus `basic` ohne Zugangsdaten 401, mit Zugangsdaten 200; im Modus `forward` mit `TRUSTED_PROXY_COUNT=1` ohne Header 401, mit Header 200, mit falscher Gruppe 403; `forward` ohne `TRUSTED_PROXY_COUNT` verweigert den Start; POST `/clear-logs` ohne CSRF-Token 400; `/api/audio/process` ist von der Dashboard-Prüfung nicht betroffen.
- Abnahme im Betrieb (in `docs/deployment/nextcloud-oidc.md` als Prüfliste): Dashboard leitet auf Nextcloud um; Konto außerhalb von `secretary-admins` wird abgewiesen; `curl -H "X-Auth-Request-User: admin" https://<host>/logs` liefert keinen Zugriff; `/api/*` mit API-Key funktioniert ohne Nextcloud-Anmeldung; Abmelden beendet die Dashboard-Sitzung.

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
Befunde: H4 (root, Dev-Server), K4 (Compose), H6 (Ressourcen). Aufwand: M. Dateien: `Dockerfile`, `docker-compose.yml`, `docker-build-run.bat`, README Deployment-Abschnitt.

Schritte:
1. `gunicorn` in requirements; `CMD ["gunicorn","-w","2","--threads","8","--timeout","900","-b","0.0.0.0:5001","src.dashboard.app:app"]`; `src/main.py` bleibt für lokale Entwicklung.
2. `RUN useradd -r -u 10001 app`, Verzeichnisse `logs temp-processing cache` an `app` übergeben, `USER app`.
3. Compose: Mongo ohne Port-Mapping, `MONGO_INITDB_ROOT_USERNAME/PASSWORD` aus `.env`, `MONGODB_URI` mit Credentials; Service mit `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `deploy.resources.limits` (RAM/CPU), `healthcheck` auf `/api/health/live`.
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
1. `after_request`: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Content-Security-Policy` für das Dashboard (Skripte nur `self` plus verwendete CDNs, danach schrittweise verschärfen), `Strict-Transport-Security` nur wenn `TRUSTED_PROXY_COUNT>0`.
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
2. `.env.example`: Atlas-Hostname durch `cluster.example.mongodb.net` und Benutzerpfad durch `<pfad>` ersetzen; gleiches in `docs/handover-ks-transkript-verlaesslichkeit.md`.
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

### AP-20 Optional: OIDC direkt in Flask oder zentraler Login für weitere Dienste
Befund: K1 (Ausbau). Aufwand: M. Nur nötig, wenn einer der beiden Fälle eintritt.

- **Fall A, oauth2-proxy soll entfallen:** `DASHBOARD_AUTH_MODE=oidc` mit `OIDC_ISSUER` (Nextcloud-Issuer aus AP-00b), `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REQUIRED_GROUP`; Anmeldung über Authlib (Authorization Code mit PKCE), Sitzungs-Cookie `Secure`, `HttpOnly`, `SameSite=Lax`, Gruppenprüfung aus dem Claim, Abmelden über `end_session_endpoint`, falls die Nextcloud-App ihn anbietet. Für die Entwicklung eine Nextcloud mit OIDC-App in `docker-compose.dev-auth.yml`.
- **Fall B, weitere Dienste (z. B. KnowledgeScout) sollen denselben Login nutzen:** je Dienst einen eigenen OIDC-Client in Nextcloud anlegen, gleiche Gruppenlogik. Reicht Nextcloud dafür nicht mehr (Mandanten, Service-Accounts, feinere Rollen), Umstieg auf Zitadel prüfen; die Flask-Seite bleibt gleich, nur der Issuer ändert sich.

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
| K1 Dashboard ohne Auth | AP-00 (Netz), AP-00b (Nextcloud), AP-02, AP-20 (optional) |
| K2 Whitelist spoofbar | AP-00 (Env), AP-01 |
| K3 Fail-open | AP-00 (Env), AP-01 |
| K4 Mongo offen | AP-00, AP-14 |
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
| 1 | AP-01 … AP-06 | 0/6 |
| 2 | AP-12 … AP-18 | 0/7 |
| 3 | AP-19 … AP-23 | 0/5 |
