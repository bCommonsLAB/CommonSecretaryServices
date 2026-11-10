# Handover KnowledgeScout: Chat-Kosten und Korrelation (10.11.2026)

Betrifft `/api/transformer/chat` und `/api/rag/embed-text`. Alle Aenderungen sind
additiv; bestehende Felder der Antworten sind unveraendert.

## Was vorher falsch war

Die Chat-Route setzte `process.llm_info` direkt und ging damit am Metrik-Tracker
vorbei. In `request_metrics` stand der Chat deshalb mit `total_tokens: 0`,
`models_used: []` und weder `priced_requests` noch `unpriced_requests`. Jetzt
laeuft der Aufruf ueber `add_llm_requests` wie bei den uebrigen Prozessoren.

## Neu in der Antwort von `/api/transformer/chat`

Feld `usage` auf oberster Ebene (neben `status`, `request`, `process`, `data`):

| Pfad | Typ | Bedeutung |
|---|---|---|
| `usage.model` | string | Modell des Aufrufs |
| `usage.prompt_tokens` | int \| null | Eingabe-Tokens laut Provider; `null` = nicht gemeldet |
| `usage.completion_tokens` | int \| null | Ausgabe-Tokens laut Provider; `null` = nicht gemeldet |
| `usage.total_tokens` | int | Gesamt-Tokens laut Provider |
| `usage.cost` | float \| null | Betrag laut Provider; `null` = kein Preis bekannt (nicht 0) |
| `usage.cost_currency` | string | immer `"USD"` |

Die Werte stammen aus `usage` der Provider-Antwort, nichts wird geschaetzt.
`process.llm_info.requests[0]` traegt zusaetzlich `prompt_tokens` und
`completion_tokens`, wenn der Provider sie meldet.

## Korrelations-Header

Optional, an jedem `POST /api/...`. Gespeichert am Metrik-Eintrag unter
`request_metrics.correlation.<feld>`:

| Header | Feld |
|---|---|
| `X-Query-Id` | `query_id` |
| `X-Library-Id` | `library_id` |
| `X-Chat-Id` | `chat_id` |
| `X-Job-Id` | `job_id` |
| `X-Source-Item-Id` | `source_item_id` |
| `X-Worker-Id` | `worker_id` |
| `X-Start-Request-Id` | `start_request_id` |

Nur Kennungen: 1 bis 128 Zeichen aus `A-Z a-z 0-9 . _ : -`. Ein anderer Wert
wird verworfen (Warnung im Log mit dem Header-Namen, ohne den Wert). Fehlen die
Header, ist `correlation` ein leeres Objekt.

## Embedding-Preis

`voyage-3-large` hat einen Listenpreis (`src/core/llm/embedding_cost.py`,
0,18 USD je 1 Mio. Tokens, Voyage-Preisseite, Stand 10.11.2026). Der Betrag ist
ein Listenpreis: das Freikontingent des Kontos ist nicht eingerechnet. Ein
Embedding-Modell ohne Eintrag zaehlt weiter als `unpriced_requests`.

## Log

- `Chat-Completion Modellaufruf` mit `model`, `model_source` (`request` oder
  `default`) und `provider` — das wirksame Modell zum Zeitpunkt des Aufrufs.
- `Transformer Processor initialisiert (Voreinstellung)` nennt mit
  `default_model` nur die Voreinstellung der LLM-Config.
- `[METRICS-TRACE] http_out` nennt zusaetzlich `priced`, `unpriced` und
  `correlation`.

In Metrik und diesen Logzeilen stehen keine Nachrichteninhalte.
