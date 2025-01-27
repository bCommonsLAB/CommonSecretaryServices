"""
Transformer processor module.
Handles text transformation using LLM models.
"""
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import traceback
import uuid

from openai import OpenAI

from src.core.models.transformer import TranslationResult, TransformationResult
from src.core.exceptions import ProcessingError
from src.utils.logger import ProcessingLogger
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.llm import LLMInfo
from src.core.models.base import RequestInfo, ProcessInfo, ErrorInfo
from src.core.models.transformer import (
    TransformerResponse, TransformerInput, TransformerOutput, 
    TransformerData
)
from src.core.models.enums import ProcessorType, OutputFormat, ProcessingStatus
from src.core.config_keys import ConfigKeys
from utils.transcription_utils import TransformationResult
from .base_processor import BaseProcessor

class TransformerProcessor(BaseProcessor):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    """
    
    def __init__(self, resource_calculator: Any, process_id: Optional[str] = None) -> None:
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id (str, optional): Die zu verwendende Process-ID vom API-Layer
        """
        super().__init__(resource_calculator=resource_calculator, process_id=process_id)
        self.logger: Optional[ProcessingLogger] = None
        
        try:
            # Konfiguration laden
            transformer_config = self.load_processor_config('transformer')
            
            # Logger initialisieren
            self.logger = self.init_logger("TransformerProcessor")
            
            # Konfigurationswerte laden
            self.model: str = transformer_config.get('model', 'gpt-4')
            self.target_format: OutputFormat = transformer_config.get('target_format', OutputFormat.TEXT)
            
            # Temporäres Verzeichnis einrichten
            self.init_temp_dir("transformer", transformer_config)
            
            # OpenAI Client initialisieren
            config_keys = ConfigKeys()
            self.client = OpenAI(api_key=config_keys.openai_api_key)
            
            # Transcriber für GPT-4 Interaktionen initialisieren
            self.transcriber = WhisperTranscriber(transformer_config)
            
            if self.logger:
                self.logger.debug("Transformer Processor initialisiert",
                                model=self.model,
                                target_format=self.target_format,
                                temp_dir=str(self.temp_dir))
                            
        except Exception as e:
            if self.logger:
                self.logger.error("Fehler bei der Initialisierung des TransformerProcessors",
                                error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def transform(
        self, 
        source_text: str, 
        source_language: str, 
        target_language: str, 
        summarize: bool = False, 
        target_format: Optional[OutputFormat] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> TransformerResponse:
        """
        Führt Übersetzung und optional Zusammenfassung durch.
        
        Args:
            source_text: Der zu transformierende Text
            source_language: Sprachcode der Quellsprache
            target_language: Sprachcode der Zielsprache
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Optional, das Zielformat
            context: Optional, zusätzliche Kontextinformationen
            
        Returns:
            TransformerResponse: Das Transformationsergebnis
        """
        
        # Response initialisieren
        response = TransformerResponse(
            request=RequestInfo(
                processor=str(ProcessorType.TRANSFORMER.value),
                timestamp=datetime.now().isoformat(),
                parameters={
                    "source_language": source_language,
                    "target_language": target_language,
                    "summarize": summarize,
                    "target_format": target_format or self.target_format
                }
            ),
            process=ProcessInfo(
                id=self.process_id or str(uuid.uuid4()),
                main_processor=str(ProcessorType.TRANSFORMER.value),
                started=datetime.now().isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text=source_text,
                    language=source_language,
                    format=target_format or self.target_format,
                    summarize=summarize
                ),
                output=TransformerOutput(
                    text="",  # Wird später gefüllt
                    language=target_language,
                    format=target_format or self.target_format,
                    summarized=summarize
                )
            )
        )
        
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            format_to_use = target_format or self.target_format
            context = self.validate_context(context)

            llm_info = LLMInfo(model=self.model, purpose="Translation")

            # Debug-Verzeichnis
            debug_dir = Path('./temp-processing/transform')
            if context and 'uploader' in context:
                debug_dir = Path(f'{debug_dir}/{context["uploader"]}')
            debug_dir.mkdir(parents=True, exist_ok=True)

            if self.logger:
                self.logger.info(f"Starte Transformation: {source_language} -> {target_language}")

            # Führe Übersetzung durch
            result_text = source_text
            if source_language != target_language:
                translation_result: TranslationResult = self.transcriber.translate_text(
                    text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = translation_result.text
                if translation_result.requests and len(translation_result.requests) > 0:
                    llm_info.add_request(translation_result.requests[0])
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=format_to_use,
                            summarized=summarize
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Führe Zusammenfassung durch
            if summarize:
                summary_result: TransformationResult = self.transcriber.summarize_text(
                    text=result_text,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text: str = summary_result.text
                if summary_result.requests and len(summary_result.requests) > 0:
                    llm_info.add_request(summary_result.requests[0])
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=format_to_use,
                            summarized=True
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Formatierung anwenden
            if format_to_use != OutputFormat.TEXT:
                format_result: TransformationResult = self.transcriber.format_text(
                    text=result_text,
                    format=format_to_use,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text: str = format_result.text
                if format_result.requests and len(format_result.requests) > 0:
                    llm_info.add_request(format_result.requests[0])
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=format_to_use,
                            summarized=response.data.output.summarized
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Debug Output
            self.transcriber.saveDebugOutput(
                text=result_text,
                context=context,
                logger=self.logger
            )

            # Response vervollständigen
            response = TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                llm_info=llm_info,
                status=ProcessingStatus.SUCCESS,
                error=None
            )
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
            if self.logger:
                self.logger.error(f"Fehler bei der Transformation: {str(e)}")
            
            return TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                status=ProcessingStatus.ERROR,
                error=error_info
            )

    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None
    ) -> TransformerResponse:
        """
        Transformiert Text basierend auf einem vordefinierten Markdown-Template.
        Die Templates befinden sich im ./templates-Ordner und enthalten Anweisungen in geschweiften Klammern
        für strukturierte Ausgaben vom LLM Modell.

        Args:
            source_text (str): Der zu transformierende Text
            source_language (str): Sprachcode (ISO 639-1) für die Quellsprache
            target_language (str): Sprachcode (ISO 639-1) für die Zielsprache
            context (Dict[str, Any], optional): Dictionary mit Kontext-Informationen für Template-Variablen
            template (str, optional): Name des Templates (ohne .md Endung)

        Returns:
            TransformerResponse: Das validierte Transformationsergebnis mit Prozess-Informationen
        """
        # Response initialisieren
        response = TransformerResponse(
            request=RequestInfo(
                processor=str(ProcessorType.TRANSFORMER.value),
                timestamp=datetime.now().isoformat(),
                parameters={
                    "source_language": source_language,
                    "target_language": target_language,
                    "template": template,
                    "context": context
                }
            ),
            process=ProcessInfo(
                id=self.process_id or str(uuid.uuid4()),
                main_processor=str(ProcessorType.TRANSFORMER.value),
                started=datetime.now().isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text=source_text,
                    language=source_language,
                    format=self.target_format,
                    summarize=False
                ),
                output=TransformerOutput(
                    text="",  # Wird später gefüllt
                    language=target_language,
                    format=self.target_format,
                    summarized=False
                )
            )
        )
        
        try:
            # Validiere Eingaben
            source_text = self.validate_text(source_text, "source_text")
            source_language = self.validate_language_code(source_language, "source_language")
            target_language = self.validate_language_code(target_language, "target_language")
            if template is not None:
                template = self.validate_text(template, "template")
            validated_context: Dict[str, Any] | None = self.validate_context(context)

            llm_info = LLMInfo(model=self.model, purpose="Template-Transformation")

            if self.logger:
                self.logger.info(f"Starte Template-Transformation: {source_language} -> {target_language}")
                
                if validated_context:
                    self.logger.debug("Context-Informationen", context=validated_context)

            # Zuerst den Quelltext übersetzen
            result_text = source_text
            if source_language != target_language:
                if self.logger:
                    self.logger.info("Übersetze Quelltext")
                    
                translation_result = self.transcriber.translate_text(
                    text=source_text,
                    source_language=source_language,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text = translation_result.text
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=self.target_format,
                            summarized=False
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Template-Transformation durchführen
            if template is not None:
                if self.logger:
                    self.logger.info("Führe Template-Transformation durch")

                format_result: TransformationResult = self.transcriber.format_text(
                    text=result_text,
                    format=OutputFormat.MARKDOWN,
                    target_language=target_language,
                    logger=self.logger
                )
                result_text: str = format_result.text
                if format_result.requests and len(format_result.requests) > 0:
                    llm_info.add_request(format_result.requests[0])
                
                response = TransformerResponse(
                    request=response.request,
                    process=response.process,
                    data=TransformerData(
                        input=response.data.input,
                        output=TransformerOutput(
                            text=result_text,
                            language=target_language,
                            format=OutputFormat.MARKDOWN,
                            summarized=False
                        )
                    ),
                    status=response.status,
                    error=response.error
                )

            # Debug Output
            self.transcriber.saveDebugOutput(
                text=result_text,
                context=validated_context,
                logger=self.logger
            )

            # Response vervollständigen
            response = TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                llm_info=llm_info,
                status=ProcessingStatus.SUCCESS,
                error=None
            )
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
            if self.logger:
                self.logger.error(f"Fehler bei der Template-Transformation: {str(e)}")
            
            return TransformerResponse(
                request=response.request,
                process=ProcessInfo(
                    id=response.process.id,
                    main_processor=response.process.main_processor,
                    started=response.process.started,
                    completed=datetime.now().isoformat()
                ),
                data=response.data,
                status=ProcessingStatus.ERROR,
                error=error_info
            ) 