"""
Utilities für die Transkription und Transformation von Text.
"""
from typing import Dict, Any, Optional, Union, List, cast, Sequence, Tuple, Protocol
from pathlib import Path
import time
from datetime import datetime
import json
import re
import os
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
import gc
import io
import uuid

from openai import OpenAI
from openai.types.audio.transcription_verbose import TranscriptionVerbose
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage
from pydantic import Field
from pydub import AudioSegment

from src.utils.logger import ProcessingLogger
from src.core.models.transformer import (
    TranslationResult, TransformationResult, TemplateField, TemplateFields
)
from src.core.models.llm import LLMRequest
from src.core.models.enums import OutputFormat
from src.core.models.audio import (
    AudioSegmentInfo, Chapter, TranscriptionResult, TranscriptionSegment
)
from src.utils.openai_utils import get_structured_gpt
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

    def transcribe_segment(
        self,
        file_path: Path,
        logger: Optional[ProcessingLogger] = None,
        segment_id: Optional[int] = None,
        segment_title: Optional[str] = None,
        source_language: str = "de",
        target_language: str = "de"
    ) -> TranscriptionResult:
        """Transkribiert ein einzelnes Audio-Segment.
        
        Args:
            file_path: Pfad zur Audio-Datei
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
                    file_path=str(file_path)
                )

            # Sende an Whisper API
            with open(file_path, 'rb') as audio_file:
                try:
                    response: TranscriptionVerbose = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=("audio.mp3", audio_file, "audio/mpeg"),
                        response_format="verbose_json"
                    )
                    
                except Exception as api_error:
                    # Behandle spezifische API-Fehler
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
            
            if not hasattr(response, 'text'):
                raise ValueError("Ungültige API-Antwort: Kein Text gefunden")
            
            # Zeitmessung beenden und Dauer in Millisekunden berechnen
            duration = int((time.time() - start_time) * 1000)
            
            # Erstelle ein LLModel für die Whisper-Nutzung
            # Schätze die Token basierend auf der Textlänge wenn usage nicht verfügbar
            estimated_tokens: float = len(response.text.split()) * 1.5 if hasattr(response, 'text') else 0
            tokens = getattr(response, 'usage', {}).get('total_tokens', int(estimated_tokens))
            
            whisper_model = LLMRequest(
                model="whisper-1",
                purpose="transcription",
                duration=duration,
                tokens=tokens
            )
            
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
                requests=[whisper_model]
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

    async def transcribe_segments(
        self,
        *,  # Erzwinge Keyword-Argumente
        segments: Union[Sequence[AudioSegmentInfo], Sequence[Chapter]],
        source_language: str,
        target_language: str,
        logger: Optional[ProcessingLogger] = None
    ) -> TranscriptionResult:
        """Transkribiert mehrere Audio-Segmente parallel."""
        try:
            # 1. Extrahiere alle Segmente und erstelle Mapping
            all_segments: List[AudioSegmentInfo] = []
            segment_to_chapter: Dict[int, str] = {}
            
            # Verarbeite Kapitel wenn vorhanden
            if isinstance(next(iter(segments)), Chapter):
                chapters = cast(Sequence[Chapter], segments)
                current_idx = 0
                for chapter in chapters:
                    # Nur Kapitel mit nicht-leerem Titel verwenden
                    chapter_title = chapter.title.strip() if chapter.title else ""
                    for segment in chapter.segments:
                        all_segments.append(segment)
                        segment_to_chapter[current_idx] = chapter_title
                        current_idx += 1
                        
                if logger:
                    logger.info(f"Verarbeite {len(all_segments)} Segmente aus {len(chapters)} Kapiteln")
            else:
                all_segments = list(cast(Sequence[AudioSegmentInfo], segments))
                if logger:
                    logger.info(f"Verarbeite {len(all_segments)} Segmente")

            # 2. Verarbeite Segmente parallel
            results: List[TranscriptionResult] = []
            with ThreadPoolExecutor(max_workers=self.batch_size) as executor:
                futures: List[Future[TranscriptionResult]] = []
                
                for i, segment in enumerate(all_segments):
                    if logger:
                        logger.debug(f"Erstelle Future für Segment {i}: {segment.file_path}")
                    
                    future = executor.submit(
                        self.transcribe_segment,
                        segment.file_path,
                        logger,
                        i,
                        segment_to_chapter.get(i),
                        source_language,
                        target_language
                    )
                    futures.append(future)

                for future in as_completed(futures):
                    try:
                        result = future.result()
                        if logger:
                            logger.debug(f"Segment {len(results)} fertig verarbeitet")
                        results.append(result)
                    except Exception as e:
                        if logger:
                            logger.error("Fehler bei der Transkription eines Segments", error=e)
                        raise

            # Sortiere Ergebnisse nach Segment-ID
            results.sort(key=lambda x: x.segments[0].segment_id if x.segments else 0)

            # 3. Kombiniere die Ergebnisse
            combined_text_parts: List[str] = []
            combined_segments: List[TranscriptionSegment] = []
            combined_requests: List[LLMRequest] = []

            # Unterscheide zwischen Kapitel- und Nicht-Kapitel-Verarbeitung
            if segment_to_chapter:  # Wenn Kapitel vorhanden
                # Organisiere Ergebnisse nach Kapiteln
                chapter_texts: Dict[str, List[str]] = {}
                current_chapter_id = None
                
                for result in results:
                    for segment in result.segments:
                        chapter_id = segment_to_chapter.get(segment.segment_id, "")
                        if chapter_id != current_chapter_id:
                            current_chapter_id = chapter_id
                            if chapter_id and chapter_id not in chapter_texts:  # Nur wenn chapter_id nicht leer
                                chapter_texts[chapter_id] = []
                                combined_text_parts.append(f"\n\n## {chapter_id}\n\n")
                        
                        # Füge den Text zum aktuellen Kapitel hinzu wenn ein Kapitel existiert
                        if chapter_id:
                            chapter_texts[chapter_id].append(segment.text)
                        # Füge den Text immer zu combined_text_parts hinzu
                        combined_text_parts.append(segment.text)
                        combined_segments.append(segment)
                        
                    # Füge LLM-Requests hinzu
                    if result.requests:
                        combined_requests.extend(result.requests)
            else:
                # Verarbeite alle Segmente als einen durchgehenden Text
                for result in results:
                    if result.text:
                        combined_text_parts.append(result.text)
                    if result.segments:
                        combined_segments.extend(result.segments)
                    if result.requests:
                        combined_requests.extend(result.requests)

            # Erstelle finales Ergebnis
            complete_text = " ".join(combined_text_parts).strip()
            
            result = TranscriptionResult(
                text=complete_text,
                source_language=source_language,
                segments=combined_segments,
                requests=combined_requests
            )
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Transkription", error=e)
            raise
        finally:
            gc.collect()