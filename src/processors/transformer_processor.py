"""
Transformer processor module.
Handles text transformation using LLM models.
"""
import re
from typing import Dict, Any, Optional
import json
import os
from pathlib import Path
import yaml
from openai import OpenAI
from datetime import datetime

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.types import TranslationResult
from src.core.config import Config
from src.core.config_keys import ConfigKeys
from .base_processor import BaseProcessor

class TransformerProcessor(BaseProcessor):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    """
    
    def __init__(self, process_id: str = None):
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            process_id (str, optional): Die zu verwendende Process-ID vom API-Layer
        """
        # Basis-Klasse zuerst initialisieren
        super().__init__(process_id=process_id)
        
        # Konfiguration aus Config laden
        config = Config()
        processors_config = config.get('processors', {})
        transformer_config = processors_config.get('transformer', {})
        
        # Logger initialisieren
        self.logger = get_logger(process_id=self.process_id, processor_name="TransformerProcessor")
        
        # Konfigurationswerte laden
        self.model = transformer_config.get('model', 'gpt-4')
        self.target_format = transformer_config.get('target_format', 'text')
        
        try:
            # OpenAI API Key über ConfigKeys laden
            config_keys = ConfigKeys()
            openai_api_key = config_keys.openai_api_key
            
            # OpenAI Client initialisieren
            self.client = OpenAI(api_key=openai_api_key)
            
            # Transcriber für GPT-4 Interaktionen initialisieren
            self.transcriber = WhisperTranscriber(transformer_config)
            
            self.logger.debug("Transformer Processor initialisiert",
                            model=self.model,
                            target_format=self.target_format)
                            
        except ValueError as e:
            raise ProcessingError(str(e))

    def transform(self, source_text: str, source_language: str, target_language: str, summarize: bool = False, target_format: str = None, context: Dict[str, Any] = None) -> TranslationResult:
        """
        Führt Übersetzung und optional Zusammenfassung durch.

        Args:
            source_text (str): Ausgangstext
            source_language (str): Sprachcode (ISO-639-1) des Ausgangstexts
            target_language (str): Sprachcode (ISO-639-1) für das Ziel
            summarize (bool): Ob der Text zusätzlich zusammengefasst werden soll
            target_format (str): Ausgabeformat (text, html, markdown). Überschreibt die Konfiguration.

        Returns:
            TranslationResult: Das validierte Übersetzungsergebnis
        """
        # Debug-Verzeichnis definieren und erstellen
        debug_dir = Path('./temp-processing/transform')
        if context and 'uploader' in context:
            debug_dir = Path(f'{debug_dir}/{context["uploader"]}')
        debug_dir.mkdir(parents=True, exist_ok=True)

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
            text=source_text,
            source_language=source_language,
            target_language=target_language,
            logger=self.logger,
            summarize=summarize
        )

        self.transcriber.saveDebugOutput(
            text=translation_result.text,
            context=context,
            logger=self.logger
        )

        # Rückgabe in einheitlicher Struktur
        return TranslationResult(
            text=translation_result.text,
            source_language=source_language,
            target_language=target_language,
            llms=translation_result.llms
        )

    def transformByTemplate(self, source_text: str, source_language: str, target_language: str, context: Dict[str, Any] = None, template: str = None) -> TranslationResult:
        """
        Transformiert Text basierend auf einem vordefinierten Markdown-Template.
        Die Templates befinden sich im ./templates-Ordner und enthalten Anweisungen in geschweiften Klammern
        für strukturierte Ausgaben vom LLM Modell.

        Args:
            source_text (str): Der zu transformierende Text
            source_language (str): Sprachcode (ISO 639-1) für die Quellsprache
            target_language (str): Sprachcode (ISO 639-1) für die Zielsprache
            context (Dict[str, Any]): Dictionary mit Kontext-Informationen für Template-Variablen
            template (str, optional): Name des Templates (ohne .md Endung)

        Returns:
            TranslationResult: Das validierte Übersetzungsergebnis mit transformiertem Template-Inhalt
        """
        
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
            # Zuerst den Quelltext übersetzen
            if source_language != target_language:
                self.logger.info("Übersetze Quelltext")

                translation_result = self.transcriber.translate_text(
                    source_text,
                    source_language,
                    target_language,
                    self.logger
                )
                translated_text = translation_result.text
                llms = translation_result.llms
            else:
                translated_text = source_text
                llms = []
                
            # Verwende die neue Methode aus WhisperTranscriber mit dem übersetzten Text
            transformed_content, template_result = self.transcriber.transform_by_template(
                text=translated_text,  # Verwende den übersetzten Text
                target_language=target_language,
                template=template,  
                context=context,
                logger=self.logger
            )
            
            # Debug-Ausgabe in temporäres Verzeichnis
            result_dict = template_result.model_dump() if template_result else {}
            
            self.transcriber.saveDebugOutput(
                text=transformed_content,
                template=template,
                result_dict=result_dict,
                context=context,
                logger=self.logger
            )

            # Erstelle das TranslationResult
            return TranslationResult(
                text=transformed_content,
                source_language=source_language,
                target_language=target_language,
                llms=llms + (template_result.llms if template_result else [])
            )
            
        except Exception as e:
            self.logger.error(f"Fehler bei der Template-Verarbeitung: {str(e)}")
            raise 