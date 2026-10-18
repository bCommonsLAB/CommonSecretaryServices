# Sicherheitsanalyse Common Secretary Services

Stand: 13. Oktober 2026, Branch `main`, Commit `7e3789f` (Version 0.1.73).
Methode: manuelle Code-Durchsicht aller Einstiegspunkte (Flask-App, API-Blueprint, Dashboard, Worker, Prozessoren), Docker/Compose, CI-Workflows, Git-History-Scan auf Geheimnisse, `pip-audit` gegen `requirements.txt`. Kein Laufzeittest gegen eine Produktionsinstanz.

## 1. Gesamtbild

Die API-Schicht unter `/api` hat eine Token-Authentifizierung und ein bewusstes Secrets-Handling (Keys nur aus Umgebungsvariablen, nie in `config.yaml` oder im Frontend). Das ist eine gute Basis. Die gravierenden Probleme liegen daneben:

1. Das **Dashboard** (`/`, `/logs`, `/llm-config/*`, `/clear-logs`, `/docs`) hat **keinerlei Authentifizierung**. Es erlaubt Lesen der Logs (inklusive Transkripte und Formulardaten), Ändern der LLM-Konfiguration, Löschen von Modellen und das Auslösen kostenpflichtiger LLM-Tests.
2. Die **API-Auth ist umgehbar**, sobald die in der README empfohlene Whitelist gesetzt ist, weil `Host`, `X-Forwarded-For` und `X-Real-IP` ungeprüft als Client-IP gewertet werden. Ohne gesetzten Token ist die API komplett offen (fail-open).
3. **MongoDB** läuft laut `docker-compose.yml` ohne Auth und ist auf dem Host-Port 27017 veröffentlicht.
4. Fast jeder Endpunkt holt **vom Client angegebene URLs serverseitig** ab (Webseiten, PDFs, Audio, Bilder, Webhooks, yt-dlp). Es gibt keinen Schutz gegen Server-Side Request Forgery (SSRF) auf interne Dienste.
5. **TLS-Verifikation** ist für yt-dlp fest abgeschaltet und kann per `PYTHONHTTPSVERIFY=0` global für den ganzen Prozess (auch OpenAI, Mistral, Mongo) deaktiviert werden.
6. Zwei **Geheimnisse liegen im Repository**: ein API-Key in `src/scripts/test_localbrain.py` und die Deploy-Webhook-URL mit Token im CI-Workflow.
7. Abhängigkeiten mit **41 bekannten Schwachstellen** (vor allem Pillow, das Uploads verarbeitet), Container als **root**, Werkzeug-**Dev-Server** in Produktion.

Wenn die Produktionsinstanz samt Dashboard öffentlich erreichbar ist, ist das aus meiner Sicht ein akuter Zustand, der zuerst an der Netzwerkgrenze (Reverse Proxy, Firewall) entschärft werden sollte, bevor Code geändert wird.

## 2. Befunde

Schweregrade: **Kritisch** (unmittelbar ausnutzbar, hoher Schaden), **Hoch** (ausnutzbar mit Token oder unter plausibler Konfiguration), **Mittel** (Härtung, Informationsabfluss, Defense in Depth), **Niedrig** (Hygiene).

### Kritisch

**K1 – Dashboard ohne Authentifizierung**
Nur der API-Blueprint registriert eine Token-Prüfung (`src/api/routes/__init__.py:111`). Die Dashboard-Blueprints (`src/dashboard/app.py`, `src/dashboard/routes/*`) haben keine. Ungeschützt sind unter anderem:

