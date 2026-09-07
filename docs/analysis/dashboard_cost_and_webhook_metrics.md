# Analyse: Dashboard-Kosten immer 0 und fehlende Webhook-Folgeaufrufe

Status: **A1 umgesetzt** (2026-09-07). B1 nicht umgesetzt.
Datum Analyse: 2026-08-21. Umsetzung A1: 2026-09-07.

> Beobachtung aus dem Dashboard: Zeilen für `rag` und `transformer` erscheinen,
> Token und Kosten sind durchgängig 0, die 24h-Karten bleiben 0. Zusätzlich
> fehlen Folgeaufrufe, die der Client während eines Webhook-Callbacks auslöst.
> Diese Datei belegt die Code-Ursachen und stellt Varianten zur Auswahl.
>
> A1 (Tracker über `add_llm_requests`, `LLMRequest.cost`, OpenRouter `usage.cost`,
> Voyage-Token, Mistral-OCR-Seitenpreis) ist im Code. Unit-Tests unter `.tests/`
> (22 passed). Nicht live gegen OpenRouter/MongoDB verifiziert.
> B1 (Webhook vom Worker-Slot entkoppeln) fehlt. Stattdessen nur
> `[METRICS-TRACE]`-Logs um den weiterhin blockierenden `requests.post`.

---

## 1. Betroffene Dateien

| Bereich | Datei |
|---|---|
| Tracker (Token/Kosten) | `src/utils/performance_tracker.py` |
| Request-Lifecycle | `src/dashboard/app.py` (`before_request`, `after_request`, `teardown_request`) |
| Dashboard-Anzeige | `src/dashboard/templates/_recent_requests.html`, `dashboard.html` |
| Aggregation | `src/core/mongodb/metrics_repository.py` |
| OpenRouter-Kosten | `src/core/llm/providers/openrouter_provider.py` |
| LLM-Modell (kein Cost-Feld) | `src/core/models/llm.py` (`LLMRequest`) |
| Modellname ohne Token | `src/processors/base_processor.py` (`_record_model`) |
| LLM-Sammeln ohne Tracker | `src/processors/base_processor.py` (`add_llm_requests`) |
| Worker / Webhooks | `src/core/mongodb/secretary_worker_manager.py`, Handler unter `src/core/processing/handlers/` |
| Serverstart | `src/main.py` (`app.run(..., debug=False)`) |

---

## 2. Problem A — Kosten und Token immer 0

### 2.1 Was das Dashboard tatsächlich anzeigt

Die Spalten Token/Kosten kommen **nicht** aus der OpenRouter-Antwort und
**nicht** aus `process.llm_info` der API-Response. Sie kommen aus dem
PerformanceTracker:

```
measurements.resources.total_tokens
measurements.resources.total_cost
```

(`map_recent_entry` in `metrics_repository.py`, Template `_recent_requests.html`).

### 2.2 Datenfluss ist unterbrochen (drei Brüche)

```
OpenRouter-Response
  usage.total_tokens     usage.cost          ← OpenRouter liefert beides
        │                      │
        ▼                      ▼
  LLMRequest.tokens      (kein Feld)         ← Bruch 1: cost wird nie gelesen/gespeichert
        │
        ▼
  ProcessInfo.llm_info                       ← landet in der API-Response
        │
        ✕  keine Verbindung
        ▼
  PerformanceTracker.resources               ← Bruch 2: add_resource_usage wird praktisch nie aufgerufen
        │                                      Bruch 3: _record_model schreibt nur den Modellnamen
        ▼
  Dashboard Token/Kosten
```

