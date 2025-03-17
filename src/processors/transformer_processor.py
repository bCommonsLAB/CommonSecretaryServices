"""
Transformer processor module.
Handles text transformation using LLM models.

LLM-Tracking Logik:
-----------------
Der Prozessor trackt die LLM-Nutzung auf zwei Ebenen:

1. Aggregierte Informationen (LLMInfo):
   - Gesamtanzahl der Tokens
   - Gesamtdauer der Verarbeitung
   - Anzahl der Requests
   - Gesamtkosten

2. Einzelne Requests (LLMRequest):
   - Pro Operation (Übersetzung, Zusammenfassung, etc.)
   - Mit Details wie Model, Zweck, Tokens, Dauer
   - Zeitstempel für Nachverfolgbarkeit

Ablauf:
1. LLMInfo wird für den Gesamtprozess initialisiert
2. Jede LLM-Operation (translate, summarize, etc.) erstellt LLMRequests
3. Diese werden zum LLMInfo hinzugefügt und aggregiert
4. Die Response enthält beide Informationsebenen

Beispiel Response:
{
  "llm_info": {
    "requests_count": 3,
    "total_tokens": 1500,
    "total_duration": 2500,
    "total_cost": 0.15,
    "requests": [
      {
        "model": "gpt-4",
        "purpose": "translation",
        "tokens": 500,
        "duration": 800,
        "timestamp": "2024-01-20T10:15:30Z"
      },
      {
        "model": "gpt-4", 
        "purpose": "summarization",
        "tokens": 400,
        "duration": 700,
        "timestamp": "2024-01-20T10:15:31Z"
      }
    ]
  }
}
"""

import hashlib
from typing import Dict, Any, Optional, List, Union, cast, TYPE_CHECKING
from datetime import datetime
import traceback
import uuid
import time
import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup as BS, ResultSet, Tag
from bs4.element import NavigableString, PageElement
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion

if TYPE_CHECKING:
    from src.core.resource_tracking import ResourceCalculator
else:
    from src.core.resource_tracking import ResourceCalculator

from src.core.models.transformer import (
    TransformationResult
)
from src.core.exceptions import ProcessingError
from src.utils.transcription_utils import WhisperTranscriber
from src.core.models.llm import LLMInfo, LLMRequest
from src.core.models.base import RequestInfo, ProcessInfo, ErrorInfo
from src.core.models.transformer import (
    TransformerResponse, TransformerInput, TransformerOutput, 
    TransformerData
)
from src.core.models.enums import ProcessorType, OutputFormat
from src.core.config_keys import ConfigKeys
from .cacheable_processor import CacheableProcessor
from src.core.config import Config

# Type-Alias für bessere Lesbarkeit
TableElement = Tag | PageElement
AttributeValue = str | None