| Route | Wirkung |
|---|---|
| `GET /logs` (`log_routes.py:189`) | Vollständige Logdatei lesbar, inklusive Formulardaten, Transkriptausschnitten, Webhook-URLs, Dateipfaden |
| `POST /clear-logs` (`main_routes.py:223`) | Logs löschen (Spurenbeseitigung) |
| `POST /llm-config/api/save` (`llm_config_routes.py:251`) | Schreibt `config/config.yaml` auf der Platte um |
| `POST /llm-config/api/import-config` (`:1618`) | YAML-Upload, der die Modell-Konfiguration in MongoDB ersetzt |
| `POST/PUT/DELETE /llm-config/api/models…` (`:1066`, `:1143`, `:1217`) | Modelle anlegen, ändern, löschen |
| `PUT /llm-config/api/use-cases/<uc>/current-model` (`:1487`) | Produktiv genutztes Modell je Use-Case umstellen (z. B. auf ein teures) |
| `POST /llm-config/api/test`, `/test-cases/batch-execute` (`:338`, `:736`) | Löst echte, bezahlte LLM-Aufrufe über alle Modelle aus |
| `POST /run_audio_test` u. a. (`main_routes.py:169-185`) | Startet Verarbeitung über die interne API |

Angriffsszenarien: Datenabfluss über Logs, Kostenexplosion über Batch-Tests, Manipulation der Modellwahl, Denial of Service. Weil es keine Sessions gibt, kann zusätzlich jede fremde Website im Browser eines Admins diese POSTs auslösen (CSRF), selbst wenn das Dashboard nur intern erreichbar ist.

**K2 – API-Whitelist und Localhost-Ausnahme per Header umgehbar**
`src/api/routes/__init__.py:146-176`: Die Kandidaten-IPs enthalten `request.host`, `X-Forwarded-For` und `X-Real-IP`. Alle drei setzt der Client selbst, sofern kein Reverse Proxy sie überschreibt. Mit `ALLOW_SWAGGER_WHITELIST=127.0.0.1` (README Zeile 319 und 361 empfehlen genau das) genügt:

```
curl -H "X-Forwarded-For: 127.0.0.1" https://host/api/audio/process ...
```

und der API-Key wird nicht mehr geprüft. Die Whitelist gilt zudem nicht nur für Swagger, sondern für **alle** `/api`-Routen. Die Localhost-Ausnahme (`:127-144`) prüft ebenfalls den `Host`-Header. Die Doku verspricht CIDR-Unterstützung (`docs/reference/environment-variables.md:55`), der Code macht String-Vergleich, so dass `192.168.1.0/24` schlicht nie matcht und Betreiber zu breiteren Einträgen greifen.

**K3 – Fail-open ohne Token**
`src/api/routes/__init__.py:171-178`: Ist `SECRETARY_SERVICE_API_KEY` nicht gesetzt, werden alle Requests durchgelassen. Ein vergessenes Secret im Deployment öffnet die komplette API.

**K4 – MongoDB ohne Authentifizierung, Port veröffentlicht**
`docker-compose.yml:21-23`: `mongo:6` ohne `MONGO_INITDB_ROOT_*`, Port `27017:27017` auf dem Host. In Mongo liegen Jobs mit Ergebnissen (Transkripte, extrahierte Dokumente), Webhook-Tokens der Aufrufer (`webhook.token`), Cache-Inhalte, Metriken mit IP und User-Agent sowie die LLM-Konfiguration.

**K5 – API-Key im Quellcode und in der Git-History**
`src/scripts/test_localbrain.py:5` und `src/scripts/test_openwebui.py:251` enthalten `sk-535b…` (gekürzt) im Klartext. Der Key ist seit dem Commit in der History und damit bei einem öffentlichen Repository als kompromittiert zu betrachten.

**K6 – Deploy-Webhook mit Token im Workflow**
`.github/workflows/ci-main.yml:93`: `curl https://dokploy.bcommonslab.org/api/deploy/compose/<token>` (Token im Klartext in der Datei). Wer das Repo lesen kann, kann jederzeit ein Deployment auslösen.

### Hoch

**H1 – Server-Side Request Forgery (SSRF) an vielen Stellen**
Vom Client gelieferte URLs werden ohne Ziel-Prüfung abgerufen:

