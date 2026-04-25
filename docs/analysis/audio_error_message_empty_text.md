# Analyse: Audio-Job meldet "Text darf nicht leer sein"

## Beobachtung

Der Live-Log zeigt zuerst mehrere konkrete Transkriptionsfehler. Die OpenAI-API antwortet mit `401 invalid_api_key`. Danach wird zusätzlich ein fehlendes Template gemeldet. Die am Job sichtbare Fehlermeldung lautet aber nur `Text darf nicht leer sein`.

## Ursache

`AudioProcessor.process()` fängt die eigentliche Exception ab und baut danach eine Fehler-Response. Dabei wurde ein `TranscriptionResult` mit leerem Text erzeugt. `TranscriptionResult.__post_init__()` verbietet leere Texte und wirft deshalb `ValueError("Text darf nicht leer sein")`.

Dieser sekundäre Validierungsfehler überschreibt die ursprüngliche Ursache. Der Job-Manager sieht nur noch den letzten Fehler und speichert deshalb die irreführende Meldung.

## Entscheidung

Die Fehler-Response erzeugt jetzt ein valides Fehler-Transkript mit der ursprünglichen Ursache. API-Schlüssel-artige Werte werden vor der Rückgabe maskiert. Damit bleibt die eigentliche Ursache für den Client sichtbar, ohne Secrets in API-Antworten zu leaken.
