import os
import sys
import json
import asyncio
import traceback
from typing import List, Dict, Any, Optional, cast
from pathlib import Path
from datetime import datetime

# Füge den src-Pfad zum Python-Pfad hinzu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.resource_tracking import ResourceCalculator
from src.core.models.story import StoryProcessorInput, StoryProcessingResult
from src.processors.story_processor import StoryProcessor
from src.core.mongodb.connection import get_mongodb_database
from src.core.mongodb.story_repository import StoryRepository

# Optionale Imports für TransformerProcessor
try:
    from src.processors.transformer_processor import TransformerProcessor
    TRANSFORMER_AVAILABLE = True
except ImportError:
    TRANSFORMER_AVAILABLE = False
    print("TransformerProcessor nicht verfügbar, verwende Standard-Methode")

async def create_test_topic_and_target_group(repository):
    """
    Erstellt ein Testthema und eine Testzielgruppe, falls sie noch nicht existieren.
    """
    # Prüfen, ob das Thema bereits existiert
    topic = repository.get_topic_by_id("gemeinschaftsbildung")
    if not topic:
        print("Erstelle Testthema 'gemeinschaftsbildung'...")
        topic_data = {
            "topic_id": "gemeinschaftsbildung",
            "display_name": {
                "de": "Gemeinschaftsbildung",
                "en": "Community Building"
            },
            "description": {
                "de": "Bildung und Stärkung von Gemeinschaften",
                "en": "Building and strengthening communities"
            },
            "keywords": ["community", "collaboration", "social", "network"],
            "primary_target_group": "general",
            "relevance_threshold": 0.6,
            "status": "active",
            "template": "ecosocial",
            "event": "lndsymposium2023",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        repository.db.topics.insert_one(topic_data)
        print("Testthema erstellt")
    else:
        print("Thema 'gemeinschaftsbildung' existiert bereits")

    # Prüfen, ob die Zielgruppe bereits existiert
    target_group = repository.get_target_group_by_id("general")
    if not target_group:
        print("Erstelle Testzielgruppe 'general'...")
        target_group_data = {
            "target_id": "general",
            "display_name": {
                "de": "Allgemein",
                "en": "General"
            },
            "description": {
                "de": "Allgemeine Zielgruppe ohne spezifische Kenntnisse",
                "en": "General audience without specific knowledge"
            },
            "status": "active",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        repository.db.target_groups.insert_one(target_group_data)
        print("Testzielgruppe erstellt")
    else:
        print("Zielgruppe 'general' existiert bereits")

async def get_sessions_by_data_topic(repository, topic_text: str):
    """
    Holt Sessions aus der Datenbank, gefiltert nach data.topic
    """
    # Filter definieren: suche nach Sessions mit dem angegebenen Thema
    filter_query = {"data.topic": topic_text}
    
    # Abfrage ausführen
    sessions = list(repository.db.session_cache.find(filter_query).limit(50))
    
    print(f"Gefunden: {len(sessions)} Sessions mit data.topic='{topic_text}'")
    
    # Die ersten 5 Session-IDs zur Debug-Ausgabe
    if sessions:
        print("Beispiel Session-IDs:")
        for i, session in enumerate(sessions[:5]):
            session_id = session.get("_id", "Keine ID")
            print(f"  - Session {i+1}: {session_id}")
    
    # Sessions in das erwartete Format konvertieren
    formatted_sessions = []
    for session in sessions:
        # Extrahiere relevante Daten
        session_id = session.get("_id", "unknown")
        session_data = session.get("data", {})
        title = session_data.get("title", f"Session {session_id}")
        content = session_data.get("markdown_content", "Kein Inhalt verfügbar")
        topic = session_data.get("topic", "unknown")
        
        # Formatiere die Session wie erwartet
        formatted_session = {
            "session_id": session_id,
            "title": title,
            "content": {
                "de": content if isinstance(content, str) else str(content)
            },
            "metadata": {
                "topics": [topic],
                "relevance": {
                    "general": 0.8  # Standard-Relevanz
                },
                "event": session_data.get("event", "unknown")
            }
        }
        formatted_sessions.append(formatted_session)
    
    return formatted_sessions

async def create_direct_story(processor, topic_id, event, target_group, languages, session_data, transformer_processor=None):
    """
    Erstellt eine Story direkt, ohne den normalen Prozessfluss.
    Diese Fallback-Methode wird verwendet, wenn die normale Verarbeitung fehlschlägt.
    
    Neue Implementierung:
    - Verwendet TransformerProcessor, wenn verfügbar
    - Kombiniert Session-Inhalte zu einem Gesamttext
    - Führt eine Template-Transformation mit diesem Text durch
    """
    # Story-Repository für direkten Zugriff auf Daten
    story_repo = processor.story_repository
    
    # Holen des Themas und der Zielgruppe
    topic = story_repo.get_topic_by_id(topic_id)
    target_group_obj = story_repo.get_target_group_by_id(target_group)
    
    if not topic or not target_group_obj:
        print(f"Fehler: Thema {topic_id} oder Zielgruppe {target_group} nicht gefunden")
        return None
    
    # Verzeichnisstruktur erstellen
    base_dir = f"stories/{event}_{target_group}/{topic_id}"
    os.makedirs(base_dir, exist_ok=True)
    
    # Ergebnisstrukturen vorbereiten
    markdown_files = {}
    markdown_contents = {}
    
    for language in languages:
        # Template-Pfad ermitteln
        template_path = f"templates/Story_{language}.md"
        if not os.path.exists(template_path):
            template_path = "templates/Story_de.md"  # Fallback
        
        # Template-Inhalt laden
        with open(template_path, "r", encoding="utf-8") as f:
            template_content = f.read()
        
        # Grundlegende Platzhalter ersetzen
        topic_display_name = topic.get("display_name", {}).get(language, topic_id)
        description = topic.get("description", {}).get(language, "Keine Beschreibung verfügbar")
        
        # TransformerProcessor verwenden, wenn verfügbar
        if transformer_processor and TRANSFORMER_AVAILABLE:
            try:
                print(f"Verwende TransformerProcessor für Story-Generierung...")
                
                # Session-Inhalte kombinieren (ähnlich wie im SessionProcessor)
                combined_text = "# Kombinierte Session-Inhalte\n\n"
                for s in session_data:
                    title = s.get('title', 'Unbekannte Session')
                    content = s.get('content', {}).get(language, 'Kein Inhalt verfügbar')
                    combined_text += f"## {title}\n\n{content}\n\n"
                
                # Kontext für das Template vorbereiten
                context = {
                    "topic_id": topic_id,
                    "topic_display_name": topic_display_name,
                    "description": description,
                    "event": event,
                    "target_group": target_group,
                    "session_count": len(session_data),
                    "tags": ", ".join(topic.get("keywords", []))
                }
                
                # Template-Transformation durchführen
                result = transformer_processor.transformByTemplate(
                    text=combined_text,
                    template="Story",  # Templatename ohne Sprachsuffix
                    source_language=language,
                    target_language=language,
                    context=context,
                    use_cache=False  # Für Tests Cache deaktivieren
                )
                
                # Ergebnis auswerten
                if hasattr(result, 'data') and result.data:
                    # Markdown-Inhalt aus dem Transformationsergebnis extrahieren
                    if hasattr(result.data, 'text'):
                        content = result.data.text
                    else:
                        # Fallback für ältere API-Versionen
                        content = template_content
                        # Einfache Platzhalter ersetzen
                        content = content.replace("{{topic_display_name}}", topic_display_name)
                        content = content.replace("{{description}}", description)
                        content = content.replace("{{tags}}", ", ".join(topic.get("keywords", [])))
                        # Platzhalter für LLM-generierte Inhalte
                        content = content.replace("{{general_summary}}", "[Platzhalter für die allgemeine Zusammenfassung]")
                        content = content.replace("{{sessions}}", "[Platzhalter für Sessions]")
                        content = content.replace("{{eco_social_relevance}}", "[Platzhalter für ökosoziale Relevanz]")
                        content = content.replace("{{eco_social_applications}}", "[Platzhalter für ökosoziale Anwendungen]")
                        content = content.replace("{{challenges}}", "[Platzhalter für Herausforderungen]")
                else:
                    # Fallback bei Fehler in der Transformation
                    print(f"Fehler bei der Template-Transformation: {getattr(result, 'error', 'Unbekannter Fehler')}")
                    raise Exception("Transformation fehlgeschlagen")
                    
            except Exception as e:
                print(f"Fehler bei der TransformerProcessor-Verarbeitung: {e}")
                print("Fallback auf einfache Template-Ersetzung...")
                
                # Fallback: Einfaches Template-Ersetzen
                content = template_content
                content = content.replace("{{topic_display_name}}", topic_display_name)
                content = content.replace("{{description}}", description)
                content = content.replace("{{general_summary}}", "[Platzhalter für die allgemeine Zusammenfassung]")
                content = content.replace("{{sessions}}", "[Platzhalter für Sessions]")
                
                # Wenn es sich um das ökosoziale Template handelt
                content = content.replace("{{tags}}", ", ".join(topic.get("keywords", [])))
                content = content.replace("{{eco_social_relevance}}", "[Platzhalter für ökosoziale Relevanz]")
                content = content.replace("{{eco_social_applications}}", "[Platzhalter für ökosoziale Anwendungen]")
                content = content.replace("{{challenges}}", "[Platzhalter für Herausforderungen]")
        else:
            # Keine Transformer-Verarbeitung: Einfaches Template-Ersetzen
            content = template_content
            content = content.replace("{{topic_display_name}}", topic_display_name)
            content = content.replace("{{description}}", description)
            content = content.replace("{{general_summary}}", "[Platzhalter für die allgemeine Zusammenfassung]")
            content = content.replace("{{sessions}}", "[Platzhalter für Sessions]")
            
            # Wenn es sich um das ökosoziale Template handelt
            content = content.replace("{{tags}}", ", ".join(topic.get("keywords", [])))
            content = content.replace("{{eco_social_relevance}}", "[Platzhalter für ökosoziale Relevanz]")
            content = content.replace("{{eco_social_applications}}", "[Platzhalter für ökosoziale Anwendungen]")
            content = content.replace("{{challenges}}", "[Platzhalter für Herausforderungen]")
        
        # Datei speichern
        file_path = f"{base_dir}/{topic_id}_{language}.md"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        
        markdown_files[language] = file_path
        markdown_contents[language] = content
    
    # Ergebnis zurückgeben (vereinfachte Struktur)
    return {
        "markdown_files": markdown_files,
        "markdown_contents": markdown_contents
    }

async def test_story_processor():
    """Hauptfunktion zum Testen des StoryProcessors"""
    try:
        # Logger initialisieren
        import logging
        logging.basicConfig(level=logging.DEBUG)
        logger = logging.getLogger("StoryProcessor-Test")
        logger.info("StoryProcessor-Logger initialisiert")
        
        # Template-Dateien erstellen, falls sie fehlen
        os.makedirs("templates", exist_ok=True)
        if not os.path.exists("templates/Story_de.md"):
            with open("templates/Story_de.md", "w", encoding="utf-8") as f:
                f.write("""---
title: "{{topic_display_name}}"
tags: {{tags}}
---

# {{topic_display_name}}

## Beschreibung
{{description}}

## Zusammenfassung
{{general_summary}}

## Ökosoziale Relevanz
{{eco_social_relevance}}

## Anwendungsfelder
{{eco_social_applications}}

## Herausforderungen
{{challenges}}

## Sessions
{{sessions}}
""")
        
        # ResourceCalculator initialisieren
        calculator = ResourceCalculator()
        
        # TransformerProcessor initialisieren, wenn verfügbar
        transformer_processor = None
        if TRANSFORMER_AVAILABLE:
            try:
                print("Initialisiere TransformerProcessor...")
                transformer_processor = TransformerProcessor(calculator)
                print("TransformerProcessor initialisiert")
            except Exception as e:
                print(f"Fehler beim Initialisieren des TransformerProcessor: {e}")
        
        # StoryProcessor initialisieren
        processor = StoryProcessor(calculator)
        logger.info("StoryProcessor initialisiert")
        
        # MongoDB-Verbindung herstellen
        db = get_mongodb_database()
        repository = StoryRepository(db)
        
        # Testthema und -zielgruppe erstellen, falls sie nicht existieren
        await create_test_topic_and_target_group(repository)
        
        # Sessions mit data.topic='Gemeinschaftsbildung' abrufen
        sessions = await get_sessions_by_data_topic(repository, "Gemeinschaftsbildung")
        
        if not sessions:
            logger.error("Keine Sessions gefunden!")
            return
        
        # StoryProcessorInput erstellen
        input_data = StoryProcessorInput(
            topic_id="gemeinschaftsbildung",
            event="lndsymposium2023", 
            target_group="general",
            languages=["de"],
            detail_level=3,
            data_topic_text="Gemeinschaftsbildung"
        )
        
        # Story-Generierung testen
        try:
            # Story über den regulären Prozessfluss generieren
            logger.info(f"Starte Story-Generierung für Thema {input_data.topic_id} mit data.topic={input_data.data_topic_text}")
            result = await processor.process_story(input_data)
            
            # Response auswerten
            if result.status == "success" and result.data:
                logger.info("Story erfolgreich generiert")
                # Ergebnisse anzeigen
                for lang, file_path in result.data.output.markdown_files.items():
                    logger.info(f"Story in {lang} gespeichert unter: {file_path}")
            else:
                error_message = result.error.get("message") if result.error else "Unbekannter Fehler"
                error_details = result.error.get("details", {}) if result.error else {}
                
                logger.error(f"Fehler bei der Story-Generierung: {error_message}")
                logger.error(f"Details: {json.dumps(error_details, indent=2)}")
                
                # Fallback: Direkte Generierung versuchen
                logger.info("Versuche direkte Story-Generierung als Fallback...")
                
                direct_result = await create_direct_story(
                    processor=processor,
                    topic_id=input_data.topic_id,
                    event=input_data.event,
                    target_group=input_data.target_group,
                    languages=input_data.languages,
                    session_data=sessions,
                    transformer_processor=transformer_processor
                )
                
                if direct_result:
                    logger.info("Story erfolgreich durch Fallback-Methode generiert")
                    for lang, file_path in direct_result["markdown_files"].items():
                        logger.info(f"Story in {lang} gespeichert unter: {file_path}")
                else:
                    logger.error("Auch die Fallback-Methode ist fehlgeschlagen")
        
        except Exception as e:
            logger.error(f"Unerwarteter Fehler: {e}")
            logger.error(traceback.format_exc())
    
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    # Event-Loop erstellen und Test ausführen
    asyncio.run(test_story_processor()) 