| Stelle | Aufruf |
|---|---|
| `src/api/routes/media_routes.py` (`/api/media/resolve`, `/download`) | yt-dlp mit Generic-Extractor holt jede URL, folgt Redirects, lädt bis zur Dateigröße |
| `src/processors/pdf_processor.py:453, 1498, 1544` | `requests.head/get` ohne Timeout |
| `src/processors/audio_processor.py:397` | `requests.get(stream=True)` ohne Timeout |
| `src/api/routes/image_analyzer_routes.py:430` | `requests.get(url)` |
| `src/processors/imageocr_processor.py:408` | `requests.get(url)` |
| `src/processors/transformer_processor.py:1914, 2288` | Webseiten-Transformation |
| `src/processors/session_processor.py:260` | Session-Seite abrufen |
| `src/processors/booklet/images.py:51` | Bild-URLs |
| Alle Handler unter `src/core/processing/handlers/*` und `secretary_worker_manager.py:366` | `requests.post(callback_url, headers={Authorization: Bearer <token>})` |

Damit lassen sich interne Dienste (Mongo-HTTP-Ports, Cloud-Metadaten `169.254.169.254`, Ollama unter `localhost:11434`, andere Container im Compose-Netz) ansprechen; der Webhook-Pfad erlaubt sogar POST mit frei wählbarem Body und Bearer-Header an beliebige interne Ziele. Mit K1 bis K3 ist das ohne Token erreichbar.

**H2 – TLS-Verifikation deaktiviert**
`src/processors/video_processor.py:166-168`: `nocheckcertificate: True`, `legacy_server_connect: True` fest kodiert; ebenso `config/config.yaml` (`youtube.ydl_opts.nocheckcertificate: true`). `src/main.py:62-66` und `media_routes.py:47-49` patchen bei `PYTHONHTTPSVERIFY=0` den globalen SSL-Kontext, was dann für OpenAI-, Mistral-, OpenRouter-, Voyage- und Mongo-Atlas-Verbindungen gilt: API-Keys sind im Netz per Man-in-the-Middle abgreifbar. `video_processor.py:366` setzt zusätzlich `verify=False`.

**H3 – Path Traversal über Upload-Dateinamen**
`src/api/routes/office_routes.py:103-108`: `os.path.join(base_dir, file.filename)` mit dem rohen Client-Dateinamen. Ein Name wie `../../app/src/main.py` schreibt die hochgeladene Datei an beliebige Stellen, im Container als root. Gleiches in `src/processors/video_processor.py:759` und `:1019` (`working_dir / video_source.file_name`). `src/api/routes/imageocr_routes.py:174` legt Temp-Dateien im Quellcode-Verzeichnis `src/api/routes/` ab.

**H4 – Container und Laufzeit**
`Dockerfile`: Basisimage `python:3.12.1-slim` (Stand Dezember 2023, zahlreiche offene CVEs in Python und Debian-Paketen), kein `USER`, Prozess läuft als root. `pip install --upgrade yt-dlp` (Zeile 28) überschreibt den in `requirements.txt` begründet gesetzten Pin, jeder Build zieht eine andere Version. `CMD python -m src.main` startet den Werkzeug-Entwicklungsserver (`app.run`, `src/main.py:81`), der nicht für Produktion gedacht ist (keine Worker-Isolation, keine Request-Timeouts, keine Header-Limits).

**H5 – Verwundbare und ungepinnte Abhängigkeiten**
`pip-audit` am 13.10.2026:

| Paket | Version | Advisories | Fix |
|---|---|---|---|
| pillow | 11.1.0 | 30 (Bildparser, verarbeitet Uploads und OCR-Eingaben) | 12.3.0 |
| pymongo | 4.13.2 | 4 CVEs | 4.18.2 |
| flask | 3.0.2 | 1 | 3.1.3 |
| pytest | 8.1.1 | 1 | 9.0.3 |

Ungepinnt (`>=`): requests, openai, PyMuPDF, pypdf, python-magic, pydub, beautifulsoup4, numpy, pandas, psutil, voyageai, jsonschema, markdown, werkzeug (transitiv). Builds sind nicht reproduzierbar, Supply-Chain-Vorfälle (siehe die Notiz zu mistralai 2.4.6 in `requirements.txt`) treffen ungebremst.

