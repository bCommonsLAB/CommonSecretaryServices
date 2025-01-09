from src.utils.types import (
    llModel,
    TranscriptionSegment,
    TranscriptionResult,
    TranslationResult,
    AudioSegmentInfo,
    ChapterInfo
)

from src.utils.logger import ProcessingLogger
import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Type, Tuple, Union
import json
import time
import asyncio
from openai import OpenAI
import tiktoken
import re
from pydub import AudioSegment
import wave
from pydantic import BaseModel, Field, ValidationError, create_model
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import math
import gc  # Import für Garbage Collection
from src.core.config import Config
from src.core.config_keys import ConfigKeys

class WhisperTranscriber:
    """Utility-Klasse für die Transkription mit OpenAI Whisper.
    
    Diese Klasse handhabt die Kommunikation mit der OpenAI API für Audiotranskriptionen.
    """
    
    # Mapping von Whisper Sprachbezeichnungen zu ISO-Codes
    LANGUAGE_MAP = {
        'english': 'en',
        'german': 'de',
        'french': 'fr',
        'spanish': 'es',
        'italian': 'it',
        'japanese': 'ja',
        'chinese': 'zh',
        'korean': 'ko',
        'russian': 'ru',
        'portuguese': 'pt',
        'turkish': 'tr',
        'polish': 'pl',
        'arabic': 'ar',
        'dutch': 'nl',
        'hindi': 'hi',
        'swedish': 'sv',
        'indonesian': 'id',
        'vietnamese': 'vi',
        'thai': 'th',
        'hebrew': 'he'
        # Weitere Sprachen können hier hinzugefügt werden
    }
    
    # Umgekehrtes Mapping von ISO-Codes zu vollen Sprachnamen (für Übersetzungen)
    ISO_TO_INSTRUCTION = {
        "en": "Can you summarize this text as compactly as possible in English?",
        "de": "Kannst du diesen Text möglichst kompakt in Deutsch zusammenfassen?",
        "fr": "Peux-tu résumer ce texte aussi compactement que possible en français?",
        "es": "¿Puedes resumir este texto de la manera más compacta posible en español?",
        "it": "Puoi riassumere questo testo nel modo più compatto possibile in italiano?",
        "ja": "このテキストをできるだけ簡潔に日本語で要約できますか？",
        "zh": "你能尽可能简洁地用中文总结这段文本吗？",
        "ko": "이 텍스트를 가능한 한 간결하게 한국어로 요약해줄 수 있나요?",
        "ru": "Можешь подвести итог этому тексту как можно более сжато на русском?",
        "pt": "Você pode resumir este texto o mais compactamente possível em português?",
        "tr": "Bu metni mümkün olduğunca kompakt bir şekilde Türkçe olarak özetleyebilir misin?",
        "pl": "Czy możesz podsumować ten tekst w jak najbardziej zwięzłej formie po polsku?",
        "ar": "هل يمكنك تلخيص هذا النص بأكبر قدر ممكن من الإيجاز باللغة العربية؟",
        "nl": "Kun je deze tekst zo compact mogelijk samenvatten in het Nederlands?",
        "hi": "क्या आप इस पाठ का संक्षेप में हिंदी में خलवा बना सकते हैं?",
        "sv": "Kan du sammanfatta denna text så kompakt som möjligt på svenska?",
        "id": "Bisakah Anda merangkum teks ini se-ringkas mungkin dalam bahasa Indonesia?",
        "vi": "Bạn có thể tóm tắt văn bản này một cách ngắn gọn nhất có thể bằng tiếng Việt không?",
        "th": "คุณสามารถสรุปข้อความนี้ให้กระชับที่สุดเป็นภาษาไทยได้ไหม?",
        "he": "האם תוכל לסכם את הטקסט הזה ככל האפשר בעברית?"
    }

    ISO_TO_FULL_NAME = {
        'en': 'English',
        'de': 'German',
        'fr': 'French',
        'es': 'Spanish',
        'it': 'Italian',
        'ja': 'Japanese',
        'zh': 'Chinese',
        'ko': 'Korean',
        'ru': 'Russian',
        'pt': 'Portuguese',
        'tr': 'Turkish',
        'pl': 'Polish',
        'ar': 'Arabic',
        'nl': 'Dutch',
        'hi': 'Hindi',
        'sv': 'Swedish',
        'id': 'Indonesian',
        'vi': 'Vietnamese',
        'th': 'Thai',
        'he': 'Hebrew'
    }
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialisiert den WhisperTranscriber.
        
        Args:
            config (Dict[str, Any], optional): Konfigurationsobjekt mit Prozessor-Einstellungen
        """
        config_keys = ConfigKeys()
        self.client = OpenAI(api_key=config_keys.openai_api_key)
        self.config = config or {}
        
        # Konfigurationswerte laden
        audio_config = self.config.get('processors', {}).get('audio', {})
        self.temp_dir = audio_config.get('temp_dir', "temp-processing/audio")
        self.batch_size = audio_config.get('batch_size', 3)  # Default: 3 parallele Verarbeitungen

        if not self.batch_size:
            raise ValueError("batch_size muss in der Konfiguration angegeben werden")

        # Erstelle temp-processing/audio Verzeichnis
        os.makedirs(self.temp_dir, exist_ok=True)
        
    def _convert_to_iso_code(self, whisper_language: str) -> str:
        """Konvertiert Whisper Sprachbezeichnung in ISO-Code.
        
        Args:
            whisper_language (str): Sprachbezeichnung von Whisper (z.B. 'english')
            
        Returns:
            str: ISO-639-1 Sprachcode (z.B. 'en') oder None wenn nicht gefunden
        """
        if not whisper_language:
            return None
            
        # Lowercase für case-insensitive Vergleich
        whisper_language = whisper_language.lower()
        return self.LANGUAGE_MAP.get(whisper_language)
        
    def translate_text(self, text: str, source_language: str, target_language: str, logger: ProcessingLogger = None, 
                     summarize: bool = False, max_words: int = None) -> TranslationResult:
        """Übersetzt den Text in die Zielsprache mit GPT-4.
        
        Args:
            text (str): Zu übersetzender Text
            source_language (str): Quellsprache (ISO 639-1 code)
            target_language (str): Zielsprache (ISO 639-1 code)
            logger (ProcessingLogger): Logger-Instanz für Logging
            summarize (bool): Ob eine Zusammenfassung erstellt werden soll
            max_words (int, optional): Maximale Anzahl Wörter für die Zusammenfassung

        Returns:
            TranslationResult: Das validierte Übersetzungsergebnis
        """
        try:
            target = self.ISO_TO_FULL_NAME.get(target_language, target_language)
            llm_model = "gpt-4o-mini"

            if summarize:
                base_instruction = self.ISO_TO_INSTRUCTION.get(target_language, "Can you rephrase this text in a more concise way?")
                if max_words:
                    instruction = f"{base_instruction} Use at most {max_words} words."
                else:
                    instruction = base_instruction
            else:
                instruction = f"Please translate this text to {target}:"
            
            if logger:
                if summarize:
                    logger.info(f"Starte Zusammenfassung in {target_language}" + (f" (max {max_words} Wörter)" if max_words else ""))
                else:
                    logger.info(f"Starte Übersetzung von {source_language} nach {target_language}")

            system_prompt = "You are a precise translator and summarizer."
            user_prompt = f"{instruction}\n\n{text}"

            response = self.client.chat.completions.create(
                model=llm_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            translated_text = response.choices[0].message.content.strip()
            
            llm_usage = llModel(
                model=llm_model,
                duration=0.0,
                token_count=response.usage.total_tokens
            )
            
            result = TranslationResult(
                text=translated_text,
                source_language=source_language,
                target_language=target_language,
                llms=[llm_usage]
            )

            # Speichere die LLM Interaktion
            self._save_llm_interaction(
                template=None,  # Kein Template für einfache Übersetzungen
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response=response,
                logger=logger
            )
            
            if logger:
                logger.info("Übersetzung abgeschlossen",
                    token_count=llm_usage.token_count)
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Übersetzung", error=str(e))
            raise

    def _read_template_file(self, template: str, logger: ProcessingLogger = None) -> str:
        """Liest den Inhalt einer Template-Datei."""
        template_dir = 'templates'
        template_path = os.path.join(template_dir, f"{template}.md")
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            if logger:
                logger.error("Template konnte nicht gelesen werden",
                    error=str(e),
                    template_path=template_path)
            raise ValueError(f"Template '{template}' konnte nicht gelesen werden: {str(e)}")

    def _replace_context_variables(self, template_content: str, context: Dict[str, Any], text: str, logger: ProcessingLogger = None) -> str:
        """Ersetzt einfache Kontext-Variablen im Template."""
        if not isinstance(context, dict):
            context = {}
        
        # Füge text als spezielle Variable hinzu
        if text:
            # Ersetze {{text}} mit dem tatsächlichen Text
            template_content = re.sub(r'\{\{text\}\}', text, template_content)
        
        # Finde alle einfachen Template-Variablen (ohne Description)
        simple_variables = re.findall(r'\{\{([a-zA-Z][a-zA-Z0-9_]*?)\}\}', template_content)
        
        for key, value in context.items():
            if value is not None and key in simple_variables:
                pattern = r'\{\{' + re.escape(str(key)) + r'\}\}'
                str_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                template_content = re.sub(pattern, str_value, template_content)

        return template_content

    def _extract_structured_variables(self, template_content: str, logger: ProcessingLogger = None) -> Dict[str, Any]:
        """Extrahiert strukturierte Variablen aus dem Template."""
        pattern = r'\{\{([a-zA-Z][a-zA-Z0-9_]*)\|([^}]+)\}\}'
        matches = re.finditer(pattern, template_content)
        
        seen_vars = set()
        field_definitions = {}
        
        for match in matches:
            var_name = match.group(1).strip()
            if var_name in seen_vars:
                continue
                
            seen_vars.add(var_name)
            description = match.group(2).strip()
            
            field_definitions[var_name] = (
                Optional[str], 
                Field(
                    description=description,
                    max_length=5000,
                    default=None
                )
            )
                    
        return field_definitions

    def _create_gpt_prompts(self, text: str, context: Dict[str, Any], target_language: str) -> Tuple[str, str]:
        """Erstellt System- und User-Prompts für GPT-4.
        
        Args:
            text (str): Zu analysierender Text
            context (Dict[str, Any]): Kontext-Informationen
            target_language (str): Zielsprache
            
        Returns:
            Tuple[str, str]: (System-Prompt, User-Prompt)
        """
        target = self.ISO_TO_FULL_NAME.get(target_language, target_language)
        context_str = (
            json.dumps(context, indent=2, ensure_ascii=False)
            if isinstance(context, dict)
            else "Kein zusätzlicher Kontext."
        )
        
        system_prompt = (
            f"You are a precise assistant for text analysis and data extraction. "
            f"Analyze the text and extract the requested information. "
            f"Provide all answers in {target}."
        )
        
        user_prompt = (
            f"Analyze the following text and extract the information:\n\n"
            f"TEXT:\n{text}\n\n"
            f"CONTEXT:\n{context_str}\n\n"
            f"Extract the information precisely and in the target language {target}."
        )
        
        return system_prompt, user_prompt

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """
        Bereinigt einen String für die Verwendung als Dateinamen.
        
        Args:
            filename (str): Der zu bereinigende String
            
        Returns:
            str: Der bereinigte String
        """
        # Entferne unerlaubte Zeichen
        safe_name = re.sub(r'[^\w\s-]', '', filename)
        # Ersetze Whitespace und mehrfache Bindestriche durch einen einzelnen Bindestrich
        safe_name = re.sub(r'[-\s]+', '-', safe_name).strip('-')
        return safe_name

    def saveDebugOutput(self, text: str, template: str = None, result_dict: Dict[str, Any] = None, context: Dict[str, Any] = None, logger: ProcessingLogger = None) -> None:
        """Speichert Debug-Ausgaben für die Transformation.
        
        Args:
            text (str): Der zu speichernde Text
            debug_dir (Path): Verzeichnis für Debug-Ausgaben
            template (str): Name des verwendeten Templates
            result_dict (Dict[str, Any], optional): Zusätzliche Ergebnisdaten
            context (Dict[str, Any], optional): Kontext-Informationen
            logger (ProcessingLogger, optional): Logger-Instanz
        """
        try:
            # Erstelle debug_dir wenn es nicht existiert

            # Debug-Verzeichnis definieren und erstellen
            debug_dir = Path('./temp-processing/transform')
            if context and 'uploader' in context:
                debug_dir = Path(f'{debug_dir}/{context["uploader"]}')
            debug_dir.mkdir(parents=True, exist_ok=True)
            
            # Erstelle Basis-Dateinamen
            filename_parts = []
            
            # Füge Datum hinzu
            if context and 'upload_date' in context:
                try:
                    date_obj = datetime.strptime(context['upload_date'], '%Y%m%d')
                    timestamp = date_obj.strftime('%Y-%m-%d')
                except ValueError:
                    timestamp = datetime.now().strftime("%Y-%m-%d")
            else:
                timestamp = datetime.now().strftime("%Y-%m-%d")
            filename_parts.append(timestamp)

            # Füge Template-Namen hinzu
            if template:
                filename_parts.append(template)

            # Füge Titel hinzu
            if context and 'title' in context:
                safe_title = self._sanitize_filename(context['title'])
                if safe_title:  # Nur hinzufügen wenn nicht leer
                    filename_parts.append(safe_title)
            
            # Erstelle finalen Dateinamen
            base_filename = "_".join(filename_parts)
            
            # Speichere transformierten Text
            text_path = debug_dir / f"{base_filename}.md"
            text_path.write_text(text, encoding='utf-8')
            
            # Speichere JSON-Ergebnis wenn vorhanden
            if result_dict:
                json_path = debug_dir / f"{base_filename}.json"
                with json_path.open('w', encoding='utf-8') as f:
                    json.dump(result_dict, f, indent=2, ensure_ascii=False)
            
            if logger:
                logger.info("Debug-Ausgabe gespeichert",
                          text_file=str(text_path),
                          json_file=str(json_path) if result_dict else None)
                          
        except Exception as e:
            if logger:
                logger.error("Fehler beim Speichern der Debug-Ausgabe",
                           error=str(e),
                           debug_dir=str(debug_dir))

    def transform_by_template(self, text: str, target_language: str, template: str, context: Dict[str, Any] = None, logger: ProcessingLogger = None) -> Tuple[str, TranslationResult]:
        """Transformiert Text basierend auf einem Template mit GPT-4.
        
        Args:
            text (str): Zu transformierender Text
            target_language (str): Zielsprache (ISO 639-1 code)
            template (str): Name des Templates (ohne .md Endung)
            context (Dict[str, Any]): Dictionary mit Kontext-Informationen für Template-Variablen
            logger (ProcessingLogger): Logger-Instanz für Logging
            
        Returns:
            Tuple[str, TranslationResult]: (Transformierter Template-Inhalt, Validiertes Übersetzungsergebnis)
        """
        try:
            if logger:
                logger.info(f"Starte Template-Transformation: {template}")

            # 1. Template-Datei lesen
            template_content = self._read_template_file(template, logger)

            # 2. Einfache Kontext-Variablen ersetzen
            template_content = self._replace_context_variables(template_content, context, text, logger)

            # 3. Strukturierte Variablen extrahieren und Model erstellen
            field_definitions = self._extract_structured_variables(template_content, logger)
            
            if not field_definitions:
                # Wenn keine strukturierten Variablen gefunden wurden, geben wir nur den Template-Inhalt zurück
                return template_content, None

            # 4. Pydantic Model erstellen
            DynamicTemplateModel = create_model(
                f'Template{template.capitalize()}Model',
                **field_definitions
            )

            # 5. GPT-4 Prompts erstellen
            system_prompt, user_prompt = self._create_gpt_prompts(text, context, target_language)

            # 6. GPT-4 Anfrage senden
            if logger:
                logger.info("Sende Anfrage an GPT-4")                
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                functions=[{
                    "name": "extract_template_info",
                    "description": "Extrahiert Informationen gemäß Template-Schema",
                    "parameters": DynamicTemplateModel.model_json_schema()
                }],
                function_call={"name": "extract_template_info"}
            )

            # 7. LLM Interaktion speichern
            self._save_llm_interaction(template, system_prompt, user_prompt, response, logger, field_definitions)

            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            # 8. GPT-4 Antwort extrahieren und validieren
            result_json = response.choices[0].message.function_call.arguments
            result = DynamicTemplateModel.model_validate_json(result_json)

            # 9. Strukturierte Variablen ersetzen
            for field_name, field_value in result.model_dump().items():
                pattern = r'\{\{' + field_name + r'\|[^}]+\}\}'
                value = str(field_value) if field_value is not None else ""
                template_content = re.sub(pattern, value, template_content)

            # 10. Erstelle ein llModel für die GPT-4 Nutzung
            llm_usage = llModel(
                model="gpt-4o-mini",
                duration=0.0,  # Diese Information haben wir aktuell nicht
                token_count=response.usage.total_tokens if hasattr(response, 'usage') else 0
            )

            # 11. Erstelle das TranslationResult
            translation_result = TranslationResult(
                text=template_content,
                source_language='de',  # Wir gehen davon aus, dass der Input-Text Deutsch ist
                target_language=target_language,
                llms=[llm_usage]
            )

            if logger:
                logger.info("Template-Transformation abgeschlossen",
                    token_count=llm_usage.token_count)
            
            return template_content, translation_result
            
        except Exception as e:
            if logger:
                logger.error("Template-Verarbeitung fehlgeschlagen", error=str(e))
            raise

    def transcribe_segment(self, audio_segment: bytes, segment_path: Path = None, logger: ProcessingLogger = None, 
                         segment_id: int = None, segment_title: str = None) -> TranscriptionResult:
        """Transkribiert ein einzelnes Audio-Segment und übersetzt es optional direkt in die Zielsprache.
        
        Args:
            audio_segment (bytes): Die Audio-Daten als Bytes
            segment_path (Path, optional): Pfad zur Audio-Datei
            logger (ProcessingLogger, optional): Logger-Instanz für Logging
            target_language (str, optional): ISO-Code der Zielsprache für direkte Übersetzung
            segment_id (int, optional): ID des Segments für die Sortierung
            segment_title (str, optional): Titel des Segments (z.B. Kapitel-Titel)
            
        Returns:
            TranscriptionResult: Das validierte Transkriptionsergebnis
        """
        try:
            if logger:
                logger.info(f"Starte Transkription von Segment {segment_id}", 
                    segment_id=segment_id,
                    segment_title=segment_title,
                    file_name=segment_path.name if segment_path else "unknown")
            
            # Wenn kein segment_path angegeben, erstelle temporären Pfad
            if segment_path is None:
                temp_path = os.path.join(self.temp_dir, f"single_segment.mp3")
            else:
                temp_path = str(segment_path)

            with open(temp_path, 'wb') as temp_audio:
                temp_audio.write(audio_segment)

            if logger:
                logger.info(f"Sende Anfrage an Whisper API für Segment {segment_id}",
                    segment_id=segment_id)
                
            with open(temp_path, 'rb') as audio_file:
                # Wenn eine Zielsprache angegeben ist und es nicht Englisch ist,
                # übersetzen wir zuerst ins Englische und dann in die Zielsprache
                api_params = {
                    "model": "whisper-1",
                    "file": audio_file,
                    "response_format": "verbose_json"
                }
                response = self.client.audio.transcriptions.create(**api_params)

            transcribed_text = response.text if hasattr(response, 'text') else str(response)
            detected_language = response.language if hasattr(response, 'language') else None
            detected_language_iso = self._convert_to_iso_code(detected_language)
            translated = False

            whisper_model = llModel(
                model="whisper-1",
                duration=response.duration,
                token_count=len(str(response).split())
            )

            # Erstelle ein TranscriptionSegment
            if segment_id is None:
                raise ValueError("segment_id darf nicht None sein")
                
            segment = TranscriptionSegment(
                text=transcribed_text,
                segment_id=segment_id,
                title=segment_title  # Füge den Segment-Titel hinzu
            )

            # Erstelle das TranscriptionResult
            result = TranscriptionResult(
                text=transcribed_text,
                detected_language=detected_language_iso,
                segments=[segment],
                llms=[whisper_model] 
            )
            
            # Speichere Transkription neben der Audio-Datei
            if segment_path:
                transcript_path = segment_path.with_suffix('.txt')
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    json.dump(result.model_dump(), f, indent=2)
            
            if logger:
                logger.info(f"Transkription von Segment {segment_id} abgeschlossen",
                    segment_id=segment_id,
                    segment_title=segment_title)
            
            return result

        except Exception as e:
            if logger:
                logger.error(f"Fehler bei der Transkription von Segment {segment_id}",
                    segment_id=segment_id,
                    segment_title=segment_title,
                    error=str(e))
            raise

    def _extract_segments_from_chapters(self, segments_or_chapters: Union[List[AudioSegmentInfo], List[ChapterInfo]], logger: ProcessingLogger = None) -> Tuple[List[AudioSegmentInfo], Dict[int, str]]:
        """Extrahiert alle Segmente aus der Kapitelstruktur und erstellt ein Mapping von Segment-IDs zu Kapitel-Titeln.
        
        Args:
            segments_or_chapters: Entweder eine Liste von AudioSegmentInfo oder eine Liste von ChapterInfo
            logger: Logger-Instanz
            
        Returns:
            Tuple[List[AudioSegmentInfo], Dict[int, str]]: (Alle Segmente, Mapping von Segment-ID zu Kapitel-Titel)
        """
        if segments_or_chapters and isinstance(segments_or_chapters[0], ChapterInfo):
            all_segments = []
            segment_to_chapter = {}  # Mapping von Segment-ID zu Kapitel-Titel
            current_idx = 0
            
            for chapter in segments_or_chapters:
                for segment in chapter.segments:
                    all_segments.append(segment)
                    segment_to_chapter[current_idx] = chapter.title
                    current_idx += 1
                    
            if logger:
                logger.info(f"Verarbeite {len(all_segments)} Segmente aus {len(segments_or_chapters)} Kapiteln")
        else:
            all_segments = segments_or_chapters
            segment_to_chapter = {}
            if logger:
                logger.info(f"Verarbeite {len(all_segments)} Segmente")
                
        return all_segments, segment_to_chapter

    def _process_segments_parallel(self, all_segments: List[AudioSegmentInfo], segment_to_chapter: Dict[int, str], 
                                 logger: ProcessingLogger = None, target_language: str = None) -> List[TranscriptionResult]:
        """Verarbeitet alle Segmente parallel mit dem ThreadPoolExecutor.
        
        Args:
            all_segments: Liste aller zu verarbeitenden Segmente
            segment_to_chapter: Mapping von Segment-ID zu Kapitel-Titel
            logger: Logger-Instanz
            target_language: Zielsprache für die Übersetzung
            
        Returns:
            List[TranscriptionResult]: Liste der Transkriptionsergebnisse
        """
        results = []
        with ThreadPoolExecutor(max_workers=self.batch_size) as executor:
            futures = []
            for idx, segment_info in enumerate(all_segments):
                if logger:
                    logger.debug(f"Erstelle Future für Segment {idx}: {segment_info.file_path.name}")
                
                try:
                    binary_data = segment_info.file_path.read_bytes()
                    future = executor.submit(
                        self.transcribe_segment, 
                        binary_data, 
                        segment_info.file_path, 
                        logger, 
                        idx,
                        segment_to_chapter.get(idx)
                    )
                    futures.append(future)
                finally:
                    del binary_data
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if logger:
                        logger.debug(f"Segment {len(results)} fertig verarbeitet")
                    results.append(result)
                except Exception as e:
                    if logger:
                        logger.error("Fehler bei der Transkription eines Segments", error=str(e))
                    raise
                    
        return results

    def _organize_results_by_chapter(self, results: List[TranscriptionResult], segment_to_chapter: Dict[int, str]) -> Tuple[Dict[str, List[str]], Dict[str, List[TranscriptionSegment]], Dict[str, str], Dict[str, int]]:
        """Organisiert die Transkriptionsergebnisse nach Kapiteln.
        
        Args:
            results: Liste der Transkriptionsergebnisse
            segment_to_chapter: Mapping von Segment-ID zu Kapitel-Titel
            
        Returns:
            Tuple[Dict, Dict, Dict, Dict]: (Kapitel-Texte, Kapitel-Segmente, Kapitel-Titel, Kapitel-Ordnung)
        """
        chapter_texts = {}      # Kapitel-ID -> Liste von Texten
        chapter_segments = {}   # Kapitel-ID -> Liste von Segmenten
        chapter_titles = {}     # Kapitel-ID -> Titel
        chapter_order = {}      # Kapitel-ID -> Originale Reihenfolge
        current_chapter_id = None
        order_counter = 0
        
        for result in results:
            for segment in result.segments:
                chapter_id = segment_to_chapter.get(segment.segment_id)
                
                if chapter_id != current_chapter_id:
                    current_chapter_id = chapter_id
                    if chapter_id not in chapter_texts:
                        chapter_texts[chapter_id] = []
                        chapter_segments[chapter_id] = []
                        chapter_titles[chapter_id] = segment.title
                        chapter_order[chapter_id] = order_counter
                        order_counter += 1
                
                chapter_texts[chapter_id].append(segment.text)
                chapter_segments[chapter_id].append(segment)
                
        return chapter_texts, chapter_segments, chapter_titles, chapter_order

    def _process_chapter_text(self, chapter_text: str, chapter_id: str, chapter_language: str, target_language: str,
                            logger: ProcessingLogger = None) -> Tuple[str, List[llModel]]:
        """Verarbeitet den Text eines Kapitels (Zusammenfassung und/oder Übersetzung).
        
        Args:
            chapter_text: Der zu verarbeitende Text
            chapter_id: ID des Kapitels
            chapter_language: Erkannte Sprache des Kapitels
            target_language: Zielsprache
            logger: Logger-Instanz
            
        Returns:
            Tuple[str, List[llModel]]: (Verarbeiteter Text, Verwendete LLMs)
        """
        word_count = len(chapter_text.split())
        used_llms = []
        
        if word_count > 10:
            if logger:
                logger.info(f"Verarbeite Kapitel",
                          chapter_id=chapter_id,
                          original_words=word_count)
            'BUG: hier ist text aber schon deutsch - wird wieder auf englisch übersetzt!!'
            summary_result = self.translate_text(
                text=chapter_text,
                source_language=chapter_language,
                target_language=target_language,
                logger=logger,
                summarize=True,
                max_words=400 
            )
            
            used_llms.extend(summary_result.llms)
            chapter_text = summary_result.text
            
            if logger:
                logger.info(f"Kapitel verarbeitet",
                          chapter_id=chapter_id,
                          final_words=len(chapter_text.split()))
                
        return chapter_text, used_llms

    def transcribe_segments(self, segments_or_chapters: Union[List[AudioSegmentInfo], List[ChapterInfo]], 
                          logger: ProcessingLogger = None, target_language: str = None) -> TranscriptionResult:
        """Transkribiert mehrere Audio-Segmente parallel.
        
        Args:
            segments_or_chapters: Entweder eine Liste von AudioSegmentInfo oder eine Liste von ChapterInfo
            logger: Logger-Instanz für Logging
            target_language: ISO-Code der Zielsprache für direkte Übersetzung (optional)
            
        Returns:
            TranscriptionResult: Das validierte Transkriptionsergebnis
        """
        try:
            # 1. Extrahiere alle Segmente und erstelle Mapping
            all_segments, segment_to_chapter = self._extract_segments_from_chapters(segments_or_chapters, logger)
            
            # 2. Verarbeite Segmente parallel
            results = self._process_segments_parallel(all_segments, segment_to_chapter, logger, target_language)
            results.sort(key=lambda x: x.segments[0].segment_id)
            
            # 3. Organisiere Ergebnisse nach Kapiteln
            chapter_texts, chapter_segments, chapter_titles, chapter_order = self._organize_results_by_chapter(results, segment_to_chapter)
            
            # 4. Erstelle den kompletten Text mit Kapiteln
            combined_text_parts = []
            combined_segments = []
            combined_llms = []
            
            # 5. Bestimme die häufigste erkannte Sprache
            detected_languages = [r.detected_language for r in results if r.detected_language]
            most_common_language = max(detected_languages, key=detected_languages.count) if detected_languages else None
            
            # Sortiere Kapitel nach ihrer originalen Reihenfolge
            sorted_chapter_ids = sorted(chapter_texts.keys(), key=lambda x: chapter_order[x])
            
            for chapter_id in sorted_chapter_ids:
                # Füge Kapitelüberschrift hinzu
                if chapter_titles[chapter_id]:
                    combined_text_parts.append(f"\n\n## {chapter_titles[chapter_id]}\n\n")
                
                # Füge Kapiteltext hinzu
                chapter_text = "".join(chapter_texts[chapter_id])
                
                # Prüfe Wortanzahl und fasse ggf. zusammen
                if logger:
                    logger.info(f"Fasse Kapitel zusammen",
                                chapter_id=chapter_id)
                
                summary_result = self.translate_text(
                    text=chapter_text,
                    source_language=most_common_language,  # Wir sind noch in der Originalsprache
                    target_language=most_common_language,  # Noch keine Übersetzung, nur Zusammenfassung
                    logger=logger,
                    summarize=True,
                    max_words=400
                )
                combined_llms.extend(summary_result.llms)
                chapter_text = summary_result.text
                
                combined_text_parts.append(chapter_text)
                combined_segments.extend(chapter_segments[chapter_id])
            
            # Füge Whisper LLMs hinzu
            for result in results:
                combined_llms.extend(result.llms)
            
            
            # 6. Übersetze den gesamten Text wenn nötig
            complete_text = "".join(combined_text_parts).strip()
            if most_common_language and target_language and most_common_language != target_language:
                if logger:
                    logger.info(f"Übersetze kompletten Text von {most_common_language} nach {target_language}")
                
                translation_result = self.translate_text(
                    text=complete_text,
                    source_language=most_common_language,
                    target_language=target_language,
                    logger=logger
                )
                complete_text = translation_result.text
                combined_llms.extend(translation_result.llms)
            
            # 7. Erstelle finales Ergebnis
            result = TranscriptionResult(
                text=complete_text,
                detected_language=most_common_language,
                segments=combined_segments,
                llms=combined_llms
            )
            
            # 8. Speichere Transkription
            if all_segments:
                process_dir = all_segments[0].file_path.parent
                full_transcript_path = process_dir / "segments_transcript.txt"
                with open(full_transcript_path, 'w', encoding='utf-8') as f:
                    json.dump(result.model_dump(), f, indent=2)

            if logger:
                logger.info("Parallele Transkription abgeschlossen",
                    segment_count=len(all_segments),
                    total_tokens=sum(llm.token_count for llm in result.llms))
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Transkription", error=str(e))
            raise
        finally:
            gc.collect()

    def _save_llm_interaction(self, template: str, system_prompt: str, user_prompt: str, response: Any, logger: ProcessingLogger = None, field_definitions: Dict[str, Any] = None) -> None:
        """Speichert LLM Interaktionen in Logdateien."""
        try:
            log_dir = Path("temp-processing/llm")
            log_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            operation_type = template if template else "translation"
            
            # Speichere Prompts und Template-Struktur
            prompts_file = log_dir / f"{operation_type}_{timestamp}_prompts.txt"
            prompts_content = (
                f"=== System Prompt ===\n{system_prompt}\n\n"
                f"=== User Prompt ===\n{user_prompt}\n"
            )
            
            if field_definitions:
                prompts_content += "\n=== Template Structure ===\n"
                for var_name, (type_hint, field) in field_definitions.items():
                    prompts_content += f"{var_name}: {field.description}\n"
                    
            prompts_file.write_text(prompts_content, encoding='utf-8')
            
            # Speichere Response
            response_file = log_dir / f"{operation_type}_{timestamp}_response.json"
            if hasattr(response.choices[0].message, 'function_call'):
                response_content = response.choices[0].message.function_call.arguments
            else:
                response_content = response.choices[0].message.content
            response_file.write_text(response_content, encoding='utf-8')
            
            # Speichere das finale Ergebnis
            result_file = log_dir / f"{operation_type}_{timestamp}_result.json"
            result_content = {
                "operation_type": operation_type,
                "timestamp": timestamp,
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response": response_content,
                "field_definitions": field_definitions if field_definitions else None
            }
            result_file.write_text(json.dumps(result_content, indent=2, ensure_ascii=False), encoding='utf-8')
                    
        except Exception as e:
            if logger:
                logger.warning("LLM Interaktion konnte nicht gespeichert werden", error=str(e))