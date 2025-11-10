"""
@fileoverview Transcription Utilities - Whisper transcription and text transformation

@description
Utilities for transcription and transformation of text. This file provides the
WhisperTranscriber class used for transcribing audio files with the OpenAI Whisper API.

Main functionality:
- WhisperTranscriber: Transcribes audio segments with Whisper API
- Segment-based transcription for large audio files
- LLM request tracking for transcription operations
- Integration with BaseProcessor for hierarchical tracking

Features:
- Asynchronous transcription of multiple segments
- Automatic segmentation of large audio files
- LLM tracking per segment
- Error handling and retry logic
- Debug mode for transcription details

@module utils.transcription_utils

@exports
- WhisperTranscriber: Class - Whisper transcription class
- AudioSegmentProtocol: Protocol - Protocol for audio segments
- TemplateFieldDefinition: Dataclass - Template field definition

@usedIn
- src.processors.audio_processor: Uses WhisperTranscriber for audio transcription
- src.processors.video_processor: Uses WhisperTranscriber for video audio transcription
- src.processors.transformer_processor: Uses WhisperTranscriber for template processing

@dependencies
- External: openai - OpenAI Whisper API
- External: pydantic - Data validation
- Internal: src.utils.logger - ProcessingLogger
- Internal: src.processors.base_processor - BaseProcessor for LLM tracking
- Internal: src.core.models.audio - Audio models (TranscriptionResult, etc.)
- Internal: src.core.models.llm - LLMRequest for tracking
"""
from typing import (
    Dict, 
    List, 
    Optional, 
    Union, 
    Any,
    cast as type_cast,
    Protocol,
    Coroutine,
    Tuple
)
from pathlib import Path
import os
import time
import io
import json
import asyncio
import traceback
from datetime import datetime
import re
from dataclasses import dataclass

from openai import OpenAI
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from openai.types.chat.chat_completion_message_param import ChatCompletionMessageParam
from openai.types.chat.chat_completion_system_message_param import ChatCompletionSystemMessageParam
from openai.types.chat.chat_completion_user_message_param import ChatCompletionUserMessageParam
from pydantic import Field

from src.utils.logger import ProcessingLogger
from src.core.models.transformer import (
    TranslationResult, TransformationResult, TemplateField, TemplateFields
)
from src.core.models.llm import LLMRequest
from src.core.models.enums import OutputFormat
from src.core.models.audio import (
    AudioSegmentInfo, Chapter, TranscriptionResult, TranscriptionSegment
)
from src.core.exceptions import ProcessingError
from src.processors.base_processor import BaseProcessor

# Type-Definitionen
FieldType = tuple[Union[type[str], type[None]], Field]

class AudioSegmentProtocol(Protocol):
    """Protocol für AudioSegment Typisierung."""
    @classmethod
    def from_file(
        cls,
        file: Union[str, io.BytesIO],
        format: Optional[str] = None,
        codec: Optional[str] = None,
        parameters: Optional[List[str]] = None,
        start_second: Optional[float] = None,
        duration: Optional[float] = None,
        **kwargs: Any
    ) -> Any: ...
    
    def export(self, out_f: Union[str, io.BytesIO], format: str, parameters: Optional[List[str]] = None, **kwargs: Any) -> Any: ...
    def __len__(self) -> int: ...

# Typ-Alias für AudioSegment
AudioSegmentType = AudioSegmentProtocol

@dataclass
class TemplateFieldDefinition:
    """Definition eines Template-Feldes."""
    description: str
    max_length: int = 5000
    default: Optional[str] = None

