import os
import sys
import json
import asyncio
import traceback
from typing import List, Dict, Any, Optional
from pathlib import Path
from datetime import datetime

# Füge den src-Pfad zum Python-Pfad hinzu
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.resource_tracking import ResourceCalculator
from src.core.models.story import StoryProcessorInput
from src.processors.story_processor import StoryProcessor
from src.core.mongodb.connection import get_mongodb_database
from src.core.mongodb.story_repository import StoryRepository

# TransformerProcessor importieren
try:
    from src.processors.transformer_processor import TransformerProcessor
    TRANSFORMER_AVAILABLE = True
except ImportError:
    TRANSFORMER_AVAILABLE = False
    print("TransformerProcessor nicht verfügbar - Test kann nicht ausgeführt werden")
    sys.exit(1)

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

async def test_transformer_story():
    """
    Hauptfunktion zum Testen der Story-Generierung mit TransformerProcessor
    """
    try:
        # Konfiguration
        topic_text = "Gemeinschaftsbildung"
        target_group_id = "general"
        event_id = "lndsymposium2023"
        topic_id = "gemeinschaftsbildung"
        language = "de"
        
        # Verzeichnis für Ausgabedateien
        output_dir = f"stories/{event_id}_{target_group_id}/{topic_id}"
        os.makedirs(output_dir, exist_ok=True)
        
        # Template erstellen
        os.makedirs("templates", exist_ok=True)
        template_path = "templates/Story_de.md"
        if not os.path.exists(template_path):
            with open(template_path, "w", encoding="utf-8") as f:
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
        
        # TransformerProcessor initialisieren
        print("Initialisiere TransformerProcessor...")
        transformer = TransformerProcessor(calculator)
        print("TransformerProcessor initialisiert")
        
        # MongoDB-Verbindung herstellen
        db = get_mongodb_database()
        repository = StoryRepository(db)
        
        # Testdaten für Topic und Target Group prüfen
        topic = repository.get_topic_by_id(topic_id)
        if not topic:
            print(f"Thema {topic_id} nicht gefunden - Test kann nicht ausgeführt werden")
            return
            
        target_group = repository.get_target_group_by_id(target_group_id)
        if not target_group:
            print(f"Zielgruppe {target_group_id} nicht gefunden - Test kann nicht ausgeführt werden")
            return
        
        # Sessions für das angegebene Thema laden
        sessions = await get_sessions_by_data_topic(repository, topic_text)
        if not sessions:
            print(f"Keine Sessions für Thema {topic_text} gefunden - Test kann nicht ausgeführt werden")
            return
        
        # Session-Inhalte kombinieren
        print("Kombiniere Session-Inhalte...")
        combined_text = "# Kombinierte Session-Inhalte für Gemeinschaftsbildung\n\n"
        
        for session in sessions:
            title = session.get("title", "Unbekannte Session")
            content = session.get("content", {}).get(language, "Kein Inhalt verfügbar")
            combined_text += f"## {title}\n\n{content}\n\n---\n\n"
        
        print(f"Kombinierter Text erstellt ({len(combined_text)} Zeichen)")
        
        # Basis-Informationen für das Template
        print("Bereite Template-Kontext vor...")
        topic_display_name = topic.get("display_name", {}).get(language, topic_id)
        description = topic.get("description", {}).get(language, "")
        
        context = {
            "topic_id": topic_id,
            "topic_display_name": topic_display_name,
            "description": description,
            "event": event_id,
            "target_group": target_group_id,
            "session_count": len(sessions),
            "tags": ", ".join(topic.get("keywords", []))
        }
        
        # Template-Transformation durchführen
        print("Starte Template-Transformation mit TransformerProcessor...")
        result = transformer.transformByTemplate(
            text=combined_text,
            template="Story",  # Templatename ohne Sprachsuffix
            source_language=language,
            target_language=language,
            context=context,
            use_cache=False  # Für Tests Cache deaktivieren
        )
        
        # Ergebnis verarbeiten
        if hasattr(result, 'data') and result.data:
            # Erfolgsfall
            print("Transformation erfolgreich abgeschlossen!")
            
            # Markdown-Inhalt aus dem Transformationsergebnis extrahieren
            content = None
            if hasattr(result.data, 'text'):
                content = result.data.text
            
            # Strukturierte Daten anzeigen (wenn vorhanden)
            structured_data = getattr(result.data, 'structured_data', None)
            if structured_data:
                print("Strukturierte Daten erhalten:")
                print(json.dumps(structured_data, indent=2))
            
            # Generierte Story speichern
            if content:
                output_file = f"{output_dir}/{topic_id}_{language}.md"
                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Story erfolgreich gespeichert: {output_file}")
            else:
                print("Kein Inhalt für die Story erzeugt!")
        else:
            # Fehlerfall
            error_info = getattr(result, 'error', {'message': 'Unbekannter Fehler'})
            print(f"Fehler bei der Transformation: {error_info}")
    
    except Exception as e:
        print(f"Unerwarteter Fehler: {e}")
        print(traceback.format_exc())

if __name__ == "__main__":
    # Test ausführen
    asyncio.run(test_transformer_story()) 