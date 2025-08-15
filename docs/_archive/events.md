# Event-Verarbeitung

## Überblick
Die Event-Verarbeitung sammelt und verarbeitet Informationen von Veranstaltungen, einschließlich:
- Metadaten (Titel, Sprecher, Datum etc.)
- Video-Aufzeichnungen mit Transkript
- Präsentationsfolien und andere Anhänge als Links
- Bildergalerien aus den Folien (extrahiert durch PDF-Processor)

## Architektur

### Datenfluss
1. Event-Metadaten werden von der Event-Seite extrahiert
2. Video wird heruntergeladen und transkribiert
3. Anhänge werden als Links eingebettet:
   - PDFs werden als direkte Links eingebunden
   - PDF-Processor extrahiert Vorschaubilder für die Galerie
4. Markdown-Datei wird mit allen Informationen generiert

### Komponenten
- **Event Processor**: Hauptkomponente zur Koordination
- **Video Processor**: Verarbeitet Videos und erstellt Transkripte
- **PDF Processor**: Extrahiert Vorschaubilder aus PDFs (ohne Download im Event-Processor)
- **Transformer**: Generiert das finale Markdown

## Template-Struktur
Das Event-Template ist in mehrere Sektionen unterteilt:

```markdown
---
# Metadaten-Header
---

# Titel

## Zusammenfassung & Highlights
[Automatisch generierte Zusammenfassung]

## Galerie / Anhang
- Präsentationsfolien (direkte Links)
- Extrahierte Vorschaubilder als Galerie
- Weitere Materialien

## Video-Transkript
[Automatisch generiertes Transkript]
```

## Implementierungsplan

### Phase 1: Video-Transkript Integration
1. Event-Template um Transkript-Sektion erweitern
2. Video-Transkript aus dem Video-Processor einbinden
3. Tests für die Transkript-Integration

### Phase 2: Anhang-Verarbeitung
1. PDF-Processor für direkte URL-Verarbeitung anpassen
2. Bildergalerie-Funktionalität im PDF-Processor implementieren
3. Anhang-Links in Template integrieren
4. Tests für die Anhang-Verarbeitung

## Technische Details

### PDF-Verarbeitung
- Verarbeitung der PDF-URL direkt im PDF-Processor
- Extraktion von Vorschaubildern ohne lokalen Download im Event-Processor
- Speicherung der Vorschaubilder im PDF-Processor Cache
- Rückgabe der Bildpfade an den Event-Processor

### Video-Verarbeitung
- Download des Videos in verschiedenen Formaten
- Transkription mit Zeitstempeln
- Übersetzung des Transkripts wenn nötig

### Markdown-Generierung
- Dynamische Template-Befüllung
- Einbettung der PDF-Links
- Integration der Vorschaubilder aus dem PDF-Processor
- Einbettung aller Assets mit korrekten Pfaden

## Konfiguration
Die Verarbeitung kann über folgende Parameter gesteuert werden:
- Quell- und Zielsprache
- Bildergalerie-Layout
- Verarbeitungsoptionen für PDFs
- Video-Transkript-Formatierung 