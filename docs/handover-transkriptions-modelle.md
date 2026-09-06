# Handover: Transkriptions-Modelle anlegen

Kurzanleitung für die einmalige Einrichtung. Ohne diesen Schritt bleibt die Auswahl in
der LLM-Konfigurationsmaske leer, und die Live-Transkription antwortet mit
`503 NO_MODEL_CONFIGURED`.

## Warum das nötig ist

Die Maske ordnet einem Use-Case nur Modelle zu, die in der MongoDB-Collection
`llm_models` existieren **und** den Use-Case in ihrem Feld `use_cases` führen. Die
Modelle stehen nicht im Code — sie sind Daten. Das Skript legt sie an.

## Ausführen

```bash
# 1. Erst schauen, was passieren würde (schreibt nichts)
python scripts/seed_llm_models.py --dry-run

# 2. Anlegen
python scripts/seed_llm_models.py
```

Das Skript braucht nur `pymongo` und eine MongoDB-URI — **keinen** Projekt-Code, keine
Systemabhängigkeiten wie ffmpeg oder tesseract. Es läuft also auch außerhalb des
Containers.

Die URI kommt aus `MONGODB_URI` oder aus `--uri`. Den Datenbanknamen nimmt es aus der
URI (so macht es auch der Dienst); fehlt er dort, hilft `--db NAME`.

Im Container geht es genauso:

```bash
docker compose exec secretary-services python scripts/seed_llm_models.py
```

Das Skript ist **idempotent**: Ein zweiter Lauf ändert nichts. Bestehende Modelle werden
nicht überschrieben — es werden nur fehlende Use-Cases ergänzt, eigene Beschreibungen
bleiben erhalten.

## Danach: in der Maske zuordnen

Unter `/llm-config`:

| Use-Case | Empfohlenes Modell |
|---|---|
| Transcription (Audio/Video) | `gpt-transcribe` |
| Live-Transcription (Realtime/Diktat) | `gpt-live-transcribe` |

## Was angelegt wird

| Modell | Use-Case | Besonderheit |
|---|---|---|
| `gpt-transcribe` | Datei | empfohlen; nimmt `keywords` und mehrere Sprachen; ~25 % günstiger als `whisper-1` |
| `gpt-live-transcribe` | Live | empfohlen für Sessions |
| `gpt-4o-transcribe` | Datei + Live | Vorgänger-Generation |
| `gpt-4o-mini-transcribe` | Datei + Live | günstiger, etwas ungenauer |
| `gpt-4o-transcribe-diarize` | **nur Datei** | Sprecher-Labels; nimmt keinen `prompt` |
| `gpt-realtime-whisper` | nur Live | ohne serverseitige Sprechpausen-Erkennung |
| `whisper-1` | nur Datei | einziges Modell mit Wort-Zeitstempeln und SRT/VTT |

Sprecher-Labels sind bewusst **nicht** bei den Live-Modellen eingetragen: Der Anbieter
beschränkt `gpt-4o-transcribe-diarize` auf die Datei-Transkription. Wer Sprecher-Labels
für eine Live-Aufnahme braucht, lässt den Mitschnitt hinterher durch `audio/process`
laufen.

## Fehlerbilder

| Meldung | Ursache |
|---|---|
| `Keine MongoDB-URI` | `MONGODB_URI` nicht gesetzt und `--uri` fehlt |
| `Die MONGODB_URI nennt keinen Datenbanknamen` | Datenbank in die URI aufnehmen oder `--db` mitgeben |
| `pymongo fehlt` | `pip install pymongo` |
| Timeout beim Verbinden | Netzwerk erreicht MongoDB nicht (Port 27017 offen? VPN?) |
| Maske zeigt trotzdem nichts | Dienst neu starten — die LLM-Konfiguration wird beim Start gelesen |

## Gegenprobe

```bash
curl -X POST "$SECRETARY_SERVICE_URL/api/realtime/transcription-session" \
  -H "Content-Type: application/json" \
  -H "X-Secretary-Api-Key: $SECRETARY_SERVICE_API_KEY" \
  -d '{"language":"de"}'
```

Erwartet: `{"status":"success","data":{"value":"ek_…","model":"gpt-live-transcribe",…}}`.
Kommt `503`, ist in der Maske nichts zugeordnet; kommt `502`, lehnt der Anbieter das
gewählte Modell für Realtime ab — dann ein anderes wählen.