**H6 – Keine Ressourcen- und Rate-Begrenzung**
`src/core/rate_limiting.py` existiert, wird aber nirgends eingebunden; `rate_limiting.enabled: true` in `config.yaml` ist wirkungslos. Jeder Request kann ffmpeg, LibreOffice, Whisper oder LLM-Aufrufe auslösen. `requests.get(stream=True)` ohne Timeout (`pdf_processor.py:453/1498/1544`, `audio_processor.py:397`) blockiert Worker unbegrenzt; die Größenprüfung vertraut dem `Content-Length`-Header, der beim Streamen nicht gilt.

**H7 – HTML-Injection im Booklet-Renderer (WeasyPrint)**
`src/processors/booklet/render.py:63-69`: `page.markdown` aus dem Request wird mit python-markdown in `Markup` gewandelt. python-markdown lässt rohes HTML durch, Jinja escaped `Markup` nicht. WeasyPrint rendert mit `base_url=work_dir` und dem Standard-URL-Fetcher, der `file://` und `http://` erlaubt. Ein Booklet mit

```html
<img src="file:///app/.env">  oder  <img src="http://169.254.169.254/latest/meta-data/">
```

bettet Dateiinhalte beziehungsweise interne Antworten ins PDF ein (Local File Inclusion und SSRF).

### Mittel

**M1 – Token-Handling**
`src/api/routes/__init__.py:186`: `token != _SERVICE_TOKEN` ist nicht zeitkonstant (`hmac.compare_digest` verwenden). Ein einziger statischer Key für alle Clients, keine Rotation, kein Audit pro Aufrufer.

**M2 – Keine Autorisierung auf Objektebene**
Mit gültigem Token sind alle Jobs lesbar: `/api/jobs/<id>`, `/stream`, `/download-archive`, `/api/booklet/jobs/<id>/assets/<file>`. `user_id` ist ein freies Feld ohne Bindung. Job-IDs sind UUIDs und schwer zu raten, für einen Mehrmandanten-Betrieb (KnowledgeScout und weitere Clients) reicht das aber nicht.

**M3 – Informationsabfluss**
Stacktraces in API-Antworten: `pdf_routes.py:592/789/962`, `session_routes.py:168/279/340`, `common_routes.py:153`. `str(e)` in nahezu allen 500-Antworten. `/api/health/*` ist von der Auth ausgenommen und verrät Provider, Modellnamen, Erreichbarkeit und das OpenRouter-Restguthaben (`src/core/llm/health.py:475`). `src/main.py:56-59` druckt Cookie-Dateipfade; `dashboard/app.py:115` loggt die rohe Whitelist.

**M4 – Fehlende Browser-Schutzmechanismen**
Keine Security-Header (CSP, `X-Frame-Options`, `X-Content-Type-Options`, HSTS), kein CSRF-Schutz im Dashboard, `PREFERRED_URL_SCHEME='http'`. Das Dashboard rendert viele API-Daten per `innerHTML` (`llm_config.html`, `llm_models_overview.html`); Modellnamen und Beschreibungen kommen aus Mongo beziehungsweise dem YAML-Import und sind damit potenzielle XSS-Vektoren.

**M5 – Logging und Datenschutz**
`config.yaml`: Level `DEBUG`, 120 MB × 5 Dateien. `office_routes.py:120-125` loggt das komplette Formular (nur `callback_token` maskiert). Transkripte, Webseiten-Inhalte, Webhook-URLs landen im Log, das ohne Auth lesbar ist (K1). Callback-Tokens der Aufrufer liegen im Klartext in Mongo (`webhook.token`) und werden mit `Sende Error-Webhook an <url>` in Job-Logs geschrieben.

**M6 – Template-Name ohne Validierung**
`src/utils/template_utils.py:92`: `os.path.join(templates_dir, f"{template_name}.md")`. Mit `template=../../docs/irgendwas` lassen sich beliebige `.md`-Dateien des Servers in den LLM-Prompt laden.

