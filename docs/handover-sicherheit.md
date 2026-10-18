# Hand-off: Sicherheit – Analyse fertig, Umsetzung beginnt

Stand 18.10.2026. Analyse und Plan sind mit Pull Request #37 in `main` gemerged (Merge-Commit `f77fd6c`).
Basis-Commit der Analyse: `7e3789f` (Version 0.1.73).

## Ziel

Die Befunde der Sicherheitsanalyse Schritt für Schritt beheben, ohne den fachlichen Funktionsumfang
zu ändern. Jede Folgesitzung setzt genau ein Arbeitspaket um und liefert es als eigenen PR.

## Was es schon gibt

| Was | Wo | Inhalt |
|---|---|---|
| Analyse | `docs/sicherheitsanalyse-2026-10.md` | 27 Befunde (K1–K6, H1–H7, M1–M10, N1–N4) mit Datei- und Zeilenverweisen, pip-audit-Ergebnis, Abhakliste |
| Umsetzungsplan | `docs/sicherheitsplan-umsetzung.md` | Arbeitspakete AP-00 bis AP-23 mit Dateien, Schritten, Akzeptanzkriterien, Checkboxen, Zuordnung Befund → AP |
| Visuelle Übersicht | Figma, Team bCommonsLab: https://www.figma.com/design/DEDSmfeQsUX5kfihTW8PJG | 34 Komponenten-Karten, farbig nach Risikostufe, mit Beschreibung, Risiko und Maßnahme |
| Dieses Dokument | `docs/handover-sicherheit.md` | Einstieg für die nächste Sitzung |

Die Zeilennummern in der Analyse beziehen sich auf Commit `7e3789f`. Wenn `main` inzwischen weitergelaufen ist,
die Stellen per Suche nach Funktionsnamen wiederfinden, nicht blind nach Zeilennummer.

## Leitprinzip

Der Dienst wird auf vielen Rechnern installiert. **Jede Schutzmaßnahme gehört in die Anwendung oder in die
mitgelieferten Dateien, nicht in die Konfiguration eines Proxys.** Eine frische Installation ohne
Sicherheitskonfiguration ist geschlossen, pro Installation genügen Umgebungsvariablen. Details im Plan unter
„Leitprinzip“. Jede Umsetzung wird daran gemessen.

## Entscheidungen

- **E1 Dashboard-Anmeldung: entschieden.** Die eigene Nextcloud ist Anmeldedienst nach OpenID Connect
  (App „OIDC Identity Provider“). Die Anwendung spricht selbst mit ihr (Authlib in Flask), ohne oauth2-proxy
  und ohne Traefik-Konfiguration. Basic Auth bleibt als Notzugang und für Installationen ohne Nextcloud-Zugang.
  Ohne Konfiguration ist das Dashboard gesperrt. Kein US-amerikanischer Identity Provider. Eine erste Variante
  mit oauth2-proxy wurde verworfen, weil sie Proxy-Konfiguration je Installation verlangt; sie steht nur noch
  als Option in AP-20.
- **E2 Proxy-Vertrauen: offen, aber nicht sicherheitskritisch.** `TRUSTED_PROXY_COUNT` (Default 0) betrifft nur
  Client-IPs für Logs, Rate-Limit und Swagger-Whitelist. Für die Produktionsinstanz hinter Dokploy vermutlich 1.
- **E3 yt-dlp Generic-Extractor: offen.** Vorschlag: bleibt erlaubt, aber nur zu öffentlichen IP-Zielen.
  Betrifft AP-12, nicht die ersten Pakete.

## Stand der Arbeitspakete

