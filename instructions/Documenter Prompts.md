# Documenter Prompts

Ich möchte systematisch eine Dokumentation für dieses Projekt erstellen.
Ich werde einige Fragen stellen und die Antworten in Markdown Dateien speichern.
Sollte es diese Dateien schon geben, diese nicht blind überschreiben, sondern nur ergänzen, wenn es sinnvoll ist.

Bitte nur folgende Verzeichnisse analysieren und dokumentieren:
config/
docs/
src/
tests/
konfigurationsdateien

# A. Grundlagen & Einstieg

## 1. Systemarchitektur (docs/01_architecture.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Wie ist das Gesamtsystem aufgebaut?
> - Welche Hauptkomponenten gibt es und wie interagieren sie miteinander?
> - Wie ist der Datenfluss durch das System?
> - Welche externen Dienste werden genutzt?
> - Systemanforderungen und Abhängigkeiten
> 
> Wichtig: Systemarchitektur und Datenflüsse sollten durch aussagekräftige Diagramme visualisiert werden.

## 2. Installation und Setup (docs/02_installation.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Systemvoraussetzungen
> - Lokale Installation
> - Docker-Setup
> - Konfigurationsschritte
> - API-Key Einrichtung
> - Erste Schritte und Tests
>
> Wichtig: Komplexe Setup-Prozesse sollten durch Flussdiagramme visualisiert werden.

## 3. Entwicklungsrichtlinien (docs/03_development.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Code-Style und Standards
> - Git-Workflow und Branching-Strategie
> - Test-Richtlinien und Coverage
> - Code-Review-Prozess
> - Dokumentationsstandards
> - Performance-Optimierung
> - Build- und Release-Prozess
>
> Wichtig: Entwicklungsprozesse und Workflows durch Diagramme darstellen.

# B. Core-Funktionalität

## 4. API und Server (docs/04_api.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Vollständige API-Endpunkte und Referenz
> - Request/Response-Formate
> - Authentifizierung und Rate-Limiting
> - Fehler-Codes und Handling
> - API-Tests und Beispiele
> - Swagger Integration
> - Performance und Skalierung
>
> Wichtig: API-Struktur, Datenflüsse und Authentifizierung durch Diagramme darstellen.

## 5. Typdefinitionen und API-Responses (docs/05_types.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> ### Basis-Datenmodelle
> - Chapter (Kapitelinformationen)
> - AudioSegmentInfo (Segmentinformationen)
> - llModel (LLM-Nutzungsinformationen)
> - TranscriptionSegment (Transkriptionssegmente)
>
> ### Verarbeitungsergebnisse
> - TranscriptionResult
> - TranslationResult
> - AudioProcessingResult
> - YoutubeProcessingResult
>
> ### Metadaten und Responses
> - AudioMetadata
> - YoutubeMetadata
> - API-Responses für alle Endpunkte
> - Fehlerformate
>
> Wichtig: 
> - Alle Modelle mit Pydantic-Validierung
> - JSON-Beispiele
> - Validierungsregeln
> - Fehlerszenarien

## 6. Audio-Verarbeitung (docs/06_audio_processing.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Funktionsweise der Audio-Verarbeitung
> - Unterstützte Formate
> - Segmentierung und Normalisierung
> - Qualitätseinstellungen
> - Temporäre Dateiverwaltung
> - Performance-Optimierung
>
> Wichtig: Verarbeitungsprozesse und Datenflüsse durch Diagramme darstellen.

## 7. YouTube-Integration (docs/07_youtube.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - YouTube-Download-System
> - Download-Einschränkungen
> - Audio-Extraktion
> - Metadaten-Verarbeitung
> - API-Limits
> - Fehlerbehandlung
>
> Wichtig: Download- und Verarbeitungsprozesse durch Flussdiagramme visualisieren.

## 8. Templates und Ausgabeformate (docs/08_templates.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Template-System Architektur
> - Unterstützte Formate
> - Variable Substitution
> - Dokumenttypen
> - Anpassungsmöglichkeiten
> - Best Practices
>
> Wichtig: Template-Struktur und Verarbeitungslogik durch Diagramme visualisieren.

# C. Betrieb & Wartung

## 9. Web-Interface (docs/09_web_interface.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> ### Dashboard
> - Systemübersicht
> - Verarbeitungsstatus
> - Metriken
>
> ### Management
> - Konfiguration
> - Logs
> - Tests
> - API-Dokumentation
>
> Wichtig: Alle Hauptfunktionen durch Screenshots und Interaktionsdiagramme darstellen.

## 10. Deployment & Monitoring (docs/10_deployment.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Deployment-Strategien
> - CI/CD-Pipeline
> - Monitoring-System
> - Performance-Tracking
> - Logging
> - Wartungsaufgaben
> - Backup-Strategien
>
> Wichtig: Deployment-Pipeline und Monitoring-Architektur durch Diagramme visualisieren.

## 11. Sicherheit & Datenschutz (docs/11_security.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Sicherheitsarchitektur
> - Authentifizierung
> - Datenschutz (DSGVO)
> - API-Sicherheit
> - Audit-Logging
> - Datenspeicherung
> - Externe Dienste
>
> Wichtig: Sicherheitsarchitektur und Datenschutzmaßnahmen durch Diagramme visualisieren.

## 12. Troubleshooting & FAQ (docs/12_troubleshooting.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Häufige Probleme und Lösungen
> - Diagnose-Tools
> - Performance-Probleme
> - Recovery-Prozeduren
> - Best Practices
> - FAQ für alle Komponenten
>
> Wichtig: Troubleshooting-Workflows und Diagnose-Prozesse durch Diagramme darstellen.

# D. Projekt & Support

## 13. Changelog & Roadmap (docs/13_changelog.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Versionshistorie
> - Feature-Updates
> - Breaking Changes
> - Geplante Features
> - Release-Zeitplan
> - Langfristige Ziele
>
> Wichtig: Entwicklungspfad und Meilensteine durch Diagramme visualisieren.

## 14. Glossar (docs/14_glossary.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Technische Begriffe
> - API-Terminologie
> - Systemkomponenten
> - Prozesse
> - Abkürzungen
> - Code-Beispiele
>
> Wichtig: Begriffe alphabetisch sortieren und klar definieren.

## 15. Kontakt, Support & Lizenz (docs/15_support.md)
> [!NOTE]
> Falls eine bestehende Dokumentation existiert, diese bitte analysieren und sinnvoll ergänzen.
> 
> Folgende Aspekte dokumentieren:
> - Support-Kanäle
> - Response-Zeiten
> - Bug-Reporting
> - Feature-Requests
> - Lizenzinformationen
> - Community-Richtlinien
>
> Wichtig: Support-Prozesse und Lizenzbestimmungen klar strukturieren.

## README.md
> [!NOTE]
> README.md aktualisieren mit:
> - Projektbeschreibung
> - Hauptfunktionen
> - Quick Start Guide
> - Dokumentationsstruktur
> - Support-Informationen
>
> Die README sollte einen schnellen Überblick ermöglichen.

## .cursorrules
> [!NOTE]
> Cursor-Regeln aktualisieren:
> - Projektzusammenfassung
> - Kontext-Informationen
> - Entwicklungsrichtlinien
> - KI-Unterstützung
>
> Der Kontext sollte KI-Assistenten optimal unterstützen.

