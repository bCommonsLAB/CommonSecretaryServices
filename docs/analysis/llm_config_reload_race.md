# Analyse: Sporadischer Fehler „Chat-Completion Provider nicht verfügbar" bei parallelen Transformer-Anfragen

Stand: 2026-09-30, Branch `fix/llm-config-reload-race` (von `origin/main`)

## Symptom

Ein Client (KnowledgeScout) hat 660 Dokumente parallel (ca. 6 Jobs gleichzeitig)
nach EN und IT übersetzt. Etwa jede siebte Anfrage schlug fehl. Die Antwort hatte
außen `status: success`, innen aber:

```
LLM-Anfrage fehlgeschlagen. Provider: konfigurierter LLM-Provider,
Modell: gpt-transcribe. Fehler: Chat-Completion Provider nicht verfügbar
```

Wiederholen half. Zwei Sprachjobs für dasselbe Dokument, die exakt gleichzeitig
starteten, scheiterten viermal in Folge.

## Ursache (verifiziert im Code)

Die Kette pro Request:

1. `src/api/routes/transformer_routes.py:95` – `get_transformer_processor()` nutzt
   `uuid.uuid4()` als Cache-Schlüssel. Der Cache trifft nie. Jeder Request erzeugt
   einen neuen `TransformerProcessor`.
2. `src/processors/transformer_processor.py:175` – der Konstruktor legt einen
   `WhisperTranscriber` an.
3. `src/utils/transcription_utils.py:167` – dessen Konstruktor ruft
   `LLMConfigManager().reload_config()` („Config immer frisch laden").
4. `src/core/llm/config_manager.py:418` – `reload_config()` setzt am **Singleton**
   zuerst `self._config = None` und ruft dann `_load_config()`, das MongoDB
   abfragt (Use-Case-Configs + Modelle, mehrere Round-Trips).

Der Server läuft als ein Prozess mit Flask-Threads (`app.run`, Docker:
`python -m src.main`). Während Thread A in Schritt 4 lädt, sieht Thread B
`self._config is None`:

- `get_provider_for_use_case()` liefert `None` → `ValueError("Chat-Completion
  Provider nicht verfügbar")` (`transcription_utils.py:1245`).
- `get_model_for_use_case()` liefert `None` → Fallback auf `self.model`, das
  Transkriptionsmodell. Daher steht „gpt-transcribe" in der Fehlermeldung.

Zweites, kleineres Race: `reload_config()` ruft danach
`ProviderManager.clear_cache()`. `ProviderManager.get_provider()` prüft
`if key not in self._providers` und greift dann per `self._providers[key]` zu.
Wird der Cache zwischen Prüfung und Zugriff geleert, gibt es einen `KeyError`.

## Lösungsvarianten

### Variante 1 – Atomarer Tausch (gewählt)

`reload_config()` setzt `_config` nicht mehr auf `None`. `_load_config()` baut die
neue `LLMConfig` vollständig und weist sie in einem Schritt zu. Parallele Leser
sehen bis dahin die alte, gültige Konfiguration. Ein `threading.Lock` verhindert,
dass sechs gleichzeitige Requests sechs parallele MongoDB-Reloads auslösen.
`get_provider()` liest einmal per `.get()` statt zweimal per `in` + `[]`.

- Änderung: 2 Dateien, ca. 15 Zeilen. Kein Verhalten nach außen ändert sich.
- Behebt die Ursache unabhängig davon, wer wann `reload_config()` ruft.

### Variante 2 – Kein Reload pro Request

Zeile 167 in `transcription_utils.py` entfernen. Das Dashboard ruft nach jeder
Konfig-Änderung selbst `reload_config()` (`dashboard/routes/llm_config_routes.py`).
Im Ein-Prozess-Betrieb reicht das.

- Spart pro Request mehrere MongoDB-Round-Trips.
- Risiko: Änderungen direkt in MongoDB (ohne Dashboard) greifen erst nach
  Neustart. Bei mehreren Worker-Prozessen (falls später eingeführt) sähen
  andere Prozesse die Dashboard-Änderung nicht.
- Behebt das Race nur indirekt; das Dashboard-Reload hätte dasselbe Problem,
  nur seltener.

### Variante 3 – Transformer-Cache reparieren

`get_transformer_processor()` mit einem festen Schlüssel cachen, sodass der
Transformer (und damit der Transcriber) einmal entsteht.

- Behebt Race nur indirekt. `TransformerProcessor` trägt aber Request-Zustand
  (`process_info`, `process_id`), ein geteilter Prozessor wäre selbst ein
  Thread-Problem. Nicht ohne größeren Umbau machbar.

## Entscheidung

Variante 1. Sie behebt die Wurzel mit minimaler Änderung. Variante 2 ist eine
sinnvolle Folgeoptimierung (Performance), aber eine Verhaltensänderung, die
separat entschieden werden sollte. Variante 3 ist ein eigenes Thema
(nutzloser Cache in `transformer_routes.py`).

## Offener Punkt (nicht Teil dieses Fixes)

Die Antwort meldet außen `status: success`, obwohl innen `status: error` steht.
Der Client musste das verschachtelte Objekt selbst auswerten. Das gehört in eine
eigene Analyse der Template-Transform-Response.

## Test

`src/tests/test_llm_config_reload_race.py`: Ein Thread ruft in Schleife
`reload_config()`, andere Threads lesen parallel `get_model_for_use_case`.
Vor dem Fix liefert das Lesen sporadisch `None`, nach dem Fix nie.
