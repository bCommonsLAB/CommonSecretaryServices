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

Noch keines umgesetzt. Die Außenprüfung aus AP-00 ist erledigt (18.10.2026, Ergebnis im Plan unter AP-00):
auf `secretaryservices.bcommonslab.org` sind Dashboard, `/logs` mit aktuellen Einträgen und `/llm-config`
ohne Anmeldung erreichbar, `/api/health/` zeigt das OpenRouter-Restguthaben. Die API selbst verlangt den Token,
auch mit gefälschtem `X-Forwarded-For`. **AP-01 und AP-02 haben deshalb Vorrang.** Eine Sperre in Dokploy ist
nur ein optionaler Sofortschutz für diese eine Instanz, bis AP-02 dort ausgerollt ist.

- **AP-00 und AP-00b sind Aufgaben für den Betreiber**, keine Code-Arbeit: Mongo-Port prüfen, Env-Variablen
  bereinigen, Keys rotieren, GitHub-Einstellungen, Nextcloud-Client anlegen. Eine Sitzung kann begleiten und
  Außenprüfungen machen, wenn die Hosts in der Netzwerkrichtlinie der Umgebung freigeschaltet sind.
- **Nächstes Code-Paket ist AP-01** (Auth-Middleware fail-closed und spoof-sicher), danach AP-02
  (Dashboard-Anmeldung in der Anwendung). AP-02 lässt sich ohne fertiges AP-00b umsetzen und mit `basic`
  ausrollen; `oidc` wird aktiv, sobald der Nextcloud-Client existiert. Danach AP-03 bis AP-07.

## So startet die nächste Sitzung

Startsatz:

```
Lies docs/handover-sicherheit.md und setze dann Arbeitspaket AP-01 aus docs/sicherheitsplan-umsetzung.md um.
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
- **Die Dashboard-Testrouten** (`/run_*_test`) rufen die eigene API ohne Token auf. Nach AP-01 schlagen sie
  fehl, bis AP-02 sie umstellt. Das ist erwartet und im PR von AP-01 zu erwähnen.
- **Pillow-Major-Update in AP-06** kann OCR, Booklet und PDF-Seitenbilder berühren. Dort gründlich testen.

## Nicht geprüft

- Der Mongo-Port 27017 der Produktion ist nicht geprüft, weil der Proxy der Cloud-Umgebung nur Web-Verbindungen
  durchlässt. Lokal mit `nc` prüfen, siehe AP-00.
- Ob die Nextcloud-OIDC-App mehrere Weiterleitungsadressen je Client und `http://localhost` erlaubt, klärt AP-00b.
  Davon hängt ab, ob alle Installationen einen gemeinsamen Client nutzen können.
- Die optionale oauth2-proxy-Vorlage in AP-20 ist nicht gegen eine laufende Installation getestet.
- Ob die Nextcloud-App die Gruppen im Token liefert und unter welchem Claim, klärt AP-00b.
- Die Tests des Projekts wurden in dieser Sitzung nicht ausgeführt.
