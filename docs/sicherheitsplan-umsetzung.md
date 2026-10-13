# Umsetzungsplan Sicherheit – Common Secretary Services

Grundlage: `docs/sicherheitsanalyse-2026-10.md` (Befunde K1–K6, H1–H7, M1–M10, N1–N4) und die Figma-Übersicht
<https://www.figma.com/design/DEDSmfeQsUX5kfihTW8PJG>.

Dieses Dokument ist der Arbeitsvorrat für Claude-Code-Sitzungen. Jedes Arbeitspaket (AP) ist so geschnitten, dass es in einer Sitzung als eigener Branch und Pull Request abgeschlossen werden kann. Status wird direkt hier gepflegt (Checkboxen), damit eine neue Sitzung ohne Vorwissen weiß, wo sie steht.

## So wird mit diesem Plan gearbeitet

1. Neue Sitzung starten mit: „Setze Arbeitspaket AP-xx aus `docs/sicherheitsplan-umsetzung.md` um.“ Die Sitzung liest zuerst dieses Dokument und den zugehörigen Abschnitt der Analyse.
2. Ein AP = ein Branch `claude/sec-ap-xx-kurzname` = ein PR gegen `main`. Keine Vermischung mehrerer APs in einem PR.
3. Vor dem Push: `pytest .tests src/tests -q` muss grün sein; neue Schutzmaßnahmen bekommen einen Test in `.tests/`.
4. Nach dem Merge: Checkbox hier abhaken, Datum und PR-Nummer eintragen, offene Reste als Notiz ans AP hängen.
5. Reihenfolge: AP-00 zuerst (Betriebsmaßnahmen ohne Code), dann Phase 1 in der angegebenen Reihenfolge, Phase 2 kann parallel laufen, Phase 3 danach.
6. Nichts aus diesem Plan ändert den fachlichen Funktionsumfang. Wo eine Maßnahme ein Verhalten ändert (z. B. fail-closed), wird das in README und `docs/reference/environment-variables.md` nachgezogen.

Legende Aufwand: S = unter einem halben Tag, M = ein Tag, L = mehrere Tage.

---

## Offene Entscheidungen (vor Phase 1 klären)

### E1 – Authentifizierung für das Dashboard (kein US-Identity-Provider)

Die Analyse fordert eine Anmeldung für das Dashboard (K1). Der Betreiber möchte keinen US-amerikanischen Identity Provider (also nicht Auth0/Okta, Microsoft Entra, Google, Clerk, AWS Cognito, Firebase). Geeignete Alternativen, alle Open Source und selbst betreibbar, Daten bleiben auf eigener Infrastruktur:

| Option | Herkunft | Betrieb | Passt, wenn … | Aufwand im Projekt |
|---|---|---|---|---|
| **Authelia** (Forward-Auth vor Traefik) | Community-Projekt, kein Unternehmen dahinter | Ein Container neben dem Service, Nutzer in YAML/LDAP, TOTP/WebAuthn eingebaut | Dokploy/Traefik bleibt die Eingangstür und das Dashboard braucht nur „wer darf rein“ ohne eigene Nutzerverwaltung im Code | **S**: keine Code-Änderung, nur Compose-Labels und Authelia-Konfiguration |
| **Zitadel** | Schweiz (Zitadel AG), Apache 2.0 | Self-hosted (Postgres) oder Cloud mit Region CH/EU | Ein OIDC-Provider für mehrere eigene Dienste (KnowledgeScout, Secretary, weitere) gewünscht, Mandanten, Service-Accounts für Maschinen | **M**: OIDC-Login in Flask über Authlib, Rollen aus Token |
| **Ory Kratos + Hydra** (oder Ory Network, EU-Region) | Ursprung und Team in München, Apache 2.0; Gesellschaftsstruktur vor Entscheidung prüfen | Self-hosted, API-first, kein fertiges Admin-UI | Entwicklerzentriert, eigene Login-UI akzeptabel | **M–L** |
| **Keycloak** | CNCF-Projekt, maßgeblich von Red Hat (IBM, US-Konzern) entwickelt; self-hosted, keine Daten beim Hersteller | Ein Container, Java, viel Funktion | Schon im Einsatz oder Enterprise-Features (SAML, LDAP-Föderation) nötig | **M**; Vorbehalt: Hersteller ist US-amerikanisch, auch wenn kein Datenabfluss stattfindet |
| **Authentik** | Open Source, Firma Authentik Security Inc. ist US-registriert, Gründer und Team in Deutschland | Self-hosted, modernes Admin-UI, Forward-Auth und OIDC | Komfortables UI gewünscht und der Firmensitz nicht stört | **M** |
| **LemonLDAP::NG** | Frankreich, Open Source | Self-hosted, Perl | Französischer Behördenstandard, sonst eher schwergewichtig | **L** |
| Vorhandener Dienst als OIDC-Provider (**Nextcloud**, **Forgejo/Gitea**, **GitLab self-hosted**) | EU-Projekte | Bereits vorhanden | Wenn es im bCommonsLAB schon ein Nextcloud oder Forgejo gibt | **M** |

Hinweis: Firmensitz und Eigentümerstruktur ändern sich. Vor der Entscheidung beim gewählten Anbieter aktuell nachsehen.

**Empfehlung:**

