# Template Content Feature

## Übersicht

Das neue `template_content` Feature ermöglicht es, Template-Inhalte direkt in API-Aufrufen zu übergeben, anstatt sich auf gespeicherte Template-Dateien zu verlassen.

## Funktionalität

### Vorher (nur Datei-basierte Templates)
```python
# Nur Template-Dateiname möglich
POST /api/transformer/template
{
    "text": "Max Mustermann ist 30 Jahre alt",
    "template": "Gedanken",  # Verweist auf templates/Gedanken.md
    "source_language": "de",
    "target_language": "de"
}
```

### Jetzt (beide Optionen verfügbar)

#### Option 1: Datei-basiertes Template (bestehende Funktionalität)
```python
POST /api/transformer/template
{
    "text": "Max Mustermann ist 30 Jahre alt",
    "template": "Gedanken",  # Verweist auf templates/Gedanken.md
    "source_language": "de",
    "target_language": "de"
}
```

#### Option 2: Direkter Template-Inhalt
```python
POST /api/transformer/template
{
    "text": "Max Mustermann ist 30 Jahre alt",
    "template_content": """
---
title: {{title|Titel der Person}}
age: {{age|Alter der Person}}
city: {{city|Wohnort der Person}}
---

# {{title}}

**Alter:** {{age}}
**Wohnort:** {{city}}

## Zusammenfassung
{{summary|Kurze Zusammenfassung der Person}}
""",
    "source_language": "de",
    "target_language": "de"
}
```

## API-Parameter

### Neue Parameter

| Parameter | Typ | Erforderlich | Beschreibung |
|-----------|-----|--------------|--------------|
| `template` | string | Nein* | Name des Templates (ohne .md Endung) |
| `template_content` | string | Nein* | Direkter Template-Inhalt (Markdown) |

*Mindestens einer der beiden Parameter muss angegeben werden.

### Validierung

- **Fehler**: Wenn weder `template` noch `template_content` angegeben wird
- **Fehler**: Wenn beide Parameter gleichzeitig angegeben werden
- **Erfolg**: Wenn genau einer der beiden Parameter angegeben wird

## Verwendung

### 1. Einfaches Template mit YAML Frontmatter

```python
template_content = """
---
title: {{title|Titel des Dokuments}}
author: {{author|Autor des Dokuments}}
date: {{date|Datum des Dokuments}}
---

# {{title}}

**Autor:** {{author}}  
**Datum:** {{date}}

## Inhalt
{{content|Hauptinhalt des Dokuments}}
"""
```

### 2. Template ohne YAML Frontmatter

```python
template_content = """
# {{title|Titel des Dokuments}}

**Autor:** {{author|Autor des Dokuments}}  
**Datum:** {{date|Datum des Dokuments}}

## Zusammenfassung
{{summary|Kurze Zusammenfassung}}

## Details
{{details|Detaillierte Beschreibung}}
"""
```

### 3. URL-basierte Transformation

```python
POST /api/transformer/template
{
    "url": "https://example.com/article",
    "template_content": """
---
title: {{title|Titel des Artikels}}
author: {{author|Autor des Artikels}}
publish_date: {{publish_date|Veröffentlichungsdatum}}
---

# {{title}}

**Von:** {{author}}  
**Veröffentlicht:** {{publish_date}}

{{content|Inhalt des Artikels}}
""",
    "source_language": "de",
    "target_language": "de"
}
```

## Vorteile

### 1. Flexibilität
- Templates können dynamisch erstellt werden
- Keine Abhängigkeit von gespeicherten Dateien
- Einfache Anpassung für spezifische Anwendungsfälle

### 2. Portabilität
- Templates können in Anwendungen eingebettet werden
- Keine Dateisystem-Abhängigkeiten
- Einfacher Austausch zwischen Systemen

### 3. Dynamische Templates
- Templates können basierend auf Benutzereingaben generiert werden
- A/B-Testing verschiedener Template-Varianten
- Kontextabhängige Template-Anpassungen

## Technische Details

### Template-Syntax

Die Template-Syntax bleibt identisch zu den Datei-basierten Templates:

- `{{feldname|beschreibung}}` - Strukturierte Felder mit Beschreibung
- `{{feldname}}` - Einfache Kontext-Variablen
- YAML Frontmatter wird unterstützt
- Systemprompts können mit `--- systemprompt` definiert werden