class WhisperTranscriber:
    """Klasse für die Interaktion mit GPT-4."""
    
    def __init__(self, config: Dict[str, Any], processor: BaseProcessor[Any]) -> None:
        """
        Initialisiert den WhisperTranscriber.
        
        Args:
            config: Konfiguration für den Transcriber
            processor: BaseProcessor für LLM-Request Tracking
        """
        self.config: Dict[str, Any] = config
        self.processor: BaseProcessor[Any] = processor
        
        # Verwende konfigurierte Verzeichnisse oder Fallback zu processor-spezifischen Verzeichnissen
        # Anmerkung: In der config.yaml sollten für jeden Prozessor temp_dir und debug_dir definiert sein
        
        # Debugging-Verzeichnis
        debug_dir_str = config.get('debug_dir')
        if debug_dir_str is not None:
            self.debug_dir: Path = Path(str(debug_dir_str))
        else:
            # Fallback zu processor.temp_dir/debug
            temp_dir_str = config.get('temp_dir')
            if temp_dir_str is not None:
                self.debug_dir = Path(str(temp_dir_str)) / "debug"
            else:
                # Letzter Fallback - sollte eigentlich nie auftreten
                from src.core.config import Config
                app_config = Config()
                cache_base = Path(app_config.get('cache', {}).get('base_dir', './cache'))
                self.debug_dir = cache_base / "default" / "debug"
        
        # Temporäres Verzeichnis
        temp_dir_str = config.get('temp_dir')
        if temp_dir_str is not None:
            self.temp_dir: Path = Path(str(temp_dir_str))
        else:
            # Letzter Fallback - sollte eigentlich nie auftreten
            from src.core.config import Config
            app_config = Config()
            cache_base = Path(app_config.get('cache', {}).get('base_dir', './cache'))
            self.temp_dir = cache_base / "default"
        
        self.model: str = config.get('model', 'gpt-4o')
        self.client: OpenAI = OpenAI(api_key=config.get('openai_api_key'))
        self.batch_size: int = config.get('batch_size', 10)
        self.temperature: float = config.get('temperature', 0.7)
        
        # Stelle sicher dass die Verzeichnisse existieren
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def create_llm_request(
        self,
        purpose: str,
        tokens: int,
        duration: float,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        response: Optional[ChatCompletion] = None,
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None
    ) -> LLMRequest:
        """
        Zentrale Methode für LLMRequest-Erstellung, Tracking und Debug-Logging.
        
        Args:
            purpose: Zweck des Requests (z.B. 'transcription', 'translation')
            tokens: Anzahl der verwendeten Tokens
            duration: Dauer in Millisekunden
            model: Optional, zu verwendendes Modell (default: self.model)
            system_prompt: Optional, verwendeter System-Prompt
            user_prompt: Optional, verwendeter User-Prompt
            response: Optional, die vollständige ChatCompletion Response
            logger: Optional, Logger für Debug-Ausgaben
            processor: Optional, Name des aufrufenden Processors
            
        Returns:
            LLMRequest: Der erstellte Request
        """
        request = LLMRequest(
            model=model or self.model,
            purpose=purpose,
            tokens=tokens,
            duration=duration,
            processor=processor or self.__class__.__name__
        )

        # Tracking im BaseProcessor 
        self.processor.add_llm_requests([request])

        # Debug-Logging der LLM-Interaktion
        if logger:
            logger.debug(f"LLM Request erstellt",
                purpose=purpose,
                tokens=tokens,
                duration=duration,
                model=request.model,
                processor=request.processor)

        # Speichere zusätzliche Debug-Informationen
        if system_prompt or user_prompt or response:
            try:
                # Verwende das konfigurierte Debug-Verzeichnis
                debug_dir = self.debug_dir / "llm"
                debug_dir.mkdir(parents=True, exist_ok=True)
                
                # Erstelle einen eindeutigen Dateinamen
                timestamp: str = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename: str = f"{timestamp}_{purpose}.json"
                
                # Bereite die Interaktionsdaten vor
                interaction_data: Dict[str, Any] = {
                    'timestamp': datetime.now().isoformat(),
                    'purpose': purpose,
                    'system_prompt': system_prompt,
                    'user_prompt': user_prompt,
                    'response': {
                        'content': response.choices[0].message.content if response and response.choices and response.choices[0].message else None,
                        'usage': {
                            'total_tokens': tokens,
                            'duration_ms': duration
                        }
                    }
                }
                
                # Speichere die Interaktionsdaten
                file_path: Path = debug_dir / filename
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(interaction_data, f, indent=2, ensure_ascii=False)
                    
                if logger:
                    logger.debug("LLM Interaktion gespeichert",
                               file=str(file_path),
                               tokens=tokens)
                    
            except Exception as e:
                if logger:
                    logger.warning("LLM Debug-Informationen konnten nicht gespeichert werden",
                                 error=e)

        return request

    def translate_text(
        self,
        text: str,
        source_language: str,
        target_language: str,
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None
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

            # System-Prompt definieren
            system_prompt: str = "You are a precise translator."
            instruction: str = f"Please translate this text to {target_language}:"
            user_prompt: str = f"{instruction}\n\n{text}"

            # Zeitmessung starten
            start_time: float = time.time()

            # OpenAI Client-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature
            )

            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = (time.time() - start_time) * 1000
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            message: ChatCompletionMessage = response.choices[0].message       
            translated_text: str = message.content or ""

            # LLM-Nutzung zentral tracken
            self.create_llm_request(
                purpose="translation",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                logger=logger,
                processor=processor
            )

            result = TranslationResult(
                text=translated_text,
                source_language=source_language,
                target_language=target_language
            )

            if logger:
                logger.info("Übersetzung abgeschlossen", duration_ms=duration)
            
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
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None
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

            # System-Prompt definieren
            system_prompt = "You are a precise Writer."
            
            # Instruction basierend auf Modus erstellen
            base_instruction: str = f"Can you summarize this text in {target_language} in a more concise way?"
            summary_instruction: str = base_instruction
            if max_words:
                summary_instruction = f"{base_instruction} Use at most {max_words} words."

            user_prompt: str = f"{summary_instruction}\n\n{text}"

            # Zeitmessung starten
            start_time: float = time.time()

            # OpenAI Client-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.temperature
            )

            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = (time.time() - start_time) * 1000
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            summary: str = response.choices[0].message.content or ""
            summary = summary.strip()

            # LLM-Nutzung zentral tracken
            self.create_llm_request(
                purpose="summarization",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                logger=logger,
                processor=processor
            )

            result = TransformationResult(
                text=summary,
                target_language=target_language
            )

            if logger:
                logger.info("Zusammenfassung abgeschlossen", duration_ms=duration)
            
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
        
        return TransformationResult(
            text=formatted,
            target_language=target_language
        )

    @staticmethod
    def _extract_json_substring(text: str) -> Optional[str]:
        """Extrahiert den ersten gültigen JSON-Objekt-Substring aus freiem Text.

        - Sucht das erste top-level '{' und matching '}' unter Beachtung von Strings und Escapes.
        - Gibt None zurück, wenn keine balancierte Struktur gefunden wird.
        """
        in_string: bool = False
        escape_next: bool = False
        depth: int = 0
        start_idx: Optional[int] = None

        for idx, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue

            if ch == "\\":
                if in_string:
                    escape_next = True
                continue

            if ch == '"':
                in_string = not in_string
                continue

            if in_string:
                continue

            if ch == '{':
                if depth == 0:
                    start_idx = idx
                depth += 1
            elif ch == '}':
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start_idx is not None:
                        return text[start_idx: idx + 1]

        return None

    @staticmethod
    def _sanitize_json_for_loading(s: str) -> str:
        """Macht typische LLM-Ausgabe zu validerem JSON.

        Fixes:
        - Ungültige Backslash-Escapes: wandelt \\x (x nicht in JSON-Escape) in \\\\x um
        - Entfernt trailing-Kommas vor } oder ]
        - Trimmt unsichtbare BOM/Whitespace
        """
        # Entferne BOM und trimme
        s = s.lstrip("\ufeff\n\r\t ").rstrip()

        # Entferne Markdown-Codeblöcke, falls vorhanden
        if s.startswith("```json"):
            s = s[7:]
        if s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()

        # Entferne trailing Commas wie ,} oder ,]
        s = re.sub(r",\s*([}\]])", r"\\1", s)

        # Ersetze ungültige Backslash-Escapes (alles außer gültigen JSON-Escapes)
        s = re.sub(r"\\(?![\\\"/bfnrtu])", r"\\\\", s)

        return s

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
        #if logger:
        #    logger.debug("Speichere Debug-Output", context=context)
            
        # TODO: Implementierung der Debug-Ausgabe
        pass

    def _clean_yaml_value(self, value: str) -> str:
        """Bereinigt einen Wert für YAML-Kompatibilität.
        
        Args:
            value: Der zu bereinigende Wert
            
        Returns:
            str: Der bereinigte Wert
        """
        # Entferne Sonderzeichen und problematische Zeichen für YAML
        # Erhalte Bindestriche, Unterstriche und Leerzeichen
        cleaned = re.sub(r'[^a-zA-Z0-9\s\-_]', '', value)
        # Entferne mehrfache Leerzeichen
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned.strip()

    def transform_by_template(
        self, 
        text: str, 
        target_language: str,
        template: Optional[str] = None, 
        template_content: Optional[str] = None,
        context: Dict[str, Any] | None = None,
        additional_field_descriptions: Optional[Dict[str, str]] = None,
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None,
        use_cache: bool = True
    ) -> TransformationResult:
        """
        Transformiert einen Text anhand eines Templates.
        
        Args:
            text: Der zu transformierende Text
            target_language: Die Zielsprache
            template: Name des Templates
            context: Optionaler Kontext für das Template
            additional_field_descriptions: Zusätzliche Feldbeschreibungen für das Template
            logger: Optional, Logger für Debug-Ausgaben
            processor: Optional, Name des aufrufenden Prozessors
            use_cache: Ob der Cache verwendet werden soll
            
        Returns:
            TransformationResult mit dem transformierten Text
        """
        try:
            if logger:
                logger.info(f"Starte Template-Transformation: {template}")

            # Validierung: Entweder Template-Name oder Template-Inhalt muss angegeben werden
            if not template and not template_content:
                raise ValueError("Entweder template oder template_content muss angegeben werden")

            if template and template_content:
                raise ValueError("Nur entweder template oder template_content darf angegeben werden, nicht beide")

            # 1. Template-Inhalt ermitteln
            template_content_str: str
            if template_content:
                # Direkter Template-Inhalt wurde übergeben
                template_content_str = template_content
                if logger:
                    logger.info(f"Verwende direkt übergebenes Template-Inhalt (Länge: {len(template_content_str)})")
            else:
                # Template-Datei lesen
                if not template:
                    raise ValueError("Template-Name darf nicht leer sein")
                try:
                    template_content_str = self._read_template_file(template, logger)
                except Exception as e:
                    # Spezifischer Fehler für Template-Lesefehler
                    error_msg = f"Template '{template}' konnte nicht gelesen werden: {str(e)}"
                    if logger:
                        logger.error(error_msg)
                    return TransformationResult(
                        text="Fehler bei der Template-Transformation: Template konnte nicht gelesen werden",
                        target_language=target_language,
                        structured_data={
                            "error": error_msg,
                            "error_type": "TemplateReadError",
                            "template": template,
                            "exception": str(e)
                        }
                    )

            # 2. Systemprompt extrahieren
            template_content_str, system_prompt = self._extract_system_prompt(template_content_str, logger)

            # 3. Kontext-Variablen ersetzen (vor LLM) – nur im Body, nicht im FrontMatter
            try:
                fm_split = re.match(r'^---\n(.*?)\n---\n?(.*)$', template_content_str, flags=re.DOTALL)
                if fm_split:
                    fm_head = fm_split.group(1)
                    body_part = fm_split.group(2)
                    body_part = self._replace_context_variables(body_part, context, text, logger)
                    template_content_str = f"---\n{fm_head}\n---\n" + body_part
                else:
                    # Kein FrontMatter – global ersetzen
                    template_content_str = self._replace_context_variables(template_content_str, context, text, logger)
            except ValueError as ve:
                # Detaillierter Fehler bei der Kontextersetzung
                error_msg = str(ve)
                if logger:
                    logger.error(f"Fehler bei Kontext-Transformation: {error_msg}")
                return TransformationResult(
                    text="Fehler bei der Template-Transformation: Kontextvariablen konnten nicht ersetzt werden",
                    target_language=target_language,
                    structured_data={
                        "error": error_msg,
                        "error_type": "ContextVariableError",
                        "template": template,
                        "context_keys": list(context.keys()) if context else []
                    }
                )
            
            # 4. Strukturierte Variablen extrahieren und Model erstellen
            field_definitions: TemplateFields = self._extract_structured_variables(template_content_str, logger)
            
            if not field_definitions.fields:
                # Wenn keine strukturierten Variablen gefunden wurden, erstellen wir eine einfache Response
                return TransformationResult(
                    text=text,
                    target_language=target_language
                )

            # 5. GPT-4 Prompts erstellen
            context_str: str = (
                json.dumps(context, indent=2, ensure_ascii=False)
                if isinstance(context, dict)
                else "No additional context."
            )
            
            # Ersetze nur den expliziten Sprach-Platzhalter im Systemprompt.
            # Wichtig: Kein str.format verwenden, da JSON-Klammern { } im Prompt sonst
            # als Format-Keys interpretiert werden und KeyError auslösen können.
            if "{target_language}" in system_prompt:
                system_prompt = system_prompt.replace("{target_language}", target_language)
            
            # Extrahiere die Feldnamen und Beschreibungen
            field_descriptions = {
                name: field.description 
                for name, field in field_definitions.fields.items()
            }

            # FrontMatter-Kontext-Only-Felder (nicht vom LLM anfordern)
            fm_context_only: set[str] = {
                name for name, field in field_definitions.fields.items()
                if getattr(field, 'isFrontmatter', False) and str(getattr(field, 'description', '')).strip() == "YAML Frontmatter Variable"
            }

            # Nur Felder im Prompt, die nicht reine Kontext-FM-Felder sind
            required_field_descriptions = {
                name: desc for name, desc in field_descriptions.items()
                if name not in fm_context_only
            }
            
            # Füge zusätzliche Feldbeschreibungen hinzu, falls vorhanden
            if additional_field_descriptions:
                field_descriptions.update(additional_field_descriptions)
                
            user_prompt: str = (
                f"Analyze the following text and extract the information as a JSON object:\n\n"
                f"TEXT:\n{text}\n\n"
                f"CONTEXT:\n{context_str}\n\n"
                f"REQUIRED FIELDS:\n"
                f"{json.dumps(required_field_descriptions, indent=2, ensure_ascii=False)}\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Extract all required information from the text\n"
                f"2. Return a single JSON object where each key matches a field name\n"
                f"3. Provide all values in language: {target_language}\n"
                f"4. Ensure the response is valid JSON\n"
                f"5. Do not include any text outside the JSON object"
            )

            # 6. OpenAI Anfrage senden
            if logger:
                logger.info("Sende Anfrage an OpenAI " + self.model)
            
            # Zeitmessung starten
            start_time: float = time.time()

            # OpenAI Client-Aufruf mit korrekten Message-Typen
            messages: list[ChatCompletionMessageParam] = [
                ChatCompletionSystemMessageParam(
                    role="system",
                    content=system_prompt
                ),
                ChatCompletionUserMessageParam(
                    role="user",
                    content=user_prompt
                )
            ]

            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature
            )

            # Zeitmessung beenden
            duration = (time.time() - start_time) * 1000

            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            # Validiere und bereinige die LLM-Antwort
            raw_content = response.choices[0].message.content
            if not raw_content or not raw_content.strip():
                raise ValueError("Leere Antwort vom LLM erhalten")

            # Versuche JSON zu extrahieren (entferne ggf. Markdown-Codeblöcke)
            content = raw_content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            try:
                # 1) Direkter Parse-Versuch
                result_json = json.loads(content)
            except json.JSONDecodeError as e_primary:
                # 2) Versuche JSON-Objekt aus Text zu extrahieren und zu sanitisieren
                candidate: str = self._extract_json_substring(content) or content
                sanitized: str = self._sanitize_json_for_loading(candidate)
                try:
                    result_json = json.loads(sanitized)
                    if logger:
                        logger.warning(
                            "LLM-JSON musste saniert werden; ursprünglicher Parse schlug fehl",
                            primary_error=str(e_primary)
                        )
                except json.JSONDecodeError as e_secondary:
                    if logger:
                        logger.error(
                            "Ungültiges JSON vom LLM (auch nach Sanitizing)",
                            primary_error=str(e_primary),
                            secondary_error=str(e_secondary),
                            snippet=sanitized[:500]
                        )
                    # Erstelle leeres JSON mit Fehlermeldung für jedes erwartete Feld
                    result_json = {
                        name: f"Fehler bei der Extraktion: {str(e_secondary)}"
                        for name in field_definitions.fields.keys()
                    }

            # LLM-Nutzung tracken mit zentraler Methode
            self.create_llm_request(
                purpose="template_transform",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration,
                model=self.model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                logger=logger,
                processor=processor
            )

            # Template mit extrahierten Daten füllen
            # Keys, die zwingend als JSON serialisiert werden müssen (Arrays/Objekte)
            json_frontmatter_keys: set[str] = {
                "chapters", "toc", "confidence", "provenance",
                # zusätzlich häufig genutzte strukturierte Felder
                "slides", "attachments", "speakers", "topics", "tags", "affiliations"
            }

            def _serialize_frontmatter(field: str, val: Any) -> str:
                """Serialisiert Frontmatter-Werte gemäß strikter Parser-Regeln.
                - Für json_frontmatter_keys immer val als gültiges JSON (mit Double-Quotes)
                - Für andere Frontmatter-Felder als explizit gequoteten String
                """
                # JSON-Felder: immer als JSON serialisieren (Double-Quotes, mehrzeilig ok)
                if field in json_frontmatter_keys:
                    try:
                        # default=str sorgt für serielle Darstellung unbekannter Typen
                        return json.dumps(val, ensure_ascii=False, default=lambda o: str(o))
                    except Exception:
                        return json.dumps(str(val), ensure_ascii=False)
                # Einfache Strings: immer in Double-Quotes, ohne Auto-Typisierung
                s = "" if val is None else str(val)
                # Trimme CR/LF ans Ende, ersetze harte Zeilenumbrüche im Frontmatter
                s = s.replace("\r", " ").replace("\n", " ")
                # YAML-sicher: doppelte Anführungszeichen escapen
                s = s.replace('"', '\\"')
                return f'"{s}"'

            for field_name, field_value in result_json.items():
                # Feldnamen defensiv escapen (sollten zwar alphanumerisch sein, ist aber sicherer)
                pattern: str = r'\{\{' + re.escape(str(field_name)) + r'\|[^}]+\}\}'

                field_def: TemplateField | None = field_definitions.fields.get(field_name)
                if field_def and getattr(field_def, 'isFrontmatter', False):
                    value_str: str = _serialize_frontmatter(field_name, field_value)
                else:
                    # Nicht-Frontmatter: Wert direkt, aber sicher ersetzen
                    value_str = "" if field_value is None else str(field_value)

                # Wichtig: Replacement als Funktion, damit Backslashes in value NICHT als Regex-Escape wirken
                template_content_str = re.sub(pattern, (lambda _m, s=value_str: s), template_content_str)

            # Danach: nackte Platzhalter {{field}} aus result_json ersetzen (Frontmatter und Body getrennt)
            try:
                fm_match = re.match(r'^---\n(.*?)\n---\n?', template_content_str, flags=re.DOTALL)
                if fm_match:
                    fm_content = fm_match.group(1)
                    body_content = template_content_str[fm_match.end():]

                    # Im Frontmatter mit strikter Serialisierung ersetzen
                    for k, v in result_json.items():
                        simple_pat = r'\{\{' + re.escape(str(k)) + r'\}\}'
                        replacement = _serialize_frontmatter(str(k), v)
                        fm_content = re.sub(simple_pat, (lambda _m, s=replacement: s), fm_content)

                    # Im Body einfache Werte einsetzen
                    for k, v in result_json.items():
                        simple_pat = r'\{\{' + re.escape(str(k)) + r'\}\}'
                        if isinstance(v, (dict, list)):
                            rep_body = json.dumps(v, ensure_ascii=False)
                        elif v is None:
                            rep_body = ""
                        else:
                            rep_body = str(v)
                        body_content = re.sub(simple_pat, (lambda _m, s=rep_body: s), body_content)

                    template_content_str = f"---\n{fm_content}\n---" + body_content
                else:
                    # Kein Frontmatter, global ersetzen
                    for k, v in result_json.items():
                        simple_pat = r'\{\{' + re.escape(str(k)) + r'\}\}'
                        if isinstance(v, (dict, list)):
                            rep = json.dumps(v, ensure_ascii=False)
                        elif v is None:
                            rep = ""
                        else:
                            rep = str(v)
                        template_content_str = re.sub(simple_pat, (lambda _m, s=rep: s), template_content_str)
            except Exception:
                pass

            # Deterministischer FrontMatter-Rebuild aus Objekten mit Kontext-Override für FM-Kontextfelder
            try:
                fm_match3 = re.match(r'^---\n(.*?)\n---\n?(.*)$', template_content_str, flags=re.DOTALL)
                if fm_match3:
                    fm_block_current = fm_match3.group(1)
                    body_part_current = fm_match3.group(2)

                    # Keys im aktuellen FM bestimmen (linke Seite vor ':')
                    fm_lines_present = [ln for ln in fm_block_current.split('\n') if ln.strip()]
                    fm_keys: list[str] = []
                    for ln in fm_lines_present:
                        if ':' in ln:
                            k = ln.split(':', 1)[0].strip()
                            if k and k not in fm_keys:
                                fm_keys.append(k)

                    # FM-Objekt aus result_json + context aufbauen; Kontext-Felder überschreiben
                    fm_obj: dict[str, Any] = {}
                    for k in fm_keys:
                        val = result_json.get(k)
                        # Kontext-Only FM-Felder strikt aus context ziehen
                        if k in fm_context_only and isinstance(context, dict):
                            val = context.get(k, val)
                        elif val is None and isinstance(context, dict):
                            # allgemeiner Fallback auf context
                            val = context.get(k, val)
                        fm_obj[k] = val

                    # Serialisieren gemäß Regeln
                    json_frontmatter_keys_rebuild: set[str] = {
                        "chapters", "toc", "confidence", "provenance",
                        "slides", "attachments", "speakers", "topics", "tags", "affiliations"
                    }
                    fm_lines_out: list[str] = []
                    for k in fm_keys:
                        v = fm_obj.get(k)
                        if k in json_frontmatter_keys_rebuild:
                            fm_lines_out.append(f"{k}: {json.dumps(v, ensure_ascii=False, default=lambda o: str(o))}")
                        else:
                            s = "" if v is None else str(v)
                            s = s.replace('"','\\"').replace("\r"," ").replace("\n"," ")
                            fm_lines_out.append(f"{k}: \"{s}\"")

                    fm_serialized = "---\n" + "\n".join(fm_lines_out) + "\n---\n"
                    template_content_str = fm_serialized + body_part_current
            except Exception:
                # Im Fehlerfall unverändert lassen
                pass

            # Fallback: verbleibende einfache Platzhalter mit Kontext ersetzen
            # Frontmatter und Body getrennt behandeln, damit FM-Strings korrekt gequotet werden
            try:
                fm_match_2 = re.match(r'^---\n(.*?)\n---\n?', template_content_str, flags=re.DOTALL)
                if fm_match_2:
                    fm_content_2 = fm_match_2.group(1)
                    body_content_2 = template_content_str[fm_match_2.end():]

                    # Ersetze im Frontmatter Kontext-Platzhalter mit strikter Serialisierung
                    if isinstance(context, dict):
                        for k, v in context.items():
                            simple_pat_ctx = r'\{\{' + re.escape(str(k)) + r'\}\}'
                            fm_repl = _serialize_frontmatter(str(k), v)
                            fm_content_2 = re.sub(simple_pat_ctx, (lambda _m, s=fm_repl: s), fm_content_2)

                    # Ersetze im Body verbleibende Kontext-Platzhalter normal
                    body_content_2 = self._replace_context_variables(body_content_2, context, text, logger)

                    template_content_str = f"---\n{fm_content_2}\n---\n" + body_content_2
                else:
                    # Kein Frontmatter – globaler Fallback
                    template_content_str = self._replace_context_variables(template_content_str, context, text, logger)
            except Exception:
                # Falls etwas schief geht, fallback auf globale Ersetzung
                template_content_str = self._replace_context_variables(template_content_str, context, text, logger)
            
            if logger:
                logger.info("Template-Transformation abgeschlossen",
                    duration_ms=duration,
                    model=self.model)

            # Response erstellen
            return TransformationResult(
                text=template_content_str,
                target_language=target_language,
                structured_data=result_json
            )
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Template-Transformation", error=e)
            # Erstelle eine Fehler-Response mit detaillierten Informationen
            error_result = TransformationResult(
                text=f"Fehler bei der Template-Transformation: {str(e)}",
                target_language=target_language,
                structured_data={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "template": template,
                    "traceback": traceback.format_exc()
                }
            )
            return error_result

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
        
        try:
            # Füge text als spezielle Variable hinzu
            if text:
                # Ersetze {{text}} mit dem tatsächlichen Text
                # WICHTIG: Replacement als Funktion, damit Backslashes im Text NICHT als Escape interpretiert werden
                template_content = re.sub(r'\{\{text\}\}', lambda _m: text, template_content)
            
            # Finde alle einfachen Template-Variablen (ohne Description)
            simple_variables: list[str] = re.findall(r'\{\{([a-zA-Z][a-zA-Z0-9_]*?)\}\}', template_content)
            
            for key, value in context.items():
                try:
                    if value is not None and key in simple_variables:
                        pattern: str = r'\{\{' + re.escape(str(key)) + r'\}\}'
                        str_value: str = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                        # Replacement als Funktion, damit Backslashes im Wert nicht als Escape interpretiert werden
                        template_content = re.sub(pattern, (lambda _m, s=str_value: s), template_content)
                except Exception as variable_error:
                    # Detaillierte Fehlerinformationen für eine spezifische Variable
                    # Bereite eine sichere String-Version des problematischen Werts vor
                    safe_value = ""
                    try:
                        if isinstance(value, (dict, list)):
                            safe_value = json.dumps(value, ensure_ascii=False)[:100]
                        else:
                            safe_value = str(value)[:100]
                    except:
                        safe_value = f"<Nicht darstellbarer Wert vom Typ {type(type_cast(object, value)).__name__}>"
                    # Versuche Positions-Infos aus der Exception zu extrahieren (z. B. "at position 2843")
                    detail_msg = str(variable_error)
                    pos_idx: Optional[int] = None
                    try:
                        import re as _re
                        m = _re.search(r"position\s+(\d+)", detail_msg)
                        if m:
                            pos_idx = int(m.group(1))
                    except Exception:
                        pos_idx = None
                    # Wenn Position extrahiert werden konnte, bereite Zeile+Caret auf Basis des Ersatz-Strings vor
                    caret_block = ""
                    if pos_idx is not None:
                        try:
                            repl_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                            # Begrenze extrem lange Strings für Darstellung
                            idx = max(0, min(pos_idx, len(repl_str)))
                            # Zeilennummer und Spalte bestimmen
                            cumulative = 0
                            line_no = 0
                            col_no = 0
                            for line_no_iter, line in enumerate(repl_str.splitlines(True)):
                                if cumulative + len(line) > idx:
                                    line_no = line_no_iter
                                    col_no = idx - cumulative
                                    line_text = line.rstrip("\r\n")
                                    # Kürzen der Zeile für bessere Lesbarkeit
                                    start = max(0, col_no - 100)
                                    end = min(len(line_text), col_no + 100)
                                    view = line_text[start:end]
                                    caret_pos = col_no - start
                                    caret_line = (" " * max(0, caret_pos)) + "^"
                                    caret_block = f"\nZeile {line_no + 1}, Spalte {col_no + 1}:\n{view}\n{caret_line}"
                                    break
                                cumulative += len(line)
                        except Exception:
                            caret_block = ""
                    
                    error_msg = (
                        f"Fehler beim Ersetzen der Variable '{key}': {detail_msg}. "
                        f"Problematischer Wert (gekürzt): {safe_value}{caret_block}"
                    )
                    if logger:
                        logger.error(error_msg, 
                                   variable=key, 
                                   value_type=type(type_cast(object, value)).__name__, 
                                   error=variable_error)
                    raise ValueError(error_msg)

            return template_content
            
        except Exception as e:
            if isinstance(e, ValueError) and "Fehler beim Ersetzen der Variable" in str(e):
                # Weiterleiten des speziellen Fehlers
                raise
            else:
                # Allgemeiner Fehler beim Ersetzen von Variablen
                error_msg = f"Fehler beim Ersetzen von Kontext-Variablen: {str(e)}"
                if logger:
                    logger.error(error_msg, error=e)
                raise ValueError(error_msg)

    def _extract_structured_variables(self, template_content: str, logger: Optional[ProcessingLogger]) -> TemplateFields:
        """Extrahiert strukturierte Variablen aus dem Template.
        
        Args:
            template_content: Der Inhalt des Templates
            logger: Optional Logger
            
        Returns:
            TemplateFields: Die extrahierten Felder mit Beschreibungen
        """
        pattern: str = r'\{\{([a-zA-Z][a-zA-Z0-9_]*)\|([^}]+)\}\}'
        matches: list[re.Match[str]] = list(re.finditer(pattern, template_content))
        
        seen_vars: set[str] = set()
        field_definitions: TemplateFields = TemplateFields(fields={})
        
        # Extrahiere YAML Frontmatter
        yaml_pattern = r'^---\n(.*?)\n---'
        yaml_match = re.search(yaml_pattern, template_content, re.DOTALL)
        
        if yaml_match:
            yaml_content = yaml_match.group(1)
            # Extrahiere Variablen aus YAML-Zeilen
            yaml_lines = yaml_content.split('\n')
            for line in yaml_lines:
                line = line.strip()
                if line and ':' in line:
                    # Extrahiere den Variablennamen vor dem ersten Doppelpunkt
                    var_name = line.split(':', 1)[0].strip()
                    if var_name and var_name not in seen_vars:
                        seen_vars.add(var_name)
                        # Suche nach einer Beschreibung in den Template-Variablen
                        description = "YAML Frontmatter Variable"
                        # Suche nach einer möglichen Beschreibung im Template
                        desc_pattern = r'\{\{' + re.escape(var_name) + r'\|([^}]+)\}\}'
                        desc_match = re.search(desc_pattern, template_content)
                        if desc_match:
                            description = desc_match.group(1).strip()
                        
                        field_def = TemplateField(
                            description=description,
                            max_length=5000,  # Standard-Länge
                            isFrontmatter=True,
                            default=None
                        )
                        field_definitions.fields[var_name] = field_def
        
        # Füge weitere Template-Variablen hinzu
        for match in matches:
            var_name: str = match.group(1).strip()
            if var_name in seen_vars:
                continue
                
            seen_vars.add(var_name)
            description: str = match.group(2).strip()
            
            field_def = TemplateField(
                description=description,
                max_length=5000,
                default=None,
                isFrontmatter=False
            )
            
            field_definitions.fields[var_name] = field_def
                    
        return field_definitions

    def _extract_system_prompt(self, template_content: str, logger: Optional[ProcessingLogger] = None) -> Tuple[str, str]:
        """
        Extrahiert den Systemprompt aus dem Template-Inhalt.
        
        Args:
            template_content: Der Inhalt des Templates
            logger: Optional Logger
            
        Returns:
            Tuple[str, str]: (Template-Inhalt ohne Systemprompt, Systemprompt)
        """
        # Standard-Systemprompt, falls keiner im Template gefunden wird
        default_system_prompt = (
            "You are a precise assistant for text analysis and data extraction. "
            "Analyze the text and extract the requested information. "
            "Provide all answers in the target language ISO 639-1 code:{target_language}. "
            "IMPORTANT: Your response must be a valid JSON object where each key corresponds to a template variable."
        )
        
        # Prüfe, ob ein Systemprompt im Template vorhanden ist
        if "--- systemprompt" in template_content:
            parts = template_content.split("--- systemprompt", 1)
            template_without_prompt = parts[0].strip()
            
            # Extrahiere den Systemprompt
            system_prompt = parts[1].strip()
            
            if logger:
                logger.info("Systemprompt aus Template extrahiert", 
                           prompt_length=len(system_prompt))
            
            # Füge die Formatierungsanweisung hinzu
            system_prompt += "\n\nIMPORTANT: Your response must be a valid JSON object where each key corresponds to a template variable."
            
            return template_without_prompt, system_prompt
        else:
            if logger:
                logger.info("Kein Systemprompt im Template gefunden, verwende Standard-Prompt")
            return template_content, default_system_prompt

    async def transcribe_segment(
        self,
        file_path: Union[Path, bytes],
        logger: Optional[ProcessingLogger] = None,
        segment_id: Optional[int] = None,
        segment_title: Optional[str] = None,
        source_language: str = "de",
        target_language: str = "de",
        processor: Optional[str] = None
    ) -> TranscriptionResult:
        """Transkribiert ein einzelnes Audio-Segment.
        
        Args:
            file_path: Pfad zur Audio-Datei oder Bytes-Objekt
            logger: Optional, Logger für Debug-Ausgaben
            segment_id: Optional, ID des Segments für die Sortierung
            segment_title: Optional, Titel des Segments (z.B. Kapitel-Titel)
            source_language: Quellsprache der Audio-Datei (ISO 639-1)
            target_language: Zielsprache für die Transkription (ISO 639-1)
            
        Returns:
            TranscriptionResult: Das Transkriptionsergebnis
        """
        # Initialisiere Zeitmessung sofort
        start_time: float = time.time()
        
        try:
            if logger:
                logger.info(
                    "Starte Transkription von Segment",
                    segment_id=segment_id,
                    segment_title=segment_title,
                    file_path=str(file_path) if isinstance(file_path, Path) else "bytes"
                )

            # Initialisiere response
            response: Optional[TranscriptionVerbose] = None

            # Async-Funktion für API-Aufruf mit Timeout
            async def call_api_with_timeout():
                if logger:
                    logger.info(f"SEGMENT-DEBUG: API-Aufruf mit Timeout für Segment {segment_id} gestartet")
                
                # Thread-übergreifende Event-Objekte zur Signalisierung
                import threading
                from typing import Any, List, Optional
                
                operation_completed = threading.Event()
                # Typisierte Listen für Thread-übergreifende Kommunikation
                operation_result: List[Any] = [None]
                operation_error: List[Optional[Exception]] = [None]

                # Definiere die blockierende Funktion, die im Thread ausgeführt wird
                def execute_api_call():
                    if logger:
                        logger.info(f"SEGMENT-DEBUG: Thread-API-Aufruf für Segment {segment_id} gestartet")
                    
                    try:
                        # Dateipfad oder Bytes-Objekt verarbeiten
                        if isinstance(file_path, Path):
                            with open(file_path, 'rb') as audio_file:
                                response = self.client.audio.transcriptions.create(
                                    model="whisper-1",
                                    file=("audio.mp3", audio_file, "audio/mpeg"),
                                    response_format="verbose_json"
                                )
                        else:
                            # Wenn file_path bereits bytes ist
                            bytes_io = io.BytesIO(file_path)
                            response: TranscriptionVerbose = self.client.audio.transcriptions.create(
                                model="whisper-1",
                                file=("audio.mp3", bytes_io, "audio/mpeg"),
                                response_format="verbose_json"
                            )
                        
                        # Erfolgreicher Aufruf - speichere Ergebnis
                        operation_result[0] = response
                        if logger:
                            logger.info(f"SEGMENT-DEBUG: Thread-API-Aufruf für Segment {segment_id} erfolgreich")
                    
                    except Exception as e:
                        # Fehler - speichere Exception
                        operation_error[0] = e
                        if logger:
                            logger.error(f"SEGMENT-DEBUG: Thread-API-Fehler für Segment {segment_id}: {str(e)}")
                    
                    finally:
                        # In jedem Fall signalisieren, dass die Operation abgeschlossen ist
                        operation_completed.set()
                
                # Thread erstellen und starten
                thread = threading.Thread(target=execute_api_call, name=f"API-Thread-{segment_id}")
                thread.daemon = True  # Als Daemon markieren, damit er automatisch beendet wird
                thread.start()
                
                try:
                    # Auf den Thread warten mit Timeout
                    # Verwende asyncio.sleep für asynchrones Warten während der Timeout-Prüfung
                    timeout_seconds = 120.0
                    check_interval = 1.0  # Prüfe jede Sekunde
                    elapsed = 0.0
                    
                    if logger:
                        logger.info(f"SEGMENT-DEBUG: Warte auf Thread-API-Antwort für Segment {segment_id} mit Timeout von {timeout_seconds} Sekunden")
                    
                    # Asynchroner Timeout-Loop
                    while elapsed < timeout_seconds:
                        # Wenn Thread fertig, breche die Schleife ab
                        if operation_completed.is_set():
                            break
                        
                        # Warte asynchron für ein Intervall
                        await asyncio.sleep(check_interval)
                        elapsed += check_interval
                    
                    # Prüfe, ob die Operation abgeschlossen wurde oder ob ein Timeout aufgetreten ist
                    if operation_completed.is_set():
                        if operation_error[0]:
                            # Es ist ein Fehler aufgetreten
                            error_obj = operation_error[0]  # Typensichere Referenz
                            if logger:
                                logger.error(
                                    f"SEGMENT-DEBUG: API-Fehler für Segment {segment_id}",
                                    error=error_obj,  # Übergebe Exception-Objekt direkt
                                    error_type=type(error_obj).__name__
                                )
                            # Fehler weiterleiten an Fehlerbehandlung
                            self._handle_api_error(error_obj)
                            return None
                        else:
                            # Erfolgreicher Abschluss
                            if logger:
                                logger.info(f"SEGMENT-DEBUG: API-Antwort für Segment {segment_id} erfolgreich empfangen")
                            return operation_result[0]
                    else:
                        # Timeout ist aufgetreten
                        if logger:
                            logger.error(f"SEGMENT-DEBUG: Timeout bei API-Anfrage für Segment {segment_id} nach {timeout_seconds} Sekunden")
                        # Thread wird als Daemon automatisch beendet
                        return None
                
                except Exception as e:
                    # Unerwartete Ausnahme während des Wartens
                    if logger:
                        logger.error(
                            f"SEGMENT-DEBUG: Unerwartete Ausnahme beim Warten auf API-Antwort für Segment {segment_id}",
                            error=e,  # Übergebe Exception-Objekt direkt
                            error_type=type(e).__name__,
                            traceback=traceback.format_exc()
                        )
                    return None

            # API aufrufen mit Timeout und klarer Fallback
            try:
                response = await call_api_with_timeout()
            except Exception as e:
                if logger:
                    logger.error(
                        f"SEGMENT-DEBUG: Unbehandelte Ausnahme bei API-Aufruf für Segment {segment_id}",
                        error=e,
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc()
                    )
                response = None

            # Wenn keine Antwort oder ungültige Antwort, gib leeres Ergebnis zurück
            if not response or not hasattr(response, 'text'):
                if logger:
                    logger.warning(
                        f"SEGMENT-DEBUG: Keine gültige API-Antwort für Segment {segment_id} erhalten, überspringe Segment"
                    )
                # Erstelle leeres Ergebnis, damit der Gesamtprozess nicht hängen bleibt
                segment = TranscriptionSegment(
                    text="",
                    segment_id=segment_id or 0,
                    start=0.0,
                    end=0.0,
                    title=segment_title
                )
                
                # Zeitmessung beenden
                duration = (time.time() - start_time) * 1000
                
                # LLM-Nutzung tracken mit zentraler Methode
                self.create_llm_request(
                    purpose="transcription_failed",
                    tokens=0,
                    duration=duration,
                    model="whisper-1"
                )

                return TranscriptionResult(
                    text="",
                    source_language=source_language,
                    segments=[segment]
                )
            
            # Zeitmessung beenden
            duration = (time.time() - start_time) * 1000
            
            # Schätze die Token basierend auf der Textlänge
            estimated_tokens: float = len(response.text.split()) * 1.5 if hasattr(response, 'text') else 0
            
            # Behebe das Usage-Objekt Problem - verwende direkte Attribute statt .get()
            tokens: int = 0
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                total_tokens_value = getattr(usage, 'total_tokens', None)
                if total_tokens_value:
                    tokens = int(total_tokens_value)
                else:
                    tokens = int(estimated_tokens)
            else:
                tokens = int(estimated_tokens)
            
            # LLM-Nutzung tracken mit zentraler Methode
            self.create_llm_request(
                processor=processor,
                purpose="transcription",
                tokens=tokens,
                duration=duration,
                model="whisper-1"  # Explizit Whisper-Modell angeben
            )

            if source_language == "auto":
                # Konvertiere Whisper Sprachcode in ISO 639-1
                source_language = self._convert_to_iso_code(response.language)

            # Prüfe ob Text leer ist und setze Fallback
            transcription_text = response.text if hasattr(response, 'text') and response.text.strip() else "[Keine Sprache erkannt]"

            # Erstelle ein einzelnes Segment für das gesamte Audio-Segment
            segment = TranscriptionSegment(
                text=transcription_text,
                segment_id=segment_id or 0,
                start=0.0,
                end=duration / 1000.0,
                title=segment_title
            )
            
            if logger:
                logger.info(
                    "Transkription erfolgreich",
                    segment_id=segment_id,
                    duration_ms=duration,
                    tokens=tokens,
                    text_length=len(transcription_text)
                )
            
            return TranscriptionResult(
                text=transcription_text,
                source_language=source_language,
                segments=[segment]  # Nur ein Segment pro Audio-Datei
            )
            
        except Exception as e:
            if logger:
                logger.error(
                    "Fehler bei der Transkription von Segment",
                    error=e,
                    error_type=type(e).__name__,
                    segment_id=segment_id,
                    segment_title=segment_title,
                    traceback=traceback.format_exc()
                )
            
            # Erstelle leeres Ergebnis, damit der Gesamtprozess nicht hängen bleibt
            segment = TranscriptionSegment(
                text="[Transkriptionsfehler]",
                segment_id=segment_id or 0,
                start=0.0,
                end=0.0,
                title=segment_title
            )
            
            # Zeitmessung beenden
            duration = (time.time() - start_time) * 1000
            
            # LLM-Nutzung tracken mit zentraler Methode für Fehler
            self.create_llm_request(
                purpose="transcription_error",
                tokens=0,
                duration=duration,
                model="whisper-1"
            )

            return TranscriptionResult(
                text=f"[Transkriptionsfehler: {str(e)}]",
                source_language=source_language,
                segments=[segment]
            )

    def _convert_to_iso_code(self, language: str) -> str:
        """Konvertiert Whisper Sprachbezeichnung in ISO 639-1 Code.
        
        Args:
            language: Sprachbezeichnung von Whisper (z.B. 'english')
            
        Returns:
            str: ISO 639-1 Sprachcode (z.B. 'en')
        """
        # Mapping der häufigsten Sprachen
        language_map: Dict[str, str] = {
            'english': 'en',
            'german': 'de',
            'french': 'fr',
            'spanish': 'es',
            'italian': 'it',
            'portuguese': 'pt',
            'arabic': 'ar',
            'chinese': 'zh',
            'japanese': 'ja',
            'korean': 'ko',
            'russian': 'ru',
            'turkish': 'tr',
            'hindi': 'hi',
            'bengali': 'bn',
            'polish': 'pl',
            'czech': 'cs',
            'dutch': 'nl'
            # Weitere Sprachen können hier hinzugefügt werden
        }
        
        # Konvertiere zu Kleinbuchstaben und entferne Leerzeichen
        normalized = language.lower().strip()
        
        # Wenn der Code bereits im ISO-Format ist (2 Buchstaben), gib ihn direkt zurück
        if len(normalized) == 2:
            return normalized
            
        # Versuche die Sprache im Mapping zu finden
        return language_map.get(normalized, 'en')  # Fallback auf 'en' wenn unbekannt

    def _handle_api_error(self, api_error: Exception) -> None:
        """Behandelt spezifische API-Fehler."""
        error_msg = str(api_error)
        if "unrecognized file format" in error_msg.lower():
            raise ProcessingError(
                "Das Audio-Format wird von der Whisper API nicht unterstützt. "
                "Unterstützte Formate sind: FLAC, M4A, MP3, MP4, MPEG, MPGA, OGA, OGG, WAV, WEBM. "
                "Bitte konvertieren Sie die Datei in eines dieser Formate.",
                details={'error_type': 'FORMAT_ERROR', 'original_error': error_msg}
            )
        elif "api_key" in error_msg.lower():
            raise ProcessingError(
                "Fehler bei der API-Authentifizierung. Bitte überprüfen Sie den API-Schlüssel.",
                details={'error_type': 'AUTH_ERROR', 'original_error': error_msg}
            )
        else:
            raise ProcessingError(
                "Fehler bei der Transkription durch die Whisper API.",
                details={'error_type': 'API_ERROR', 'original_error': error_msg}
            )

    async def transcribe_segments(
        self,
        *,  # Erzwinge Keyword-Argumente
        segments: Union[List[AudioSegmentInfo], List[Chapter]],
        source_language: str = "de",
        target_language: str = "de",
        logger: Optional[ProcessingLogger] = None,
        processor: Optional[str] = None
    ) -> TranscriptionResult:
        """Transkribiert mehrere Audio-Segmente parallel (max. 5 gleichzeitig).
        
        Args:
            segments: Liste von AudioSegmentInfo oder Chapter Objekten
            source_language: Quellsprache (ISO 639-1)
            target_language: Zielsprache (ISO 639-1)
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            TranscriptionResult: Das Transkriptionsergebnis
        """
        # Logging: Start der Segment-Verarbeitung
        if logger:
            logger.info(f"TRANSKRIPTION-DEBUG: Starte parallele Transkription von {len(segments)} Segmenten/Kapiteln")
            
        combined_text_parts: List[str] = []
        combined_requests: List[LLMRequest] = []
        detected_language: str = source_language

        # Extrahiere alle Segmente aus der Kapitelstruktur
        all_segments: List[AudioSegmentInfo] = []
        
        # Hilfsfunktion zum Umgang mit Kapiteln
        if segments and isinstance(next(iter(segments)), Chapter):
            chapters: List[Chapter] = type_cast(List[Chapter], segments)
            for chapter in chapters:
                if chapter.title and chapter.title.strip():
                    combined_text_parts.append(f"\n## {chapter.title}\n")
                all_segments.extend(chapter.segments)
                if logger:
                    logger.info(f"TRANSKRIPTION-DEBUG: Kapitel '{chapter.title}' mit {len(chapter.segments)} Segmenten extrahiert")
        else:
            all_segments = type_cast(List[AudioSegmentInfo], segments)
            if logger:
                logger.info(f"TRANSKRIPTION-DEBUG: {len(all_segments)} Segmente direkt verarbeitet")

        # Batch-Größe für parallele Verarbeitung
        BATCH_SIZE = 5
        
        # Verarbeite Segmente in Batches parallel
        if logger:
            logger.info(f"TRANSKRIPTION-DEBUG: Starte parallele Verarbeitung von {len(all_segments)} Segmenten mit {BATCH_SIZE} gleichzeitig")
        
        # Verarbeite alle Segmente in Batches
        for batch_start in range(0, len(all_segments), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(all_segments))
            current_batch = all_segments[batch_start:batch_end]
            
            if logger:
                logger.info(f"TRANSKRIPTION-DEBUG: Verarbeite Batch {batch_start//BATCH_SIZE + 1} mit {len(current_batch)} Segmenten")
            
            # Erstelle Tasks für alle Segmente im aktuellen Batch
            segment_tasks: List[Coroutine[Any, Any, TranscriptionResult]] = []
            for i, segment in enumerate(current_batch):
                segment_index = batch_start + i
                segment_tasks.append(self.transcribe_segment(
                    file_path=segment.get_audio_data(),
                    segment_id=segment_index,
                    segment_title=segment.title,
                    source_language=source_language,
                    target_language=target_language,
                    logger=logger,
                    processor=processor
                ))
            
            # Führe alle Tasks im Batch parallel aus und warte auf Ergebnisse
            try:
                # Expliziter Typecast für die Ergebnisse
                results = await asyncio.gather(*segment_tasks)
                batch_results: List[TranscriptionResult] = results
                
                # Verarbeite die Ergebnisse des Batches
                for i, result in enumerate(batch_results):
                    segment_index = batch_start + i
                    
                    if logger:
                        logger.info(f"TRANSKRIPTION-DEBUG: Segment {segment_index} - Verarbeitung abgeschlossen, Textlänge: {len(result.text or '')}")
                    
                    
                    # Übersetzung, falls nötig
                    if result.source_language != target_language and result.text.strip():
                        if logger:
                            logger.info(f"TRANSKRIPTION-DEBUG: Segment {segment_index} - Starte Übersetzung von {result.source_language} nach {target_language}")
                        
                        translation_result = self.translate_text(
                            text=result.text,
                            source_language=result.source_language,
                            target_language=target_language,
                            logger=logger,
                            processor=processor
                        )
                        
                        if logger:
                            logger.info(f"TRANSKRIPTION-DEBUG: Segment {segment_index} - Übersetzung abgeschlossen, Textlänge: {len(translation_result.text or '')}")
                        
                        # Verwende übersetzten Text
                        if translation_result.text.strip():
                            combined_text_parts.append(translation_result.text)
                        else:
                            combined_text_parts.append(result.text if result.text.strip() else "")
                    else:
                        # Verwende Original-Text
                        combined_text_parts.append(result.text if result.text.strip() else "")
                    
                    # Aktualisiere die erkannte Sprache
                    if result.source_language != "auto" and result.source_language != detected_language:
                        detected_language = result.source_language
                
            except Exception as e:
                if logger:
                    logger.error(
                        f"TRANSKRIPTION-DEBUG: Batch {batch_start//BATCH_SIZE + 1} - Fehler bei der Verarbeitung",
                        error=e,
                        error_type=type(e).__name__,
                        traceback=traceback.format_exc()
                    )
                # Bei Fehler fahren wir mit dem nächsten Batch fort
        
        # Erstelle das finale Ergebnis
        result_text = "\n".join(combined_text_parts).strip()
        
        if logger:
            logger.info(
                f"TRANSKRIPTION-DEBUG: Parallele Verarbeitung abgeschlossen - Ergebnis mit {len(combined_text_parts)} Segmenten und {len(combined_requests)} Requests"
            )
            logger.info(f"TRANSKRIPTION-DEBUG: Finales Ergebnis erstellt, Textlänge: {len(result_text)}")
        
        return TranscriptionResult(
            text=result_text,
            source_language=detected_language,
            segments=[]  # Keine Segmente im Output
        )