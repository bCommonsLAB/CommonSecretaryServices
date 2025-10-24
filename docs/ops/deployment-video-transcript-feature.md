# Deployment: video_transcript Feature

## Übersicht der Änderungen

Das neue `video_transcript` Parameter-Feature wurde in folgenden Dateien implementiert:

### Geänderte Dateien
1. `src/api/routes/session_routes.py` - API Input Model
2. `src/core/models/session.py` - SessionInput Dataclass
3. `src/processors/session_processor.py` - Prozessor-Logik

### Neue Dateien
1. `docs/processors/session/video-transcript-parameter.md` - Feature-Dokumentation
2. `docs/ops/cache-and-logging-inspection.md` - Cache & Logging Guide
3. `docs/ops/deployment-video-transcript-feature.md` - Diese Datei

## Deployment-Checkliste

### ✅ Vorbereitung (Bereits erledigt)

- [x] Code-Änderungen implementiert
- [x] Rückwärtskompatibilität gewährleistet (neuer Parameter ist optional)
- [x] Cache-Key-Generierung angepasst
- [x] Dokumentation erstellt

### 📋 Deployment-Schritte

#### 1. **Code-Review und Tests** (Empfohlen)

```bash
# Linter prüfen
python -m mypy src/

# Unit-Tests ausführen (wenn vorhanden)
pytest tests/

# Manueller API-Test
curl -X POST http://localhost:5000/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "Test Event",
    "session": "Test Session",
    "url": "https://example.com",
    "filename": "test.md",
    "track": "test",
    "video_transcript": "Test transcript"
  }'
```

#### 2. **Git Commit & Push**

```bash
# Status prüfen
git status

# Dateien hinzufügen
git add src/api/routes/session_routes.py
git add src/core/models/session.py
git add src/processors/session_processor.py
git add docs/processors/session/video-transcript-parameter.md
git add docs/ops/cache-and-logging-inspection.md
git add docs/ops/deployment-video-transcript-feature.md

# Commit
git commit -m "feat: Add video_transcript parameter to session API

- Add optional video_transcript parameter to skip video processing
- Update SessionInput dataclass with new field
- Implement conditional logic in SessionProcessor
- Update cache key generation to include transcript hash
- Add comprehensive documentation

BREAKING CHANGE: None (backward compatible, new parameter is optional)"

# Push to remote
git push origin main
```

#### 3. **Lokales Deployment (Development)**

**Option A: Ohne Docker**
```bash
# Virtuelle Umgebung aktivieren
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Keine neuen Dependencies installiert - skip
# pip install -r requirements.txt

# Server neu starten
# Ctrl+C zum Stoppen
python src/main.py
```

**Option B: Mit Docker**
```bash
# Docker Container stoppen
docker-compose down

# Neu bauen und starten
docker-compose up --build -d

# Logs verfolgen
docker-compose logs -f secretary-services
```

#### 4. **Production Deployment**

##### A. Docker Production Deployment

```bash
# 1. Code pullen
git pull origin main

# 2. Docker Image neu bauen
docker build -t secretary-services:latest .

# 3. Alte Container stoppen
docker-compose down

# 4. Neue Container starten
docker-compose up -d

# 5. Health Check
curl http://localhost:5001/api/
# Erwartete Response: {"message": "Welcome to the Processing Service API!"}

# 6. Logs prüfen
docker-compose logs -f secretary-services | grep "video_transcript"
```

##### B. Traditionelles Production Deployment (ohne Docker)

```bash
# 1. Code pullen
cd /opt/secretary  # oder dein Installationspfad
git pull origin main

# 2. Virtuelle Umgebung aktivieren
source venv/bin/activate

# 3. Dependencies aktualisieren (keine neuen in diesem Feature)
# pip install -r requirements.txt

# 4. Service neu starten
sudo systemctl restart secretary.service

# 5. Status prüfen
sudo systemctl status secretary.service

# 6. Logs verfolgen
tail -f /var/log/secretary/prod.log
```

## Verifikation nach Deployment

### 1. API-Endpoint testen

**Test 1: Mit video_transcript (NEU)**
```bash
curl -X POST http://localhost:5001/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "Deployment Test",
    "session": "Video Transcript Test",
    "url": "https://example.com/test",
    "filename": "test-transcript.md",
    "track": "test",
    "video_transcript": "This is a test transcript to verify the new feature."
  }'
```

**Erwartete Response:**
- Status: 200 OK
- `process.duration` sollte sehr kurz sein (< 10 Sekunden)
- Logs sollten zeigen: `"Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)"`

**Test 2: Ohne video_transcript (Bestehende Funktionalität)**
```bash
curl -X POST http://localhost:5001/api/session/process \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "Deployment Test",
    "session": "Normal Processing Test",
    "url": "https://example.com/test",
    "filename": "test-normal.md",
    "track": "test",
    "video_url": "https://example.com/video.mp4"
  }'
```

**Erwartete Response:**
- Status: 200 OK
- Video-Verarbeitung läuft normal ab

