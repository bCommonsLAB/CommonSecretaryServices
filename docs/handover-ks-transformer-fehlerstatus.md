# Hand-off an KnowledgeScout: Transformer-Fehler kommen jetzt als Fehler an

Stand 11.10.2026. Secretary-Branch `claude/transformer-fehlerstatus`.
Vertrag: `docs/reference/api/endpoints/transformer.md`, Abschnitt „Response (Error)".

## Was war

Prod 10.10.2026, 23:12–23:19 UTC: Der Secretary nahm für Template-Transformationen das
Standardmodell `deepseek/deepseek-v4-flash-latest`, weil die Library „Dachverband für
Soziales" kein Template-Modell gesetzt hat (`config.secretaryService.llmModel` leer) und
die Brücke deshalb keins mitschickte. OpenRouter kennt den Namen nur mit Tilde
(`~deepseek/deepseek-v4-flash-latest`) und wies jede Anfrage ab.

Der Secretary antwortete trotzdem mit **HTTP 200 und außen `status: "success"`**; die
eigentliche Fehlerantwort steckte in `data`. KS hat den Job richtig scheitern lassen,
aber erst über die Prüfung „kein `structured_data`" (Job `7104c1dd`). Die Ursache stand
nur tief im Antwortauszug.

## Was der Secretary jetzt tut

Für `/api/transformer/template`, `/api/transformer/text` und `/api/transformer/text/file`:

- HTTP **400**
- außen `status: "error"`, `error.code` und `error.message` des Processors, `data: null`
- kein Python-Traceback mehr in `error.details` (steht im Dienst-Log)

```json
{
  "status": "error",
  "error": {
    "code": "TEMPLATE_TRANSFORMATION_ERROR",
    "message": "Fehler bei der Template-Transformation: LLM-Anfrage fehlgeschlagen. Modell: deepseek/deepseek-v4-flash-latest. Fehler: … is not a valid model ID",
    "details": { "error_type": "ProcessingError", "template": "" }
  },
  "data": null
}
```

Der Job-Weg (`callback_url`) hat Fehler schon vorher richtig gemeldet; unverändert.

## Was KS nachziehen muss (eine Stelle)

`src/lib/external-jobs/template-run.ts`, Zweig „HTTP-Status nicht OK": Dort steht

```ts
if ('error' in data) {
  errorText = String((data as { error?: unknown }).error)
}
```

`error` ist beim Secretary ein Objekt. `String(...)` macht daraus `[object Object]`, und
die Meldung des Dienstes geht verloren. Vorschlag:

```ts
const err = (data as { error?: unknown }).error
if (err && typeof err === 'object') {
  const { code, message } = err as { code?: unknown; message?: unknown }
  errorText = [code, message].filter((v) => typeof v === 'string' && v).join(': ') || JSON.stringify(err).slice(0, 500)
} else if (err !== undefined) {
  errorText = String(err)
}
```

Danach steht im Job-Trace direkt
`TEMPLATE_TRANSFORMATION_ERROR: … is not a valid model ID` statt „kein gültiges
structured_data". Dieselbe Stelle gibt es sinngemäß in `document-translation.ts` und
`process-text/route.ts`, falls dort ebenfalls `error` als Text gelesen wird.

## Unabhängig davon

- In den Libraries ohne Template-Modell (u. a. beide „Dachverband für Soziales",
  „Pluriversum") das Modell in den Secretary-Einstellungen setzen.
- Die App wählt bei leerem Feld still das erste Modell der Liste vor und zeigt es, als
  wäre es die Library-Einstellung; die Brücke schickt in diesem Fall keins. Beide sollten
  sich gleich verhalten (Vorschlag: sichtbar machen, dass der Secretary-Standard gilt).
