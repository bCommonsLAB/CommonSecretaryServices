# Analyse: Unnötige Übersetzung von Deutsch nach Deutsch bei `gpt-4o-transcribe`

## Beobachtung

Bei der Verarbeitung einer deutschen Audio-Datei (`Besprechung Alex martina aryan.m4a`) ohne explizit
mitgegebene Quellsprache wird nach jeder Transkription eine Übersetzung gestartet. Im Log:

```
2026-04-30 16:45:18 - Starte Übersetzung von  nach de
```

Das `von` ist **leer**. Im Debug-File `cache/audio/temp/debug/llm/20260430_164525_translation.json` steht:

- Eingabetext: deutscher Originaltext
- User-Prompt: `"Please translate this text to de: ..."`
- Antwort: `"content": null` (das LLM weiß nicht was es tun soll)

Konfiguriertes Transkriptions-Modell: `openai/gpt-4o-transcribe`.

## Ursachenkette

1. Die API in `src/api/routes/audio_routes.py:287` setzt als Default `source_language='auto'`,
   wenn der Client nichts mitgibt.
2. Der Audio-Handler `src/core/processing/handlers/audio_handler.py:69` übernimmt `"auto"` aus den
   Job-Parametern.
3. `src/processors/audio_processor.py:774` prüft `source_language or "de"`. Da `"auto"` truthy ist,
   bleibt der Wert `"auto"`.
4. `transcribe_segment` ruft den Provider mit `language=None` auf (siehe
   `src/utils/transcription_utils.py:1607`).
5. Im `OpenAIProvider.transcribe` (`src/core/llm/providers/openai_provider.py`) wird `verbose_json`
   angefordert. `gpt-4o-transcribe` lehnt das ab, der Retry in Zeile 128–141 setzt das Format auf
   `"json"`. Dieses Format liefert **kein** `response.language`-Feld.
6. Damit bleibt `detected_language` in der Provider-Logik bei `"auto"` (Zeile 169–171). Auch der
   zweite Konvertierungsversuch in `transcription_utils.py:1785-1787` liefert weiter `"auto"`,
   weil der Eingabewert leer/unbekannt ist.
7. In `transcribe_segments` (Zeile 2009–2024) ist die Bedingung
   `result.source_language == "auto"` erfüllt. Es wird **erzwungen** eine Übersetzung gestartet,
   mit `effective_source = ""` und `target_language = "de"`.
8. Resultat: Die Pipeline bezahlt für eine sinnlose Deutsch-nach-Deutsch-Übersetzung pro Segment
   (im konkreten Job: 23 Segmente). Das LLM antwortet mit `null`, der Originaltext geht durch den
   Fallback in Zeile 2030 nicht verloren – aber Tokens, Latenz und Logs sind verschmutzt.

## Drei Lösungsvarianten

### Variante A – Sofort-Workaround beim Aufruf (kein Code-Fix)

Den Client dazu bringen, immer eine konkrete `source_language` mitzugeben (z.B. `"de"`).
Damit wird `language="de"` an die API geschickt, der Auto-Pfad wird übersprungen und die
Bedingung `result.source_language == "auto"` ist nie wahr.

- **Vorteil:** Null Code-Risiko, sofort wirksam.
- **Nachteil:** Verschiebt die Verantwortung auf jeden Aufrufer. Sobald irgendwo wieder
  `auto` benutzt wird, tritt der Bug erneut auf. Behebt die eigentliche Ursache nicht.

### Variante B – Defaults im Backend härten

In `audio_routes.py:287` und `audio_handler.py:69` den Default von `"auto"` auf `"de"` ändern
(bzw. auf einen konfigurierbaren Default). Optional zusätzlich in `audio_processor.py:774`
`"auto"` aktiv auf `"de"` umsetzen.

- **Vorteil:** Kleine, lokale Änderung. Greift in **allen** Aufrufern.
- **Nachteil:** Verliert die Möglichkeit zur echten Auto-Erkennung. Bei nicht-deutschen Audios
  würde Whisper eine Sprache erzwungen bekommen, die unter Umständen falsch ist. Whisper liefert
  bei falschem `language`-Parameter manchmal schlechtere Ergebnisse.

### Variante C – Logik in `transcribe_segments` reparieren (empfohlen)

Den eigentlichen Defekt in `src/utils/transcription_utils.py:2009-2024` adressieren. Konkret:

1. Wenn `result.source_language == "auto"` (Erkennung fehlgeschlagen), als Fallback
   `target_language` annehmen statt zwanghaft zu übersetzen. Begründung: Wir wissen es nicht
   besser, und eine Übersetzung mit unbekannter Quelle bringt nachweislich nichts.
2. Zusätzlich in `translate_text` einen No-Op einbauen: Wenn `source_language == target_language`
   ODER `source_language` leer ist, sofort den Originaltext zurückgeben, ohne LLM-Aufruf.

Optional ergänzend in `openai_provider.py`: Beim Fallback auf `response_format="json"` ein
WARNING loggen, damit klar ist, dass Sprach-Erkennung in dem Modus nicht möglich ist.

- **Vorteil:** Behebt die Ursache. Robust gegen alle aktuellen und zukünftigen Modelle, die
  keine Sprache zurückgeben. Spart Tokens und Latenz. Verändert das öffentliche API-Verhalten
  nicht.
- **Nachteil:** Mehr Code-Änderungen als Variante A/B. Erfordert Tests, dass die echte
  Übersetzungspfad (z.B. EN → DE) weiterhin funktioniert.

## Empfehlung

Variante C – kombiniert mit Variante A als sofortiger Workaround. Variante B alleine ist
unsauber, weil sie die Auto-Erkennung kaputt macht.

## Betroffene Dateien (bei Variante C)

- `src/utils/transcription_utils.py` – Bedingung `needs_translation` und `translate_text`
- `src/core/llm/providers/openai_provider.py` – optionales WARNING beim Format-Fallback

## Offene Fragen vor Implementierung

- Soll der Fallback bei nicht erkennbarer Sprache `target_language` annehmen oder den Job
  als "Sprache unbekannt" markieren und den Aufrufer informieren?
- Soll der No-Op in `translate_text` zusätzlich eine Warnung loggen, damit man sieht, dass
  ein unnötiger Übersetzungsversuch passiert ist?
