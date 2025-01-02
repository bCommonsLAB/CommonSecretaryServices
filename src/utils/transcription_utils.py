import re

import openai
import io
from typing import List, Dict, Any, Optional, Type, Tuple
import tempfile
import os
from pydub import AudioSegment
import wave
import json
from utils.logger import ProcessingLogger
from pathlib import Path
from pydantic import BaseModel, Field, ValidationError, create_model
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import math

# Basis-Schemas für wiederverwendbare Komponenten
class Step(BaseModel):
    """Schema für einen einzelnen Verarbeitungsschritt."""
    explanation: str = Field(description="Erklärung des Verarbeitungsschritts")
    output: str = Field(description="Ausgabe des Verarbeitungsschritts")

class TranscriptionSegment(BaseModel):
    """Schema für ein einzelnes Transkriptionssegment."""
    text: str = Field(description="Der transkribierte Text des Segments")
    start_time: Optional[float] = Field(None, description="Startzeit des Segments in Sekunden")
    end_time: Optional[float] = Field(None, description="Endzeit des Segments in Sekunden")
    confidence: Optional[float] = Field(None, description="Konfidenzwert der Transkription")

# Haupt-Response-Schemas
class TranscriptionResult(BaseModel):
    """Schema für das Gesamtergebnis einer Transkription."""
    text: str = Field(description="Der vollständige transkribierte Text")
    detected_language: Optional[str] = Field(None, description="Der erkannte ISO Sprachcode")
    segments: List[TranscriptionSegment] = Field(default_factory=list, description="Liste der einzelnen Transkriptionssegmente")
    steps: List[Step] = Field(default_factory=list, description="Liste der Verarbeitungsschritte")
    model: str = Field(description="Das verwendete Modell für die Transkription")
    token_count: int = Field(description="Anzahl der verwendeten Tokens")

