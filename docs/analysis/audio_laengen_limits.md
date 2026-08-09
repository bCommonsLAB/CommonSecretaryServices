# Analyse: Längen- und Größenlimits bei der Audio-Transkription

Status: Ursache bestätigt durch Log (2026-08-09).
`max_file_size` in `config/config.yaml` und Fallback in `src/core/config.py`
auf 500000000 Bytes angehoben. Server-Neustart nötig, damit die Config greift.

## Problem

Beim Transkribieren von Audiodateien kommt es häufig zu Fehlern wegen "Überlänge".
Der genaue Fehlertext ist noch offen. Der String "Überlänge" existiert **nicht** im
Repository. Die Meldung stammt also von einer der unten genannten Prüfungen oder
von der OpenAI-API.

## Gefundene Limits (Kette vom Upload bis zur API)

Eine Audiodatei durchläuft vier unabhängige Grenzen. Jede kann alleine abbrechen.

| # | Grenze | Wert aktuell | Ort |
|---|--------|--------------|-----|
| 1 | HTTP-Upload-Größe | 500 MB | `.env` → `MAX_UPLOAD_SIZE_MB=500`, gelesen in `src/api/__init__.py:88` |
| 2 | Dateigröße im Prozessor | 200 MB | `config/config.yaml:191` → `processors.audio.max_file_size` |
| 3 | Max. Segmentanzahl | 100 Segmente à 300 s = ca. 8,3 h | `config/config.yaml:192-193` |
| 4 | Whisper-API pro Request | ca. 25 MB (extern, OpenAI) | nicht im Code hinterlegt |

### 1. Flask-Upload (HTTP 413)

`MAX_CONTENT_LENGTH` und `MAX_FORM_MEMORY_SIZE` werden beide auf denselben Wert
gesetzt. Bei Überschreitung bricht Werkzeug ab, bevor eigener Code läuft.
Meldung: `Request zu groß (HTTP 413). Content-Length: ...`

### 2. Prozessor-Dateigröße

Zwei Prüfstellen in `src/processors/audio_processor.py`:

- Zeile 373: beim Download per URL (nutzt den `content-length`-Header)
- Zeile 413: bei lokaler Datei (nutzt `os.path.getsize`)

Meldung in beiden Fällen: `Audio-Datei zu groß: {size} Bytes (max: {max} Bytes)`

### 3. Segmentanzahl — stilles Abschneiden

In `get_audio_segments` (`audio_processor.py:543` und `:576`) wird die
Segmentierung bei `max_segments` einfach abgebrochen. Es gibt **keine**
Fehlermeldung, nur einen Log-Eintrag. Der Rest der Aufnahme fehlt dann
kommentarlos im Transkript. Das ist ein eigenes Risiko, aber kein "Überlänge"-Fehler.

### 4. Whisper-API

Segmente werden als Mono-MP3 mit 16 kHz exportiert
(`audio_processor.py:554-557`). 5 Minuten ergeben grob 5 MB. Das 25-MB-Limit
der API wird damit normalerweise nicht erreicht. Nur bei stark erhöhter
`segment_duration` würde das relevant.

### Nebenbefund: Video-Pfad

`src/processors/video_processor.py:1039` wirft
`Video zu lang: {duration} Sekunden (Maximum: {max_duration})`.
`processors.video.max_duration` fehlt in der `config.yaml`, daher greift der
Code-Fallback von 3600 s (1 Stunde). Wenn die Audiodatei aus einem Video kommt,
ist das der wahrscheinlichste Auslöser einer "zu lang"-Meldung.

## Drei Lösungsvarianten

### Variante A — Werte in der Konfiguration anheben (minimal)

Nur Zahlen in `.env` und `config/config.yaml` ändern, kein Code-Eingriff.

- `MAX_UPLOAD_SIZE_MB` auf z. B. 1000
- `processors.audio.max_file_size` auf z. B. 1000000000
- `processors.audio.max_segments` auf z. B. 500 (entspricht ca. 41 h)
- `processors.video.max_duration` explizit ergänzen, z. B. 36000

Vorteil: eine Zeile pro Limit, sofort wirksam, kein Regressionsrisiko.
Nachteil: löst nur die Grenzen, nicht die Ursachen. Bei sehr großen Dateien
steigt der Arbeitsspeicherbedarf stark, weil pydub die komplette Datei
über `AudioSegment.from_file` in den RAM lädt. Laufzeit und API-Kosten wachsen
linear mit der Länge.

### Variante B — Limits abschaltbar machen (`0` bzw. `null` = unbegrenzt)

Zusätzlich zu A: die Prüfungen so anpassen, dass ein Wert von `0` oder `null`
das Limit deaktiviert. Betroffen wären `audio_processor.py:373`, `:413`,
`:543`, `:576` und `video_processor.py:1039`.

Vorteil: Limits bleiben als Schutz erhalten, lassen sich aber pro Umgebung
gezielt aufheben.
Nachteil: Code-Änderung an fünf Stellen inklusive Tests. Ohne jede Grenze
kann ein einziger großer Upload den Server per Out-of-Memory beenden.

### Variante C — Streaming-Segmentierung statt Vollladen

Die Datei nicht mehr komplett per pydub in den RAM laden, sondern direkt per
ffmpeg (`-f segment`) in Stücke schneiden und diese einzeln transkribieren.
Das Größenlimit wird dadurch weitgehend gegenstandslos.

Vorteil: löst die eigentliche Ursache, konstanter Speicherbedarf unabhängig
von der Dateilänge.
Nachteil: deutlich größerer Eingriff. Die Kapitel-Logik in `get_audio_segments`
müsste umgebaut werden, ebenso die Pfade in `video_processor` und
`youtube_processor`. Braucht eine eigene Teststrecke.

## Empfehlung

Zuerst Variante A, weil sie ohne Risiko prüfbar macht, ob das Limit überhaupt
die Ursache war. Variante C nur, wenn regelmäßig Dateien jenseits von
etwa 500 MB verarbeitet werden sollen.

## Offene Frage vor der Umsetzung

Der exakte Fehlertext aus dem Log entscheidet, welches der vier Limits greift.
Ohne diesen Text wäre jede Änderung geraten.
