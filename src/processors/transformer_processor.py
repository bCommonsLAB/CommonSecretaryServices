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
import traceback

from src.core.exceptions import ProcessingError
from src.utils.logger import get_logger
from src.utils.transcription_utils import WhisperTranscriber
from src.utils.types import TranslationResult, ErrorInfo, LLModel
from src.core.config import Config
from src.core.config_keys import ConfigKeys
from .base_processor import BaseProcessor, BaseProcessorResponse

class TransformerResponse(BaseProcessorResponse):
    """Response-Klasse für den TransformerProcessor."""
    
    def __init__(self):
        """Initialisiert die TransformerResponse."""
        super().__init__("transformer")
        self.translation: Optional[TranslationResult] = None
        self.data = {
            "input": {},
            "output": {}
        }
        
    def set_translation(self, translation: TranslationResult):
        """Setzt das Übersetzungsergebnis."""
        self.translation = translation
        
        # Aktualisiere data mit den Übersetzungsinformationen
        self.data["output"]["text"] = translation.text
        self.data["output"]["language"] = translation.target_language
        self.data["input"]["language"] = translation.source_language
        
        # LLM-Informationen aus der Translation übernehmen
        if translation.llms:
            for llm in translation.llms:
                self.add_llm_info(
                    model=llm.model,
                    purpose="translation",
                    tokens=llm.tokens,
                    duration=llm.duration
                )
                
    def add_parameter(self, key: str, value: Any):
        """Fügt einen Parameter zur Request-Info hinzu und speichert ihn auch in data."""
        super().add_parameter(key, value)
        self.data["input"][key] = value