**M7 – Prompt-Injection durch fremde Inhalte**
Webseiten, PDFs, Audio und frei übermittelte `template_content` fließen in LLM-Prompts; Ergebnisse landen in Mongo, Webhooks und im KnowledgeScout-Archiv. Fremde Inhalte können so Modellausgaben steuern. Das ist konzeptbedingt nicht vollständig vermeidbar, aber die Ausgaben sollten als untrusted behandelt werden (Schema-Validierung, kein ungeprüftes HTML-Rendering, keine Aktionen aus LLM-Output).

**M8 – CI/CD-Härtung**
`ci-main.yml`: `cbrgm/semver-bump-action@main` ungepinnt (ein kompromittierter Fork-Commit hätte Zugriff auf `CI_PAT` und `GITHUB_TOKEN` mit `contents/packages/actions: write`); `CI_PAT` ist ein persönlicher Token mit Push auf `main`; der PR-Check (`checks.yml`) baut nur das Image, führt weder Tests noch Linter noch Security-Scans aus; keine Dependabot-Konfiguration, kein CODEOWNERS, kein `SECURITY.md`.

**M9 – Verarbeitung fremder Dokumente**
LibreOffice headless (`office_via_pdf_handler.py:62`, `pdf_processor.py:1197`), ffmpeg, Tesseract, poppler, PyMuPDF, python-docx/pptx/openpyxl parsen Angreifer-Dateien im selben Prozess beziehungsweise Container wie die API mit allen Secrets. Office-Dateien sind ZIPs (Zip-Bomb-Risiko, openpyxl lädt komplett in den Speicher). Dateityp wird über die Endung bestimmt, nicht über den Inhalt.

**M10 – Irreführende oder tote Konfiguration**
`config.yaml` `server.debug: true` wird nirgends ausgewertet; `rate_limiting` ebenfalls nicht. Die Dashboard-Testrouten (`dashboard/routes/tests/audio_test.py:85`) rufen die eigene API ohne Token auf und funktionieren nur bei abgeschalteter Auth oder Whitelist, was zu unsicheren Konfigurationen verleitet.

### Niedrig

- **N1** `.env.example:7` enthält den echten Atlas-Hostnamen `bcommonslab.kh9co.mongodb.net`; `.env.example:19` und `docs/handover-ks-transkript-verlaesslichkeit.md:156` enthalten einen Windows-Benutzerpfad.
- **N2** Repo-Hygiene: `.obsidian/` (inklusive Plugin-JS und `workspace.json`), `.vscode/`, das MkDocs-Build `site/` und zwei Test-PDFs (4 MB) sind eingecheckt, obwohl `.gitignore` einige davon nennt.
- **N3** yt-dlp-Cookie-Dateien (`YTDLP_COOKIES_FILE`) sind Browser-Session-Cookies des Betreibers auf dem Server; über die Media-Endpunkte können Aufrufer damit auf Inhalte zugreifen, die nur diesem Konto sichtbar sind.
- **N4** MD5 als Cache-Key für Bildinhalte (`image_analyzer_routes.py:437`): theoretisches Cache-Poisoning über Kollisionen. SHA-256 kostet nichts extra.

### Was bereits gut ist

- Token-Auth für `/api` mit zwei Header-Varianten, klar dokumentiert.
- API-Keys ausschließlich aus Umgebungsvariablen; UI zeigt nur `has_api_key`.
- `.env` in `.gitignore` und `.dockerignore`; kein echter LLM-Key in der History gefunden.
- `yaml.safe_load` durchgängig, kein `eval`/`exec`/`pickle`, `subprocess` immer als Liste ohne `shell=True`.
- Booklet-Asset-Download und Docs-Auslieferung mit korrekter Pfadprüfung (`booklet_routes.py:199-204`, `send_from_directory`).
- Upload-Limit über `MAX_CONTENT_LENGTH`; mistralai-Pin mit Begründung gegen eine kompromittierte Version.

