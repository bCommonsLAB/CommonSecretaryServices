# Media API Endpoints

Medien einer Webseite oder Player-Adresse per yt-dlp auflösen, laden oder als Playlist auflisten.
Gebaut für KnowledgeScout („Webseite als Quelle erschließen", „Playlist erschließen"). Kein stiller
Fallback: kennt yt-dlp die Seite nicht, kommt ein Fehler mit Grund.

`noplaylist` ist für `/resolve` und `/download` gesetzt: ein Video-Link mit `&list=` liefert dort nur
das eine Video, nie die ganze Playlist. Nur `/playlist` löst Listen auf.

## Anmeldung je Aufruf: Feld `cookies`

Alle drei Routen nehmen optional ein Feld `cookies` mit dem Inhalt einer Netscape-`cookies.txt`
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

## Konfiguration

| Variable | Wirkung |
|---|---|
| `YTDLP_COOKIES_FILE` | Netscape-Cookie-Datei des Servers für yt-dlp, wenn die Seite eine Anmeldung verlangt; ein mitgeschicktes Feld `cookies` hat Vorrang |

## Siehe auch

- [Video Endpoints](video.md) für die vollständige YouTube-Verarbeitung mit Transkription.
