"""
Utilities für die Transkription und Transformation von Text.
"""
from typing import Dict, Any, Optional, Union
from pathlib import Path
import time
from datetime import datetime
import json
import re
import os
from dataclasses import dataclass

from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from pydantic import Field

from src.utils.logger import ProcessingLogger
from src.core.models.transformer import (
    TranslationResult, TransformationResult, TemplateField, TemplateFields
)
from src.core.models.llm import LLMRequest
from src.core.models.enums import OutputFormat
from src.utils.openai_utils import get_structured_gpt

# Type-Definitionen
FieldType = tuple[Union[type[str], type[None]], Field]

@dataclass
class TemplateFieldDefinition:
    """Definition eines Template-Feldes."""
    description: str
    max_length: int = 5000
    default: Optional[str] = None

class WhisperTranscriber:
    """Klasse für die Interaktion mit GPT-4."""
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialisiert den WhisperTranscriber.
        
        Args:
            config: Konfiguration für den Transcriber
        """
        self.config: Dict[str, Any] = config
        self.debug_dir: Path = Path(config.get('debug_dir', './temp-processing/transform'))
        self.model: str = config.get('model', 'gpt-4')
        self.client: OpenAI = OpenAI(api_key=config.get('openai_api_key'))

    def translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        logger: Optional[ProcessingLogger] = None
    ) -> TranslationResult:
        """
        Übersetzt Text in die Zielsprache mit GPT-4.
        
        Args:
            text: Der zu übersetzende Text
            source_language: Quellsprache (ISO 639-1)
            target_language: Zielsprache (ISO 639-1)
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            TranslationResult: Das validierte Übersetzungsergebnis
        """
        try:
            if logger:
                logger.info(f"Starte Übersetzung von {source_language} nach {target_language}")

            # LLM-Modell und System-Prompt definieren
            llm_model: str = self.model
            system_prompt: str = "You are a precise translator."
            instruction: str = f"Please translate this text to {target_language}:"
            user_prompt: str = f"{instruction}\n\n{text}"

            # Zeitmessung starten
            start_time: float = time.time()

            # OpenAI Client-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = int((time.time() - start_time) * 1000)
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            message: ChatCompletionMessage = response.choices[0].message       
            translated_text: str = message.content or ""
            
            self._save_llm_interaction(
                purpose="translation",
                system_prompt=system_prompt, 
                user_prompt=user_prompt, 
                response=response, 
                logger=logger,
            ) 


            # LLM-Nutzung tracken
            llm_usage = LLMRequest(
                model=llm_model,
                purpose="translation",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration
            )
            
            result = TranslationResult(
                text=translated_text,
                source_language=source_language,
                target_language=target_language,
                requests=[llm_usage]
            )

            if logger:
                logger.info("Übersetzung abgeschlossen",
                    tokens=llm_usage.tokens,
                    duration_ms=duration)
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Übersetzung", error=e)
            raise

    def summarize_text(
        self,
        text: str,
        target_language: str,
        max_words: Optional[int] = None,
        logger: Optional[ProcessingLogger] = None
    ) -> TransformationResult:
        """
        Fasst Text zusammen.
        
        Args:
            text: Der zusammenzufassende Text
            target_language: Zielsprache (ISO 639-1)
            max_words: Optional, maximale Anzahl Wörter
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            TransformationResult: Das Zusammenfassungsergebnis
        """
        try:
            if logger:
                logger.info(f"Starte Zusammenfassung in {target_language}" + (f" (max {max_words} Wörter)" if max_words else ""))

            # LLM-Modell und System-Prompt definieren
            llm_model = self.model
            system_prompt = "You are a precise Writer."
            
            # Instruction basierend auf Modus erstellen
            base_instruction: str = f"Can you summarize this text in {target_language} in a more concise way?"
            if max_words:
                instruction: str = f"{base_instruction} Use at most {max_words} words."
            else:
                instruction: str = base_instruction

            user_prompt: str = f"{instruction}\n\n{text}"

            # Zeitmessung starten
            start_time: float = time.time()

            # OpenAI Client-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = int((time.time() - start_time) * 1000)
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            summary: str = response.choices[0].message.content or ""
            summary = summary.strip()

            self._save_llm_interaction(
                purpose="summarization",
                system_prompt=system_prompt, 
                user_prompt=user_prompt, 
                response=response, 
                logger=logger,
            ) 

            # LLM-Nutzung tracken
            llm_usage = LLMRequest(
                model=llm_model,
                purpose="summarization",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration
            )
            
            result = TransformationResult(
                text=summary,
                target_language=target_language,
                requests=[llm_usage]
            )

            if logger:
                logger.info("Zusammenfassung abgeschlossen",
                    tokens=llm_usage.tokens,
                    duration_ms=duration)
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Zusammenfassung", error=e)
            raise
       
       
    def format_text(
        self,
        text: str,
        format: OutputFormat,
        target_language: str,
        logger: Optional[ProcessingLogger] = None
    ) -> TransformationResult:
        """
        Formatiert Text in das gewünschte Format.
        
        Args:
            text: Der zu formatierende Text
            format: Das Zielformat
            target_language: Zielsprache für das Ergebnis
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            TransformationResult: Das Formatierungsergebnis
        """
        if logger:
            logger.debug(f"Formatiere Text als {format.value}")
            
        # TODO: Implementierung der Formatierung
        formatted = f"[Formatted as {format.value}]: {text}"
        
        # Dummy LLM Info für die Formatierung
        llm_usage = LLMRequest(
            model=self.model,
            purpose="formatting",
            tokens=len(text.split()),
            duration=1
        )
        
        return TransformationResult(
            text=formatted,
            target_language=target_language,
            requests=[llm_usage]
        )

    def saveDebugOutput(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        logger: Optional[ProcessingLogger] = None
    ) -> None:
        """
        Speichert Debug-Ausgaben.
        
        Args:
            text: Der zu speichernde Text
            context: Optional, zusätzliche Kontextinformationen
            logger: Optional, Logger für Debug-Ausgaben
        """
        if logger:
            logger.debug("Speichere Debug-Output", context=context)
            
        # TODO: Implementierung der Debug-Ausgabe
        pass

    def transform_by_template(
        self, 
        text: str, 
        target_language: str,
        template: str, 
        context: Dict[str, Any] | None = None,
        logger: Optional[ProcessingLogger] = None
    ) -> TransformationResult:
        """Transformiert Text basierend auf einem Template."""
        try:
            if logger:
                logger.info(f"Starte Template-Transformation: {template}")

            # 1. Template-Datei lesen
            template_content: str = self._read_template_file(template, logger)

            # 2. Einfache Kontext-Variablen ersetzen
            template_content = self._replace_context_variables(template_content, context, text, logger)

            # 3. Strukturierte Variablen extrahieren und Model erstellen
            field_definitions: TemplateFields = self._extract_structured_variables(template_content, logger)
            
            if not field_definitions.fields:
                # Wenn keine strukturierten Variablen gefunden wurden, erstellen wir eine einfache Response
                return TransformationResult(
                    text=text,
                    target_language=target_language,
                    requests=[]
                )

            # 4. GPT-4 Prompts erstellen
            context_str: str = (
                json.dumps(context, indent=2, ensure_ascii=False)
                if isinstance(context, dict)
                else "No additional context."
            )
            system_prompt: str = (
                f"You are a precise assistant for text analysis and data extraction. "
                f"Analyze the text and extract the requested information. "
                f"Provide all answers in the target language ISO 639-1 code:{target_language}."
            )
            
            user_prompt: str = (
                f"Analyze the following text and extract the information:\n\n"
                f"TEXT:\n{text}\n\n"
                f"CONTEXT:\n{ context_str}\n\n"
                f"Extract the information precisely and in the target language ISO 639-1 code: {target_language}."
            )

            # 5. GPT-4 Anfrage senden
            if logger:
                logger.info("Sende Anfrage an GPT-4")

            # GPT-4 Anfrage durchführen und Ergebnis validieren
            template_model_result, result_json, llm_usage = get_structured_gpt(
                client=self.client,
                template=template,
                field_definitions=field_definitions,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=self.model,
                logger=logger
            )
            
            # 9. Strukturierte Variablen ersetzen
            for field_name, field_value in template_model_result.model_dump().items():
                pattern: str = r'\{\{' + field_name + r'\|[^}]+\}\}'
                value: str = str(field_value) if field_value is not None else ""
                template_content = re.sub(pattern, value, template_content)

            if logger:
                logger.info("Template-Transformation abgeschlossen",
                    tokens=llm_usage.tokens,
                    duration_ms=llm_usage.duration)

            # 11. Response erstellen
            return TransformationResult(
                text=template_content,
                target_language=target_language,
                requests=[llm_usage],
                structured_data=result_json
            )

        except Exception as e:
            if logger:
                logger.error("Fehler bei der Template-Transformation", error=e)
            raise

    def _read_template_file(self, template: str, logger: Optional[ProcessingLogger]) -> str:
        """Liest den Inhalt einer Template-Datei."""
        template_dir: str = 'templates'
        template_path: str = os.path.join(template_dir, f"{template}.md")
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            if logger:
                logger.error("Template konnte nicht gelesen werden",
                    error=e,
                    template_path=template_path)
            raise ValueError(f"Template '{template}' konnte nicht gelesen werden: {str(e)}")

    def _replace_context_variables(self, template_content: str, context: Optional[Dict[str, Any]], text: str, logger: Optional[ProcessingLogger]) -> str:
        """Ersetzt einfache Kontext-Variablen im Template."""
        if not isinstance(context, dict):
            context = {}
        
        # Füge text als spezielle Variable hinzu
        if text:
            # Ersetze {{text}} mit dem tatsächlichen Text
            template_content = re.sub(r'\{\{text\}\}', text, template_content)
        
        # Finde alle einfachen Template-Variablen (ohne Description)
        simple_variables: list[str] = re.findall(r'\{\{([a-zA-Z][a-zA-Z0-9_]*?)\}\}', template_content)
        
        for key, value in context.items():
            if value is not None and key in simple_variables:
                pattern: str = r'\{\{' + re.escape(str(key)) + r'\}\}'
                str_value: str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                template_content = re.sub(pattern, str_value, template_content)

        return template_content

    def _extract_structured_variables(self, template_content: str, logger: Optional[ProcessingLogger]) -> TemplateFields:
        """Extrahiert strukturierte Variablen aus dem Template."""
        pattern: str = r'\{\{([a-zA-Z][a-zA-Z0-9_]*)\|([^}]+)\}\}'
        matches: list[re.Match[str]] = list(re.finditer(pattern, template_content))
        
        seen_vars: set[str] = set()
        field_definitions: TemplateFields = TemplateFields(fields={})
        
        for match in matches:
            var_name: str = match.group(1).strip()
            if var_name in seen_vars:
                continue
                
            seen_vars.add(var_name)
            description: str = match.group(2).strip()
            
            field_def = TemplateField(
                description=description,
                max_length=5000,
                default=None
            )
            
            field_definitions.fields[var_name] = field_def
                    
        return field_definitions

    def _save_llm_interaction(
        self, 
        purpose: str,
        system_prompt: str, 
        user_prompt: str, 
        response: ChatCompletion, 
        logger: Optional[ProcessingLogger] = None,
        template: Optional[str] = None, 
        field_definitions: Optional[TemplateFields] = None,
    ) -> None:
        """Speichert die LLM-Interaktion für Debugging und Analyse."""
        try:
            debug_dir: Path = Path('./temp-processing/llm')
            debug_dir.mkdir(parents=True, exist_ok=True)
            
            # Erstelle einen eindeutigen Dateinamen
            timestamp: str = datetime.now().strftime('%Y%m%d_%H%M%S')
            template_name: str = template if template else 'direct'
            filename: str = f"{timestamp}_{purpose}_{template_name}.json"
            
            # Bereite die Interaktionsdaten vor
            interaction_data: Dict[str, Any] = {
                'timestamp': datetime.now().isoformat(),
                'template': template,
                'system_prompt': system_prompt,
                'user_prompt': user_prompt,
                'response': {
                    'content': response.choices[0].message.content if response.choices and response.choices[0].message else None,
                    'function_call': response.choices[0].message.function_call.arguments if response.choices and response.choices[0].message and hasattr(response.choices[0].message, 'function_call') and response.choices[0].message.function_call else None,
                    'usage': {
                        'total_tokens': response.usage.total_tokens if response.usage else 0,
                        'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                        'completion_tokens': response.usage.completion_tokens if response.usage else 0
                    }
                }
            }
            
            if field_definitions:
                interaction_data['field_definitions'] = {
                    name: field.description for name, field in field_definitions.fields.items()
                }
            
            # Speichere die Interaktionsdaten
            file_path: Path = debug_dir / filename
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(interaction_data, f, indent=2, ensure_ascii=False)
                
            if logger:
                logger.debug("LLM Interaktion gespeichert",
                           file=str(file_path),
                           tokens=interaction_data['response']['usage']['total_tokens'])
                
        except Exception as e:
            if logger:
                logger.warning("LLM Interaktion konnte nicht gespeichert werden",
                             error=e,
                             template=template)