- **Jetzt (Phase 1, AP-02):** Forward-Auth mit **Authelia** vor `/` (Dashboard) und `/api/doc`. Das schließt K1 ohne eine Zeile Python, bringt Zwei-Faktor-Anmeldung mit und ist mit Traefik/Dokploy eine reine Konfigurationsfrage. Als Rückfallebene zusätzlich im Code ein Dashboard-Secret (Basic Auth) hinter `DASHBOARD_AUTH_MODE=basic`, damit lokale und Docker-Compose-Setups ohne Proxy nicht offen sind.
- **Mittelfristig (Phase 3, AP-20):** Wenn mehrere eigene Dienste einen gemeinsamen Login brauchen, **Zitadel** (CH) oder **Ory** (DE) als OIDC-Provider; das Dashboard bekommt dann einen OIDC-Login über Authlib, Authelia kann als Forward-Auth-Schicht gegen denselben Provider weiterlaufen oder entfällt.
- **Maschinenzugriff bleibt API-Key:** KnowledgeScout und andere Clients authentifizieren sich weiter mit Service-Tokens (AP-19 macht daraus mehrere Keys mit Rechten). OIDC Client-Credentials ist dafür später möglich, aber nicht nötig.

Entscheidung: `[ ]` Authelia + Basic-Fallback (empfohlen) `[ ]` Zitadel `[ ]` Ory `[ ]` andere: ______ (Datum, Name)

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
- [ ] In Dokploy/Traefik nur `/api/*` öffentlich routen; `/`, `/logs`, `/llm-config`, `/docs`, `/test*` auf interne IPs oder VPN beschränken (bis AP-02 fertig ist).
- [ ] Produktions-Env: `ALLOW_SWAGGER_WHITELIST` leeren, `ALLOW_LOCALHOST_NO_AUTH=false`, `PYTHONHTTPSVERIFY` nicht gesetzt.
- [ ] `SECRETARY_SERVICE_API_KEY` gesetzt und mindestens 32 Zufallsbytes (`openssl rand -hex 32`). Clients (KnowledgeScout) aktualisieren.
- [ ] Dokploy-Deploy-Token rotieren (K6); neuen Wert als GitHub-Secret `DOKPLOY_DEPLOY_URL` ablegen (wird in AP-15 im Workflow verwendet).
- [ ] LocalBrain/OpenWebUI-Key aus `src/scripts/test_localbrain.py` beim Zielsystem rotieren (K5).
- [ ] Falls `PYTHONHTTPSVERIFY=0` je auf einem Server lief: OpenAI-, Mistral-, OpenRouter-, Voyage-Keys rotieren.
- [ ] MongoDB: Port-Mapping entfernen, Root-User setzen, `MONGODB_URI` mit Credentials; Compose-Änderung kommt mit AP-14, bis dahin manuell.
- [ ] GitHub: Secret Scanning + Push Protection aktivieren, Branch-Protection für `main` (PR-Pflicht, Checks erforderlich).

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

### AP-02 Dashboard authentifizieren
Befunde: K1, M4 (CSRF). Aufwand: M. Dateien: `src/dashboard/app.py`, neue Datei `src/dashboard/auth.py`, `docker-compose.yml`, `docs/deployment/authelia.md` (neu), Templates für Logout-Link.

Schritte:
1. `DASHBOARD_AUTH_MODE` mit Werten `basic` (Default), `forward` (Proxy liefert `Remote-User`-Header, nur zusammen mit `TRUSTED_PROXY_COUNT>0` akzeptiert), `off` (nur mit `ALLOW_INSECURE_NO_AUTH=true`).
2. `basic`: `DASHBOARD_USER` und `DASHBOARD_PASSWORD_HASH` (Argon2 oder Werkzeug `pbkdf2`), geprüft in einem `app.before_request`, das alle Pfade außer `/api/*` (eigene Middleware) und `/api/health/live` abdeckt.
3. `forward`: Header `Remote-User` muss vorhanden sein, sonst 401; Nutzername ins Log-Kontext.
4. CSRF: für alle Dashboard-POSTs ein Double-Submit-Cookie oder `flask-wtf` CSRFProtect; die Fetch-Aufrufe in `llm_config.html` senden den Token als Header.
5. Dashboard-Testrouten (`/run_*_test`) senden den Service-Token an die interne API mit, statt auf eine Auth-Ausnahme zu bauen.
6. Beispiel-Compose-Ausschnitt und Traefik-Labels für Authelia in `docs/deployment/authelia.md`, inklusive `access_control` (Dashboard: zwei Faktoren; `/api/doc`: ein Faktor).

Akzeptanz: Tests: `/logs` ohne Auth 401, mit Basic 200; POST `/clear-logs` ohne CSRF-Token 400; `forward` ohne `TRUSTED_PROXY_COUNT` wird beim Start abgelehnt.

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

### AP-20 OIDC-Login für das Dashboard (je nach E1)
Befund: K1 (Ausbau). Aufwand: M. Dateien: `src/dashboard/auth.py`, `requirements.txt` (`authlib`), Templates.

Schritte: `DASHBOARD_AUTH_MODE=oidc` mit `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`; Login-Flow über Authlib (`authorization_code` + PKCE), Session-Cookie `Secure, HttpOnly, SameSite=Lax`, Rollenprüfung aus Claim `roles` oder Gruppen; Logout über `end_session_endpoint`. Getestet gegen den in E1 gewählten Provider (Zitadel oder Ory in Docker-Compose für Entwicklung).

- [ ] erledigt am ______, PR #____

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
| K1 Dashboard ohne Auth | AP-00 (Netz), AP-02, AP-20 |
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
| 0 | AP-00 | 0/1 |
| 1 | AP-01 … AP-06 | 0/6 |
| 2 | AP-12 … AP-18 | 0/7 |
| 3 | AP-19 … AP-23 | 0/5 |