## 3. Maßnahmenplan in Reihenfolge

Die Reihenfolge folgt dem Verhältnis von Risiko zu Aufwand: zuerst das, was ohne Code-Änderung sofort schließt, dann kleine Code-Fixes mit großer Wirkung, dann strukturelle Härtung.

### Phase 0 – Sofort, ohne Code-Änderung (Stunden)

1. **Erreichbarkeit prüfen.** Von außen testen, ob Dashboard (`/`, `/logs`, `/llm-config`) und Port 27017 der Produktionsinstanz erreichbar sind. Falls ja: im Reverse Proxy (Dokploy/Traefik) nur `/api/*` durchreichen, alles andere auf ein internes Netz oder VPN beschränken; Mongo-Port in der Firewall schließen.
2. **Auth-Konfiguration bereinigen.** In Produktion `ALLOW_SWAGGER_WHITELIST` leeren und `ALLOW_LOCALHOST_NO_AUTH=false` setzen. Sicherstellen, dass `SECRETARY_SERVICE_API_KEY` gesetzt ist (mindestens 32 zufällige Bytes, z. B. `openssl rand -hex 32`).
3. **Secrets rotieren.** Dokploy-Deploy-Token (K6), LocalBrain/OpenWebUI-Key (K5). Falls jemals `PYTHONHTTPSVERIFY=0` auf einem Server lief: OpenAI-, Mistral-, OpenRouter-, Voyage-Keys vorsorglich rotieren.
4. **MongoDB absichern.** Port-Mapping aus `docker-compose.yml` entfernen, `MONGO_INITDB_ROOT_USERNAME/PASSWORD` setzen, `MONGODB_URI` mit Credentials.

### Phase 1 – Diese Woche, kleine Code-Änderungen mit großer Wirkung (1 bis 3 Tage)

5. **Dashboard authentifizieren.** Ein `app.before_request` in `src/dashboard/app.py`, das für alle Nicht-`/api`-Pfade ein eigenes Dashboard-Secret (Basic Auth oder Cookie-Session mit Login) verlangt; zusätzlich `DASHBOARD_ENABLED=false` als Schalter für reine API-Deployments. Testrouten des Dashboards den API-Token mitgeben lassen oder entfernen.
6. **Auth-Middleware fixen** (`src/api/routes/__init__.py`): fail-closed (Start abbrechen ohne Token, außer explizit `ALLOW_INSECURE_NO_AUTH=true`); Whitelist nur auf `request.remote_addr` und nur für `/api/doc` und `/api/swagger.json`; `X-Forwarded-For` nur über `werkzeug.middleware.proxy_fix.ProxyFix(x_for=1)` und nur, wenn `TRUSTED_PROXY=true` gesetzt ist; `hmac.compare_digest`; Doku zu CIDR korrigieren oder `ipaddress`-Netze implementieren.
7. **Dateinamen entschärfen.** `werkzeug.utils.secure_filename` beziehungsweise `uuid + Suffix` in `office_routes.py:103`, `video_processor.py:759/1019`; `imageocr_routes.py:174` auf `tempfile.mkdtemp` umstellen. `template_name` in `template_utils.py:92` auf `^[A-Za-z0-9_-]+$` prüfen.
8. **Timeouts und Größenlimits.** Jedem `requests`-Aufruf `timeout=(5, 60)` geben; beim Streamen die gelesenen Bytes zählen und bei `max_file_size` abbrechen, nicht dem `Content-Length` vertrauen.
9. **TLS-Verifikation wieder einschalten.** `nocheckcertificate`, `legacy_server_connect`, `verify=False` entfernen; `PYTHONHTTPSVERIFY=0` nur noch akzeptieren, wenn gleichzeitig `FLASK_ENV=development`, und mit lauter Warnung. Windows-Probleme über `SSL_CERT_FILE` mit `certifi` lösen.
10. **Fehlerausgaben bereinigen.** Tracebacks nur loggen, in Antworten generische Codes; `/api/health/live` öffentlich lassen, alle anderen Health-Routen hinter den Token.
11. **Abhängigkeiten aktualisieren.** pillow ≥ 12.3.0, pymongo ≥ 4.18.2, flask ≥ 3.1.3, pytest ≥ 9.0.3; die `pip install --upgrade yt-dlp`-Zeile aus dem `Dockerfile` entfernen; Basisimage auf das aktuelle `python:3.12-slim`-Patch-Level. Anschließend `pip-audit` erneut laufen lassen.

