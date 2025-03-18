# Testszenario für Story-Generierung

Diese Anleitung beschreibt, wie Sie die Story-Generierungsfunktion testen und die Ergebnisse überprüfen können.

## Voraussetzungen

1. MongoDB muss installiert und erreichbar sein
2. Die Python-Umgebung muss eingerichtet sein (`pip install -r requirements.txt`)
3. Die API muss gestartet sein

## Schritt 1: Test-Daten erstellen

Führen Sie das folgende Skript aus, um die erforderlichen Test-Daten in der Datenbank zu erstellen:

```bash
cd test
python create_test_data.py
```

Dies erstellt:
- 3 Test-Topics (Nachhaltigkeit, Digitalisierung, Energie)
- 3 Zielgruppen (Politik, Wirtschaft, Zivilgesellschaft)
- 3 Test-Sessions mit Inhalten, die mit den Topics verknüpft sind

## Schritt 2: Topic und Zielgruppen auflisten (optional)

Um zu überprüfen, welche Topics und Zielgruppen verfügbar sind, können Sie die folgenden API-Endpunkte aufrufen:

```bash
# Topics abrufen
curl http://localhost:5000/api/story/topics

# Zielgruppen abrufen
curl http://localhost:5000/api/story/target-groups
```

## Schritt 3: Story generieren

Um eine Story zu generieren, senden Sie eine POST-Anfrage an den `/api/story/generate`-Endpunkt:

```bash
curl -X POST http://localhost:5000/api/story/generate \
  -H "Content-Type: application/json" \
  -d '{
    "topic_id": "nachhaltigkeit-2023",
    "event": "forum-2023",
    "target_group": "politik",
    "languages": ["de", "en"],
    "detail_level": 3
  }'
```

Beispiel für eine Anfrage mit bestimmten Session-IDs:

```bash
curl -X POST http://localhost:5000/api/story/generate \
  -H "Content-Type: application/json" \
  -d '{
    "topic_id": "nachhaltigkeit-2023",
    "event": "forum-2023",
    "target_group": "politik",
    "languages": ["de", "en"],
    "detail_level": 3,
    "session_ids": ["session1", "session3"]
  }'
```

## Schritt 4: Generierte Story überprüfen

### Markdown-Dateien im Dateisystem

Die generierten Markdown-Dateien werden im Verzeichnis `stories/<event>_<target_group>/<topic_id>` gespeichert. Zum Beispiel:

```
stories/forum-2023_politik/nachhaltigkeit-2023/nachhaltigkeit-2023_de.md
stories/forum-2023_politik/nachhaltigkeit-2023/nachhaltigkeit-2023_en.md
```

### Markdown-Inhalte in der API-Antwort

Die API-Antwort enthält die generierten Markdown-Inhalte in der Struktur:

```json
{
  "status": "success",
  "request": { ... },
  "process": { ... },
  "data": {
    "input": { ... },
    "output": {
      "topic_id": "nachhaltigkeit-2023",
      "event": "forum-2023",
      "target_group": "politik",
      "markdown_files": {
        "de": "stories/forum-2023_politik/nachhaltigkeit-2023/nachhaltigkeit-2023_de.md",
        "en": "stories/forum-2023_politik/nachhaltigkeit-2023/nachhaltigkeit-2023_en.md"
      },
      "markdown_contents": {
        "de": "# Nachhaltigkeit und Umweltschutz\n\n...",
        "en": "# Sustainability and Environmental Protection\n\n..."
      },
      "session_count": 2,
      "metadata": { ... }
    }
  }
}
```

## Struktur der generierten Story

Die generierte Story enthält:

1. Titel und Beschreibung des Themas
2. Allgemeine Informationen wie Event, Zielgruppe, Anzahl der Sessions
3. Eine Liste der relevanten Sessions mit Titeln und Inhalten
4. Platzhalter für zukünftige LLM-generierte Inhalte (werden in Phase B implementiert)

## Template-Anpassungen (optional)

Die Story-Generierung verwendet Templates, die im Verzeichnis `templates/` gespeichert sind. Sie können diese anpassen oder neue erstellen:

- `templates/Story_default_de.md`: Standard-Template (Deutsch)
- `templates/Story_default_en.md`: Standard-Template (Englisch)
- `templates/Story_eco_social_de.md`: Öko-soziales Template (Deutsch)
- `templates/Story_eco_social_en.md`: Öko-soziales Template (Englisch)

## Fehlerbehandlung

Wenn bei der Story-Generierung Fehler auftreten, enthält die API-Antwort detaillierte Fehlerinformationen:

```json
{
  "status": "error",
  "request": { ... },
  "process": { ... },
  "error": {
    "code": "TOPIC_NOT_FOUND",
    "message": "Thema mit ID xyz nicht gefunden",
    "details": { ... }
  }
}
```

Häufige Fehlercodes:
- `VALIDATION_ERROR`: Eingabedaten sind ungültig
- `TOPIC_NOT_FOUND`: Das angegebene Thema existiert nicht
- `TARGET_GROUP_NOT_FOUND`: Die angegebene Zielgruppe existiert nicht
- `NO_SESSIONS_FOUND`: Es wurden keine relevanten Sessions gefunden
- `STORY_PROCESSING_ERROR`: Allgemeiner Fehler bei der Story-Verarbeitung 