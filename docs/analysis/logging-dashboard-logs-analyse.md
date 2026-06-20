# Analyse: Logging, Dashboard & Logs

Status: **Analyse / Entscheidungsvorlage** (keine Code-Änderungen durchgeführt).
Datum: 2026-06-19

> Ziel: Den Ist-Zustand von Logging, Dashboard-Statistiken und Logs-Ansicht
> kritisch erfassen, die konkreten Defekte belegen und drei Modernisierungs-
> Varianten zur Auswahl stellen. Es wurde noch **nichts** repariert oder getestet.

---

## 1. Untersuchte Komponenten

| Bereich | Datei(en) |
|---|---|
| Logging-Kern | `src/utils/logger.py` |
| Performance-Tracking | `src/utils/performance_tracker.py` |
| Dashboard-Statistik | `src/dashboard/routes/main_routes.py` (`home`, `load_logs_for_requests`) |
| Logs-Ansicht (Variante 1) | `src/dashboard/routes/main_routes.py` (`logs`) |
| Logs-Ansicht (Variante 2) | `src/dashboard/routes/log_routes.py` (`view_logs`) |
| Logs-Template | `src/dashboard/templates/logs.html` |
| App-Verdrahtung | `src/dashboard/app.py` |
| Konfiguration | `config/config.yaml` (Abschnitt `logging`) |

---

## 2. Ist-Zustand (Kurzbeschreibung)

- **Logging**: `LoggerService` (Singleton) erzeugt pro `process_id` einen
  `ProcessingLogger`. Ausgabe an Konsole + Datei (`logs/dev_detailed.log`).
  Format: `Zeit - LEVEL - [datei:func:zeile] - [Processor] Process[id] - Nachricht`.
- **Performance-Tracking**: `PerformanceTracker` misst Operationen pro Request
  und soll am Ende via `complete_tracking()` nach `logs/performance.json`
  schreiben. Das Dashboard (`home`) liest diese Datei und berechnet Kennzahlen.
- **Logs-Ansicht**: Liest die Logdatei zeilenweise und stellt sie in einer
  Tabelle dar (siehe Screenshots: funktioniert sichtbar).

---

## 3. Konkrete Defekte (mit Belegen)

### D1 — `complete_tracking()` wird nie aufgerufen → Dashboard immer leer
`get_performance_tracker()` wird in vielen Routen/Prozessoren genutzt, aber
`complete_tracking()` existiert **nur als Definition** (`performance_tracker.py:364`)
und hat **keine einzige Aufrufstelle**. Folge: `logs/performance.json` wird im
Normalbetrieb nie geschrieben → alle Dashboard-Kennzahlen bleiben 0
(deckt sich mit dem Screenshot: Gesamtanfragen 0, Dauer 0, Erfolgsrate 0).

### D2 — `clear_performance_tracker()` wird nie aufgerufen → Tracker-Leak
Der Tracker liegt im Thread-Local (`performance_tracker.py:499`). Ohne
`clear_performance_tracker()` (keine Aufrufstelle) bleibt er an den
Worker-Thread gebunden und wird vom **nächsten** Request wiederverwendet →
vermischte Messungen.

### D3 — `set_endpoint_info()` wird nie aufgerufen
Endpoint/IP/User-Agent bleiben `None` (`performance_tracker.py:172`, keine
Aufrufstelle).

### D4 — Struktur-Mismatch Dashboard ↔ Tracker
`home()` liest `r.get('operations')`, `r.get('processors')`,
`r.get('resources')` auf **oberster** Ebene (`main_routes.py:264,273,291`).
`complete_tracking()` schreibt diese aber **verschachtelt** unter
`measurements.*` (`performance_tracker.py:427-431`). Selbst wenn D1 behoben
wäre, würden Operationen/Processor-Statistiken/Ressourcen falsch gelesen.