### Phase 2 – Diesen Monat, strukturelle Härtung (1 bis 2 Wochen)

12. **Zentraler SSRF-Schutz.** Eine Hilfsfunktion `safe_fetch(url, max_bytes, timeout)` in `src/utils/`, die nur `http/https` zulässt, den Hostnamen auflöst und private, Loopback-, Link-Local- und Metadaten-Adressen ablehnt (auch nach jedem Redirect), und sie an allen Stellen aus H1 verwenden. Für yt-dlp eine Extractor-Allowlist (`allowed_extractors`), mindestens den `generic`-Extractor sperren. Für Webhooks eine Host-Allowlist per Umgebungsvariable (`WEBHOOK_ALLOWED_HOSTS`).
13. **Booklet-Renderer härten.** Markdown-Ausgabe mit `nh3` oder `bleach` auf eine Tag-Allowlist reduzieren; WeasyPrint einen eigenen `url_fetcher` geben, der nur `images/` unter `work_dir` und das Template-Verzeichnis erlaubt.
14. **Container härten.** `USER app` im Dockerfile, gunicorn (`gunicorn -w 2 --threads 8 --timeout 600 src.dashboard.app:app`) statt `app.run`, im Compose `read_only: true` mit `tmpfs` für Temp-Pfade, `cap_drop: [ALL]`, `security_opt: [no-new-privileges]`, Memory- und CPU-Limits. Mittelfristig Worker (ffmpeg, LibreOffice, yt-dlp) in einen eigenen Container ohne ausgehendes Netz außer den nötigen Zielen.
15. **CI/CD.** Actions per Commit-SHA pinnen; `permissions` auf das Minimum je Job; `CI_PAT` durch eine GitHub App oder einen fine-grained Token mit nur diesem Repo ersetzen; im PR-Workflow `pytest`, `bandit -r src`, `pip-audit`, `gitleaks` und `trivy image` laufen lassen; Dependabot für pip, Docker und Actions aktivieren; Branch-Protection auf `main` mit Pflicht-Checks; GitHub Secret Scanning mit Push Protection einschalten.
16. **Browser-Schutz und Rate-Limiting.** Security-Header per `after_request` oder `flask-talisman`; CSRF-Token für Dashboard-POSTs; `flask-limiter` mit Limits pro Token und pro IP, strengere Limits für teure Endpunkte (Media, Audio, Batch-Tests).
17. **Logging und Datenschutz.** Level `INFO` in Produktion; Redaktion von Texten, Transkripten und URLs mit Query-Strings; Aufbewahrungsfrist definieren; Callback-Tokens nach Zustellung aus dem Job-Dokument löschen oder nur als Hash speichern.
18. **Repo-Hygiene.** `.obsidian/`, `.vscode/`, `site/`, Test-PDFs aus dem Index entfernen (`git rm --cached`), `.env.example` und Handover-Dokumente von Hostnamen und Benutzerpfaden befreien, `SECURITY.md` mit Meldeweg anlegen.

### Phase 3 – Laufend und strukturell (Quartal)