**AP-01 und AP-02 sind umgesetzt** (18.10.2026, PR #38, Details und Abweichungen im Plan bei den Paketen):

- API fail-closed: ohne `SECRETARY_SERVICE_API_KEY` startet `src/main.py` nicht, geschützte Routen antworten sonst 503.
  Frei ist nur `/api/health/live`. Header-Umgehungen über `X-Forwarded-For`, `X-Real-IP` und `Host` sind geschlossen.
- Dashboard in der Anwendung geschützt: Nextcloud per OIDC, Basic als Notzugang, ohne Konfiguration gesperrt, CSRF-Schutz.
- 63 neue Tests in `.tests/test_api_auth.py`, `.tests/test_dashboard_auth.py`, `.tests/test_dashboard_oidc.py`.

Die Außenprüfung aus AP-00 (18.10.2026) hatte auf `secretaryservices.bcommonslab.org` ein offenes Dashboard, offene
`/logs` und `/llm-config` und ein öffentliches Restguthaben unter `/api/health/` gezeigt. **Nach dem Rollout von PR #38
ist das Dashboard dort gesperrt**, bis die Anmeldung konfiguriert ist (`docs/deployment/dashboard-anmeldung.md`).

Beim Rollout beachten:
- Clients, die `/api/health/` ohne Token abfragen (Vorab-Prüfung in KnowledgeScout?), bekommen jetzt 401 und müssen den Token senden.
- Swagger braucht Token, Dashboard-Anmeldung oder `SWAGGER_IP_WHITELIST`.

- **AP-00 und AP-00b sind Aufgaben für den Betreiber**, keine Code-Arbeit: Mongo-Port prüfen, Env-Variablen
  bereinigen, Keys rotieren, GitHub-Einstellungen, Nextcloud-Client anlegen. Eine Sitzung kann begleiten und
  Außenprüfungen machen, wenn die Hosts in der Netzwerkrichtlinie der Umgebung freigeschaltet sind.
- **AP-07 ist umgesetzt** (PR #40): mitgelieferte Compose mit MongoDB ohne Host-Port und mit `--auth`, Pflichtwerte
  `MONGO_ROOT_USER`/`MONGO_ROOT_PASSWORD`, Migrationsanleitung `docs/deployment/mongo-migration.md`.
- **Nachtrag Rollout PR #38/#39:** Der Basic-Notzugang ist in Produktion aktiv. Der Passwort-Hash wird am robustesten in der
  Punkt-Schreibweise ohne `$` eingetragen (`python -m src.dashboard.auth hash-password`). Eine unvollständige
  Dashboard-Konfiguration sperrt nur das Dashboard, nicht den Start.
- **Nächstes Code-Paket ist AP-03** (Dateinamen und Temp-Dateien), dann AP-04 bis AP-06.

## So startet die nächste Sitzung

Startsatz:

```
Lies docs/handover-sicherheit.md und setze dann Arbeitspaket AP-03 aus docs/sicherheitsplan-umsetzung.md um.
```

Ablauf je Paket:

1. Handover, das Arbeitspaket im Plan und die zugehörigen Befunde in der Analyse lesen.
2. Vom aktuellen `main` abzweigen.
3. Branch `claude/sec-ap-xx-kurzname` anlegen. Ein Paket pro Branch und PR, keine Pakete mischen.
4. Umsetzen, die Akzeptanztests aus dem Plan als echte Tests unter `.tests/` schreiben.
5. Tests laufen lassen. `pytest.ini` sammelt nur `.tests/`. Weitere Tests liegen in `src/tests/` und
   müssen ausdrücklich mit angegeben werden: `pytest .tests src/tests -q`.
6. README und `docs/reference/environment-variables.md` nachziehen, wenn sich Verhalten oder Variablen ändern.
7. Im Plan die Checkbox des Pakets mit Datum und PR-Nummer abhaken und die Fortschrittstabelle aktualisieren.

## Stolpersteine aus dieser Sitzung

- **Keine Geheimnisse in Dateien, Commits oder PR-Texte kopieren.** Der Push wurde blockiert, solange der
  Bericht Bruchstücke eines echten Keys und des Deploy-Tokens enthielt. Fundstellen nur mit Datei und Zeile
  nennen, Werte kürzen oder als `<token>` schreiben.
- **pip-audit scheitert an `requirements.txt`**, weil die Pillow-Zeile `--only-binary :all:` enthält.
  Für den Audit eine Kopie ohne diese Option verwenden (AP-06 löst das mit einem Lockfile).
- **Zwei Einstiegspunkte:** Produktiv startet `src/main.py` die App aus `src/dashboard/app.py`.
  `src/api/__init__.py` ist eine zweite, laut Kommentar ungenutzte App-Factory. Auth-Änderungen müssen in
  `src/dashboard/app.py` und im API-Blueprint `src/api/routes/__init__.py` wirken.
- **Die Hintergrund-Worker starten beim ersten Request** in `before_request` von `src/dashboard/app.py`.
  Beim Wechsel auf gunicorn mit mehreren Prozessen (AP-14) liefen sie mehrfach. Das ist im Plan vermerkt.
- **Test-Umgebung:** Unter Python 3.13 fehlt `audioop` (pydub); dort `audioop-lts` installieren oder Python 3.12
  wie in der Produktion verwenden. Ohne MongoDB, Voyage-Key und die Schrift Jost scheitern 7 vorhandene Tests
  umgebungsbedingt (Booklet-Schrift, zwei RAG-Endpunkt-Tests, RAG-Prozessor, drei Mongo-Cache-Tests). Mit einer
  nicht erreichbaren `MONGODB_URI` ohne kurze Timeouts hängen manche Tests minutenlang.
- **Tests, die die API per Test-Client aufrufen, brauchen einen Token** (Muster: `.tests/test_rag_embed_text_endpoint.py`
  oder `.tests/auth_test_support.py`).
- **Pillow-Major-Update in AP-06** kann OCR, Booklet und PDF-Seitenbilder berühren. Dort gründlich testen.

## Nicht geprüft

- Der Mongo-Port 27017 der Produktion ist nicht geprüft, weil der Proxy der Cloud-Umgebung nur Web-Verbindungen
  durchlässt. Lokal mit `nc` prüfen, siehe AP-00.
- Ob die Nextcloud-OIDC-App mehrere Weiterleitungsadressen je Client und `http://localhost` erlaubt, klärt AP-00b.
  Davon hängt ab, ob alle Installationen einen gemeinsamen Client nutzen können.
- Die optionale oauth2-proxy-Vorlage in AP-20 ist nicht gegen eine laufende Installation getestet.
- Ob die Nextcloud-App die Gruppen im Token liefert und unter welchem Claim, klärt AP-00b.
- Die OIDC-Anmeldung ist gegen einen nachgebildeten Anbieter getestet, noch nicht gegen die echte Nextcloud.
