# Media API Endpoints

Medien einer Webseite oder Player-Adresse per yt-dlp auflösen, laden, als Playlist auflisten oder
ihre fertigen Untertitel als Transkript holen.
Gebaut für KnowledgeScout („Webseite als Quelle erschließen", „Playlist erschließen"). Kein stiller
Fallback: kennt yt-dlp die Seite nicht, kommt ein Fehler mit Grund.

`noplaylist` ist für `/resolve` und `/download` gesetzt: ein Video-Link mit `&list=` liefert dort nur
das eine Video, nie die ganze Playlist. Nur `/playlist` löst Listen auf.

## Anmeldung je Aufruf: Feld `cookies`

Alle vier Routen nehmen optional ein Feld `cookies` mit dem Inhalt einer Netscape-`cookies.txt`
(Export aus dem Browser, z. B. „Get cookies.txt LOCALLY"). KnowledgeScout hinterlegt diese Datei
je Person im Konto („Video-Anmeldung") und schickt sie bei jedem Medien-Aufruf mit. So braucht
der Server keine gemeinsame Anmeldung, und YouTube-Sperren („Sign in to confirm you're not a bot",
private oder nur für Mitglieder sichtbare Videos) lassen sich mit dem eigenen Konto umgehen.

```json
{ "url": "https://www.youtube.com/watch?v=VIDEO_ID", "cookies": "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t...\n" }
```

Verhalten:

- Der Inhalt landet je Aufruf in einer temporären Datei mit Rechten `0600`, geht als `cookiefile` an
  yt-dlp und wird nach dem Aufruf gelöscht, auch wenn yt-dlp scheitert. Nichts bleibt auf dem Server.
- Er hat Vorrang vor der Server-Datei `YTDLP_COOKIES_FILE`. Ohne das Feld gilt die Server-Datei wie bisher.
- Er taucht in keiner Antwort und keinem Log auf; geloggt wird nur, ob eine Anmeldung mitkam (`anmeldung`).
- Geprüft werden nur Typ, Leere und Größe (höchstens 256 KiB); das Format kennt yt-dlp, die Pflicht-Cookies
  prüft KnowledgeScout beim Hinterlegen.

**Fehler**: `400 INVALID_COOKIES`, wenn das Feld kein Text, leer, größer als 256 KiB ist oder Null-Bytes enthält.

## POST /api/media/resolve

Löst eine Seiten- oder Player-Adresse zur direkten Medienadresse auf und liefert die Metadaten,
die yt-dlp über die Seite kennt. Lädt nichts herunter.

### Request

```json
{ "url": "https://www.youtube.com/watch?v=VIDEO_ID" }
```

Optional `cookies`, siehe [Anmeldung je Aufruf](#anmeldung-je-aufruf-feld-cookies).

### Response

```json
{
  "status": "success",
  "data": {
    "extractor": "youtube",
    "title": "start.klar. mit Gast",
    "duration": 3721,
    "ext": "m4a",
    "url": "https://.../audio.m4a",
    "protocol": "https",
    "http_headers": {},
    "ist_audio": true,
    "metadata": {
      "id": "VIDEO_ID",
      "description": "Gast: ...\n\nThema: ...",
      "upload_date": "2015-03-12",
      "uploader": "Markus Lobis",
      "channel": "start.klar.",
      "chapters": [{ "title": "Begrüßung", "start_time": 0.0, "end_time": 60.0 }],
      "tags": ["Bruneck", "Dialog"],
      "thumbnail": "https://i.ytimg.com/vi/VIDEO_ID/maxresdefault.jpg",
      "webpage_url": "https://www.youtube.com/watch?v=VIDEO_ID"
    }
  }
}
```

| Feld in `metadata` | Bedeutung |
|---|---|
| `description` | Beschreibung der Seite wörtlich, wie yt-dlp sie liefert |
| `upload_date` | Veröffentlichungsdatum als `JJJJ-MM-TT`; `null`, wenn yt-dlp keines kennt (wird nicht geraten) |
| `uploader`, `channel` | Konto und Kanal; `channel` kann bei Vimeo/PeerTube fehlen |
| `chapters` | Kapitel mit Zeitmarken in Sekunden, leer wenn keine |
| `tags` | Schlagworte der Seite, leer wenn keine |
| `thumbnail` | Vorschaubild in der höchsten bekannten Auflösung |
| `webpage_url` | Kanonische Seitenadresse |

Die Felder außerhalb von `metadata` sind unverändert zu früheren Versionen.

**Fehler**: `400 MISSING_URL`, `400 INVALID_COOKIES`, `422 MEDIA_NOT_RESOLVABLE` (unbekannte Seite oder keine direkte Medienadresse).

`400 SSRF_BLOCKED` bei allen vier Endpunkten, wenn die Adresse oder ein Ziel, das yt-dlp daraus abruft, kein öffentliches Ziel ist (eigener Rechner, privates Netz, Cloud-Metadaten) oder nicht `http`/`https` verwendet. Ausnahmen je Installation: `FETCH_ALLOWED_HOSTS`.

## POST /api/media/download

Lädt das Medium per yt-dlp (HLS/DASH über ffmpeg) und liefert die Datei als Antwort. Mit
`nur_audio` (Vorgabe `true`) zieht ffmpeg die Tonspur als m4a heraus.

### Request

```json
{ "url": "https://www.rainews.it/...", "nur_audio": true }
```

Optional `cookies`, siehe [Anmeldung je Aufruf](#anmeldung-je-aufruf-feld-cookies).

### Response

Dateibytes mit den Headern `X-Media-Ext`, `X-Media-Title` (URL-kodiert), `X-Media-Duration`,
`X-Media-Is-Audio`, `X-Media-Extractor`.

**Fehler**: `400 MISSING_URL`, `400 INVALID_NUR_AUDIO`, `400 INVALID_COOKIES`, `422 MEDIA_NOT_DOWNLOADABLE`.

## POST /api/media/playlist

Löst eine Playlist flach auf: nur die Liste der Einträge, kein Abruf je Video, kein Download.
Geht mit allem, was yt-dlp als Playlist kennt (YouTube, Vimeo, PeerTube). Private oder gelöschte
Einträge bleiben in der Liste und tragen einen Grund, damit die Positionen stimmen und nichts
stillschweigend fehlt.

### Request

```json
{ "url": "https://www.youtube.com/playlist?list=PLAYLIST_ID" }
```

Optional `cookies`, siehe [Anmeldung je Aufruf](#anmeldung-je-aufruf-feld-cookies).

### Response

```json
{
  "status": "success",
  "data": {
    "extractor": "youtube:tab",
    "id": "PLAYLIST_ID",
    "title": "start.klar. im UFO Bruneck",
    "uploader": "Markus Lobis",
    "channel": "Markus Lobis",
    "description": "Dialogreihe seit 2015",
    "webpage_url": "https://www.youtube.com/playlist?list=PLAYLIST_ID",
    "anzahl": 32,
    "anzahl_verfuegbar": 31,
    "entries": [
      { "position": 1, "id": "VIDEO_ID", "url": "https://www.youtube.com/watch?v=VIDEO_ID",
        "title": "Folge 1", "duration": 3600, "verfuegbar": true, "grund": null },
      { "position": 2, "id": "VIDEO_ID2", "url": "https://www.youtube.com/watch?v=VIDEO_ID2",
        "title": "[Private video]", "duration": null, "verfuegbar": false, "grund": "privat" }
    ]
  }
}
```

| Feld | Bedeutung |
|---|---|
| `anzahl` | Zahl der Einträge in der Liste, auch die nicht verfügbaren |
| `anzahl_verfuegbar` | Einträge, die sich mit `/resolve` oder `/download` holen lassen |
| `position` | Stelle in der Playlist, 1-basiert (yt-dlp `playlist_index`, sonst Reihenfolge) |
| `duration` | Dauer in Sekunden, `null` wenn yt-dlp sie flach nicht kennt |
| `verfuegbar`, `grund` | `false` mit Grund (`privat`, `geloescht`, `Anmeldung noetig`, `nur Premium`, `nur Abonnenten`, angekündigte Premiere) |

Für Beschreibung, Datum und Kapitel eines einzelnen Videos anschließend `/resolve` auf die
`url` des Eintrags rufen; die flache Liste enthält diese Felder nicht.

**Fehler**: `400 MISSING_URL`, `400 INVALID_COOKIES`, `422 PLAYLIST_NOT_RESOLVABLE` (unbekannte Seite, private oder
gelöschte Playlist, leere Playlist, oder die Adresse ist keine Playlist sondern ein einzelnes Video).

## POST /api/media/subtitles

Liefert die fertigen Untertitel einer Videoseite als Transkript mit Zeitmarken. Lädt das Medium nicht
und transkribiert nichts: yt-dlp liest die Seite, wählt genau eine Spur und lädt nur diese eine Datei.
Die Antwort kommt in Sekunden, auch bei langen Videos.

### Welche Spur gilt

1. Die **von Hand gepflegte** Spur der gewünschten Sprache (`sprache`; ohne Angabe die Originalsprache
   des Videos).
2. Sonst die **automatisch erzeugte** Spur in der Originalsprache des Videos (bei YouTube `<sprache>-orig`).

Maschinell übersetzte Spuren (bei YouTube etwa `de` zu einem englischen Video) sind Übersetzungen der
automatischen Spur und gelten nie als Transkript. Der Live-Chat eines früheren Livestreams ist keine
Untertitelspur. Gelesen werden die Formate `json3`, `vtt` und `srt`, in dieser Reihenfolge.

### Request

```json
{ "url": "https://www.youtube.com/watch?v=VIDEO_ID", "sprache": "en" }
```

`sprache` ist optional. Optional `cookies`, siehe [Anmeldung je Aufruf](#anmeldung-je-aufruf-feld-cookies).

### Response

```json
{
  "status": "success",
  "data": {
    "extractor": "youtube",
    "id": "VIDEO_ID",
    "title": "Beyond the Numbers",
    "duration": 5120,
    "sprache": "en",
    "art": "automatisch",
    "spur": "en-orig",
    "format": "json3",
    "verfuegbar": { "manuell": [], "automatisch_original": ["en"], "automatisch_uebersetzt": 175, "originalsprache": "en" },
    "abdeckung": { "beginn": 1.2, "ende": 5104.0, "anteil": 0.997, "groesste_luecke": 12.4, "groesste_luecke_bei": 2310.0, "zeilen": 2890, "woerter": 11840 },
    "absaetze": [{ "start": 1.2, "text": "good morning everyone ..." }],
    "text": "[00:00:01] good morning everyone ...\n\n[00:01:03] ...",
    "metadata": { "id": "VIDEO_ID", "description": "...", "upload_date": "2026-11-10", "chapters": [] }
  }
}
```

| Feld | Bedeutung |
|---|---|
| `sprache` | Sprache der gelieferten Spur (Grundsprache, z. B. `en`); kann von der gewünschten abweichen, wenn es nur die automatische Spur gibt |
| `art` | `manuell` (von Hand gepflegt) oder `automatisch` (von der Plattform erzeugt) |
| `spur`, `format` | Schlüssel der Spur bei yt-dlp und gelesenes Format |
| `verfuegbar` | Was das Video trägt: gepflegte Spuren, automatische Spuren in der Originalsprache, Zahl der übersetzten Spuren, erkannte Originalsprache |
| `abdeckung` | Erste und letzte Zeile in Sekunden, Anteil der letzten Zeile an der Dauer (`null` ohne Dauer), größte Lücke und ihre Stelle, Zahl der Zeilen und Wörter. Bei früheren Livestreams zeigt sich hier, ob die Spur das ganze Video abdeckt |
| `absaetze` | Die Zeilen zu Absätzen zusammengezogen: neu je Kapitelbeginn und rund je Minute (bevorzugt nach einem Satzende, spätestens nach 90 Sekunden), `start` in Sekunden |
| `text` | Dieselben Absätze als Text, jeder mit Zeitmarke `[hh:mm:ss]` |
| `metadata` | Derselbe Block wie bei `/resolve`; ein zweiter Aufruf für Beschreibung, Datum und Kapitel entfällt |

Automatische Untertitel wiederholen im Format `vtt` jede Zeile (rollende Anzeige); die Wiederholungen
fallen beim Lesen weg.

### Fehler

`400 MISSING_URL`, `400 INVALID_SPRACHE`, `400 INVALID_COOKIES`, `400 SSRF_BLOCKED`.

`422 SUBTITLES_NOT_AVAILABLE`, wenn es keine brauchbare Spur gibt. Der Grund steht in
`error.details.grund`, was das Video trägt in `error.details.verfuegbar`:

| `grund` | Bedeutung |
|---|---|
| `KEINE_UNTERTITEL` | Das Video trägt keine Untertitel, oder keine in der gewünschten Sprache und keine automatische Spur |
| `NUR_UEBERSETZTE_SPUREN` | Es gibt nur maschinell übersetzte Spuren, die Originalspur fehlt |
| `SPRACHE_NICHT_EINDEUTIG` | Mehrere Spuren, aber die Sprache des Videos ist unbekannt: `sprache` angeben |
| `FORMAT_NICHT_LESBAR` | Die Spur gibt es nur in einem Format, das hier nicht gelesen wird |
| `SPUR_LEER` | Die Spur ist angekündigt, lieferte aber keinen Inhalt oder keine Textzeilen |
| `VIDEO_LAEUFT_NOCH` | Livestream läuft noch oder ist erst angekündigt |

Es gibt keinen stillen Rückfall auf die Tonspur: ob danach `/download` und eine Transkription folgen,
entscheidet der Aufrufer. Scheitert yt-dlp an YouTube (Anmeldung, Sperre), kommt ebenfalls
`422 SUBTITLES_NOT_AVAILABLE` mit den Gründen der anderen Medien-Routen (`YOUTUBE_ANMELDUNG_FEHLT`,
`YOUTUBE_SERVER_GESPERRT` …).

## Konfiguration

| Variable | Wirkung |
|---|---|
| `YTDLP_COOKIES_FILE` | Netscape-Cookie-Datei des Servers für yt-dlp, wenn die Seite eine Anmeldung verlangt; ein mitgeschicktes Feld `cookies` hat Vorrang |

## Siehe auch

- [Video Endpoints](video.md) für die vollständige YouTube-Verarbeitung mit Transkription.
