"""
Utilities für die Transkription und Transformation von Text.
"""
from typing import Dict, Any, Optional
from pathlib import Path
import time
from datetime import datetime

from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
from openai.types.chat.chat_completion_message import ChatCompletionMessage

from src.utils.logger import ProcessingLogger
from src.core.models.transformer import TranslationResult, TransformationResult, TransformerResponse
from src.core.models.llm import LLMRequest
from src.core.models.base import RequestInfo, ProcessInfo
from src.core.models.transformer import TransformerData, TransformerInput, TransformerOutput
from src.core.models.enums import ProcessorType, OutputFormat

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

    def transform_text(
        self, 
        text: str, 
        template: str, 
        context: Dict[str, Any] | None = None
    ) -> TransformerResponse:
        """Transformiert Text basierend auf einem Template."""
        
        now: datetime = datetime.now()
        request = RequestInfo(
            processor=ProcessorType.TRANSFORMER.value,
            timestamp=now.isoformat()
        )
        process = ProcessInfo(
            id="transform_" + now.strftime("%Y%m%d_%H%M%S"),
            main_processor=ProcessorType.TRANSFORMER.value,
            started=now.isoformat()
        )
        data = TransformerData(
            input=TransformerInput(
                text=text,
                language=context.get("language", "de") if context else "de",
                format=OutputFormat.MARKDOWN
            ),
            output=TransformerOutput(
                text=template.replace("{{text}}", text),
                language=context.get("language", "de") if context else "de",
                format=OutputFormat.MARKDOWN
            )
        )
        
        return TransformerResponse.create(request=request, process=process, data=data)