19. **Mehrere API-Keys mit Scopes.** Keys als Hash in Mongo, pro Key Name, erlaubte Namespaces und Rate-Limit; Jobs an den Key binden, so dass `/api/jobs/<id>` nur dem Ersteller antwortet.
20. **Sandboxing der Konverter.** LibreOffice, ffmpeg und Tesseract in einem separaten Worker-Container mit seccomp-Profil, ohne Secrets und ohne Netz; Dateityp per `python-magic` statt Endung; Größenlimits je Typ; Zip-Entpackgröße begrenzen.
21. **LLM-Pipeline-Bedrohungsmodell.** Prompt-Injection explizit dokumentieren, `jsonschema`-Validierung für alle strukturierten Ausgaben erzwingen, Ausgaben im Dashboard und in KnowledgeScout nie ungeescaped rendern, keine Tool- oder Shell-Aktionen aus Modellausgaben.
22. **Regelmäßigkeit.** Monatlich `pip-audit` und Image-Scan, vierteljährlich Key-Rotation, bei jedem Release ein kurzer Blick auf neue Endpunkte gegen die Checkliste aus diesem Dokument.

## 4. Anhang

### 4.1 Geprüfte Bereiche

- Einstiegspunkte: `src/main.py`, `src/api/__init__.py`, `src/dashboard/app.py`, alle Blueprints unter `src/api/routes/` und `src/dashboard/routes/`
- Auth-Middleware, Whitelist, Health-Ausnahmen
- Datei-Auslieferung (`send_file`, `send_from_directory`), Upload-Speicherung, Temp-Verzeichnisse
- Subprozesse (ffmpeg, yt-dlp CLI, LibreOffice), Deserialisierung (`yaml`, `json`, `pickle`), `eval`/`exec`
- Ausgehende HTTP-Aufrufe (`requests`, `urllib`, yt-dlp), Webhooks
- Jinja/Markup/`innerHTML` im Dashboard und Booklet
- MongoDB-Abfragen auf Operator-Injection (keine gefunden; Filter werden aus festen Keys gebaut)
- Docker, Compose, CI-Workflows, `.gitignore`/`.dockerignore`
- Git-History auf Schlüsselmuster (OpenAI, OpenRouter, Mongo-URIs mit Passwort, AWS, GitHub-Tokens, private Keys)

### 4.2 pip-audit (gekürzt)

```
Found 41 known vulnerabilities in 4 packages
flask    3.0.2   PYSEC-2026-2151                      -> 3.1.3
pymongo  4.13.2  CVE-2026-88029, -96747, -96748, -96749 -> 4.18.2
pytest   8.1.1   PYSEC-2026-1845                      -> 9.0.3
pillow   11.1.0  30 Advisories (PYSEC-2026-165 … 3496) -> 12.3.0
```

### 4.3 Befund-Kurzliste zum Abhaken

| ID | Thema | Phase |
|---|---|---|
| K1 | Dashboard ohne Auth | 0 (Netz), 1 (Code) |
| K2 | Whitelist/Localhost per Header spoofbar | 0 (Env), 1 (Code) |
| K3 | Fail-open ohne Token | 0 (Env), 1 (Code) |
| K4 | Mongo ohne Auth, Port offen | 0 |
| K5 | API-Key im Code | 0 |
| K6 | Deploy-Token im Workflow | 0 |
| H1 | SSRF | 2 |
| H2 | TLS-Verifikation aus | 1 |
| H3 | Path Traversal Upload | 1 |
| H4 | root, Dev-Server, altes Image, yt-dlp-Upgrade | 1 (Image, Pin), 2 (Rest) |
| H5 | Verwundbare Abhängigkeiten | 1 |
| H6 | Keine Limits, fehlende Timeouts | 1 (Timeouts), 2 (Rate-Limit) |
| H7 | HTML-Injection Booklet | 2 |
| M1 | Token-Vergleich, Einzel-Key | 1 (compare_digest), 3 (Multi-Key) |
| M2 | Objekt-Autorisierung | 3 |
| M3 | Stacktraces, Health-Infos | 1 |
| M4 | Security-Header, CSRF, innerHTML | 2 |
| M5 | Logging, Token-Speicherung | 2 |
| M6 | Template-Name Traversal | 1 |
| M7 | Prompt-Injection | 3 |
| M8 | CI/CD | 2 |
| M9 | Konverter-Sandbox | 3 |
| M10 | Tote Konfiguration, Testrouten | 1 |
| N1–N4 | Hygiene | 2 |