class TransformerProcessor(CacheableProcessor[TransformationResult]):
    """
    Prozessor für Text-Transformationen mit LLM-Modellen.
    Unterstützt verschiedene Modelle und Template-basierte Transformationen.
    
    Verwendet MongoDB-Caching zur effizienten Wiederverwendung von Transformationsergebnissen.
    """
    
    # Name der Cache-Collection für MongoDB
    cache_collection_name = "transformer_cache"
    
    def __init__(self, resource_calculator: ResourceCalculator, process_id: Optional[str] = None, parent_process_info: Optional[ProcessInfo] = None):
        """
        Initialisiert den TransformerProcessor.
        
        Args:
            resource_calculator: Calculator für Ressourcenverbrauch
            process_id: Process-ID für Tracking
            parent_process_info: Optional ProcessInfo vom übergeordneten Prozessor
        """
        # Zeit für Gesamtinitialisierung starten
        init_start = time.time()
        
        # Zeit für Superklasse-Initialisierung messen
        super_init_start = time.time()
        super().__init__(resource_calculator=resource_calculator, process_id=process_id, parent_process_info=parent_process_info)
        super_init_end = time.time()
        
        try:
            # Konfiguration laden
            config_load_start = time.time()
            config = Config()
            processor_config = config.get('processors', {})
            transformer_config = processor_config.get('transformer', {})
            config_load_end = time.time()
            
            # Konfigurationswerte für OpenAI-Modell laden
            self.model: str = transformer_config.get('model', 'gpt-4o')
            self.temperature: float = transformer_config.get('temperature', 0.7)
            self.max_tokens: int = transformer_config.get('max_tokens', 4000)
            self.target_format: OutputFormat = transformer_config.get('target_format', OutputFormat.TEXT)
            
            # Performance-Einstellungen
            self.max_concurrent_requests: int = transformer_config.get('max_concurrent_requests', 10)
            self.timeout_seconds: int = transformer_config.get('timeout_seconds', 120)
            
            # Templates-Verzeichnis
            self.templates_dir: str = transformer_config.get('templates_dir', 'resources/templates')
            
            # OpenAI Client initialisieren
            client_init_start = time.time()
            config_keys = ConfigKeys()
            self.client = OpenAI(api_key=config_keys.openai_api_key)
            client_init_end = time.time()
            
            # Transcriber für GPT-4 Interaktionen initialisieren
            transcriber_init_start = time.time()
            transcriber_config = {
                'processor_name': 'transformer',
                'cache_dir': str(self.cache_dir),  # Haupt-Cache-Verzeichnis
                'temp_dir': str(self.temp_dir),    # Temporäres Unterverzeichnis
                'debug_dir': str(self.temp_dir / "debug"),  # Debug-Verzeichnis im temp-Bereich
                'model': self.model,
                'temperature': self.temperature,
                'max_tokens': self.max_tokens
            }
            self.transcriber = WhisperTranscriber(transcriber_config)
            transcriber_init_end = time.time()
            
            # Debug-Logging der Konfiguration
            self.logger.debug("Transformer Processor initialisiert",
                            model=self.model,
                            temperature=self.temperature,
                            max_tokens=self.max_tokens,
                            target_format=self.target_format,
                            max_concurrent_requests=self.max_concurrent_requests,
                            timeout_seconds=self.timeout_seconds,
                            templates_dir=self.templates_dir)
                            
            # Zeit für Gesamtinitialisierung beenden
            init_end = time.time()
            
            # Log alle Zeitmessungen
            self.logger.info(f"Zeit für Super-Initialisierung: {(super_init_end - super_init_start) * 1000:.2f} ms")
            self.logger.info(f"Zeit für Konfiguration laden: {(config_load_end - config_load_start) * 1000:.2f} ms")
            self.logger.info(f"Zeit für OpenAI Client-Initialisierung: {(client_init_end - client_init_start) * 1000:.2f} ms")
            self.logger.info(f"Zeit für Transcriber-Initialisierung: {(transcriber_init_end - transcriber_init_start) * 1000:.2f} ms")
            self.logger.info(f"Gesamte Initialisierungszeit: {(init_end - init_start) * 1000:.2f} ms")
                            
        except Exception as e:
            self.logger.error("Fehler bei der Initialisierung des TransformerProcessors",
                            error=e)
            raise ProcessingError(f"Initialisierungsfehler: {str(e)}")

    def _create_cache_key(self, 
                         source_text: str, 
                         source_language: str, 
                         target_language: str, 
                         template: Optional[str] = None,
                         summarize: bool = False) -> str:
        """
        Erstellt einen Cache-Schlüssel basierend auf den Eingabeparametern.
        
        Args:
            source_text: Der Quelltext
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            template: Optional, das verwendete Template
            summarize: Ob der Text zusammengefasst werden soll
            
        Returns:
            str: Der generierte Cache-Schlüssel
        """
        # Für längere Texte nur die ersten 1000 Zeichen und einen Hash verwenden
        if len(source_text) > 1000:
            text_for_key = source_text[:1000] + hashlib.md5(source_text.encode()).hexdigest()
        else:
            text_for_key = source_text
            
        # Basis-Schlüssel aus Text, Sprachen und Modell generieren
        base_key = f"{text_for_key}_{source_language}_{target_language}_{self.model}"
        
        # Zusammenfassung-Flag hinzufügen
        if summarize:
            base_key = f"{base_key}_summarize"
        
        # Template hinzufügen, wenn vorhanden
        if template:
            template_key = hashlib.md5(template.encode()).hexdigest()
            base_key = f"{base_key}_{template_key}"
            
        # Hash generieren
        return self.generate_cache_key(base_key)
    
    def serialize_for_cache(self, result: TransformationResult) -> Dict[str, Any]:
        """
        Serialisiert das TransformationResult für die Speicherung im Cache.
        
        Args:
            result: Das TransformationResult
            
        Returns:
            Dict[str, Any]: Die serialisierten Daten
        """
        # Hauptdaten speichern (keine LLM-Informationen im Cache)
        cache_data = {
            "text": result.text,
            "target_language": result.target_language,
            "structured_data": result.structured_data,
            "cached_at": datetime.now().isoformat(),
            "model": self.model
        }
        
        return cache_data
    
    def deserialize_cached_data(self, cached_data: Dict[str, Any]) -> TransformationResult:
        """
        Deserialisiert die Cache-Daten zurück in ein TransformationResult.
        
        Args:
            cached_data: Die Daten aus dem Cache
            
        Returns:
            TransformationResult: Das deserialisierte TransformationResult
        """
        # TransformationResult aus Cache-Daten erstellen
        # LLM-Informationen werden bewusst weggelassen, da sie bei Cache-Treffern nicht vorhanden sind
        return TransformationResult.from_cache(cached_data)
    
    def _create_specialized_indexes(self, collection: Any) -> None:
        """
        Erstellt spezialisierte Indizes für die Collection.
        
        Args:
            collection: Die MongoDB-Collection
        """
        # Index für Zielsprache
        collection.create_index("target_language")
        
        # Index für das verwendete Modell
        collection.create_index("model")
        
        # Index für das Erstellungsdatum
        collection.create_index("cached_at")
    
    def transform(self, 
                 source_text: str, 
                 source_language: str, 
                 target_language: str, 
                 summarize: bool = False, 
                 target_format: Optional[OutputFormat] = None,
                 context: Optional[Dict[str, Any]] = None,
                 use_cache: bool = True) -> TransformerResponse:
        """
        Transformiert einen Text von einer Sprache in eine andere.
        
        Args:
            source_text: Der Quelltext
            source_language: Die Quellsprache (ISO 639-1 Code)
            target_language: Die Zielsprache (ISO 639-1 Code)
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Das Zielformat (TEXT, HTML, MARKDOWN)
            context: Optionaler Kontext für die Transformation
            use_cache: Ob der Cache verwendet werden soll (default: True)
            
        Returns:
            TransformerResponse: Die Antwort mit dem transformierten Text
        """
        process_start = time.time()
        self.logger.info(f"Transformer Process-Methode gestartet")
        
        # Initialisiere leere LLMInfo
        llm_info = LLMInfo()
        
        try:
            # Setze Standardwerte
            if not target_format:
                target_format = self.target_format
            
            # Validiere Parameter
            validation_start = time.time()
            source_text = self.validate_text(source_text)
            validation_end = time.time()
            self.logger.info(f"Zeit für Parameter-Validierung: {(validation_end - validation_start) * 1000:.2f} ms")
            
            # Cache-Schlüssel erstellen
            cache_key_start = time.time()
            cache_key: str = self._create_cache_key(
                source_text=source_text,
                source_language=source_language,
                target_language=target_language,
                summarize=summarize
            )
            cache_key_end = time.time()
            self.logger.info(f"Zeit für Cache-Key Generierung: {(cache_key_end - cache_key_start) * 1000:.2f} ms")
            
            # Cache prüfen (wenn aktiviert)
            cache_check_start = time.time()
            cache_hit = False
            cached_result = None
            
            if use_cache and self.is_cache_enabled():
                # Versuche, aus dem MongoDB-Cache zu laden
                cache_hit, cached_result = self.get_from_cache(cache_key)
                
                if cache_hit and cached_result:
                    self.logger.info(f"Cache-Hit für Transformation")
                    
                    # Response aus Cache erstellen
                    response_start = time.time()
                    response: TransformerResponse = self._create_response_from_cached_result(
                        cached_result=cached_result,
                        source_text=source_text,
                        source_language=source_language,
                        target_language=target_language,
                        summarize=summarize,
                        target_format=target_format,
                        cache_key=cache_key
                    )
                    response_end = time.time()
                    self.logger.info(f"Zeit für Response-Erstellung aus Cache: {(response_end - response_start) * 1000:.2f} ms")
                    
                    process_end = time.time()
                    self.logger.info(f"Gesamte Process-Zeit (Cache-Hit): {(process_end - process_start) * 1000:.2f} ms")
                    
                    return response
            cache_check_end = time.time()
            self.logger.info(f"Zeit für Cache-Prüfung: {(cache_check_end - cache_check_start) * 1000:.2f} ms")
            
            # Ab hier nur fortfahren, wenn kein Cache-Hit erfolgt ist
            
            # Erstelle Prompt für OpenAI
            prompt_creation_start = time.time()
            system_message = self._create_system_message(
                source_language=source_language,
                target_language=target_language,
                summarize=summarize,
                target_format=target_format,
                context=context
            )
            prompt_creation_end = time.time()
            self.logger.info(f"Zeit für Prompt-Erstellung: {(prompt_creation_end - prompt_creation_start) * 1000:.2f} ms")
            
            # Text transformieren mit OpenAI
            llm_call_start = time.time()
            completion: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": source_text}
                ],
                temperature=0.7,
            )
            llm_call_end = time.time()
            llm_duration = llm_call_end - llm_call_start
            self.logger.info(f"Zeit für LLM-Anfrage: {llm_duration * 1000:.2f} ms")
            
            # Erstelle Antworttext und tracke LLM-Nutzung
            transformed_text = completion.choices[0].message.content or ""
            
            # LLM-Nutzung im LLMInfo tracken
            usage_tracking_start = time.time()
            usage = completion.usage
            if usage:
                # Erstelle ein LLMRequest-Objekt über die zentrale Methode
                request: LLMRequest = self.transcriber.create_llm_request(
                    purpose="text_transformation",
                    tokens=usage.total_tokens,
                    duration=llm_duration * 1000,  # Millisekunden als float
                    model=self.model,
                    system_prompt=system_message,
                    user_prompt=source_text,
                    response=completion,
                    logger=self.logger,
                    processor=self.__class__.__name__
                )
                llm_info.add_request(request)
                
            usage_tracking_end = time.time()
            self.logger.info(f"Zeit für LLM-Tracking: {(usage_tracking_end - usage_tracking_start) * 1000:.2f} ms")
            
            # Erstelle TransformationResult
            result_creation_start = time.time()
            result = TransformationResult(
                text=transformed_text,
                target_language=target_language,
                structured_data={}
            )
            result_creation_end = time.time()
            self.logger.info(f"Zeit für Ergebnis-Erstellung: {(result_creation_end - result_creation_start) * 1000:.2f} ms")
            
            # Im Cache speichern (wenn aktiviert)
            cache_save_start = time.time()
            if use_cache and self.is_cache_enabled():
                self.save_to_cache(
                    cache_key=cache_key,
                    result=result
                )
                self.logger.debug(f"Transformer-Ergebnis im Cache gespeichert: {cache_key}")
            cache_save_end = time.time()
            self.logger.info(f"Zeit für Cache-Speicherung: {(cache_save_end - cache_save_start) * 1000:.2f} ms")
            
            # Erstelle Response
            response_creation_start = time.time()
            response = self.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    'source_text': source_text[:100] + "..." if len(source_text) > 100 else source_text,
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format.value if target_format else None
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=cache_key
            )
            response_creation_end = time.time()
            self.logger.info(f"Zeit für Response-Erstellung: {(response_creation_end - response_creation_start) * 1000:.2f} ms")
            
            process_end = time.time()
            self.logger.info(f"Gesamte Process-Zeit (ohne Cache): {(process_end - process_start) * 1000:.2f} ms")
            
            return response
            
        except Exception as e:
            self.logger.error("Fehler bei der Transformation",
                              error=e,
                              source_language=source_language,
                              target_language=target_language,
                              summarize=summarize)
            
            error_info = ErrorInfo(
                code="TRANSFORMATION_ERROR",
                message=str(e),
                details={
                    "error_type": type(e).__name__,
                    "source_language": source_language,
                    "target_language": target_language,
                    "summarize": summarize
                }
            )
            
            # Erstelle Error-Response
            return self.create_response(
                processor_name="transformer",
                result=TransformationResult(
                    text="",
                    target_language=target_language,
                    structured_data={}
                ),
                request_info={
                    'source_text': source_text[:100] + "..." if len(source_text) > 100 else source_text,
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': summarize,
                    'target_format': target_format.value if target_format else None
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )

    def _create_system_message(self,
                               source_language: str,
                               target_language: str, 
                               summarize: bool,
                               target_format: Optional[OutputFormat] = None,
                               context: Optional[Dict[str, Any]] = None) -> str:
        """
        Erstellt die System-Nachricht für den OpenAI-API-Aufruf.
        
        Args:
            source_language: Die Quellsprache (ISO 639-1 Code)
            target_language: Die Zielsprache (ISO 639-1 Code)
            summarize: Ob der Text zusammengefasst werden soll
            target_format: Das gewünschte Ausgabeformat
            context: Zusätzlicher Kontext für die Transformation
            
        Returns:
            str: Die fertige System-Nachricht
        """
        format_instruction = ""
        if target_format == OutputFormat.HTML:
            format_instruction = "Formatiere die Ausgabe als HTML mit korrekten Tags."
        elif target_format == OutputFormat.MARKDOWN:
            format_instruction = "Formatiere die Ausgabe im Markdown-Format."
        
        summarize_instruction = ""
        if summarize:
            summarize_instruction = "Fasse den Text prägnant zusammen, behalte aber alle wichtigen Informationen bei."
        
        context_instruction = ""
        if context:  # Der Typ Dict[str, Any] garantiert bereits, dass es ein dict ist
            context_str = json.dumps(context, ensure_ascii=False)
            context_instruction = f"Berücksichtige den folgenden Kontext bei der Transformation: {context_str}"
        
        return f"""Du bist ein Textverarbeitungsassistent, der Texte perfekt übersetzt und formatiert.

Aufgabe: Übersetze den Eingabetext von {source_language} nach {target_language}.
{summarize_instruction}
{format_instruction}
{context_instruction}

Gib nur den transformierten Text zurück, ohne zusätzliche Erklärungen oder Metadaten.
"""

    def validate_text(self, text: Optional[str], field_name: str = "text") -> str:
        """
        Validiert den Eingabetext.
        
        Args:
            text: Der zu validierende Text
            field_name: Name des Feldes für Fehlermeldungen
            
        Returns:
            str: Der validierte Text
        
        Raises:
            ValueError: Wenn der Text leer ist oder zu lang
        """
        # Rufe die Basismethode auf
        result = super().validate_text(text, field_name)
        
        # Zusätzliche Validierung für die maximale Länge
        if result and len(result) > 100000:
            raise ValueError(f"Der {field_name} ist zu lang: {len(result)} Zeichen (maximal 100.000)")
        
        return result
        
    def _create_response_from_cached_result(self,
                                           cached_result: Union[Dict[str, Any], TransformationResult],
                                           source_text: str,
                                           source_language: str,
                                           target_language: str,
                                           summarize: bool,
                                           cache_key: str,
                                           target_format: Optional[OutputFormat]) -> TransformerResponse:
        """
        Erstellt eine TransformerResponse aus einem gecachten Ergebnis.
        
        Args:
            cached_result: Das gecachte Ergebnis (als Dict oder TransformationResult)
            source_text: Der Quelltext
            source_language: Die Quellsprache
            target_language: Die Zielsprache
            summarize: Ob der Text zusammengefasst wurde
            target_format: Das Zielformat
            
        Returns:
            TransformerResponse: Die erstellte Response
        """
        # Deserialisiere das gecachte Ergebnis je nach Typ
        transformation_result: TransformationResult
        if isinstance(cached_result, dict):
            text = cast(str, cached_result.get("text", "")) # type: ignore
            target_lang = cast(str, cached_result.get("target_language", target_language)) # type: ignore
            struct_data = cast(Dict[str, Any], cached_result.get("structured_data", {})) # type: ignore
            
            transformation_result = TransformationResult(
                text=text,
                target_language=target_lang,
                structured_data=struct_data
            )
        else:
            # Es ist bereits ein TransformationResult
            transformation_result = cached_result
        
        # Stelle sicher, dass ein gültiges OutputFormat vorhanden ist
        # TEXT ist der Default-Wert, wenn nichts anderes angegeben ist
        actual_format = OutputFormat.TEXT
        if target_format is not None:
            actual_format = target_format
        
        # Erstelle ein TransformerData-Objekt mit korrekter Struktur
        transformer_data = TransformerData(
            input=TransformerInput(
                text=source_text,
                language=source_language,
                format=actual_format,
                translated_text=None,
                summarize=summarize
            ),
            output=TransformerOutput(
                text=transformation_result.text,
                language=transformation_result.target_language,
                format=actual_format,
                structured_data=transformation_result.structured_data,
                summarized=summarize
            )
        )
        
        # Erstelle Response mit ResponseFactory, explizit from_cache=True setzen
        return self.create_response(
            processor_name="transformer",
            result=transformer_data,
            request_info={
                'source_text': source_text[:100] + "..." if len(source_text) > 100 else source_text,
                'source_language': source_language,
                'target_language': target_language,
                'summarize': summarize,
                'target_format': target_format.value if target_format else None
            },
            response_class=TransformerResponse,
            from_cache=True,  # Explizit True, da es sich um ein Ergebnis aus dem Cache handelt
            cache_key=cache_key
        )

    def transformByTemplate(
        self,
        source_text: str,
        source_language: str,
        target_language: str,
        context: Optional[Dict[str, Any]] = None,
        template: Optional[str] = None,
        additional_field_descriptions: Optional[Dict[str, str]] = None,
        use_cache: bool = True
    ) -> TransformerResponse:
        """
        Transformiert einen Text anhand eines Templates.
        
        Args:
            source_text: Der zu transformierende Text
            source_language: Die Quellsprache des Texts
            target_language: Die Zielsprache für die Transformation
            context: Optionaler zusätzlicher Kontext für das Template
            template: Optional, Name des zu verwendenden Templates
            additional_field_descriptions: Zusätzliche Feldbeschreibungen für das Template
            use_cache: Optional, ob die Ergebnisse zwischengespeichert werden sollen
            
        Returns:
            TransformerResponse mit dem transformierten Text
        """
        try:
            # Hole den Template-Prozessor
            template_processor: WhisperTranscriber = self.get_template_processor()
            
            # Transformiere den Text
            result: TransformationResult = template_processor.transform_by_template(
                text=source_text,
                target_language=target_language,
                template=template or "default",
                context=context,
                additional_field_descriptions=additional_field_descriptions,
                logger=self.logger
            )
            

            if result.requests:
                # Füge die LLM-Informationen zur Prozessinfo hinzu
                self.add_llm_requests(result.requests)


            # Erstelle Response
            response: TransformerResponse = self.create_response(
                processor_name="transformer",
                result=result,
                request_info={
                    'source_text': source_text[:100] + "..." if len(source_text) > 100 else source_text,
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': False,
                    'target_format': self.target_format.value if self.target_format else None
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key=""
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
            self.logger.error(f"Fehler bei der Template-Transformation: {str(e)}")
            
            # Erstelle TransformerData mit Minimal-Struktur für Fehlerfälle
            actual_format = self.target_format or OutputFormat.TEXT  # Verwende TEXT als Standardformat, wenn None
            
            transformer_data = TransformerData(
                input=TransformerInput(
                    text=source_text,
                    language=source_language,
                    format=actual_format,
                    translated_text=None,
                    summarize=False
                ),
                output=TransformerOutput(
                    text="",
                    language=target_language,
                    format=actual_format,
                    summarized=False
                )
            )
            
            return self.create_response(
                processor_name="transformer",
                result=transformer_data,
                request_info={
                    'source_text': source_text[:100] + "..." if len(source_text) > 100 else source_text,
                    'source_language': source_language,
                    'target_language': target_language,
                    'summarize': False,
                    'target_format': self.target_format.value if self.target_format else None
                },
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            )

    def _extract_link_info(self, link: PageElement | Tag, source_url: str) -> Dict[str, str]:
        """Extrahiert Name und URL aus einem Link-Tag."""
        if not isinstance(link, Tag):
            return {"Name": str(link.get_text(strip=True)) if hasattr(link, 'get_text') else ""}
            
        href_attr = link.get('href')
        href: str = str(href_attr) if href_attr is not None else ''
        if href:
            return {
                "Name": str(link.get_text(strip=True)),
                "Url": urljoin(source_url, href)
            }
        return {"Name": str(link.get_text(strip=True))}

    def _process_cell_content(self, cell: Tag, source_url: str) -> Any:
        """Verarbeitet den Inhalt einer Tabellenzelle."""
        links = cell.find_all('a')
        if not links:
            return str(cell.get_text(strip=True))
            
        if len(links) == 1 and isinstance(links[0], Tag):
            return self._extract_link_info(links[0], source_url)
            
        link_objects = [
            self._extract_link_info(link, source_url) 
            for link in links 
            if isinstance(link, Tag)
        ]
        return link_objects if link_objects else str(cell.get_text(strip=True))

    def transformHtmlTable(
        self,
        source_url: str,
        output_format: str = "json",
        table_index: Optional[int] = None,
        start_row: Optional[int] = None,
        row_count: Optional[int] = None
    ) -> TransformerResponse:
        """
        Transformiert HTML-Tabellen von einer Webseite in JSON Format.
        
        Args:
            source_url: Die URL der Webseite mit der Tabelle
            output_format: Das gewünschte Ausgabeformat (default: "json")
            table_index: Optional - Index der gewünschten Tabelle (0-basiert). 
                        Wenn None, werden alle Tabellen zurückgegeben.
            start_row: Optional - Startzeile für das Paging (0-basiert)
            row_count: Optional - Anzahl der zurückzugebenden Zeilen
            
        Returns:
            TransformerResponse: Das Transformationsergebnis
        """
        # Response initialisieren
        response = TransformerResponse(
            request=RequestInfo(
                processor=str(ProcessorType.TRANSFORMER.value),
                timestamp=datetime.now().isoformat(),
                parameters={
                    "source_url": source_url,
                    "output_format": output_format,
                    "table_index": table_index,
                    "start_row": start_row,
                    "row_count": row_count
                }
            ),
            process=ProcessInfo(
                id=self.process_id or str(uuid.uuid4()),
                main_processor=str(ProcessorType.TRANSFORMER.value),
                started=datetime.now().isoformat()
            ),
            data=TransformerData(
                input=TransformerInput(
                    text=source_url,
                    language="html",
                    format=OutputFormat.HTML
                ),
                output=TransformerOutput(
                    text="",  # Wird später gefüllt
                    language="json",
                    format=OutputFormat.JSON
                )
            )
        )
        
        try:
            # Validiere Eingaben
            if not source_url.strip():
                raise ValueError("source_url darf nicht leer sein")
            
            if output_format.lower() != "json":
                raise ValueError("Aktuell wird nur JSON als output_format unterstützt")

            if table_index is not None and table_index < 0:
                raise ValueError("table_index muss größer oder gleich 0 sein")

            if start_row is not None and start_row < 0:
                raise ValueError("start_row muss größer oder gleich 0 sein")

            if row_count is not None:
                if row_count < 0:
                    raise ValueError("row_count muss größer oder gleich 0 sein")
                if row_count == 0:
                    row_count = None

            self.logger.info("Starte HTML-Tabellen Transformation")
            
            # Verwende requests für das Abrufen der Webseite
            import requests
            
            # Hole die Webseite
            try:
                request_headers: Dict[str, str] = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                page = requests.get(source_url, headers=request_headers, timeout=10)
                page.raise_for_status()  # Wirft HTTPError für 4XX/5XX Status
                source_html = page.text
            except requests.RequestException as e:
                raise ProcessingError(f"Fehler beim Abrufen der Webseite: {str(e)}")
            
            soup = BS(source_html, 'html.parser')
            tables = soup.find_all('table')
            
            if not tables:
                raise ValueError("Keine HTML-Tabelle auf der Webseite gefunden")

            if table_index is not None and table_index >= len(tables):
                raise ValueError(f"table_index {table_index} ist zu groß. Es wurden nur {len(tables)} Tabellen gefunden.")
            
            all_tables: List[Dict[str, Any]] = []
            tables_to_process = [tables[table_index]] if table_index is not None else tables
            
            for idx, table in enumerate(tables_to_process):
                if not isinstance(table, Tag):
                    continue
                    
                # Headers extrahieren
                headers = [
                    th.get_text(strip=True) 
                    for th in table.find_all('th') 
                    if isinstance(th, Tag)
                ]
                
                # Wenn keine Headers gefunden wurden, erste Zeile als Header verwenden
                if not headers:
                    first_row: PageElement | Tag | NavigableString | None = table.find('tr')
                    if first_row and isinstance(first_row, Tag):
                        headers: List[str] = [
                            td.get_text(strip=True) 
                            for td in first_row.find_all('td') 
                            if isinstance(td, Tag)
                        ]
                
                rows: List[Dict[str, Any]] = []
                current_group_info: Dict[str, str] = {}
                
                # Zeilen verarbeiten
                for tr in table.find_all('tr')[1 if headers else 0:]:
                    if not isinstance(tr, Tag):
                        continue
                        
                    cells: ResultSet[PageElement | Tag | NavigableString] = tr.find_all('td')
                    if not cells:
                        continue
                        
                    # Gruppierungsinfo verarbeiten
                    first_cell = cells[0]
                    if len(cells) == 1 and isinstance(first_cell, Tag):
                        if first_cell.get('colspan'):
                            links: ResultSet[PageElement | Tag | NavigableString] = first_cell.find_all('a')
                            if links and len(links) == 1 and isinstance(links[0], Tag):
                                current_group_info: Dict[str, str] = self._extract_link_info(links[0], source_url)
                            else:
                                current_group_info = {"Name": first_cell.get_text(strip=True)}
                            continue
                    
                    # Normale Zeile verarbeiten
                    row = {
                        headers[i]: self._process_cell_content(cell, source_url)
                        for i, cell in enumerate(cells)
                        if i < len(headers) and isinstance(cell, Tag)
                    }
                    
                    if row and any(row.values()):
                        if current_group_info:
                            row['group'] = current_group_info
                        rows.append(row)

                # Paging anwenden
                total_rows: int = len(rows)
                start_idx: int = start_row if start_row is not None else 0
                
                if row_count is None:
                    end_idx = total_rows
                else:
                    end_idx = min(start_idx + row_count, total_rows)
                
                rows = rows[start_idx:end_idx]

                # Tabellendaten sammeln
                table_data: Dict[str, Any] = {
                    "table_index": table_index if table_index is not None else idx,
                    "headers": list(headers) + ["group"] if current_group_info else list(headers),
                    "rows": rows,
                    "metadata": {
                        "total_rows": total_rows,
                        "column_count": len(headers),
                        "has_group_info": bool(current_group_info),
                        "paging": {
                            "start_row": start_row if start_row is not None else 0,
                            "row_count": len(rows),
                            "has_more": end_idx < total_rows
                        }
                    }
                }
                all_tables.append(table_data)
            
            # Gesamtergebnis erstellen
            result: Dict[str, str | int | List[Dict[str, Any]]] = {
                "url": source_url,
                "table_count": len(all_tables),
                "tables": all_tables
            }

            response: TransformerResponse = self.create_response(
                processor_name=response.process.main_processor,
                result=TransformerData(
                    input=response.data.input,
                    output=TransformerOutput(
                        text="",
                        language="json",
                        format=OutputFormat.JSON,
                        structured_data=result
                    )
                ),
                request_info=response.request.parameters,
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
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
            self.logger.error(f"Fehler bei der HTML-Tabellen Transformation: {str(e)}")
            
            return self.create_response(
                processor_name=response.process.main_processor,
                result=response.data,
                request_info=response.request.parameters,
                response_class=TransformerResponse,
                from_cache=False,
                cache_key="",
                error=error_info
            ) 

    def get_template_processor(self) -> WhisperTranscriber:
        """Gibt den Template-Prozessor zurück."""
        return self.transcriber 