### Verarbeitung

1. **Validierung**: Prüfung auf exklusive Verwendung von `template` oder `template_content`
2. **Template-Extraktion**: Direkte Verwendung des `template_content` oder Laden der Datei
3. **Systemprompt-Extraktion**: Automatische Erkennung und Extraktion von Systemprompts
4. **Variablen-Erkennung**: Parsing der Template-Variablen und Beschreibungen
5. **LLM-Verarbeitung**: Strukturierte Extraktion der Daten
6. **Template-Füllung**: Ersetzung der Variablen mit extrahierten Daten

### Caching

- Templates werden nicht gecacht (da sie dynamisch sein können)
- Extraktionsergebnisse werden weiterhin gecacht
- Cache-Keys basieren auf Text, Sprachen und Template-Inhalt

## Beispiele

### Beispiel 1: Person-Profile

```python
template_content = """
---
name: {{name|Vollständiger Name}}
age: {{age|Alter in Jahren}}
profession: {{profession|Beruf oder Tätigkeit}}
location: {{location|Wohnort oder Standort}}
---

# {{name}}

**Alter:** {{age}} Jahre  
**Beruf:** {{profession}}  
**Standort:** {{location}}

## Biografie
{{biography|Kurze Biografie oder Beschreibung}}

## Interessen
{{interests|Hobbys und Interessen}}
"""
```

### Beispiel 2: Event-Beschreibung

```python
template_content = """
---
event_name: {{event_name|Name des Events}}
date: {{date|Datum des Events}}
location: {{location|Veranstaltungsort}}
organizer: {{organizer|Veranstalter}}
---

# {{event_name}}

**Datum:** {{date}}  
**Ort:** {{location}}  
**Veranstalter:** {{organizer}}

## Beschreibung
{{description|Detaillierte Beschreibung des Events}}

## Teilnehmer
{{participants|Liste der Teilnehmer oder Zielgruppe}}

## Programm
{{program|Ablauf oder Programm des Events}}
"""
```

### Beispiel 3: Produkt-Review

```python
template_content = """
---
product_name: {{product_name|Name des Produkts}}
rating: {{rating|Bewertung (1-5 Sterne)}}
price: {{price|Preis des Produkts}}
category: {{category|Produktkategorie}}
---

# Review: {{product_name}}

**Bewertung:** {{rating}}/5 ⭐  
**Preis:** {{price}}  
**Kategorie:** {{category}}

## Zusammenfassung
{{summary|Kurze Zusammenfassung der Bewertung}}

## Pros
{{pros|Positive Aspekte des Produkts}}

## Cons
{{cons|Negative Aspekte oder Verbesserungsvorschläge}}

## Fazit
{{conclusion|Abschließende Bewertung und Empfehlung}}
"""
```

## Migration

### Von Datei-basierten zu Inline-Templates

1. **Template-Datei lesen**:
   ```bash
   cat templates/mein_template.md
   ```

2. **Inhalt in API-Aufruf einbetten**:
   ```python
   template_content = """
   [Inhalt der Template-Datei hier einfügen]
   """
   ```

3. **API-Aufruf anpassen**:
   ```python
   # Vorher
   {"template": "mein_template"}
   
   # Nachher
   {"template_content": template_content}
   ```

## Tests

Die neue Funktionalität wird durch umfassende Tests abgedeckt:

```bash
# Alle Template-Tests ausführen
pytest tests/test_template_content.py -v

# Spezifischen Test ausführen
pytest tests/test_template_content.py::TestTemplateContent::test_transform_with_template_content -v
```

## Bekannte Einschränkungen

1. **Template-Größe**: Sehr große Templates (>100KB) können Performance-Probleme verursachen
2. **Caching**: Template-Inhalte werden nicht gecacht, nur die Extraktionsergebnisse
3. **Validierung**: Keine Syntax-Validierung der Template-Inhalte vor der Verarbeitung

## Zukunft

Geplante Erweiterungen:

1. **Template-Validierung**: Syntax-Check für Template-Inhalte
2. **Template-Bibliothek**: Zentrale Verwaltung wiederverwendbarer Template-Snippets
3. **Template-Versionierung**: Versionskontrolle für Template-Inhalte
4. **Template-Editor**: Web-basierter Editor für Template-Erstellung 