### D5 — Doppelte `/logs`-Route, eine davon tot
- `main_routes.py:479` registriert `@main.route('/logs')` → `main.logs`.
- `log_routes.py:191` registriert `@logs.route('/logs')` → `logs.view_logs`.
In `app.py` wird `main` vor `logs` registriert (`app.py:195-197`), daher
gewinnt `main.logs`. `logs.view_logs` ist **toter Code**.

### D6 — Template passt nur zu einer Route; Filter wirkungslos
`logs.html` iteriert über `log_files.items()` und zerlegt **rohe Zeilen**
(`logs.html:28,51`). Diese Variable liefert nur `main.logs`. Die von
`logs.view_logs` übergebenen Daten (`logs`, `pagination`) werden im Template
**nicht** verwendet → Pagination/strukturierte Filterung ist toter Code.
Die Links/Clear-Buttons zeigen auf `logs.view_logs` (`logs.html:21,82`), landen
durch D5 aber bei `main.logs`, das `session_id` ignoriert → **Session-Filter
ohne Wirkung**.

### D7 — Rotation konfiguriert, aber nicht implementiert
`config.yaml` setzt `max_size: 120000000` und `backup_count: 5`
(`config.yaml:173-177`). Der Code nutzt jedoch ein einfaches
`logging.FileHandler` (`logger.py:249`), **kein** `RotatingFileHandler`. Der
Docstring behauptet „Automatic log file rotation" (`logger.py:10`) — das ist
faktisch falsch. Die Logdatei wächst unbegrenzt.

### D8 — Teurer/fragiler Stack-Walk pro Log-Aufruf
`RelativePathFormatter` läuft bei **jedem** Log-Eintrag per `sys._getframe()`
durch den Call-Stack (`logger.py:201-234`), um Datei/Zeile zu korrigieren.
Das ist langsam und bricht bei geänderter Aufrufkette.

### D9 — Unbegrenztes Wachstum von `_loggers`
`LoggerService._loggers` legt pro `process_id` einen Logger an
(`logger.py:258-280`) und entfernt nie etwas. Da `process_id` je Request/Job
variiert, wächst das Dict (und die `logging`-interne Logger-Registry)
unbegrenzt → Speicher-/Handler-Leck bei langer Laufzeit.

### D10 — `warning()` ohne Observer-Benachrichtigung
`debug/info/error` rufen `notify_observers`, `warning()` nicht
(`logger.py:416-419`). Inkonsistenz für Live-Log-Beobachter.

### D11 — Fragiler ` - `-Parser
Sowohl `load_logs_for_requests` (`main_routes.py:115`) als auch das Template
(`logs.html:51`) splitten an ` - `. Enthält eine Nachricht ` - `, verschiebt
sich das Parsing. Mehrzeilige Einträge (Stacktraces) werden nur teilweise
korrekt zugeordnet.

### D12 — Unrealistische Kostenberechnung
Kosten werden pauschal mit `tokens * 0.0001` angesetzt
(`performance_tracker.py:255,267,279,288,465,479,485`) — unabhängig vom Modell.
Die „Kosten/Anfrage" im Dashboard wären damit bestenfalls grobe Schätzung.

---

## 4. Bewertung

Der Logging-Kern (Datei-/Konsolen-Ausgabe) **funktioniert** und wird real
genutzt — die Logs-Seite zeigt echte Einträge. Defekt bzw. ungenutzt sind vor
allem:
1. die gesamte **Performance-/Dashboard-Kennzahlen-Kette** (D1–D4, D12),
2. die **doppelte/inkonsistente Logs-Implementierung** (D5, D6),
3. **Betriebsrisiken** im Logger (D7 Rotation, D9 Leak) sowie Performance/
   Robustheit (D8, D11).

Aussage „wird nie benutzt, da es nicht funktioniert" trifft damit konkret auf
die Performance-/Dashboard-Statistik und die zweite Logs-Route zu — nicht auf
das Basis-Logging selbst.

---

## 5. Drei Lösungsvarianten

