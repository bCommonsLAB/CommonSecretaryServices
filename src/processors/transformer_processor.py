import os
import re
from pathlib import Path
from typing import Dict, Any, Optional
import json

from src.utils.logger import get_logger
from src.core.config import Config
from src.core.config_keys import ConfigKeys
from src.utils.transcription_utils import WhisperTranscriber
from openai import OpenAI

class TransformerProcessor:
    """TransformerProcessor für die Verarbeitung von Text-Transformationen.
    
    Diese Klasse kümmert sich um Übersetzung und (optionale) Zusammenfassung von Text.
    Die Konfiguration wird direkt aus der Config-Klasse geladen.
    
    Attributes:
        model (str): Name des zu verwendenden Sprachmodells
        target_format (str): Zielformat für die Ausgabe (text, html, markdown)
        client (OpenAI): OpenAI Client für API-Zugriff
        process_id (str): Eindeutige Prozess-ID
        logger: Logger-Instanz für diesen Processor
    """
    def __init__(self):
        # Konfiguration aus Config laden
        config = Config()
        config_keys = ConfigKeys()
        transform_config = config.get('processors.transformer', {})
        
        # Konfigurationswerte mit Validierung laden
        self.model = transform_config.get('model', 'gpt-4')
        self.target_format = transform_config.get('target_format', 'text')
        
        # Validierung der erforderlichen Konfigurationswerte
        if not config_keys.openai_api_key:
            raise ValueError("OpenAI API Key muss in der Konfiguration angegeben werden")
            
        # Weitere Konfigurationswerte laden
        self.process_id = "transformer"
        self.logger = get_logger(process_id=self.process_id, processor_name="TransformerProcessor")
        self.transcriber = WhisperTranscriber(transform_config)
        
        # OpenAI Client initialisieren
        self.client = OpenAI(api_key=config_keys.openai_api_key)
        
        self.logger.debug("Transformer Processor initialisiert",
                         model=self.model,
                         target_format=self.target_format)

    def transform(self, source_text: str, source_language: str, target_language: str, summarize: bool = False, target_format: str = None) -> Dict[str, Any]:
        """
        Führt Übersetzung und optional Zusammenfassung durch.

        Args:
            source_text (str): Ausgangstext
            source_language (str): Sprachcode (ISO-639-1) des Ausgangstexts
            target_language (str): Sprachcode (ISO-639-1) für das Ziel
            summarize (bool): Ob der Text zusätzlich zusammengefasst werden soll
            target_format (str): Ausgabeformat (text, html, markdown). Überschreibt die Konfiguration.

        Returns:
            Dict[str, Any]: Dictionary mit dem transformierten Text, Modellinfos und weiteren Metadaten
        """
        # Format aus Parameter oder Konfiguration verwenden
        format_to_use = target_format or self.target_format
        if format_to_use not in ['text', 'html', 'markdown']:
            self.logger.warning(f"Ungültiges Format '{format_to_use}', verwende 'text'")
            format_to_use = 'text'

        self.logger.info(f"Starte Transformation: {source_language} -> {target_language} (Summarize={summarize}, Format={format_to_use})")

        # Format-spezifische Anweisung erstellen
        format_instruction = ""
        if format_to_use == 'html':
            format_instruction = "Format the output as clean HTML with appropriate tags for structure and readability."
        elif format_to_use == 'markdown':
            format_instruction = "Format the output in Markdown syntax for better structure and readability."

        # Beispiel: Verwendung einer Methode der WhisperTranscriber-Klasse zum Übersetzen/ Zusammenfassen.
        # Hier nur Platzhalterlogik:
        translation_result = self.transcriber.translate_text(
            source_text,
            target_language,
            self.logger,
            summarize,
            format_instruction=format_instruction  # Neue Format-Anweisung übergeben
        )

        # Rückgabe in einheitlicher Struktur
        return {
            "text": translation_result.text,
            "source_text": source_text,
            "translation_model": self.model,
            "token_count": translation_result.token_count,
            "format": format_to_use
        }

    def transformByTemplate(self, source_text: str, source_language: str, target_language: str, context: Dict[str, Any] = None, template: str = None) -> Dict[str, Any]:
        """
        Transformiert Text basierend auf einem vordefinierten Markdown-Template.
        Die Templates befinden sich im ./templates-Ordner und enthalten Anweisungen in geschweiften Klammern
        für strukturierte Ausgaben vom LLM Modell.

        Args:
            source_text (str): Der zu transformierende Text
            source_language (str): Sprachcode (ISO 639-1) für die Zielsprache
            target_language (str): Sprachcode (ISO 639-1) für die Zielsprache
            context (Dict[str, Any]): Dictionary mit Kontext-Informationen für Template-Variablen
            template (str, optional): Name des Templates (ohne .md Endung)

        Returns:
            Dict[str, Any]: Dictionary mit dem transformierten Text und Metadaten
        """
        from datetime import datetime
        from pathlib import Path
        import json

        # Debug-Verzeichnis definieren und erstellen
        debug_dir = Path('./temp-processing/transform')
        debug_dir.mkdir(parents=True, exist_ok=True)
        
        # Wenn kein Template angegeben, Error werfen
        if not template:
            raise ValueError("Template muss angegeben werden")

        # Stelle sicher, dass context ein Dictionary oder None ist
        if context is not None and not isinstance(context, dict):
            self.logger.warning("Context ist kein Dictionary, wird ignoriert",
                context_type=type(context).__name__,
                context_value=str(context)[:200] if context else None)
            context = None

        self.logger.info(f"Starte Transformation: {source_language} -> {target_language}")
        
        if context:
            self.logger.debug("Context-Informationen", context=context)

        try:
            # Verwende die neue Methode aus WhisperTranscriber
            transformed_content, result = self.transcriber.transform_by_template(
                source_text,
                target_language,
                template,
                context=context,  # Context ist jetzt garantiert ein Dict oder None
                logger=self.logger
            )
            
            # Debug-Ausgabe in temporäres Verzeichnis
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Versuche einen Titel aus der JSON-Antwort zu extrahieren
            debug_filename = f"{timestamp}.md"
            result_dict = result.model_dump()
            if 'title' in result_dict:
                # Bereinige den Titel für die Verwendung als Dateiname
                safe_title = re.sub(r'[^\w\s-]', '', result_dict['title'])
                safe_title = re.sub(r'[-\s]+', '-', safe_title).strip('-')
                debug_filename = f"{safe_title}_{timestamp}.md"
            
            debug_file_path = debug_dir / debug_filename
            
            # Speichere transformiertes Template
            with open(debug_file_path, 'w', encoding='utf-8') as f:
                f.write(transformed_content)
                
            # Speichere auch die rohe JSON-Antwort
            json_debug_path = debug_dir / f"{debug_filename}.json"
            with open(json_debug_path, 'w', encoding='utf-8') as f:
                json.dump(result_dict, f, indent=2, ensure_ascii=False)
            
            self.logger.info(f"Debug-Ausgabe gespeichert in: {debug_file_path}")

            return {
                "text": transformed_content,
                "source_text": source_text,
                "template_used": template,
                "translation_model": self.model,
                "token_count": getattr(result, 'token_count', 0),
                "structured_data": result_dict,
                "debug_files": {
                    "transformed": str(debug_file_path),
                    "json": str(json_debug_path)
                }
            }
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Template-Verarbeitung: {str(e)}")
            raise 