class TranslationResult(BaseModel):
    """Schema für Übersetzungsergebnisse."""
    text: str = Field(description="Der übersetzte Text")
    source_language: Optional[str] = Field(None, description="Ursprüngliche Sprache (ISO code)")
    target_language: str = Field(description="Zielsprache (ISO code)")
    steps: List[Step] = Field(default_factory=list, description="Liste der Übersetzungsschritte")
    token_count: int = Field(description="Anzahl der verwendeten Tokens")

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
        "hi": "क्या आप इस पाठ का संक्षेप में हिंदी में خلاصा बना सकते हैं?",
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
    
    def __init__(self, api_key: str, config: Dict[str, Any] = None):
        """
        Args:
            api_key (str): OpenAI API-Schlüssel
            config (Dict[str, Any], optional): Konfigurationsobjekt mit Prozessor-Einstellungen
        """
        self.client = openai.OpenAI(api_key=api_key)
        self.config = config or {}
        # Erstelle temp-processing/audio Verzeichnis
        self.temp_dir = self.config.get('processors', {}).get('audio', {}).get('temp_dir', "temp-processing/audio")
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
        
    def translate_text(self, text: str, target_language: str, logger: ProcessingLogger = None, summarize: bool = False, format_instruction: str = "") -> TranslationResult:
        """Übersetzt den Text in die Zielsprache mit GPT-4.
        
        Args:
            text (str): Zu übersetzender Text
            target_language (str): Zielsprache (ISO 639-1 code)
            logger (ProcessingLogger): Logger-Instanz für Logging
            summarize (bool): Ob eine Zusammenfassung erstellt werden soll
            format_instruction (str): Optionale Anweisung für das Ausgabeformat

        Returns:
            TranslationResult: Das validierte Übersetzungsergebnis
        """
        try:
            target = self.ISO_TO_FULL_NAME.get(target_language, target_language)
            
            if summarize:
                instruction = self.ISO_TO_INSTRUCTION.get(target_language, "Kannst du diesen Textes möglichst kompakt in Deutsch zusammenfassen:")
            else:
                instruction = f"Please translate this text to {target}:"

            if format_instruction:
                instruction = f"{instruction}\n{format_instruction}"
            
            if logger:
                logger.info(f"Starte Übersetzung ins {target_language}")

            # System- und User-Prompts erstellen
            system_prompt = "You are a precise assistant for text translation and summarization."
            user_prompt = f"{instruction}\n\nTEXT:\n{text}"

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                functions=[{
                    "name": "translate_text",
                    "description": "Extracts translation result according to schema",
                    "parameters": TranslationResult.model_json_schema()
                }],
                function_call={"name": "translate_text"}
            )
            
            if not response.choices or not response.choices[0].message:
                raise ValueError("Keine gültige Antwort vom LLM erhalten")

            # Extrahiere und validiere das Ergebnis
            result_json = response.choices[0].message.function_call.arguments
            result = TranslationResult.model_validate_json(result_json)
            
            if logger:
                logger.info("Übersetzung abgeschlossen",
                    token_count=result.token_count)
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Übersetzung", error=str(e))
            raise

    def _read_template_file(self, template_name: str, logger: ProcessingLogger = None) -> str:
        """Liest den Inhalt einer Template-Datei."""
        template_dir = 'templates'
        template_path = os.path.join(template_dir, f"{template_name}.md")
        
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            if logger:
                logger.error("Template konnte nicht gelesen werden",
                    error=str(e),
                    template_path=template_path)
            raise ValueError(f"Template '{template_name}' konnte nicht gelesen werden: {str(e)}")

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

    def transform_by_template(self, text: str, target_language: str, template_name: str, context: Dict[str, Any] = None, logger: ProcessingLogger = None) -> Tuple[str, BaseModel]:
        """Transformiert Text basierend auf einem Template mit GPT-4.
        
        Args:
            text (str): Zu transformierender Text
            target_language (str): Zielsprache (ISO 639-1 code)
            template_name (str): Name des Templates (ohne .md Endung)
            context (Dict[str, Any]): Dictionary mit Kontext-Informationen für Template-Variablen
            logger (ProcessingLogger): Logger-Instanz für Logging

        Returns:
            Tuple[str, BaseModel]: (Transformierter Template-Inhalt, Validiertes Pydantic Model)
        """
        try:
            if logger:
                logger.info(f"Starte Template-Transformation: {template_name}")

            # 1. Template-Datei lesen
            template_content = self._read_template_file(template_name, logger)

            # 2. Einfache Kontext-Variablen ersetzen
            template_content = self._replace_context_variables(template_content, context, text, logger)

            # 3. Strukturierte Variablen extrahieren und Model erstellen
            field_definitions = self._extract_structured_variables(template_content, logger)
            
            if not field_definitions:
                return template_content, None

            # 4. Pydantic Model erstellen
            DynamicTemplateModel = create_model(
                f'Template{template_name.capitalize()}Model',
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
            self._save_llm_interaction(template_name, system_prompt, user_prompt, response, logger, field_definitions)

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

            if logger:
                logger.info("Template-Transformation abgeschlossen",
                    token_count=response.usage.total_tokens if hasattr(response, 'usage') else 0)
            
            return template_content, result
            
        except Exception as e:
            if logger:
                logger.error("Template-Verarbeitung fehlgeschlagen", error=str(e))
            raise

    def transcribe_segment(self, audio_segment: bytes, segment_path: Path = None, logger: ProcessingLogger = None) -> Dict[str, Any]:
        """Transkribiert ein einzelnes Audio-Segment.
        
        Args:
            audio_segment (bytes): Audio-Segment als Bytes
            segment_path (Path): Pfad zur Audio-Datei (optional)
            logger (ProcessingLogger): Logger-Instanz für Logging

        Returns:
            Dict[str, Any]: {
                'text': str,           # Transkribierter Text
                'model': str,          # Verwendetes Modell
                'token_count': int     # Anzahl verwendeter Tokens
            }
        """
        try:
            if logger:
                logger.info("Starte Transkription eines Audio-Segments")
            
            # Wenn kein segment_path angegeben, erstelle temporären Pfad
            if segment_path is None:
                temp_path = os.path.join(self.temp_dir, f"single_segment.mp3")
            else:
                temp_path = str(segment_path)
                
            with open(temp_path, 'wb') as temp_audio:
                temp_audio.write(audio_segment)

            if logger:
                logger.info("Sende Anfrage an Whisper API")
                
            with open(temp_path, 'rb') as audio_file:
                response = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json"
                )
            
            transcribed_text = response.text if hasattr(response, 'text') else str(response)
            detected_language = response.language if hasattr(response, 'language') else None
            detected_language_iso = self._convert_to_iso_code(detected_language)
            
            result = {
                'text': transcribed_text,
                'model': "whisper-1",
                'token_count': len(str(response).split()),
                'detected_language': detected_language_iso,
                'whisper_language': detected_language
            }
            
            # Speichere Transkription neben der Audio-Datei
            if segment_path:
                transcript_path = segment_path.with_suffix('.txt')
                with open(transcript_path, 'w', encoding='utf-8') as f:
                    json.dump(result, f, indent=2)
            
            return result
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Transkription", error=str(e))
            raise

    def transcribe_segments(self, segments: List[bytes], segment_paths: List[Path], logger: ProcessingLogger = None, batch_size: int = None) -> Dict[str, Any]:
        """Transkribiert mehrere Audio-Segmente parallel in Batches und fügt sie zusammen.
        
        Args:
            segments (List[bytes]): Liste der Audio-Segmente als Bytes
            segment_paths (List[Path]): Liste der Pfade für die Segmente
            logger (ProcessingLogger, optional): Logger für Statusmeldungen
            batch_size (int, optional): Anzahl der parallel zu verarbeitenden Segmente. 
                                      Falls None, wird der Wert aus der Konfiguration verwendet.
        
        Returns:
            Dict[str, Any]: {
                'text': str,           # Kompletter transkribierter Text
                'model': str,          # Verwendetes Modell
                'token_count': int,    # Gesamtzahl der Tokens
                'segments': List[Dict]  # Details der einzelnen Segmente
            }
        """
        # Verwende batch_size aus Konfiguration, falls nicht explizit angegeben
        if batch_size is None:
            batch_size = self.config.get('processors', {}).get('audio', {}).get('batch_size', 3)
            
        if logger:
            logger.info(f"Starte parallele Transkription von {len(segments)} Segmenten in Batches von {batch_size}")
        
        # Initialisiere Liste für alle Transkriptionen
        all_transcriptions = [None] * len(segments)
        total_tokens = 0
        
        # Berechne Anzahl der Batches
        num_batches = math.ceil(len(segments) / batch_size)
        
        for batch_num in range(num_batches):
            start_idx = batch_num * batch_size
            end_idx = min((batch_num + 1) * batch_size, len(segments))
            
            if logger:
                logger.info(f"Verarbeite Batch {batch_num + 1}/{num_batches} (Segmente {start_idx + 1}-{end_idx})")
            
            # Erstelle Batch von Segmenten
            batch_segments = segments[start_idx:end_idx]
            batch_paths = segment_paths[start_idx:end_idx]
            
            # Verarbeite Batch parallel
            with ThreadPoolExecutor(max_workers=batch_size) as executor:
                # Erstelle Future-Objekte für jeden Job im Batch
                future_to_idx = {
                    executor.submit(
                        self.transcribe_segment, 
                        segment, 
                        path, 
                        logger
                    ): idx 
                    for idx, (segment, path) in enumerate(zip(batch_segments, batch_paths), start=start_idx)
                }
                
                # Sammle Ergebnisse in der richtigen Reihenfolge
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        result = future.result()
                        all_transcriptions[idx] = result
                        total_tokens += result['token_count']
                        
                        if logger:
                            logger.info(f"Segment {idx + 1}/{len(segments)} abgeschlossen")
                    except Exception as e:
                        if logger:
                            logger.error(f"Fehler bei Segment {idx + 1}", error=str(e))
                        raise
        
        # Erstelle Gesamtergebnis
        result = {
            'text': " ".join(t['text'] for t in all_transcriptions),
            'model': "whisper-1",
            'token_count': total_tokens,
            'segments': all_transcriptions,
            'detected_language': max(
                (t['detected_language'] for t in all_transcriptions if t.get('detected_language')),
                key=lambda x: sum(1 for t in all_transcriptions if t.get('detected_language') == x),
                default=None
            )
        }
        
        # Speichere komplette Transkription
        if segment_paths:
            process_dir = segment_paths[0].parent
            full_transcript_path = process_dir / "complete_transcript.txt"
            with open(full_transcript_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
        
        if logger:
            logger.info("Parallele Transkription abgeschlossen",
                segment_count=len(segments),
                total_tokens=total_tokens)
        
        return result

    def _save_llm_interaction(self, template_name: str, system_prompt: str, user_prompt: str, response: Any, logger: ProcessingLogger = None, field_definitions: Dict[str, Any] = None) -> None:
        """Speichert LLM Interaktionen in Logdateien."""
        try:
            log_dir = Path("temp-processing/llm")
            log_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Speichere Prompts und Template-Struktur
            prompts_file = log_dir / f"{template_name}_{timestamp}_prompts.txt"
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
            response_file = log_dir / f"{template_name}_{timestamp}_response.json"
            if hasattr(response.choices[0].message, 'function_call'):
                response_content = response.choices[0].message.function_call.arguments
            else:
                response_content = response.choices[0].message.content
            response_file.write_text(response_content, encoding='utf-8')
                    
        except Exception as e:
            if logger:
                logger.warning("LLM Interaktion konnte nicht gespeichert werden", error=str(e))