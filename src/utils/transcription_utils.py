"""
Utilities für die Transkription und Transformation von Text.
"""
from typing import Dict, Any, Optional, Union, List, cast, Protocol
from pathlib import Path
import time
from datetime import datetime
import json
import re
import os
from dataclasses import dataclass
import io

from openai import OpenAI
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage
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
    
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialisiert den WhisperTranscriber.
        
        Args:
            config: Konfiguration für den Transcriber
        """
        self.config: Dict[str, Any] = config
        self.debug_dir: Path = Path(config.get('debug_dir', './temp-processing/transform'))
        self.temp_dir: Path = Path(config.get('temp_dir', './temp-processing/audio'))
        self.model: str = config.get('model', 'gpt-4')
        self.client: OpenAI = OpenAI(api_key=config.get('openai_api_key'))
        self.batch_size: int = config.get('batch_size', 10)
        
        # Stelle sicher dass die Verzeichnisse existieren
        self.debug_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def create_llm_request(
        self,
        purpose: str,
        tokens: int,
        duration: float,
        model: Optional[str] = None
    ) -> LLMRequest:
        """
        Zentrale Methode für LLMRequest-Erstellung.
        
        Args:
            purpose: Zweck des Requests (z.B. 'transcription', 'translation')
            tokens: Anzahl der verwendeten Tokens
            duration: Dauer in Millisekunden
            model: Optional, zu verwendendes Modell (default: self.model)
            
        Returns:
            LLMRequest: Der erstellte Request
        """
        return LLMRequest(
            model=model or self.model,
            purpose=purpose,
            tokens=tokens,
            duration=int(duration)  # Konvertiere zu int für Millisekunden
        )

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
                ]
            )

            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = (time.time() - start_time) * 1000
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            message: ChatCompletionMessage = response.choices[0].message       
            translated_text: str = message.content or ""
            
            self._save_llm_interaction(
                purpose="translation",
                system_prompt=system_prompt, 
                user_prompt=user_prompt, 
                response=response, 
                logger=logger
            )

            # LLM-Nutzung tracken mit zentraler Methode
            llm_request = self.create_llm_request(
                purpose="translation",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration
            )
            
            result = TranslationResult(
                text=translated_text,
                source_language=source_language,
                target_language=target_language,
                requests=[llm_request]
            )

            if logger:
                logger.info("Übersetzung abgeschlossen",
                    tokens=llm_request.tokens,
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

            # System-Prompt definieren
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
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = (time.time() - start_time) * 1000
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            summary: str = response.choices[0].message.content or ""
            summary = summary.strip()

            self._save_llm_interaction(
                purpose="summarization",
                system_prompt=system_prompt, 
                user_prompt=user_prompt, 
                response=response, 
                logger=logger
            )

            # LLM-Nutzung tracken mit zentraler Methode
            llm_request = self.create_llm_request(
                purpose="summarization",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration
            )
            
            result = TransformationResult(
                text=summary,
                target_language=target_language,
                requests=[llm_request]
            )

            if logger:
                logger.info("Zusammenfassung abgeschlossen",
                    tokens=llm_request.tokens,
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
                f"Provide all answers in the target language ISO 639-1 code:{target_language}. "
                f"IMPORTANT: Your response must be a valid JSON object where each key corresponds to a template variable."
            )
            
            # Extrahiere die Feldnamen und Beschreibungen
            field_descriptions = {
                name: field.description 
                for name, field in field_definitions.fields.items()
            }
            
            user_prompt: str = (
                f"Analyze the following text and extract the information as a JSON object:\n\n"
                f"TEXT:\n{text}\n\n"
                f"CONTEXT:\n{context_str}\n\n"
                f"REQUIRED FIELDS:\n"
                f"{json.dumps(field_descriptions, indent=2, ensure_ascii=False)}\n\n"
                f"INSTRUCTIONS:\n"
                f"1. Extract all required information from the text\n"
                f"2. Return a single JSON object where each key matches a field name\n"
                f"3. Provide all values in language: {target_language}\n"
                f"4. Ensure the response is valid JSON\n"
                f"5. Do not include any text outside the JSON object"
            )

            # 5. GPT-4 Anfrage senden
            if logger:
                logger.info("Sende Anfrage an GPT-4")

            # Zeitmessung starten
            start_time: float = time.time()

            # OpenAI Client-Aufruf
            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )

            # Zeitmessung beenden
            duration = (time.time() - start_time) * 1000

            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            # LLM-Nutzung tracken mit zentraler Methode
            llm_request = self.create_llm_request(
                purpose="template_transform",
                tokens=response.usage.total_tokens if response.usage else 0,
                duration=duration
            )

            # Debug-Informationen speichern
            self._save_llm_interaction(
                purpose="template_transform",
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                logger=logger,
                template=template,
                field_definitions=field_definitions
            )

            # Strukturierte Daten extrahieren
            result_json = json.loads(response.choices[0].message.content or "{}")

            # Template mit extrahierten Daten füllen
            for field_name, field_value in result_json.items():
                pattern: str = r'\{\{' + field_name + r'\|[^}]+\}\}'
                value: str = str(field_value) if field_value is not None else ""
                template_content = re.sub(pattern, value, template_content)

            if logger:
                logger.info("Template-Transformation abgeschlossen",
                    tokens=llm_request.tokens,
                    duration_ms=duration)

            # Response erstellen
            return TransformationResult(
                text=template_content,
                target_language=target_language,
                requests=[llm_request],
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

    def transcribe_segment(
        self,
        file_path: Union[Path, bytes],
        logger: Optional[ProcessingLogger] = None,
        segment_id: Optional[int] = None,
        segment_title: Optional[str] = None,
        source_language: str = "de",
        target_language: str = "de"
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
        try:
            start_time: float = time.time()
            
            if logger:
                logger.info(
                    "Starte Transkription von Segment",
                    segment_id=segment_id,
                    segment_title=segment_title,
                    file_path=str(file_path) if isinstance(file_path, Path) else "bytes"
                )

            # Initialisiere response
            response: Optional[TranscriptionVerbose] = None

            # Sende an Whisper API
            if isinstance(file_path, Path):
                with open(file_path, 'rb') as audio_file:
                    try:
                        response = self.client.audio.transcriptions.create(
                            model="whisper-1",
                            file=("audio.mp3", audio_file, "audio/mpeg"),
                            response_format="verbose_json"
                        )
                    except Exception as api_error:
                        self._handle_api_error(api_error)
            else:
                # Wenn file_path bereits bytes ist
                try:
                    response = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=("audio.mp3", io.BytesIO(file_path), "audio/mpeg"),
                        response_format="verbose_json"
                    )
                except Exception as api_error:
                    self._handle_api_error(api_error)
            
            if not response or not hasattr(response, 'text'):
                raise ValueError("Ungültige API-Antwort: Kein Text gefunden")
            
            # Zeitmessung beenden
            duration = (time.time() - start_time) * 1000
            
            # Schätze die Token basierend auf der Textlänge
            estimated_tokens: float = len(response.text.split()) * 1.5 if hasattr(response, 'text') else 0
            tokens = getattr(response, 'usage', {}).get('total_tokens', int(estimated_tokens))
            
            # LLM-Nutzung tracken mit zentraler Methode
            whisper_request = self.create_llm_request(
                purpose="transcription",
                tokens=tokens,
                duration=duration,
                model="whisper-1"  # Explizit Whisper-Modell angeben
            )
            
            if source_language == "auto":
                # Konvertiere Whisper Sprachcode in ISO 639-1
                source_language = self._convert_to_iso_code(response.language)

            # Erstelle ein einzelnes Segment für das gesamte Audio-Segment
            segment = TranscriptionSegment(
                text=response.text,
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
                    text_length=len(response.text)
                )
            
            return TranscriptionResult(
                text=response.text,
                source_language=source_language,
                segments=[segment],  # Nur ein Segment pro Audio-Datei
                requests=[whisper_request]
            )
            
        except Exception as e:
            if logger:
                logger.error(
                    "Fehler bei der Transkription von Segment",
                    error=e,
                    error_type=type(e).__name__,
                    segment_id=segment_id,
                    segment_title=segment_title
                )
            if isinstance(e, ProcessingError):
                raise
            raise ProcessingError(f"Transkription fehlgeschlagen: {str(e)}")

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
        logger: Optional[ProcessingLogger] = None
    ) -> TranscriptionResult:
        """Transkribiert mehrere Audio-Segmente.
        
        Args:
            segments: Liste von AudioSegmentInfo oder Chapter Objekten
            source_language: Quellsprache (ISO 639-1)
            target_language: Zielsprache (ISO 639-1)
            logger: Optional, Logger für Debug-Ausgaben
            
        Returns:
            TranscriptionResult: Das Transkriptionsergebnis
        """
        combined_text_parts: List[str] = []
        combined_requests: List[LLMRequest] = []
        total_duration: int = 0
        total_tokens: int = 0

        # Extrahiere alle Segmente aus der Kapitelstruktur
        all_segments: List[AudioSegmentInfo] = []
        if segments and isinstance(next(iter(segments)), Chapter):
            chapters: List[Chapter] = cast(List[Chapter], segments)
            for chapter in chapters:
                if chapter.title and chapter.title.strip():
                    combined_text_parts.append(f"\n## {chapter.title}\n")
                all_segments.extend(chapter.segments)
        else:
            all_segments = cast(List[AudioSegmentInfo], segments)

        # Verarbeite jedes Segment
        for segment in all_segments:
            try:
                # Transkribiere das Segment
                result: TranscriptionResult = self.transcribe_segment(
                    file_path=segment.get_audio_data(),  # Verwende get_audio_data() statt direktem Zugriff
                    segment_id=len(combined_requests),  # Verwende Request-Count als ID
                    segment_title=segment.title,
                    source_language=source_language,
                    target_language=target_language,
                    logger=logger
                )
                
                if result.source_language != source_language:
                    source_language = result.source_language

                if result.text.strip():
                    combined_text_parts.append(result.text)
                
                # Sammle LLM Informationen
                if result.requests:
                    combined_requests.extend(result.requests)
                    for req in result.requests:
                        if req.duration:
                            total_duration += int(req.duration)  # Konvertiere zu int
                        if req.tokens:
                            total_tokens += req.tokens

            except Exception as e:
                if logger:
                    logger.error(
                        "Fehler bei der Transkription von Segment",
                        error=e,
                        segment_title=segment.title
                    )
                continue

        # Erstelle das finale Ergebnis mit allen einzelnen Requests
        return TranscriptionResult(
            text="\n".join(combined_text_parts).strip(),
            source_language=source_language,
            segments=[],  # Keine Segmente im Output
            requests=combined_requests  # Alle einzelnen Requests
        )