import openai
import io
from typing import List, Dict, Any
import tempfile
import os
from pydub import AudioSegment
import wave
import json
from src.utils.logger import ProcessingLogger
from pathlib import Path

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
    
    def __init__(self, api_key: str):
        """
        Args:
            api_key (str): OpenAI API-Schlüssel
        """
        self.client = openai.OpenAI(api_key=api_key)
        # Erstelle temp-processing/audio Verzeichnis
        self.temp_dir = "temp-processing/audio"
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
        
    def translate_text(self, text: str, target_language: str, logger: ProcessingLogger = None, summarize: bool = False) -> Dict[str, Any]:
        """Übersetzt den Text in die Zielsprache mit GPT-4.
        
        Args:
            text (str): Zu übersetzender Text
            target_language (str): Zielsprache (ISO 639-1 code)
            logger (ProcessingLogger): Logger-Instanz für Logging
            summarize (bool): Ob eine Zusammenfassung erstellt werden soll

        Returns:
            Dict[str, Any]: {
                'text': str,           # Übersetzter Text
                'token_count': int     # Anzahl der verwendeten Tokens
            }
        """
        try:
            # Hole den vollen Sprachnamen aus dem ISO-Code
            target = self.ISO_TO_FULL_NAME.get(target_language, target_language)
            
            # Erstelle die passende Anweisung basierend auf summarize
            if summarize:
                instruction = self.ISO_TO_INSTRUCTION.get(target_language, "Kannst du diesen Textes möglichst kompakt in Deutsch zusammenfassen:")
            else:
                instruction = f"Please translate this text to {target}:"

            
            if logger:
                logger.info(f"Starte Übersetzung ins {target_language}",
                            summarize=summarize,
                            instruction=instruction)

            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                max_tokens=4096,
                temperature=1.0,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant who translates and summarizes text."},
                    {"role": "user", "content": f"{instruction}\n{text}"}
                ]
            )
            
            translated_text = response.choices[0].message.content
            # Berechne die Token-Anzahl für Input und Output
            total_tokens = response.usage.total_tokens if hasattr(response, 'usage') else len(text.split()) + len(translated_text.split())
            
            if logger:
                logger.debug("Übersetzung abgeschlossen",
                           original_length=len(text),
                           translated_length=len(translated_text),
                           token_count=total_tokens,
                           instruction=instruction,
                           original_text=text,
                           translated_text=translated_text
                        )
            
            return {
                'text': translated_text,
                'token_count': total_tokens
            }
            
        except Exception as e:
            if logger:
                logger.error("Fehler bei der Übersetzung", error=str(e))
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
            
            # Audio-Analyse
            try:
                audio = AudioSegment.from_mp3(temp_path)
                if logger:
                    logger.debug("Audio-Format analysiert",
                               format="MP3",
                               channels=audio.channels,
                               sample_width=audio.sample_width,
                               frame_rate=audio.frame_rate,
                               duration=len(audio) / 1000.0)
            except Exception as e:
                if logger:
                    logger.warning(f"Konnte Audio-Format nicht analysieren: {e}")

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
            
            # Konvertiere Whisper Sprachbezeichnung in ISO-Code
            detected_language_iso = self._convert_to_iso_code(detected_language)
            
            if logger:
                if detected_language_iso:
                    logger.info("Whisper hat Sprache erkannt", 
                              whisper_language=detected_language,
                              iso_code=detected_language_iso)
                else:
                    logger.warning("Konnte Whisper Sprache nicht in ISO-Code konvertieren",
                                 whisper_language=detected_language)
            
            result = {
                'text': transcribed_text,
                'model': "whisper-1",
                'token_count': len(str(response).split()),
                'detected_language': detected_language_iso,
                'whisper_language': detected_language  # Optional: Original Whisper Bezeichnung behalten
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

    def transcribe_segments(self, segments: List[bytes], segment_paths: List[Path], logger: ProcessingLogger = None) -> Dict[str, Any]:
        """Transkribiert mehrere Audio-Segmente und fügt sie zusammen.
        
        Returns:
            Dict[str, Any]: {
                'text': str,           # Kompletter transkribierter Text
                'model': str,          # Verwendetes Modell
                'token_count': int,    # Gesamtzahl der Tokens
                'segments': List[Dict]  # Details der einzelnen Segmente
            }
        """
        if logger:
            logger.info(f"Starte Transkription von {len(segments)} Segmenten")
        
        transcriptions = []
        total_tokens = 0
        
        for i, (segment, path) in enumerate(zip(segments, segment_paths), 1):
            if logger:
                logger.info(f"Verarbeite Segment {i}/{len(segments)}")
            segment_result = self.transcribe_segment(segment, path, logger)
            transcriptions.append(segment_result)
            total_tokens += segment_result['token_count']
            
            if logger:
                logger.debug(f"Segment {i} transkribiert",
                           text_length=len(segment_result['text']),
                           token_count=segment_result['token_count'])
        
        result = {
            'text': " ".join(t['text'] for t in transcriptions),
            'model': "whisper-1",
            'token_count': total_tokens,
            'segments': transcriptions,
            'detected_language': max(
                (t['detected_language'] for t in transcriptions if t.get('detected_language')),
                key=lambda x: sum(1 for t in transcriptions if t.get('detected_language') == x),
                default=None
            )
        }
        
        # Speichere komplette Transkription
        if segment_paths:
            process_dir = segment_paths[0].parent
            full_transcript_path = process_dir / "complete_transcript.txt"
            with open(full_transcript_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, indent=2)
        
        return result