**Bruch 1 — OpenRouter-Kosten werden verworfen.**
`OpenRouterProvider.chat_completion` liest `prompt_tokens`, `completion_tokens`,
`total_tokens` und schreibt sie in `LLMRequest`. `usage.cost` / `usage.cost_details`
werden nicht gelesen. `LLMRequest` hat kein `cost`-Feld. OpenRouter liefert
`usage.cost` laut aktueller Doku in jeder Antwort mit
([Usage Accounting](https://openrouter.ai/docs/cookbook/administration/usage-accounting)).

**Bruch 2 — Token aus `LLMInfo` erreichen den Tracker nicht.**
`BaseProcessor.add_llm_requests` hängt Requests an `process_info.llm_info`
(API-Response). Der PerformanceTracker wird dort nicht aktualisiert.
`add_resource_usage()` existiert, wird aber nur über `eval_result()` in wenigen
Routen aufgerufen (z. B. HTML-Table-Transform). Die im Screenshot sichtbaren
`rag`- und `transformer`-Pfade rufen das nicht auf.

**Bruch 3 — `_record_model` ist bewusst tokenlos.**
Kommentar in `PerformanceTracker.set_model`: „kein Token-/Kosten-Tracking, nur
der Modellname“. Deshalb zeigt `rag` `voyage-3-large`, aber Token=0.
`transformer` ruft `_record_model` nur im XXL-Pfad auf, nicht in
`transformByTemplate` → Modellspalte „—“.

Zusätzlich: Embeddings (`voyage-3-large`) laufen über Provider `voyageai`,
nicht OpenRouter (`config.yaml` Use-Case `embedding`). Dort gibt es kein
`usage.cost` im OpenRouter-Sinn.

`eval_result()` rechnet außerdem `cost = tokens * 0.0001` (Platzhalter), nicht
den OpenRouter-Betrag. Selbst wenn dieser Pfad greifen würde, wären die Kosten
falsch.

### 2.3 Varianten für Problem A

**Variante A1 — Zentral an `add_llm_requests` (empfohlen, kleinste Fläche).**
Beim Sammeln der LLM-Requests gleichzeitig `tracker.add_resource_usage(tokens, cost, model)`
aufrufen. Dafür `LLMRequest` um optionales `cost: float = 0.0` erweitern und im
OpenRouter-Provider `usage.cost` übernehmen. RAG/Voyage kann Token (und ggf.
geschätzte Kosten) analog setzen.

- Pro: ein Hebel für alle Prozessoren; echte OpenRouter-Kosten; bestehende API-Response bleibt additiv.
- Contra: Dataclass-Änderung an `LLMRequest` (frozen, Validierung, Tests, mypy).

**Variante A2 — Nur im OpenRouter-Provider den Tracker füttern.**
Kein neues Feld; Provider ruft `get_performance_tracker().add_resource_usage(...)`
direkt nach dem API-Call.

- Pro: keine Typänderung; schnell.
- Contra: andere Provider (Voyage, Mistral OCR, OpenAI Whisper) bleiben 0; bricht
  die Schichttrennung (Provider kennt Dashboard-Tracker).

**Variante A3 — In `teardown_request` / Worker-`finally` `process_info.llm_info` abgreifen.**
Tracker hat heute keine Referenz auf den Prozessor. Man müsste llm_info extra
am Tracker ablegen oder den Prozessor thread-lokal merken.

- Pro: eine Abschlussstelle.
- Contra: zusätzlicher State, leicht zu vergessen in Worker-Pfaden; cost fehlt
  weiterhin in `LLMRequest`, solange Bruch 1 bleibt.

Empfehlung: **A1**. Ohne Cost-Feld in `LLMRequest` bleibt die OpenRouter-Zahl
auch in der API-Response unsichtbar.

---

## 3. Problem B — Folgeaufrufe während Webhooks fehlen

### 3.1 Prozessmodell (was technisch möglich ist)

Es gibt **keine isolierten Node-Prozesse in diesem Service**. Der Server ist
ein Python-Prozess (`python src/main.py`, `debug=False` → kein Werkzeug-Reloader,
kein zweiter Prozess).

Innerhalb dieses Prozesses laufen **Threads**, kein `multiprocessing`:

1. Flask-Request-Thread (bei `app.run` ohne `threaded=True`: **ein** Request
   gleichzeitig auf dem Main-Thread).
2. `SecretaryWorkerManager`-Monitor-Thread (pollt Jobs alle 5 s).
3. Bis zu `generic_worker.max_concurrent` (Default 3) Job-Worker-Threads.

Der PerformanceTracker liegt in `threading.local()`. Threads teilen sich den
Tracker **nicht** im Speicher. Das ist Absicht, verliert aber keine Dashboard-
Zeilen, weil `complete_tracking()` nach MongoDB schreibt. Alle Threads desselben
Prozesses nutzen dieselbe MongoDB.

Node-Client und Python-Server sind getrennte Prozesse. Das ist normal: der
Client spricht per HTTP. Ein Node-Prozess „weiß“ nichts vom Python-Tracker —
muss er auch nicht, solange der HTTP-Call den Flask-Lifecycle durchläuft.

### 3.2 Wann ein HTTP-Call überhaupt in der Liste landet

Voraussetzung: `POST /api/<namespace>/...`, Tracker überlebt bis
`teardown_request` → `complete_tracking()`.

Bewusste Ausnahmen in `app.py`:

- kein POST → kein Tracker.
- HTTP **202** → Tracker wird in `after_request` **verworfen**. Die Metrik soll
  der Worker schreiben, wenn der Job fertig ist.
- Job noch laufend → noch kein `complete_tracking()` → keine Zeile.

### 3.3 Plausible Ursache für „Webhook-Folgeaufruf fehlt“

Ablauf:

1. Client startet z. B. PDF async → 202, Worker-Thread verarbeitet.
2. Worker macht `requests.post(webhook, timeout=30)` und **blockiert** in
   genau diesem Worker-Thread, bis der Client antwortet.
3. Der Client verarbeitet den Webhook und ruft uns erneut auf (RAG, Transformer).

Das ist **kein** Speicher-Isolation-Bug zwischen Prozessen. Es sind zwei andere
Effekte, die zusammenpassen:

**Effekt 1 — 202-Verwerfen.** Ist der Folgeaufruf selbst async (`callback_url`
gesetzt, z. B. `/api/transformer/template`), erscheint er nicht als Flask-
Request, sondern erst als Worker-Job (`transformer_template`), und nur wenn
dieser Job tatsächlich startet und `complete_tracking()` erreicht.

**Effekt 2 — Worker-Slot blockiert durch den Webhook.** Solange der PDF-Worker
auf die Webhook-HTTP-Antwort wartet, zählt er als laufender Worker. Ein
geschachtelter async Job braucht einen freien Slot (`max_concurrent: 3`).
Wenn der Client **im Webhook-Handler synchron auf den Folge-Job wartet**,
kann das zum Timeout (30 s) führen: Parent-Worker wartet auf den Client,
Client wartet auf den Folge-Job, Folge-Job wartet auf einen Slot. Nach Timeout
läuft der Folge-Job ggf. verspätet oder der Client hat den Call schon aufgegeben.
Das ist Thread-Blockade, nicht Prozess-Amnesie.

Sync-POSTs (`/api/rag/embed-text`, Transformer ohne callback) laufen auf dem
Flask-Main-Thread. Der ist nach dem 202 frei. Diese Calls **sollten** in der
Liste erscheinen — der Screenshot zeigt `rag` und `transformer`. Wenn genau
diese fehlen, ist die Hypothese: der Call hat Flask nie erreicht oder nicht
bis `teardown_request` (Timeout/Deadlock), nicht „ein anderer Prozess kennt
die Liste nicht“.

### 3.4 Karten oben = 0, Liste unten ≠ 0

Der Auto-Refresh (`setInterval` 3 s) aktualisiert **nur** `#recent-requests-list`.
Die 24h-Karten und die Performance-Tabelle werden nur beim Seitenladen gerendert.
Ein offenes Dashboard behält also 0er-Karten, während die Liste nachzieht.
Das erklärt den Screenshot, ohne dass die Aggregation falsch sein muss.
Ein harter Reload sollte die Karten füllen, sofern `created_at` in MongoDB
stimmt. Das wurde nicht gegen die DB geprüft.

### 3.5 Varianten für Problem B

**Variante B1 — Webhook nicht im Worker-Thread blockieren (empfohlen).**
Webhook asynchron senden (eigener Thread / Queue), Worker-Slot sofort
freigeben. Folge-Jobs können starten, während der Client noch arbeitet.

- Pro: adressiert die Blockade direkt; weniger Timeouts.
- Contra: Job gilt intern „fertig“, bevor der Client den Webhook bestätigt hat;
  Fehlerbehandlung des Webhooks muss entkoppelt werden.

**Variante B2 — Folgeaufrufe im Client erst nach Webhook-Response auslösen.**
Kein Server-Change. Der Client bestätigt den Webhook schnell und macht RAG/
Transformer danach (nicht innerhalb des Callbacks).

- Pro: kein Server-Risiko; bricht den Deadlock auf Client-Seite.
- Contra: ändert Client-Orchestrierung; hilft nicht, wenn der Folgeaufruf
  selbst 202 ist und der Worker hängt.

**Variante B3 — Tracker auch bei 202 schreiben und/oder `threaded=True`.**
202-Zeile als „accepted“ plus Worker-Zeile; Flask multithreaded.

- Pro: Submission wäre sofort sichtbar.
- Contra: Doppelzeilen (accepted + completed), wenn man nicht filtert;
  `threaded=True` allein behebt den Worker-Slot-Deadlock nicht.

Empfehlung: **B1 + B2**. Server: Webhook vom Worker-Slot entkoppeln. Client:
Folgearbeit nicht im blockierenden Webhook-Handler. B3 nur wenn die 202-
Submission bewusst in der Liste stehen soll.

---

## 4. Umsetzung A1 (2026-09-07)

A1 ist im Code. `transformByTemplate` braucht kein extra `_record_model`:
`WhisperTranscriber` hängt am Processor und ruft `create_llm_request` →
`add_llm_requests` auf. Damit landen Modell, Token und Kosten im Tracker.

Zusätzlich: Mistral-OCR über Seitenpreis (`ocr_cost.py`), Voyage-Token ohne USD,
`[METRICS-TRACE]` für HTTP/Worker/Webhook (kein Verhaltenswechsel).

B1 bleibt offen: Webhook-POST blockiert weiter den Worker-Slot.
Nicht denselben PR wie A1 mischen.

---

## 5. Was nicht behauptet wird

- Nicht live geprüft, ob MongoDB nach dem Fix `total_cost > 0` schreibt.
- Nicht live geprüft, ob ein konkreter Webhook-Folgecall Flask erreicht hat.
- Node-seitig wurde dieses Repo nicht inspiziert; die Client-Orchestrierung
  steht in einem anderen Projekt.