class TransformerProcessor(BaseProcessor):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    """
    
    def __init__(self, resource_calculator, process_id: Optional[str] = None):
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID vom API-Layer
        """
        # Basis-Klasse zuerst initialisieren
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        
        try:
            # Konfiguration aus Config laden
            transformer_config = self.load_processor_config('transformer')
            
            # Logger initialisieren
            self.init_logger("TransformerProcessor")
            
            # Konfigurationswerte laden
            self.model = transformer_config.get('model', 'gpt-4')
            self.target_format = transformer_config.get('target_format', 'text')
            
            # Temporäres Verzeichnis einrichten
            self.init_temp_dir("transformer", transformer_config)
            
            # OpenAI API Key über ConfigKeys laden
            config_keys = ConfigKeys()
            openai_api_key = config_keys.openai_api_key
            
            # OpenAI Client initialisieren
            self.client = OpenAI(api_key=openai_api_key)
            
            # Transcriber für GPT-4 Interaktionen initialisieren
            self.transcriber = WhisperTranscriber(transformer_config)
            
            self.logger.debug("Transformer Processor initialisiert",
                            model=self.model,
                            target_format=self.target_format,
                            temp_dir=str(self.temp_dir))
                            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des TransformerProcessors",
                            error=str(e))
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def transform(self, source_text: str, source_language: str, target_language: str, summarize: bool = False, target_format: str = None, context: Dict[str, Any] = None) -> TransformerResponse:
        """
        Führt Übersetzung und optional Zusammenfassung durch.

        Args:
            source_text (str): Ausgangstext
            source_language (str): Sprachcode (ISO-639-1) des Ausgangstexts
            target_language (str): Sprachcode (ISO-639-1) für das Ziel
            summarize (bool): Ob der Text zusätzlich zusammengefasst werden soll
            target_format (str): Ausgabeformat (text, html, markdown). Überschreibt die Konfiguration.
            context (Dict[str, Any]): Optionaler Kontext für die Transformation

        Returns:
            TransformerResponse: Das validierte Transformationsergebnis mit Prozess-Informationen
            
        Raises:
            ValueError: Wenn der Eingabetext leer ist
        """
        # Response initialisieren
        response = TransformerResponse()
        response.add_parameter("source_language", source_language)
        response.add_parameter("target_language", target_language)
        response.add_parameter("summarize", summarize)
        response.add_parameter("target_format", target_format or self.target_format)
        
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            format_to_use = self.validate_format(target_format)
            context = self.validate_context(context)

            # Debug-Verzeichnis definieren und erstellen
            debug_dir = Path('./temp-processing/transform')
            if context and 'uploader' in context:
                debug_dir = Path(f'{debug_dir}/{context["uploader"]}')
            debug_dir.mkdir(parents=True, exist_ok=True)

            self.logger.info(f"Starte Transformation: {source_language} -> {target_language} (Summarize={summarize}, Format={format_to_use})")

            # Format-spezifische Anweisung erstellen
            format_instruction = ""
            if format_to_use == 'html':
                format_instruction = "Format the output as clean HTML with appropriate tags for structure and readability."
            elif format_to_use == 'markdown':
                format_instruction = "Format the output in Markdown syntax for better structure and readability."

            # Führe Übersetzung durch, wenn Sprachen unterschiedlich sind
            if source_language != target_language:
                translation_result = self.transcriber.translate_text(
                    text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    logger=self.logger,
                    summarize=summarize
                )
                result_text = translation_result.text
                response.add_sub_processor("translator")
                response.set_translation(translation_result)
            else:
                result_text = source_text

            # Führe Zusammenfassung durch, wenn angefordert
            if summarize:
                summary_result = self.transcriber.summarize_text(
                    text=result_text,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = summary_result.text
                response.add_sub_processor("summarizer")
                response.set_translation(summary_result)

            # Formatierung anwenden, wenn nicht 'text'
            if format_to_use != 'text':
                format_result = self.transcriber.format_text(
                    text=result_text,
                    format=format_to_use,
                    logger=self.logger
                )
                result_text = format_result.text
                response.add_sub_processor("formatter")
                response.set_translation(format_result)

            self.transcriber.saveDebugOutput(
                text=result_text,
                context=context,
                logger=self.logger
            )

            # Response vervollständigen
            response.set_completed()
            return response

        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            response.set_error(error_info)
            self.logger.error(f"Fehler bei der Transformation: {str(e)}")
            return response

    def transformByTemplate(self, source_text: str, source_language: str, target_language: str, context: Dict[str, Any] = None, template: str = None) -> TransformerResponse:
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
            TransformerResponse: Das validierte Transformationsergebnis mit Prozess-Informationen
        """
        # Response initialisieren
        response = TransformerResponse()
        response.add_parameter("source_language", source_language)
        response.add_parameter("target_language", target_language)
        response.add_parameter("template", template)
        response.add_parameter("context", context)
        
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            template = self.validate_text(template, "template")
            context = self.validate_context(context)

            self.logger.info(f"Starte Template-Transformation: {source_language} -> {target_language}")
            
            if context:
                self.logger.debug("Context-Informationen", context=context)

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
                response.set_translation(translation_result)
                response.add_sub_processor("translator")
            else:
                translated_text = source_text
                
            # Template-Transformation durchführen
            transformed_content = self.transcriber.transform_by_template(
                text=translated_text,
                target_language=target_language,
                template=template,
                context=context,
                logger=self.logger
            )
            
            # Template-Ergebnis in Response speichern
            template_result = TranslationResult(
                text=transformed_content,
                source_language=target_language,
                target_language=target_language,
                llms=[LLModel(
                    model=self.model,
                    duration=0.0,  # Wird später aktualisiert
                    tokens=0,      # Wird später aktualisiert
                    timestamp=datetime.now().isoformat()
                )]
            )
            response.set_translation(template_result)
            response.add_sub_processor("template_transformer")
            
            # Debug-Ausgabe
            self.transcriber.saveDebugOutput(
                text=transformed_content,
                template=template,
                context=context,
                logger=self.logger
            )
            
            # Response vervollständigen
            response.set_completed()
            return response
            
        except Exception as e:
            error_info = ErrorInfo(
                code=type(e).__name__,
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "traceback": traceback.format_exc()
                }
            )
            response.set_error(error_info)
            self.logger.error(f"Fehler bei der Template-Transformation: {str(e)}")
            return response 