### Variante A — Minimal-Reparatur (Bestehendes zum Laufen bringen)
**Inhalt:**
- `complete_tracking()` + `clear_performance_tracker()` zentral in einem Flask
  `after_request`/`teardown_request` aufrufen; Tracker pro Request in
  `before_request` anlegen + `set_endpoint_info()` füllen.
- Struktur-Mismatch D4 beheben (entweder flach schreiben oder `home()`
  anpassen).
- Rotation: `FileHandler` → `RotatingFileHandler` (D7).
- Zweite Logs-Route entfernen, eine Quelle der Wahrheit (D5/D6).

**Aufwand:** niedrig–mittel. **Risiko:** gering (lokal begrenzt).
**Pro:** schnell, wenig neue Abhängigkeiten. **Contra:** behält das
selbstgebaute JSON-/Datei-Modell inkl. fragilem Parser (D8, D11) und
Skalierungsgrenzen bei.
**Betroffen:** `app.py`, `performance_tracker.py`, `main_routes.py`,
`log_routes.py`, `logs.html`, `logger.py`.

### Variante B — Konsolidierung + MongoDB-Persistenz (empfohlen zur Prüfung)
**Inhalt:**
- Strukturiertes Logging als **JSON-Lines** (eine Zeile = ein JSON-Objekt) →
  Parser D11 entfällt; Filter/Suche werden trivial und robust.
- Performance-Metriken in **MongoDB** statt JSON-Datei schreiben (MongoDB ist
  bereits im Projekt vorhanden) → keine Datei-Korruption, einfache Aggregation,
  TTL-Index für Aufbewahrung.
- Dashboard liest Kennzahlen über ein kleines Repository (Aggregation in der DB
  statt Python-Schleifen).
- Eine einzige, sauber paginierte Logs-Ansicht.
- Rotation/Leak (D7/D9) sauber lösen.

**Aufwand:** mittel. **Risiko:** mittel (Schema/Migration, mehr Code).
**Pro:** robust, skaliert, passt zur vorhandenen Infrastruktur, testbar.
**Contra:** mehr Implementierungs- und Testaufwand; DB-Abhängigkeit für
Metriken.
**Betroffen:** `logger.py`, `performance_tracker.py`, neues
`core/mongodb`-Repository, `main_routes.py`/`log_routes.py`, Templates.

### Variante C — Standard-Tooling (structlog + OpenTelemetry/Prometheus)
**Inhalt:**
- Logging auf `structlog` umstellen; Metriken via Prometheus-Client
  exportieren (`/metrics`) bzw. OpenTelemetry; Visualisierung in Grafana.
- Eigenes Dashboard für Kennzahlen entfällt langfristig.

**Aufwand:** hoch. **Risiko:** höher (neue Abhängigkeiten, Betriebsthema
Grafana/Prometheus). **Pro:** Industriestandard, zukunftssicher, beste
Observability. **Contra:** Overkill, falls nur das interne Dashboard benötigt
wird; zusätzlicher Betriebsaufwand.

---

## 6. Empfehlung (zur Diskussion)

Wenn die Kennzahlen dauerhaft gebraucht werden: **Variante B**, weil sie die
Kern-Defekte strukturell behebt und die vorhandene MongoDB nutzt.
Wenn es nur darum geht, vor dem Publizieren „nichts Kaputtes" auszuliefern und
schnell ein funktionierendes Dashboard zu haben: **Variante A**.
**Variante C** nur, falls externe Observability ohnehin geplant ist.

---

## 7. Offene Fragen / nächste Schritte

1. Werden die Dashboard-Kennzahlen (Tokens/Kosten/Dauer) tatsächlich benötigt,
   oder reicht die reine Logs-Ansicht?
2. Sollen Metriken in MongoDB (Variante B) oder in Datei (Variante A) liegen?
3. Aufbewahrungsdauer für Logs/Metriken?
4. Vor jeder Umsetzung: Reproduktions-Test definieren (z. B. echten Request
   absetzen und prüfen, ob `performance.json`/DB befüllt wird und das Dashboard
   echte Werte zeigt).