### 2. Logs prüfen

```bash
# Windows PowerShell
Get-Content logs/dev_detailed.log -Tail 50 | Select-String "video_transcript|Video-Verarbeitung"

# Linux
tail -50 logs/dev_detailed.log | grep -E "video_transcript|Video-Verarbeitung"
```

**Erwartete Log-Einträge:**
```
INFO - Verwende vorhandenes Video-Transkript (Video-Verarbeitung übersprungen)
DEBUG - Session-Ergebnis im Cache gespeichert
```

### 3. MongoDB Cache prüfen

```javascript
mongosh
use <your-database-name>

// Neue Sessions mit video_transcript finden
db.session_cache.find({
  "result.input_data.video_transcript": { $ne: null }
}).pretty()

// Cache-Key sollte video_transcript_hash enthalten
db.session_cache.findOne({
  "data.session": "Video Transcript Test"
}, {
  "cache_key": 1,
  "data.session": 1,
  "result.input_data.video_transcript": 1
})
```

### 4. Swagger/OpenAPI Dokumentation prüfen

```bash
# Browser öffnen
open http://localhost:5001/api/docs

# Prüfe:
# 1. SessionInput Model hat neues Feld "video_transcript"
# 2. Beschreibung: "Vorhandenes Video-Transkript (überspringt Video-Verarbeitung wenn gesetzt)"
```

## Rollback-Plan

Falls Probleme auftreten:

### Option 1: Git Revert
```bash
# Letzten Commit rückgängig machen
git revert HEAD
git push origin main

# Deployment wiederholen
```

### Option 2: Zu vorheriger Version zurück
```bash
# Vorherigen Git-Hash finden
git log --oneline -10

# Zu vorheriger Version wechseln
git checkout <previous-commit-hash>

# Docker neu bauen
docker-compose up --build -d
```

### Option 3: Hotfix (falls nur Prozessor-Logik betroffen)

Kommentiere in `src/processors/session_processor.py` die neue Logik aus:

```python
# Temporärer Hotfix: video_transcript deaktivieren
video_transcript = None  # Force disable new feature

# Original-Code bleibt unverändert
if video_url:
    video_transcript_text = await self._process_video(...)
```

## Monitoring nach Deployment

### KPIs zu überwachen:

1. **API-Response-Zeit**
   - Sessions mit `video_transcript` sollten deutlich schneller sein (2-5 Minuten gespart)

2. **Cache-Hit-Rate**
   - Sollte gleich bleiben oder steigen

3. **Fehlerrate**
   - Sollte nicht steigen

4. **Log-Einträge**
   ```bash
   # Neue Feature-Nutzung zählen
   grep -c "Verwende vorhandenes Video-Transkript" logs/dev_detailed.log
   ```

5. **MongoDB Collection Größe**
   ```javascript
   db.session_cache.stats()
   ```

## Besonderheiten

### Keine Breaking Changes
- ✅ Alle bestehenden API-Calls funktionieren unverändert
- ✅ Neuer Parameter ist optional
- ✅ Keine Datenbankmigrationen erforderlich
- ✅ Keine neuen Dependencies

### Cache-Kompatibilität
- ✅ Alte Cache-Einträge bleiben gültig
- ✅ Neue Cache-Keys enthalten `video_transcript_hash` nur wenn gesetzt
- ✅ Cache-Key-Format ist abwärtskompatibel

### Logging
- ✅ Neuer Log-Eintrag identifiziert Feature-Nutzung
- ✅ Keine Änderungen am Log-Format
- ✅ Log-Level bleibt unverändert

## Dokumentation-Updates

Nach erfolgreichem Deployment:

1. ✅ Interne Docs aktualisiert (`docs/processors/session/`)
2. ✅ Ops-Dokumentation erstellt (`docs/ops/`)
3. 📝 API-Dokumentation (Swagger) wird automatisch aktualisiert
4. 📝 Optional: Changelog/Release Notes erstellen
5. 📝 Optional: Team über neues Feature informieren

## Support & Troubleshooting

### Häufige Probleme

**Problem 1: "video_transcript Parameter wird ignoriert"**
```bash
# Lösung: Server neu starten, Code-Cache löschen
find . -type d -name "__pycache__" -exec rm -rf {} +
docker-compose restart
```

**Problem 2: "Cache-Key-Fehler"**
```bash
# Lösung: Cache für Test-Sessions löschen
mongosh --eval 'db.session_cache.deleteMany({"data.event": "Deployment Test"})'
```

**Problem 3: "Logs zeigen alte Logik"**
```bash
# Prüfe, ob der richtige Code deployed ist
docker exec -it <container-id> cat /app/src/processors/session_processor.py | grep -A5 "video_transcript"
```

## Kontakt

Bei Problemen oder Fragen zum Deployment:
- Logs prüfen: `logs/dev_detailed.log`
- MongoDB prüfen: Collection `session_cache`
- Dokumentation: `docs/processors/session/video-transcript-parameter.md`

